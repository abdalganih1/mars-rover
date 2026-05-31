# 05 — إصلاحات كود الراسبيري باي (Python)

إصلاحات دقيقة لكل ملف، مع أرقام الأسطر المرجعية (قد تتغيّر قليلاً بعد التعديل).
كل بند مرقّم = تقرير مستقل محتمل في `Reports/`.

---

## 5.1 `modules/motors.py` — دعم 4 محركات + توحيد

### F1 — توسعة الحالة إلى m3/m4
**الحالي (أسطر 56–60):** `_m1_speed`, `_m2_speed`, `_s1_angle`, `_s2_angle` فقط.
**المطلوب:** أضف `_m3_speed`, `_m4_speed` (افتراضي 0) وعالجها في `set_motor_speed`, `get_state`, `_build_command`, `emergency_stop`.

### F2 — جداول التوجيه لـ 4 عجلات
**الحالي (أسطر 31–43):** `DIRECTION_PRESETS` تحوي m1/m2 فقط.
**المطلوب:** خياران:
- **(أ) إبقاء الواجهة بجهتين** (left/right) وتحويلها في `_build_command` إلى m1=m3=left و m2=m4=right.
- **(ب)** توسيع الجداول لـ m1..m4 صراحةً.
موصى به (أ) لأنه أبسط ويطابق منطق الأردوينو `driveSides`. مثال:
```python
DIRECTION_PRESETS = {
  "F":{"l":200,"r":200}, "B":{"l":-200,"r":-200},
  "L":{"l":-150,"r":150}, "R":{"l":150,"r":-150},
  "S":{"l":0,"r":0},
  "FL":{"l":100,"r":200}, "FR":{"l":200,"r":100},
  "BL":{"l":-100,"r":-200}, "BR":{"l":-200,"r":-100},
  "SPIN_L":{"l":-200,"r":200}, "SPIN_R":{"l":200,"r":-200},
}
# عند الإرسال: m1=m3=l ، m2=m4=r
```

### F3 — توحيد الـ payload مع البروتوكول
**الحالي (أسطر 340–357):** `_build_command` يضيف `"type":"motor"`.
**المطلوب:** احذف `"type"` (انظر `04_json_protocol.md`). أرسل m1..m4/s1/s2 فقط.

### F4 — تقليل عدد الإرسالات
**الحالي (أسطر 244–253):** المحركات والسيرفو يُرسلان في payload منفصلين أحياناً (إرسالان).
**المطلوب:** ادمج كل التغييرات في رسالة JSON واحدة قدر الإمكان لتقليل ازدحام HC-05.

---

## 5.2 `app.py` — باگات مؤكدة

### F5 — 🐞 `_emit_sensor_list` يستخدم سمات غير موجودة
**الحالي (أسطر 425–441):**
```python
"min_value": s.min_value,   # ❌ غير موجودة
"max_value": s.max_value,   # ❌ غير موجودة
```
كائن `Sensor` يملك `min_val`/`max_val` (انظر `sensors.py:63-64`). هذا يرمي `AttributeError`
ويُفشل إرسال قائمة الحساسات بالكامل.
**المطلوب:**
```python
"min_value": s.min_val,
"max_value": s.max_val,
```
(أو وحّد الأسماء في `Sensor`). تحقّق أيضاً من `s.enabled` (غير موجود — `getattr` افتراضي آمن، أبقه).

### F6 — 🐞 SocketIO غير مربوط بوحدة الحساسات
**الحالي (أسطر 83, 88):** `sensor_manager = SensorManager()` ثم `sensor_manager._socketio = socketio`.
لكن `sensors.py` يبثّ عبر **متغيّر وحدة عام** `_socketio` يُضبط فقط بـ `init_socketio()`
(`sensors.py:21-25`) الذي **لا يُستدعى أبداً** → كل `_emit_sensor_data/_emit_sensor_warning` تُبتلع.
**المطلوب:** بعد إنشاء `socketio`:
```python
from modules import sensors as sensors_mod
sensors_mod.init_socketio(socketio)
```
واحذف السطر المضلّل `sensor_manager._socketio = socketio` (لا أثر له).

### F7 — ربط قراءات الأردوينو بمدير الحساسات
**الحالي:** لا شيء يستدعي `sensor_manager.update()` ببيانات حقيقية → التاريخ/الرسوم/التحذيرات فارغة.
**المطلوب:** مرّر `sensor_manager` إلى `BluetoothManager` (مُنشئ أو setter) ووجّه القراءات إليه
(انظر F9 و`04_json_protocol.md §3`).

### F8 — اتساق الإعدادات الافتراضية
**الحالي (أسطر 490–509):** `reset_settings` يبني `default_config` ناقص حقولاً موجودة في `config.yaml`
(camera brightness=0 مقابل 50، يفقد `sensors.definitions`, إلخ).
**المطلوب:** اجعل الافتراضي مطابقاً لبنية `config.yaml` الحالية (أو حمّله من ملف افتراضي مرجعي).

---

## 5.3 `modules/bluetooth.py` — توجيه الرسائل

### F9 — 🐞 `_data_reader_loop` يبثّ كل شيء كـ sensor_data
**الحالي (أسطر 303–315):** أي قاموس وارد يُبثّ `sensor_data` (يشمل heartbeat/ack/error).
**المطلوب:** توجيه حسب النوع + تمرير القراءات لـ `sensor_manager.update()` (الكود في `04 §3`).
أضف حقل `self._sensor_manager` و`self._last_hb`.

