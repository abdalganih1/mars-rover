# 04 - بناء الـ Backend (Flask + WebSocket)

## الهدف
إنشاء سيرفر Flask يخدم صفحات الويب ويتعامل مع WebSocket للبث الحي والتحكم الآني.

## الملف الرئيسي
- `app.py` — نقطة الدخول الرئيسية

## الملفات الداعمة
- `modules/` — كل الوحدات (bluetooth, camera, motors, sensors, scenarios)

## تفاصيل `app.py`

### الهيكل العام
```python
from flask import Flask, render_template, request, jsonify
from flask_socketio import SocketIO, emit
from flask_cors import CORS
import threading
import yaml
import logging

# تحميل الإعدادات
with open('config.yaml', 'r') as f:
    config = yaml.safe_load(f)

app = Flask(__name__)
app.config['SECRET_KEY'] = 'robot-control-secret'
CORS(app)
socketio = SocketIO(app, cors_allowed_origins="*", async_mode="gevent")

# تهيئة الوحدات
bt_manager = BluetoothManager(config['bluetooth'])
camera_manager = CameraManager(config['camera'])
motor_controller = MotorController(bt_manager)
sensor_manager = SensorManager()
scenario_manager = ScenarioManager()
```

### Routes (مسارات HTTP)

#### `GET /`
- يعرض الصفحة الرئيسية (index.html)
- تحتوي على الكاميرا + أزرار التحكم + قراءات الحساسات

#### `GET /settings`
- يعرض صفحة الإعدادات (settings.html)
- جميع إعدادات النظام

#### `GET /api/status`
- يرجع حالة النظام بالكامل:
```json
{
    "bluetooth": {"connected": true, "device": "HC-05", "address": "00:XX:XX:XX:XX:XX"},
    "camera": {"running": true, "mode": "RGB", "resolution": "640x480"},
    "motors": {"M1": 0, "M2": 0, "S1": 90, "S2": 90},
    "sensors": {"T": 25.5, "G": 0.2, "H": 60},
    "scenarios_count": 3,
    "uptime": 3600
}
```

#### `GET /api/config`
- يرجع الإعدادات الحالية (config.yaml)

#### `POST /api/config`
- يحدث الإعدادات ويحفظها:
```python
@app.route('/api/config', methods=['POST'])
def update_config():
    new_config = request.json
    # دمج مع الإعدادات الحالية
    # حفظ في config.yaml
    # تطبيق التغييرات على الوحدات
    return jsonify({"success": True})
```

#### `POST /api/command`
- يرسل أمر مباشر للأردوينو:
```python
@app.route('/api/command', methods=['POST'])
def send_command():
    command = request.json  # {"M1": 200, "M2": 200, "S1": 90}
    success = bt_manager.send_json(command)
    return jsonify({"success": success})
```

### WebSocket Events (أحداث Socket.IO)

#### أحداث من العميل → السيرفر

##### `connect`
- عميل جديد اتصل
- إرسال الحالة الحالية

##### `disconnect`
- عميل انقطع
- لو هو آخر عميل → إرسال أمر توقف (S)

##### `move`
- أمر حركة من الأزرار:
```javascript
// Frontend يرسل:
socket.emit('move', { direction: 'F', speed: 200 });
// أو:
socket.emit('move', { M1: 200, M2: 200, S1: 90, S2: 90 });
```
```python
@socketio.on('move')
def handle_move(data):
    motor_controller.execute_move(data)
```

##### `stop`
- أمر توقف:
```javascript
socket.emit('stop');
```

##### `servo_control`
- تحكم بمحرك سيرفو محدد:
```javascript
socket.emit('servo_control', { servo: 'S1', angle: 45 });
```

##### `motor_speed`
- تغيير سرعة محرك:
```javascript
socket.emit('motor_speed', { motor: 'M1', speed: 150 });
```

##### `camera_settings`
- تحديث إعدادات الكاميرا:
```javascript
socket.emit('camera_settings', { color_mode: 'Grayscale', brightness: 70 });
```

##### `bluetooth_scan`
- طلب بحث عن أجهزة:
```python
@socketio.on('bluetooth_scan')
def handle_bluetooth_scan():
    devices = bt_manager.scan_devices()
    emit('bluetooth_devices', devices)
```

##### `bluetooth_connect`
- طلب اتصال بجهاز:
```javascript
socket.emit('bluetooth_connect', { address: '00:XX:XX:XX:XX:XX' });
```

##### `bluetooth_disconnect`
- طلب قطع اتصال

