"""
app.py — السيرفر الرئيسي
Flask + Flask-SocketIO + جميع وحدات التحكم
"""

import os
import sys
import json
import yaml
import logging
import time
import threading
from datetime import datetime
from pathlib import Path

from flask import Flask, render_template, request, jsonify, send_from_directory
from flask_socketio import SocketIO, emit
from flask_cors import CORS

# إضافة المجلد الحالي لمسار الاستيراد
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from modules.bluetooth import BluetoothManager
from modules.camera import CameraManager
from modules.motors import MotorController
from modules.sensors import SensorManager
from modules.scenarios import ScenarioManager
from modules import sensors as sensors_mod

# ══════════════════════ تحميل الإعدادات ══════════════════════

CONFIG_PATH = os.path.join(os.path.dirname(__file__), "config.yaml")

def load_config():
    with open(CONFIG_PATH, "r") as f:
        return yaml.safe_load(f)

def save_config(config):
    with open(CONFIG_PATH, "w") as f:
        yaml.dump(config, f, default_flow_style=False, allow_unicode=True)

config = load_config()

# ══════════════════════ إعداد السيرفر ══════════════════════

app = Flask(__name__)
app.config["SECRET_KEY"] = config.get("server", {}).get("secret_key", "robot-secret")

server_cfg = config.get("server", {})
if server_cfg.get("cors_enabled", True):
    CORS(app)

socketio = SocketIO(app, cors_allowed_origins="*", async_mode="threading")

# ربط SocketIO بوحدة الحساسات (F6)
sensors_mod.init_socketio(socketio)

# ══════════════════════ إعداد السجلات ══════════════════════

log_cfg = config.get("logging", {})
log_level = getattr(logging, log_cfg.get("level", "INFO").upper(), logging.INFO)
log_file = log_cfg.get("file")

if log_file:
    os.makedirs(os.path.dirname(log_file), exist_ok=True)
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=[
            logging.FileHandler(log_file),
            logging.StreamHandler(),
        ],
    )
else:
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

logger = logging.getLogger("RobotControl")

# ══════════════════════ تهيئة الوحدات ══════════════════════

bt_manager = BluetoothManager(config.get("bluetooth", {}))
camera_manager = CameraManager(config.get("camera", {}))
motor_controller = MotorController(bt_manager, socketio)
sensor_manager = SensorManager()
scenario_manager = ScenarioManager(motor_controller, bt_manager, socketio)

# تسجيل SocketIO في BluetoothManager
bt_manager._socketio = socketio
# ملاحظة: sensor_manager._socketio لا أثر له — الإرسال يتم عبر sensors_mod._socketio (init_socketio)

# ربط sensor_manager بـ BluetoothManager لتوجيه القراءات (F7)
bt_manager._sensor_manager = sensor_manager

# تحميل الحساسات الافتراضية
sensor_manager.load_default_sensors()

# تحميل الحساسات من الإعدادات
sensor_defs = config.get("sensors", {}).get("definitions", [])
for sdef in sensor_defs:
    try:
        sensor_manager.register_sensor_from_params(
            code=sdef["code"],
            name=sdef["name"],
            unit=sdef["unit"],
            icon=sdef.get("icon", "📊"),
            min_val=sdef.get("min", 0),
            max_val=sdef.get("max", 100),
            warn_high=sdef.get("warn_high"),
            warn_low=sdef.get("warn_low"),
            color=sdef.get("color", "#00b894"),
        )
    except Exception as e:
        logger.warning(f"Skip sensor {sdef.get('code')}: {e}")

# تحميل السيناريوهات المحفوظة
scenario_manager.load_all()

# وقت بدء التشغيل
START_TIME = time.time()

# ══════════════════════ Routes (HTTP) ══════════════════════

@app.route("/")
def index():
    """الصفحة الرئيسية"""
    return render_template("index.html")


@app.route("/settings")
def settings_page():
    """صفحة الإعدادات"""
    return render_template("settings.html")


@app.route("/api/status")
def api_status():
    """حالة النظام الكاملة"""
    uptime = int(time.time() - START_TIME)
    return jsonify({
        "bluetooth": bt_manager.get_status(),
        "camera": {
            "running": camera_manager.is_running,
            "mode": camera_manager.color_mode,
            "resolution": f"{camera_manager.frame_width}x{camera_manager.frame_height}",
            "settings": camera_manager.get_settings(),
        },
        "motors": motor_controller.get_state(),
        "sensors": sensor_manager.get_all(),
        "scenarios": scenario_manager.list_scenarios(),
        "uptime": uptime,
    })


