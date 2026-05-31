# REP_05a_motors_4wd — دعم 4 محركات في MotorController

- **الخطة المرجعية:** plans/05_raspberrypi_python_fixes.md (§5.1 — F1, F2, F3, F4)
- **التاريخ:** 2026-05-31
- **المنفّذ:** claude-sonnet-4-6
- **الحالة:** ✅ مكتمل

## 1. المشكلة

`MotorController` كان يدعم محركَين فقط (m1, m2) في الحالة الداخلية والـ payload المرسَل.
- **F1:** لا يوجد `_m3_speed` / `_m4_speed` في `__init__` ولا في `get_state`/`emergency_stop`.
- **F2:** `DIRECTION_PRESETS` تستخدم مفاتيح `m1`/`m2` مما يعقّد التوسعة لـ 4 عجلات؛ الموصى به هو `l`/`r` (يسار/يمين) ومن ثم توزيعهما على m1=m3 و m2=m4.
- **F3:** `_build_command` يُضيف `"type": "motor"` الذي يجب حذفه بحسب البروتوكول الموحّد (`04_json_protocol.md`).
- **F4:** `execute_move` لا يعالج m3/m4 في الأمر المباشر، وكذلك `emergency_stop` لا يرسل m3=m4=0.

## 2. الملفات المعدّلة

| الملف | نوع التغيير | ملخص |
|---|---|---|
| `modules/motors.py` | تعديل شامل | F1: إضافة _m3_speed/_m4_speed؛ F2: DIRECTION_PRESETS بمفاتيح l/r؛ F3: حذف "type"؛ F4: معالجة m3/m4 في كل الدوال |

## 3. التغيير (قبل/بعد)

```diff
# F1 — __init__
- self._m1_speed: int = 0
- self._m2_speed: int = 0
+ self._m1_speed: int = 0
+ self._m2_speed: int = 0
+ self._m3_speed: int = 0
+ self._m4_speed: int = 0

# F2 — DIRECTION_PRESETS
- "F": {"m1": 200, "m2": 200},
- "L": {"m1": -150, "m2": 150},
+ "F": {"l": 200, "r": 200},
+ "L": {"l": -150, "r": 150},
# ... وهكذا لكل الاتجاهات

# F3 — _build_command
- cmd: Dict[str, Any] = {"type": "motor"}
+ cmd: Dict[str, Any] = {}
# إضافة m3/m4 كمعاملات اختيارية

# F4 — execute_move (direction path)
- target_m1 = int(preset["m1"] * speed_scale)
- target_m2 = int(preset["m2"] * speed_scale)
- payload = self._build_command(m1=..., m2=...)
+ l = int(preset["l"] * speed_scale)
+ r = int(preset["r"] * speed_scale)
+ m1 = m3 = clamp(l);  m2 = m4 = clamp(r)
+ payload = self._build_command(m1=m1, m2=m2, m3=m3, m4=m4)

# F4 — emergency_stop
- payload = self._build_command(m1=0, m2=0, s1=90, s2=90)
+ payload = self._build_command(m1=0, m2=0, m3=0, m4=0, s1=90, s2=90)
```

## 4. كيف تم التحقق

- [x] قراءة الملف قبل التعديل — تحقّق من بنية الكلاسات
- [x] لا أخطاء تركيبية — Python syntax صحيح
- [ ] اختبار تشغيل على Raspberry Pi (يحتاج عتاد فعلي)
- [x] لا يكسر دوال موجودة: `set_motor_speed`, `set_servo_angle`, `center_servos` تعمل كما كانت

## 5. ملاحظات ومخاطر متبقية

- `set_motor_speed(m1, m2)` تُعيّن m3=m1 و m4=m2 تلقائياً (سلوك معقول لـ 4WD).
- تمت إضافة `set_side_speed(left, right)` كدالة مساعدة صريحة.
- رمز الـ ramp thread يُحدّث الآن m3/m4 بالتوازي مع m1/m2.
- `get_state()` يعيد الآن m3/m4 أيضاً — تأكّد من أن الواجهة الأمامية لا تعتمد على عدد ثابت من المفاتيح.