##### `sensor_add`
- إضافة حساس جديد:
```javascript
socket.emit('sensor_add', {
    code: 'P',           // حرف كود
    name: 'Pressure',    // اسم
    unit: 'hPa',         // وحدة
    min: 900,            // حد أدنى
    max: 1100,           // حد أقصى
    warning_high': 1050, // تحذير عالي
    warning_low: 950     // تحذير منخفض
});
```

##### `scenario_save`
- حفظ سيناريو:
```javascript
socket.emit('scenario_save', {
    name: 'patrol_square',
    steps: [
        {"M1": 200, "M2": 200, "duration": 2000},
        {"S1": 0, "duration": 500},
        {"M1": 200, "M2": 200, "duration": 2000},
        {"S1": 180, "duration": 500}
    ]
});
```

##### `scenario_run`
- تنفيذ سيناريو:
```javascript
socket.emit('scenario_run', { name: 'patrol_square' });
```

#### أحداث من السيرفر → العميل

##### `camera_frame`
- بث إطار كاميرا:
```python
socketio.emit('camera_frame', {'data': base64_frame})
```

##### `sensor_data`
- بيانات حساسات جديدة:
```python
socketio.emit('sensor_data', {"T": 25.5, "G": 0.2, "H": 60})
```

##### `bluetooth_status`
- تحديث حالة البلوتوث:
```python
socketio.emit('bluetooth_status', {"connected": True, "name": "HC-05"})
```

##### `bluetooth_devices`
- قائمة أجهزة مكتشفة:
```python
socketio.emit('bluetooth_devices', [{"name": "HC-05", "address": "00:XX:XX:XX:XX:XX"}])
```

##### `motor_status`
- حالة المحركات الحالية:
```python
socketio.emit('motor_status', {"M1": 200, "M2": 200, "S1": 90, "S2": 90})
```

##### `scenario_progress`
- تقدم تنفيذ سيناريو:
```python
socketio.emit('scenario_progress', {"step": 2, "total": 8, "name": "patrol_square"})
```

##### `log`
- رسالة سجل:
```python
socketio.emit('log', {"level": "info", "message": "Connected to HC-05"})
```

##### `error`
- رسالة خطأ:
```python
socketio.emit('error', {"message": "Bluetooth connection lost"})
```

## خيوط الخلفية (Background Threads)

### Thread 1: Camera Stream
```python
def camera_stream_thread():
    while camera_manager.is_running:
        frame = camera_manager.get_frame()
        if frame:
            encoded = base64.b64encode(frame).decode('utf-8')
            socketio.emit('camera_frame', {'data': encoded})
        time.sleep(1.0 / camera_manager.fps)
```

### Thread 2: Sensor Reader
```python
def sensor_read_thread():
    while True:
        if bt_manager.is_connected:
            data = bt_manager.read_json()
            if data:
                sensor_manager.update(data)
                socketio.emit('sensor_data', sensor_manager.get_all())
        time.sleep(0.5)  # قراءة كل 0.5 ثانية
```

### Thread 3: Connection Monitor
```python
def connection_monitor_thread():
    while True:
        if not bt_manager.is_connected and bt_manager.auto_reconnect:
            bt_manager.auto_connect()
            socketio.emit('bluetooth_status', bt_manager.get_status())
        time.sleep(5)
```

## تشغيل السيرفر

```python
if __name__ == '__main__':
    # تشغيل خيوط الخلفية
    threading.Thread(target=camera_stream_thread, daemon=True).start()
    threading.Thread(target=sensor_read_thread, daemon=True).start()
    threading.Thread(target=connection_monitor_thread, daemon=True).start()
    
    # الاتصال التلقائي
    if config['bluetooth']['auto_connect_on_start']:
        bt_manager.auto_connect()
    
    # تشغيل السيرفر
    socketio.run(
        app,
        host='0.0.0.0',       # متاح من أي جهاز في الشبكة
        port=5000,
        debug=False,
        use_reloader=False     # مهم: تجنب مشاكل مع الخيوط
    )
```

## إعدادات السيرفر (في config.yaml)

```yaml
server:
  host: "0.0.0.0"
  port: 5000
  debug: false
  secret_key: "change-this-in-production"
  max_connections: 5
  cors_enabled: true

logging:
  level: "INFO"
  file: "/home/user/program/logs/app.log"
  max_size_mb: 10
```

## معالجة الأخطاء

| الخطأ | المعالجة |
|-------|----------|
| المنفذ 5000 مشغول | محاولة المنفذ 5001, 5002, ... |
| خطأ في WebSocket | إعادة الاتصال تلقائي من Frontend |
| استثناء في خيط خلفية | تسجيل + إعادة تشغيل الخيط |
| استهلاك ذاكرة عالي | تنظيف المخزن المؤقت + تقليل FPS |