@app.route("/api/config", methods=["GET"])
def get_config():
    """يرجع الإعدادات الحالية"""
    return jsonify(config)


@app.route("/api/config", methods=["POST"])
def update_config():
    """يحدث الإعدادات"""
    global config
    try:
        new_config = request.json
        # دمج عميق
        _deep_merge(config, new_config)
        save_config(config)
        _apply_config(config)
        return jsonify({"success": True})
    except Exception as e:
        logger.error(f"Config update error: {e}")
        return jsonify({"success": False, "error": str(e)}), 400


@app.route("/api/command", methods=["POST"])
def send_command():
    """يرسل أمر مباشر للأردوينو"""
    try:
        command = request.json
        success = bt_manager.send_json(command)
        return jsonify({"success": success})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 400


@app.route("/api/sensors/history/<code>")
def sensor_history(code):
    """تاريخ قراءات حساس"""
    limit = request.args.get("limit", 20, type=int)
    data = sensor_manager.get_chart_data(code, limit)
    if data is not None:
        return jsonify(data)
    return jsonify({"error": "Sensor not found"}), 404


@app.route("/photos/<filename>")
def serve_photo(filename):
    """يخدم الصور الملتقطة"""
    return send_from_directory(
        camera_manager.photo_path, filename
    )


@app.route("/recordings/<filename>")
def serve_recording(filename):
    """يخدم التسجيلات"""
    return send_from_directory(
        camera_manager.recording_path, filename
    )


# ══════════════════════ WebSocket Events ══════════════════════

@socketio.on("connect")
def handle_connect():
    """عميل جديد اتصل"""
    logger.info(f"Client connected: {request.sid}")
    # إرسال الحالة الحالية
    emit("bluetooth_status", bt_manager.get_status())
    emit("motor_status", motor_controller.get_state())
    emit("sensor_data", sensor_manager.get_all())


@socketio.on("disconnect")
def handle_disconnect():
    """عميل انقطع"""
    logger.info(f"Client disconnected: {request.sid}")


# ─────────── التحكم بالحركة ───────────

@socketio.on("move")
def handle_move(data):
    """أمر حركة"""
    motor_controller.execute_move(data)


@socketio.on("stop")
def handle_stop():
    """أمر توقف"""
    motor_controller.emergency_stop()


# ─────────── التحكم بالمحركات ───────────

@socketio.on("servo_control")
def handle_servo_control(data):
    """تحكم بسيرفو محدد"""
    servo = data.get("servo", "").upper()
    angle = data.get("angle", 90)
    if servo in ("S1", "S2"):
        motor_controller.set_servo_angle(
            s1=angle if servo == "S1" else None,
            s2=angle if servo == "S2" else None,
        )


@socketio.on("motor_speed")
def handle_motor_speed(data):
    """تغيير سرعة محرك"""
    m1 = data.get("M1")
    m2 = data.get("M2")
    motor_controller.set_motor_speed(
        m1=m1 if m1 is not None else None,
        m2=m2 if m2 is not None else None,
    )


# ─────────── البلوتوث ───────────

@socketio.on("bluetooth_scan")
def handle_bluetooth_scan():
    """بحث عن أجهزة بلوتوث"""
    devices = bt_manager.scan_devices()
    emit("bluetooth_devices", devices)


@socketio.on("bluetooth_connect")
def handle_bluetooth_connect(data):
    """اتصال بجهاز بلوتوث"""
    address = data.get("address", "") or data.get("mac", "")
    baud = data.get("baud", None)
    port = data.get("port", None)
    
    if baud:
        bt_manager.baudrate = int(baud)
    if port:
        bt_manager.serial_port = port
    
    success = bt_manager.connect(address)
    emit("bluetooth_status", bt_manager.get_status())
    if success:
        emit("log", {"level": "info", "message": f"Connected to {address}"})
    else:
        emit("log", {"level": "error", "message": f"Failed to connect to {address}"})


@socketio.on("bluetooth_disconnect")
def handle_bluetooth_disconnect():
    """قطع اتصال البلوتوث"""
    bt_manager.disconnect()
    emit("bluetooth_status", bt_manager.get_status())


# ─────────── الكاميرا ───────────

