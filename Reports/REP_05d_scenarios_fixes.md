# REP_05d_scenarios_fixes — إصلاحات scenarios.py

- **الخطة المرجعية:** plans/05_raspberrypi_python_fixes.md (§5.4 — F12, F13, F14)
- **التاريخ:** 2026-05-31
- **المنفّذ:** claude-sonnet-4-6
- **الحالة:** ✅ مكتمل

## 1. المشكلة

ثلاثة أخطاء في `modules/scenarios.py`:

- **F12:** `ScenarioStep.__init__` يخزّن مفاتيح المحركات بأحرف كبيرة (`M1`, `M2`, `S1`, `S2`) بينما `execute_move` يقرأ أحرفاً صغيرة (`m1`, `m2`, `s1`, `s2`) — لا تنفّذ أي خطوة أي حركة فعلية.
- **F13:** `SCENARIOS_DIR = "/home/user/program/scenarios"` مسار مطلق ثابت لبيئة مختلفة — يرمي `OSError` على أي نظام آخر.
- **F14:** لا تدعم الخطوات حقل `direction`/`speed` — لا يمكن للسيناريو استخدام الاتجاهات العالية المستوى.

## 2. الملفات المعدّلة

| الملف | نوع التغيير | ملخص |
|---|---|---|
| `modules/scenarios.py` | تعديل — سطر 19 | F13: تحويل SCENARIOS_DIR إلى مسار نسبي |
| `modules/scenarios.py` | تعديل — `ScenarioStep.__init__` | F12+F14: تطبيع الأحرف + دعم direction/speed |
| `modules/scenarios.py` | تعديل — استيراد | إضافة `Any` إلى typing |

## 3. التغيير (قبل/بعد)

```diff
# F13 — المسار
- SCENARIOS_DIR = "/home/user/program/scenarios"
+ SCENARIOS_DIR = os.path.join(
+     os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
+     "scenarios"
+ )

# F12 + F14 — ScenarioStep.__init__
- self.motors: Dict[str, int] = {
-     "M1": motors.get("M1", 0),
-     "M2": motors.get("M2", 0),
-     "S1": motors.get("S1", 0),
-     "S2": motors.get("S2", 0),
- }
+ # تطبيع جميع المفاتيح إلى أحرف صغيرة (F12)
+ raw = {k.lower(): v for k, v in motors.items()}
+ self.motors: Dict[str, Any] = {}
+ for key in ("m1", "m2", "m3", "m4"):
+     if key in raw and raw[key] is not None:
+         self.motors[key] = raw[key]
+ for key in ("s1", "s2"):
+     if key in raw and raw[key] is not None:
+         self.motors[key] = raw[key]
+ # دعم direction/speed (F14)
+ if "direction" in raw and raw["direction"] is not None:
+     self.motors["direction"] = raw["direction"]
+ if "speed" in raw and raw["speed"] is not None:
+     self.motors["speed"] = raw["speed"]
```

## 4. كيف تم التحقق

- [x] قراءة `motors.py` — تأكيد أن `execute_move` يقرأ `m1`/`m2`/`direction` بأحرف صغيرة
- [x] قراءة `scenarios.py` — تأكيد أن `_run_loop` يمرّر `step.motors` مباشرة لـ `execute_move`
- [x] لا أخطاء تركيبية — Python syntax صحيح
- [ ] اختبار تشغيل سيناريو على Raspberry Pi

## 5. ملاحظات ومخاطر متبقية

- السلوك القديم كان يخزّن S1/S2 كصفر افتراضي دائماً حتى عند غيابهما — السلوك الجديد يحذف المفاتيح غير الموجودة، مما يعني أن `execute_move` لن يُغيّر السيرفو إن لم تُحدَّد. هذا أصح سلوكاً.
- السيناريوهات المحفوظة قديماً بمفاتيح `M1`/`M2` ستُحمَّل وتُطبَّق صحيحاً الآن بفضل التطبيع في `__init__`.
- أضاف F14 دعم m3/m4 في السيناريوهات — متوافق مع التوسعة في motors.py (F1-F4).
