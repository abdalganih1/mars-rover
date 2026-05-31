# REP_05b_app_sensor_fixes — إصلاحات app.py للحساسات والمعايرة

- **الخطة المرجعية:** plans/05_raspberrypi_python_fixes.md (§5.2 — F5, F6, F7, F8)
- **التاريخ:** 2026-05-31
- **المنفّذ:** claude-sonnet-4-6
- **الحالة:** ✅ مكتمل

## 1. المشكلة

أربعة أخطاء مستقلة في `app.py`:

- **F5:** `_emit_sensor_list` تستخدم `s.min_value` و`s.max_value` اللتين لا توجدان في كلاس `Sensor`؛ الصحيح `s.min_val`/`s.max_val` — يرمي `AttributeError` ويمنع إرسال قائمة الحساسات للواجهة.
- **F6:** `sensors_mod.init_socketio()` لا يُستدعى أبداً، مما يجعل كل `_emit_sensor_data` و`_emit_sensor_warning` تُبتلع (المتغيّر الوحدي `_socketio` يبقى `None`). السطر `sensor_manager._socketio = socketio` لا أثر له.
- **F7:** لا يوجد ربط بين `BluetoothManager` و`sensor_manager`، فالقراءات الواردة من الأردوينو لا تصل لـ `sensor_manager.update()`.
- **F8:** أحداث SocketIO لمعايرة EEPROM غائبة تماماً.

## 2. الملفات المعدّلة

| الملف | نوع التغيير | ملخص |
|---|---|---|
| `app.py` | تعديل — سطر 434-435 | F5: تصحيح min_value/max_value → min_val/max_val |
| `app.py` | إضافة — بعد socketio | F6: `sensors_mod.init_socketio(socketio)` |
| `app.py` | إضافة — كتلة التهيئة | F7: `bt_manager._sensor_manager = sensor_manager` |
| `app.py` | إضافة — بعد scenario_list | F8: 9 أحداث SocketIO للمعايرة |
| `app.py` | استيراد | إضافة `from modules import sensors as sensors_mod` |

## 3. التغيير (قبل/بعد)

```diff
# F5 — _emit_sensor_list
- "min_value": s.min_value,
- "max_value": s.max_value,
+ "min_value": s.min_val,
+ "max_value": s.max_val,

# F6 — بعد إنشاء socketio
+ sensors_mod.init_socketio(socketio)

# F7 — كتلة التهيئة
- sensor_manager._socketio = socketio  # لا أثر له
+ bt_manager._sensor_manager = sensor_manager

# F8 — أحداث معايرة جديدة (9 أحداث)
+ @socketio.on("calib_run_port")
+ @socketio.on("calib_set_map")
+ @socketio.on("calib_test_dir")
+ @socketio.on("calib_set_invert")
+ @socketio.on("calib_move_servo")
+ @socketio.on("calib_set_servo")
+ @socketio.on("calib_save")
+ @socketio.on("calib_get")
+ @socketio.on("calib_reset")
```

## 4. كيف تم التحقق

- [x] قراءة `sensors.py` — تأكيد أن الخاصية هي `min_val`/`max_val` (سطر 63-64)
- [x] قراءة `sensors.py` — تأكيد وجود `init_socketio()` وأنها تضبط المتغيّر العام `_socketio`
- [x] لا أخطاء تركيبية — Python syntax صحيح
- [ ] اختبار تشغيل على Raspberry Pi

## 5. ملاحظات ومخاطر متبقية

- **F5** كان bug قاتل يمنع `get_settings` من إرجاع قائمة الحساسات.
- **F6** ضروري لأن SensorManager يُرسل الأحداث عبر دالة `_emit` الثابتة التي تقرأ `_socketio` الوحدي، وليس من خاصية الكائن.
- أحداث F8 لا تتحقق من حالة الاتصال (`bt_manager.is_connected`) — إن أُرسل قبل الاتصال سيعيد `False` بصمت. يمكن إضافة تحقق لاحقاً إن لزم.