@socketio.on("camera_start")
def handle_camera_start():
    """تشغيل الكاميرا"""
    if camera_manager.start():
        camera_manager.start_stream(socketio)
        emit("log", {"level": "info", "message": "Camera started"})
    else:
        emit("log", {"level": "error", "message": "Failed to start camera"})


@socketio.on("camera_stop")
def handle_camera_stop():
    """إيقاف الكاميرا"""
    camera_manager.stop()
    emit("log", {"level": "info", "message": "Camera stopped"})


@socketio.on("camera_settings")
def handle_camera_settings(data):
    """تحديث إعدادات الكاميرا"""
    camera_manager.update_settings(data)
    emit("camera_settings_updated", camera_manager.get_settings())


@socketio.on("camera_capture")
def handle_camera_capture():
    """التقاط صورة"""
    filepath = camera_manager.capture_photo()
    if filepath:
        filename = os.path.basename(filepath)
        emit("photo_captured", {"filename": filename, "url": f"/photos/{filename}"})
    else:
        emit("log", {"level": "error", "message": "Failed to capture photo"})


@socketio.on("camera_record_start")
def handle_camera_record_start():
    """بدء تسجيل"""
    if camera_manager.start_recording():
        emit("log", {"level": "info", "message": "Recording started"})
    else:
        emit("log", {"level": "error", "message": "Failed to start recording"})


@socketio.on("camera_record_stop")
def handle_camera_record_stop():
    """إيقاف تسجيل"""
    filepath = camera_manager.stop_recording()
    if filepath:
        emit("log", {"level": "info", "message": f"Recording saved: {filepath}"})
    else:
        emit("log", {"level": "info", "message": "Recording stopped"})


# ─────────── الحساسات ───────────

@socketio.on("sensor_add")
def handle_sensor_add(data):
    """إضافة حساس جديد"""
    try:
        sensor_manager.register_sensor_from_params(
            code=data["code"],
            name=data["name"],
            unit=data.get("unit", ""),
            icon=data.get("icon", "📊"),
            min_val=data.get("min", 0),
            max_val=data.get("max", 100),
            warn_high=data.get("warn_high"),
            warn_low=data.get("warn_low"),
            color=data.get("color", "#00b894"),
        )
        emit("log", {"level": "info", "message": f"Sensor {data['code']} added"})
        emit("sensor_data", sensor_manager.get_all())
        _emit_sensor_list()
    except Exception as e:
        emit("log", {"level": "error", "message": str(e)})


@socketio.on("sensor_remove")
def handle_sensor_remove(data):
    """إزالة حساس"""
    if isinstance(data, str):
        code = data
    else:
        code = data.get("code", "")
    sensor_manager.remove_sensor(code)
    emit("sensor_data", sensor_manager.get_all())
    sensor_manager.save_config()
    emit("log", {"level": "info", "message": f"Sensor {code} removed"})


@socketio.on("sensor_edit")
def handle_sensor_edit(data):
    """تعديل حساس موجود"""
    code = data.get("code", "")
    sensor = sensor_manager.get(code)
    if not sensor:
        emit("log", {"level": "error", "message": f"Sensor {code} not found"})
        return
    # تحديث الحقول
    if "name" in data:
        sensor.name = data["name"]
    if "unit" in data:
        sensor.unit = data["unit"]
    if "icon" in data:
        sensor.icon = data["icon"]
    if "min_val" in data:
        sensor.min_val = float(data["min_val"])
    if "max_val" in data:
        sensor.max_val = float(data["max_val"])
    if "warn_high" in data:
        sensor.warn_high = float(data["warn_high"]) if data["warn_high"] is not None else None
    if "warn_low" in data:
        sensor.warn_low = float(data["warn_low"]) if data["warn_low"] is not None else None
    if "color" in data:
        sensor.color = data["color"]
    sensor_manager.save_config()
    emit("sensor_data", sensor_manager.get_all())
    emit("log", {"level": "info", "message": f"Sensor {code} updated"})


def _emit_sensor_list():
    """يبعت قائمة الحساسات للعميل"""
    sensors_list = []
    for code, s in sensor_manager.sensors.items():
        sensors_list.append({
            "code": code,
            "name": s.name,
            "unit": s.unit,
            "icon": s.icon,
            "min_value": s.min_val,
            "max_value": s.max_val,
            "warn_high": s.warn_high,
            "warn_low": s.warn_low,
            "color": getattr(s, "color", "#00b4d8"),
            "enabled": getattr(s, "enabled", True),
        })
    emit("sensor_list", sensors_list)


# ─────────── الإعدادات ───────────