### F10 — مهلة pairing/اتصال
**الحالي (أسطر 98–150):** `connect()` يعمل pair/trust/rfcomm bind في كل اتصال (بطيء، وقد يطلب PIN).
**المطلوب (تحسين):** تخطّي pair/trust إن كان الجهاز مقترناً مسبقاً؛ وثّق أن HC-05 PIN غالباً `1234`/`0000`،
وأن `rfcomm bind` قد يحتاج صلاحيات (المشروع يستخدم `sudo` بالفعل).

### F11 — تنظيف ازدواج المنطق
`read_data/read_json` في BluetoothManager تكرّر `serial_comm`؛ مقبول، لكن تأكّد أن
خيط القراءة وخيط المراقبة لا يتنافسان على نفس القفل بشكل يسبب تجويعاً (القفل موجود في `serial_comm.py:21`).

---

## 5.4 `modules/scenarios.py` — باگات مؤكدة

### F12 — 🐞 تعارض حالة الأحرف (M1 مقابل m1)
**الحالي (أسطر 33–38, 346):** الخطوة تخزّن `M1/M2/S1/S2` (كبيرة) وتُمرَّر إلى
`motor_controller.execute_move(step.motors)`. لكن `execute_move` (motors.py:181, 219-222)
يقرأ `direction` أو `m1/m2/s1/s2` (صغيرة) → **لا تنفّذ الخطوة أي حركة**.
**المطلوب:** إمّا:
- حوّل المفاتيح إلى صغيرة قبل التمرير: `{k.lower():v for k,v in step.motors.items()}`، أو
- اجعل `execute_move` غير حسّاس لحالة الأحرف.
موصى به: تطبيع المفاتيح في `ScenarioStep` إلى الشكل الذي يفهمه `execute_move`.

### F13 — 🐞 مسار مطلق ثابت
**الحالي (سطر 19):** `SCENARIOS_DIR = "/home/user/program/scenarios"` + `os.makedirs` في `__init__`.
**المطلوب:** اجعله نسبياً للمشروع:
```python
SCENARIOS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scenarios")
```

### F14 — دعم خطوات الاتجاه في السيناريو
بما أن السيناريو يعتمد على `motors` فقط، اسمح للخطوة بحمل `{"direction":"F","speed":..}`
بالإضافة لـ m1..m4 (يمرّرها `execute_move` أصلاً).

---

## 5.5 `modules/sensors.py`

### F15 — مسار ملف الإعدادات
**الحالي (أسطر 134–136):** `DEFAULT_CONFIG_PATH = .../config/sensors.json` بينما المشروع يستخدم `config.yaml`،
ولا يوجد مجلد `config/`. غير قاتل (الافتراضيات + yaml تُحمّل في app.py)، لكن وحّد المصدر:
**المطلوب:** إمّا إزالة `save_config/load_config` المعتمدة على `config/sensors.json`، أو توجيهها لمسار نسبي
واضح (`<root>/config/sensors.json`) وإنشاء المجلد عند الحفظ فقط.

### F16 — توحيد أسماء سمات Sensor
يملك `Sensor` كلاً من `min_val/max_val` و(في `to_dict`) يصدّرهما كـ `min_val/max_val`؛
لكن الواجهة/`_emit_sensor_list` تستخدم `min_value/max_value`. وحّد التسمية في كل المسارات
(يفضّل اعتماد `min_value/max_value` في الـ JSON المرسل للواجهة مع الإبقاء على `min_val/max_val` داخلياً،
وهو ما يصلحه F5).

---

## 5.6 `config.yaml`

### F17 — تحديثات الإعدادات
- `motors.dc.count: 2` → **`4`** (سطر 54).
- أضف تعريف حساس **المطر** ضمن `sensors.definitions`:
```yaml
- code: "R"
  name: "Rain"
  unit: "%"
  icon: "🌧️"
  min: 0
  max: 100
  warn_high: null
  warn_low: null
  color: "#2980b9"
```
- حوّل المسارات المطلقة إلى نسبية:
  - `camera.recording_path`, `camera.photo_path` (أسطر 40–41)
  - `logging.file` (سطر 104)
  مثال: `recordings`, `photos`, `logs/app.log` (مع إنشائها نسبةً لجذر المشروع في app.py).

---

## 5.7 `requirements.txt`

### F18 — تضارب حلقات الأحداث
يضمّ `eventlet` و`gevent` و`gevent-websocket` معاً بينما `app.py` يستخدم
`async_mode="threading"` (`app.py:52`). غير قاتل لكنه مربك ويزيد التبعيات.
**المطلوب:** ثبّت على وضع واحد. إن بقي `threading` فيمكن إزالة `eventlet`/`gevent*`
(أو وثّق سبب إبقائها). لا تغيّر دون اختبار التشغيل.

---

## ✅ قائمة تحقق عامة بعد إصلاحات البايثون

- [ ] `python app.py` يقلع دون استثناءات.
- [ ] فتح الواجهة → قائمة الحساسات تظهر (F5/F6 يعملان).
- [ ] حقن قراءة وهمية → تظهر في الواجهة مع تاريخ/تحذير (F7/F9).
- [ ] تشغيل سيناريو بسيط → المحركات تتحرك فعلاً (F12).
- [ ] لا مسارات مطلقة `/home/user/...` متبقية (F13/F17).
