# REP_05e_config_update — تحديث config.yaml

- **الخطة المرجعية:** plans/05_raspberrypi_python_fixes.md (§5.6 — F17)
- **التاريخ:** 2026-05-31
- **المنفّذ:** claude-sonnet-4-6
- **الحالة:** ✅ مكتمل

## 1. المشكلة

ثلاثة مشاكل في `config.yaml`:

- **F17a:** `motors.dc.count: 2` — لا يعكس عدد المحركات الفعلي (4 محركات في مشروع 4WD).
- **F17b:** حساس المطر (`R`) غائب من `sensors.definitions` رغم أن البروتوكول الموحّد (`04_json_protocol.md`) يدعمه.
- **F17c:** المسارات المطلقة `/home/user/program/...` تُفشل التشغيل على أي جهاز آخر.

## 2. الملفات المعدّلة

| الملف | نوع التغيير | ملخص |
|---|---|---|
| `config.yaml` | تعديل — سطر 54 | motors.dc.count: 2 → 4 |
| `config.yaml` | إضافة — sensors.definitions | تعريف حساس المطر (code: "R") |
| `config.yaml` | تعديل — camera | recording_path/photo_path → نسبي |
| `config.yaml` | تعديل — logging | file → "logs/app.log" نسبي |

## 3. التغيير (قبل/بعد)

```diff
# F17a — عدد المحركات
  dc:
-   count: 2
+   count: 4

# F17b — حساس المطر (مضاف بعد حساس المسافة)
+ - code: "R"
+   name: "Rain"
+   unit: "%"
+   icon: "🌧️"
+   min: 0
+   max: 100
+   warn_high: null
+   warn_low: null
+   color: "#2980b9"

# F17c — مسارات نسبية
- recording_path: "/home/user/program/recordings"
- photo_path: "/home/user/program/photos"
+ recording_path: "recordings"
+ photo_path: "photos"

- file: "/home/user/program/logs/app.log"
+ file: "logs/app.log"
```

## 4. كيف تم التحقق

- [x] قراءة الملف قبل التعديل وبعده — البنية YAML صحيحة
- [x] حساس المطر بكود `R` متطابق مع `04_json_protocol.md §2.2`
- [x] `app.py` يستخدم `os.makedirs(os.path.dirname(log_file), exist_ok=True)` — `"logs"` صالح نسبياً
- [ ] تشغيل `python app.py` على Raspberry Pi للتحقق من إنشاء المجلدات

## 5. ملاحظات ومخاطر متبقية

- المسارات النسبية ستُحلّ نسبةً لمجلد العمل الحالي عند تشغيل `python app.py`. يُوصى بتشغيل الأمر من جذر المشروع دائماً.
- `motors.dc.count` مجرد قيمة إعلامية حالياً (لا يقرأها `MotorController` برمجياً)؛ لكنها تعكس الواقع وقد تُستخدم مستقبلاً.
- حساس المطر `R` مضاف للتعريف فقط — لا توجد قيم تحذير افتراضية (warn_high/warn_low: null) لأن قيم المطر تعتمد على السياق.