@socketio.on("get_settings")
def handle_get_settings():
    """يرسل الإعدادات الحالية للعميل"""
    emit("settings_loaded", config)
    # بعت قائمة الحساسات كمان
    _emit_sensor_list()


@socketio.on("save_settings")
def handle_save_settings(data):
    """يحفظ الإعدادات من صفحة الإعدادات"""
    global config
    try:
        _deep_merge(config, data)
        save_config(config)
        _apply_config(config)
        emit("settings_loaded", config)
        emit("log", {"level": "info", "message": "Settings saved ✅"})
    except Exception as e:
        logger.error(f"Save settings error: {e}")
        emit("log", {"level": "error", "message": str(e)})


@socketio.on("export_settings")
def handle_export_settings():
    """يصدر الإعدادات كملف JSON"""
    emit("settings_exported", config)


@socketio.on("import_settings")
def handle_import_settings(data):
    """يستورد إعدادات من JSON"""
    global config
    try:
        config = data
        save_config(config)
        _apply_config(config)
        emit("settings_loaded", config)
        emit("log", {"level": "info", "message": "Settings imported ✅"})
    except Exception as e:
        logger.error(f"Import settings error: {e}")
        emit("log", {"level": "error", "message": str(e)})


@socketio.on("reset_settings")
def handle_reset_settings():
    """يعيد تعيين الإعدادات للقيم الافتراضية"""
    global config
    try:
        default_config = {
            "server": {"host": "0.0.0.0", "port": 5000, "secret_key": "robot-secret", "cors_enabled": True},
            "bluetooth": {"device_name": "HC-05", "device_address": "", "serial_port": "/dev/rfcomm0", "baudrate": 9600, "auto_connect_on_start": False, "auto_reconnect": False, "reconnect_attempts": 5, "reconnect_delay": 3, "scan_timeout": 10},
            "camera": {"enabled": True, "camera_index": 0, "width": 640, "height": 480, "fps": 24, "jpeg_quality": 70, "default_color_mode": "RGB", "rotate_180": False, "flip_h": False, "flip_v": False, "edge_detection": False, "threshold": False, "brightness": 0, "contrast": 0, "saturation": 100},
            "motors": {"default_speed": 200, "max_speed": 255, "min_speed": 50, "ramp_duration": 500, "invert_m1": False, "invert_m2": False, "servo1_center": 90, "servo2_center": 90, "servo1_min": 0, "servo1_max": 180, "servo2_min": 0, "servo2_max": 180},
            "sensors": {"definitions": []},
            "logging": {"level": "INFO", "file": "logs/app.log"},
        }
        config = default_config
        save_config(config)
        _apply_config(config)
        emit("settings_loaded", config)
        emit("log", {"level": "info", "message": "Settings reset to defaults ✅"})
    except Exception as e:
        emit("log", {"level": "error", "message": str(e)})


# ─────────── السيناريوهات ───────────

@socketio.on("scenario_save")
def handle_scenario_save(data):
    """حفظ سيناريو"""
    try:
        name = data.get("name", "unnamed")
        description = data.get("description", "")
        steps = data.get("steps", [])
        loop = data.get("loop", False)
        scenario_manager.create_scenario(name, description, steps, loop)
        emit("log", {"level": "info", "message": f"Scenario '{name}' saved"})
        emit("scenarios_list", scenario_manager.list_scenarios())
    except Exception as e:
        emit("log", {"level": "error", "message": str(e)})


@socketio.on("scenario_run")
def handle_scenario_run(data):
    """تشغيل سيناريو"""
    name = data.get("name", "")
    if scenario_manager.run_scenario(name):
        emit("log", {"level": "info", "message": f"Running scenario '{name}'"})
    else:
        emit("log", {"level": "error", "message": f"Scenario '{name}' not found"})


@socketio.on("scenario_stop")
def handle_scenario_stop():
    """إيقاف السيناريو الجاري"""
    scenario_manager.stop_scenario()
    emit("log", {"level": "info", "message": "Scenario stopped"})


@socketio.on("scenario_delete")
def handle_scenario_delete(data):
    """حذف سيناريو"""
    name = data.get("name", "")
    scenario_manager.delete_scenario(name)
    emit("scenarios_list", scenario_manager.list_scenarios())


@socketio.on("scenario_list")
def handle_scenario_list():
    """قائمة السيناريوهات"""
    emit("scenarios_list", scenario_manager.list_scenarios())


# ─────────── معايرة EEPROM (F8) ───────────

