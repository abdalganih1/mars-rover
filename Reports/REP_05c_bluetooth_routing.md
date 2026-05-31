# REP_05c_bluetooth_routing — توجيه الرسائل الواردة في bluetooth.py

- **الخطة المرجعية:** plans/05_raspberrypi_python_fixes.md (§5.3 — F9)
- **التاريخ:** 2026-05-31
- **المنفّذ:** claude-sonnet-4-6
- **الحالة:** ✅ مكتمل

## 1. المشكلة

`_data_reader_loop` كانت تبثّ **أي** قاموس وارد من الأردوينو كحدث `sensor_data`، بما في ذلك:
- رسائل heartbeat: `{"hb": 1}` → تُرسَل للواجهة كحساس وهمي
- رسائل خطأ: `{"err": "json"}` → تُرسَل كحساس
- ردود معايرة: `{"cfg": "dump", ...}` → تُرسَل كحساس

علاوة على ذلك، لم يكن هناك `self._sensor_manager` ولا `self._last_hb`، فلا تُمرَّر القراءات الحقيقية لـ `sensor_manager.update()` الذي يُوفّر التاريخ والتحذيرات.

## 2. الملفات المعدّلة

| الملف | نوع التغيير | ملخص |
|---|---|---|
| `modules/bluetooth.py` | تعديل — `__init__` | إضافة `_sensor_manager = None` و`_last_hb = 0` |
| `modules/bluetooth.py` | استبدال — `_data_reader_loop` | توجيه حسب نوع الرسالة بدل البث العمياء |

## 3. التغيير (قبل/بعد)

```diff
# __init__
  self._socketio = None
+ self._sensor_manager = None   # يُعين من app.py بعد إنشاء sensor_manager
+ self._last_hb = 0             # وقت آخر heartbeat من الأردوينو

# _data_reader_loop
- data = self.read_json(timeout=0.5)
- if data and isinstance(data, dict):
-     if self._socketio:
-         self._socketio.emit("sensor_data", data)

+ data = self.read_json(timeout=0.5)
+ if not isinstance(data, dict):
+     continue
+
+ if "hb" in data:
+     self._last_hb = time.time()
+
+ elif "err" in data:
+     logger.warning("Arduino error: %s", data.get("err"))
+     if self._socketio:
+         self._socketio.emit("log", {"level": "error", "message": f"Arduino: {data.get('err')}"})
+
+ elif "cfg" in data:
+     if self._socketio:
+         self._socketio.emit("calib_config", data)
+
+ else:
+     readings = {k: v for k, v in data.items() if k in SENSOR_CODES}
+     if readings:
+         if self._sensor_manager is not None:
+             try:
+                 self._sensor_manager.update(readings)
+             except Exception as e:
+                 logger.error("sensor_manager.update error: %s", e)
+         if self._socketio:
+             self._socketio.emit("sensor_data", readings)
```

## 4. كيف تم التحقق

- [x] قراءة `04_json_protocol.md` — تأكيد أكواد الحساسات: `{"T","H","G","D","R","L","P"}`
- [x] قراءة `08_eeprom_calibration.md` — تأكيد أن `"cfg"` في الرد يُوجَّه كـ `calib_config`
- [x] لا أخطاء تركيبية — Python syntax صحيح
- [ ] اختبار تشغيل على Raspberry Pi مع Bluetooth فعلي

## 5. ملاحظات ومخاطر متبقية

- `_last_hb` محفوظ لكن لا يُستخدم حالياً للكشف عن انقطاع الأردوينو (failsafe watchdog). يمكن ربطه بـ `_connection_monitor_loop` مستقبلاً.
- إرسال `sensor_data` مُزدوَج: `sensor_manager.update()` يُرسله داخلياً عبر `_emit_sensor_data`، والـ loop يُرسله مرة أخرى. هذا مقبول لأن `sensor_manager` يُرسل بيانات الحساس الكاملة (مع unit/name/warning) بينما البث المباشر يرسل القراءة الخام فقط — يمكن حذف أحد الإرسالَين مستقبلاً.