@socketio.on("calib_run_port")
def handle_calib_run_port(data):
    """تشغيل منفذ فيزيائي مفرد للمعايرة"""
    bt_manager.send_json({"cal": "port", "port": data.get("port", 1),
                          "spd": data.get("spd", 150), "ms": data.get("ms", 700)})


@socketio.on("calib_set_map")
def handle_calib_set_map(data):
    """تعيين ربط العجلات المنطقية بالمنافذ"""
    bt_manager.send_json({"cfg": "map", "FL": data["FL"], "FR": data["FR"],
                          "RL": data["RL"], "RR": data["RR"]})


@socketio.on("calib_test_dir")
def handle_calib_test_dir(data):
    """اختبار اتجاه عجلة منطقية"""
    bt_manager.send_json({"cal": "dir", "wheel": data.get("wheel", "FL"),
                          "spd": data.get("spd", 150), "ms": data.get("ms", 700)})


@socketio.on("calib_set_invert")
def handle_calib_set_invert(data):
    """عكس اتجاه عجلة"""
    bt_manager.send_json({"cfg": "inv", "wheel": data.get("wheel"),
                          "invert": data.get("invert", 0)})


@socketio.on("calib_move_servo")
def handle_calib_move_servo(data):
    """تحريك سيرفو لزاوية محددة للمعايرة"""
    bt_manager.send_json({"cal": "servo", "id": data.get("id", 1),
                          "angle": data.get("angle", 90)})


@socketio.on("calib_set_servo")
def handle_calib_set_servo(data):
    """ضبط حدود واتجاه سيرفو"""
    bt_manager.send_json({"cfg": "servo", "id": data.get("id", 1),
                          "min": data.get("min", 0), "max": data.get("max", 180),
                          "center": data.get("center", 90),
                          "invert": data.get("invert", 0)})


@socketio.on("calib_save")
def handle_calib_save():
    """حفظ الإعدادات في EEPROM"""
    bt_manager.send_json({"cfg": "save"})


@socketio.on("calib_get")
def handle_calib_get():
    """قراءة الإعدادات الحالية من EEPROM"""
    bt_manager.send_json({"cfg": "get"})


@socketio.on("calib_reset")
def handle_calib_reset():
    """إعادة ضبط المصنع"""
    bt_manager.send_json({"cfg": "reset"})


# ══════════════════════ أدوات مساعدة ══════════════════════

def _deep_merge(base, override):
    """دمج عميق لقاموسين"""
    for key, value in override.items():
        if key in base and isinstance(base[key], dict) and isinstance(value, dict):
            _deep_merge(base[key], value)
        else:
            base[key] = value


def _apply_config(cfg):
    """يطبق الإعدادات الجديدة على الوحدات"""
    if "bluetooth" in cfg:
        bt_manager.update_config(cfg["bluetooth"])
    if "camera" in cfg:
        camera_manager.update_settings(cfg["camera"])
    if "motors" in cfg:
        mc = cfg["motors"]
        motor_controller.default_speed = mc.get("default_speed", 200)
        motor_controller.max_speed = mc.get("max_speed", 255)


# ══════════════════════ تشغيل السيرفر ══════════════════════

if __name__ == "__main__":
    host = config.get("server", {}).get("host", "0.0.0.0")
    port = config.get("server", {}).get("port", 5000)

    logger.info("=" * 50)
    logger.info("🤖 Robot Control System Starting...")
    logger.info(f"   Host: {host}")
    logger.info(f"   Port: {port}")
    logger.info("=" * 50)

    # تشغيل خيوط المراقبة
    bt_manager.start_monitor(socketio)

    # تشغيل الكاميرا تلقائياً
    if config.get("camera", {}).get("enabled", True):
        if camera_manager.start():
            camera_manager.start_stream(socketio)
            logger.info("📷 Camera started")
        else:
            logger.warning("📷 Camera not available")

    # اتصال تلقائي بالبلوتوث
    if config.get("bluetooth", {}).get("auto_connect_on_start", False):
        threading.Thread(target=bt_manager.auto_connect_with_retry, daemon=True).start()

    try:
        socketio.run(
            app,
            host=host,
            port=port,
            debug=False,
            use_reloader=False,
            allow_unsafe_werkzeug=True,
        )
    except KeyboardInterrupt:
        logger.info("Shutting down...")
        camera_manager.stop()
        bt_manager.disconnect()
        bt_manager.stop_monitor()
