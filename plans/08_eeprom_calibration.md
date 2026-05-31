# 08 — نظام المعايرة والإعدادات عبر EEPROM (بدون إعادة برمجة)

> الهدف: الأردوينو يخزّن كل إعدادات المحركات والسيرفو في **EEPROM**، ويستقبل تعديلاتها
> **عبر البلوتوث (JSON)** من صفحة إعدادات بالراسبيري باي، ويحفظها — بحيث **لا تحتاج إعادة رفع
> برنامج الأردوينو** عند كل تغيير. أول رفعة فقط تكتب قيم افتراضية.

هذا يحلّ مشاكل لا يمكن معرفتها إلا بعد التركيب الفعلي:
- أي منفذ M1..M4 بالشيلد يقابل أي عجلة (أمامي يمين/يسار، خلفي يمين/يسار).
- اتجاه دوران كل محرك (هل "أمام" منطقياً = FORWARD أم BACKWARD كهربائياً).
- أي سيرفو هو سيرفو التوجيه يمين/يسار، واتجاهه، وحدوده الميكانيكية (زاوية صغرى/عظمى/مركز).

---

## 1. الفكرة بالكامل (Flow)

```
[أول رفعة للأردوينو]
   └─> يفحص EEPROM: هل البايت السحري (MAGIC) موجود؟
         ├─ لا  → يكتب إعدادات افتراضية (DEFAULT_CONFIG) + MAGIC
         └─ نعم → يحمّل الإعدادات المخزّنة
   └─> يطبّق الإعدادات على المحركات/السيرفو وقت التشغيل

[لاحقاً — من صفحة الإعدادات بالراسبيري]
   └─> "ضبط المحركات": شغّل منفذ 1 → المستخدم يحدّد أي عجلة تحرّكت + اتجاهها
   └─> "ضبط السيرفو": حرّك سيرفو لزاوية → المستخدم يحدّد جهته + حدوده
   └─> الراسبيري يرسل JSON تحديث → الأردوينو يطبّق فوراً
   └─> المستخدم يضغط "حفظ" → الأردوينو يكتب EEPROM (يبقى بعد إعادة التشغيل)
```

> ⚠️ EEPROM في الـ ATmega328 سعتها 1024 بايت وتتحمّل ~100,000 دورة كتابة لكل بايت.
> لذلك **لا نكتب EEPROM إلا عند "حفظ" صريح**، وليس عند كل تعديل تجريبي.

---

## 2. بنية الإعدادات (Config Struct)

تُخزّن ككتلة ثنائية واحدة في EEPROM من العنوان 0.

```cpp
#include <EEPROM.h>

#define CFG_MAGIC   0xA5    // علامة "الإعدادات صالحة"
#define CFG_VERSION 1       // رقم نسخة المخطط (نزيده لو غيّرنا البنية)
#define CFG_ADDR    0       // عنوان البداية في EEPROM

struct RobotConfig {
  uint8_t magic;            // = CFG_MAGIC إذا كانت صالحة
  uint8_t version;          // = CFG_VERSION

  // ── ربط العجلات: أي منفذ شيلد (1..4) لكل عجلة منطقية ──
  uint8_t port_FL;          // Front-Left  → منفذ 1..4
  uint8_t port_FR;          // Front-Right
  uint8_t port_RL;          // Rear-Left
  uint8_t port_RR;          // Rear-Right

  // ── عكس اتجاه كل عجلة (1 = اعكس) ──
  uint8_t inv_FL;
  uint8_t inv_FR;
  uint8_t inv_RL;
  uint8_t inv_RR;

  // ── السيرفو 1 ──
  uint8_t s1_role;          // 0 = توجيه، 1 = كاميرا/أخرى (اختياري)
  uint8_t s1_min;           // الزاوية الصغرى المسموحة (قيد ميكانيكي)
  uint8_t s1_max;           // الزاوية العظمى المسموحة
  uint8_t s1_center;        // زاوية المنتصف/الراحة
  uint8_t s1_invert;        // 1 = اعكس اتجاه الزاوية (180 - angle)

  // ── السيرفو 2 ──
  uint8_t s2_role;
  uint8_t s2_min;
  uint8_t s2_max;
  uint8_t s2_center;
  uint8_t s2_invert;

  // ── عام ──
  uint8_t default_speed;    // سرعة افتراضية 0..255

  uint8_t checksum;         // XOR لكل البايتات قبله (تحقّق سلامة)
};

RobotConfig cfg;
```

### القيم الافتراضية (أول رفعة)

```cpp
void loadDefaults() {
  cfg.magic   = CFG_MAGIC;
  cfg.version = CFG_VERSION;
  // ربط مبدئي 1:1 (يصحّحه المستخدم لاحقاً بالمعايرة)
  cfg.port_FL = 1; cfg.port_FR = 2; cfg.port_RL = 3; cfg.port_RR = 4;
  cfg.inv_FL = 0; cfg.inv_FR = 0; cfg.inv_RL = 0; cfg.inv_RR = 0;
  cfg.s1_role = 0; cfg.s1_min = 0;  cfg.s1_max = 180; cfg.s1_center = 90; cfg.s1_invert = 0;
  cfg.s2_role = 0; cfg.s2_min = 0;  cfg.s2_max = 180; cfg.s2_center = 90; cfg.s2_invert = 0;
  cfg.default_speed = 200;
}
```

---

## 3. دوال EEPROM (تحميل/حفظ/تحقّق)

```cpp
uint8_t calcChecksum(const RobotConfig &c) {
  const uint8_t *p = (const uint8_t*)&c;
  uint8_t x = 0;
  for (size_t i = 0; i < sizeof(RobotConfig) - 1; i++) x ^= p[i];  // كل شيء عدا checksum
  return x;
}

void saveConfig() {
  cfg.magic = CFG_MAGIC;
  cfg.version = CFG_VERSION;
  cfg.checksum = calcChecksum(cfg);
  EEPROM.put(CFG_ADDR, cfg);            // EEPROM.put لا يكتب البايت إن لم يتغيّر (يقلّل التآكل)
}

bool loadConfig() {
  EEPROM.get(CFG_ADDR, cfg);
  if (cfg.magic != CFG_MAGIC || cfg.version != CFG_VERSION
      || cfg.checksum != calcChecksum(cfg)) {
    loadDefaults();
    saveConfig();                       // أول رفعة: اكتب الافتراضي
    return false;                       // لم تكن هناك إعدادات صالحة
  }
  return true;                          // حُمّلت إعدادات صالحة
}
```

> **"البرنامج الأولي" الذي طلبته** = هذا المنطق: عند أول تشغيل تكون EEPROM فارغة/عشوائية،
> فلا يطابق MAGIC → يكتب `loadDefaults()` (القيمة الثابتة) ثم يحفظها. بعدها أي تعديل عبر
> البلوتوث + حفظ يحلّ محلّها دون إعادة برمجة.

---

## 4. تطبيق الإعدادات وقت التشغيل

### 4.1 المحركات (ربط منطقي + عكس)

```cpp
AF_DCMotor motors[4] = { AF_DCMotor(1), AF_DCMotor(2), AF_DCMotor(3), AF_DCMotor(4) };

// يشغّل منفذ فيزيائي 1..4 بسرعة موقّعة (للمعايرة)
void runPort(uint8_t port, int speed) {
  if (port < 1 || port > 4) return;
  AF_DCMotor &m = motors[port - 1];
  speed = constrain(speed, -255, 255);
  if (speed > 0)      { m.setSpeed(speed);  m.run(FORWARD); }
  else if (speed < 0) { m.setSpeed(-speed); m.run(BACKWARD); }
  else                { m.setSpeed(0);      m.run(RELEASE); }
}

// يشغّل عجلة منطقية مع تطبيق منفذها وعكسها من cfg
void runWheel(uint8_t port, uint8_t invert, int speed) {
  runPort(port, invert ? -speed : speed);
}

// driveSides يستخدم cfg
void driveSides(int left, int right) {
  runWheel(cfg.port_FL, cfg.inv_FL, left);
  runWheel(cfg.port_RL, cfg.inv_RL, left);
  runWheel(cfg.port_FR, cfg.inv_FR, right);
  runWheel(cfg.port_RR, cfg.inv_RR, right);
}
```

### 4.2 السيرفو (حدود + عكس + مركز)

```cpp
Servo servo1, servo2;

int applyServoLimits(int angle, uint8_t mn, uint8_t mx, uint8_t invert) {
  if (invert) angle = 180 - angle;
  return constrain(angle, mn, mx);
}

void writeServo1(int angle) { servo1.write(applyServoLimits(angle, cfg.s1_min, cfg.s1_max, cfg.s1_invert)); }
void writeServo2(int angle) { servo2.write(applyServoLimits(angle, cfg.s2_min, cfg.s2_max, cfg.s2_invert)); }

// في setup بعد attach: ضع كل سيرفو على مركزه
// writeServo1(cfg.s1_center); writeServo2(cfg.s2_center);
```

---

## 5. بروتوكول المعايرة عبر JSON (الأردوينو ↔ الراسبيري)

كل الرسائل سطر JSON واحد منتهٍ بـ `\n` عبر `btSerial` (انظر `04_json_protocol.md`).

### 5.1 قراءة الإعدادات الحالية
الراسبيري → الأردوينو:
```json
{"cfg":"get"}
```
الأردوينو → الراسبيري (يرجع كل القيم):
```json
{"cfg":"dump","port_FL":1,"port_FR":2,"port_RL":3,"port_RR":4,
 "inv_FL":0,"inv_FR":0,"inv_RL":0,"inv_RR":0,
 "s1_min":0,"s1_max":180,"s1_center":90,"s1_invert":0,
 "s2_min":0,"s2_max":180,"s2_center":90,"s2_invert":0,
 "default_speed":200,"ver":1}
```

### 5.2 معايرة المحركات
**(أ) تشغيل منفذ فيزيائي مفرد ليرى المستخدم أي عجلة تتحرك:**
```json
{"cal":"port","port":1,"spd":150,"ms":700}
```
الأردوينو يشغّل المنفذ 1 للأمام لمدة `ms` ثم يوقفه (RELEASE).

**(ب) تعيين ربط العجلات** (بعد ما عرف المستخدم أي منفذ = أي عجلة):
```json
{"cfg":"map","FL":3,"FR":1,"RL":4,"RR":2}
```

**(ج) اختبار اتجاه عجلة منطقية** (يشغّلها "للأمام" منطقياً):
```json
{"cal":"dir","wheel":"FL","spd":150,"ms":700}
```
المستخدم يلاحظ: هل دارت بالاتجاه الذي يدفع الروبوت **للأمام**؟
- إذا لا → اعكسها:
```json
{"cfg":"inv","wheel":"FL","invert":1}
```

### 5.3 معايرة السيرفو
**(أ) تحريك سيرفو لزاوية ليرى المستخدم أيّه وأين يتجه:**
```json
{"cal":"servo","id":1,"angle":0}
```
ثم `{"cal":"servo","id":1,"angle":180}` ليرى المدى.

**(ب) ضبط الحدود/العكس/المركز:**
```json
{"cfg":"servo","id":1,"min":20,"max":160,"center":95,"invert":0}
```
(تستخدم الحدود لو كان هناك قيد ميكانيكي يمنع 0..180 كاملة).

### 5.4 الحفظ في EEPROM
```json
{"cfg":"save"}
```
الأردوينو يحفظ ويردّ:
```json
{"cfg":"saved"}
```

### 5.5 إعادة الضبط للمصنع
```json
{"cfg":"reset"}
```
→ `loadDefaults()` + `saveConfig()` ثم `{"cfg":"reset_done"}`.

---

## 6. معالج الأوامر في الأردوينو (داخل processJson)

```cpp
void handleCfg(JsonDocument &doc) {
  const char* cmd = doc["cfg"];                 // get/map/inv/servo/save/reset
  if (!cmd) return;

  if (!strcmp(cmd, "get"))   { dumpConfig(); }
  else if (!strcmp(cmd, "map")) {
    if (doc["FL"].is<int>()) cfg.port_FL = doc["FL"];
    if (doc["FR"].is<int>()) cfg.port_FR = doc["FR"];
    if (doc["RL"].is<int>()) cfg.port_RL = doc["RL"];
    if (doc["RR"].is<int>()) cfg.port_RR = doc["RR"];
  }
  else if (!strcmp(cmd, "inv")) {
    const char* w = doc["wheel"]; uint8_t v = doc["invert"] | 0;
    if (!strcmp(w,"FL")) cfg.inv_FL=v; else if (!strcmp(w,"FR")) cfg.inv_FR=v;
    else if (!strcmp(w,"RL")) cfg.inv_RL=v; else if (!strcmp(w,"RR")) cfg.inv_RR=v;
  }
  else if (!strcmp(cmd, "servo")) {
    uint8_t id = doc["id"] | 1;
    if (id == 1) {
      if (doc["min"].is<int>())    cfg.s1_min=doc["min"];
      if (doc["max"].is<int>())    cfg.s1_max=doc["max"];
      if (doc["center"].is<int>()) cfg.s1_center=doc["center"];
      if (doc["invert"].is<int>()) cfg.s1_invert=doc["invert"];
    } else {
      if (doc["min"].is<int>())    cfg.s2_min=doc["min"];
      if (doc["max"].is<int>())    cfg.s2_max=doc["max"];
      if (doc["center"].is<int>()) cfg.s2_center=doc["center"];
      if (doc["invert"].is<int>()) cfg.s2_invert=doc["invert"];
    }
  }
  else if (!strcmp(cmd, "save"))  { saveConfig();  btSerial.println(F("{\"cfg\":\"saved\"}")); }
  else if (!strcmp(cmd, "reset")) { loadDefaults(); saveConfig(); btSerial.println(F("{\"cfg\":\"reset_done\"}")); }
}

void handleCal(JsonDocument &doc) {
  const char* what = doc["cal"];                // port/dir/servo
  int spd = doc["spd"] | 150;
  int ms  = doc["ms"]  | 700;
  if (!strcmp(what, "port")) {
    runPort(doc["port"] | 0, spd);
    delay(ms); runPort(doc["port"] | 0, 0);     // delay مقبول هنا (وضع معايرة فقط)
  } else if (!strcmp(what, "dir")) {
    const char* w = doc["wheel"];
    uint8_t port=0, inv=0;
    if (!strcmp(w,"FL")){port=cfg.port_FL;inv=cfg.inv_FL;}
    else if (!strcmp(w,"FR")){port=cfg.port_FR;inv=cfg.inv_FR;}
    else if (!strcmp(w,"RL")){port=cfg.port_RL;inv=cfg.inv_RL;}
    else if (!strcmp(w,"RR")){port=cfg.port_RR;inv=cfg.inv_RR;}
    runWheel(port, inv, spd); delay(ms); runWheel(port, inv, 0);
  } else if (!strcmp(what, "servo")) {
    uint8_t id = doc["id"] | 1; int a = doc["angle"] | 90;
    if (id==1) writeServo1(a); else writeServo2(a);
  }
}
```
> في `processJson`: إذا `doc["cfg"]` موجود → `handleCfg`؛ إذا `doc["cal"]` موجود → `handleCal`؛
> غير ذلك → أوامر الحركة العادية (dir/m1../stop). **حدّث الـ failsafe ليتجاهل وضع المعايرة**
> أو يستخدم delay القصير فيه فقط.

```cpp
void dumpConfig() {
  JsonDocument d;
  d["cfg"]="dump";
  d["port_FL"]=cfg.port_FL; d["port_FR"]=cfg.port_FR; d["port_RL"]=cfg.port_RL; d["port_RR"]=cfg.port_RR;
  d["inv_FL"]=cfg.inv_FL; d["inv_FR"]=cfg.inv_FR; d["inv_RL"]=cfg.inv_RL; d["inv_RR"]=cfg.inv_RR;
  d["s1_min"]=cfg.s1_min; d["s1_max"]=cfg.s1_max; d["s1_center"]=cfg.s1_center; d["s1_invert"]=cfg.s1_invert;
  d["s2_min"]=cfg.s2_min; d["s2_max"]=cfg.s2_max; d["s2_center"]=cfg.s2_center; d["s2_invert"]=cfg.s2_invert;
  d["default_speed"]=cfg.default_speed; d["ver"]=cfg.version;
  serializeJson(d, btSerial); btSerial.println();
}
```

---

## 7. صفحة الإعدادات في الراسبيري باي (معالج المعايرة - Wizard)

تُضاف تبويبة جديدة في `templates/settings.html` باسم **"ضبط المحركات والسيرفو"**،
وأحداث SocketIO في `app.py` تُمرّر الأوامر إلى `bt_manager.send_json(...)`.

### 7.1 معالج معايرة المحركات (خطوة بخطوة كما طلبت)

```
الخطوة 1 — تحديد مواقع العجلات:
  • الواجهة ترسل {"cal":"port","port":1,"spd":150,"ms":700}
  • تسأل المستخدم: «أي عجلة تحرّكت؟»  [أمامي يمين | أمامي يسار | خلفي يمين | خلفي يسار]
  • يكرّر للمنافذ 2,3,4
  • بعد تحديد الأربعة → ترسل {"cfg":"map","FL":..,"FR":..,"RL":..,"RR":..}

الخطوة 2 — تحديد اتجاه الدوران لكل عجلة:
  • الواجهة ترسل {"cal":"dir","wheel":"FL","spd":150,"ms":700}
  • تسأل: «بأي اتجاه دارت العجلة؟»  [للأمام (يدفع الروبوت للأمام) | للخلف]
  • إن كانت "للخلف" → ترسل {"cfg":"inv","wheel":"FL","invert":1}
  • يكرّر لكل عجلة (FL,FR,RL,RR)

الخطوة 3 — حفظ:
  • ترسل {"cfg":"save"} وتنتظر {"cfg":"saved"}
```

### 7.2 معالج معايرة السيرفو

```
الخطوة 1 — تمييز السيرفو واتجاهه:
  • ترسل {"cal":"servo","id":1,"angle":0} ثم بعد ثانية {"cal":"servo","id":1,"angle":180}
  • تسأل: «أي سيرفو تحرّك؟ ولأي جهة عند الزاوية 0؟»  [توجيه يمين | توجيه يسار]
  • إن كان اتجاهه معكوساً عن المطلوب → invert=1

الخطوة 2 — ضبط الحدود (قيود ميكانيكية):
  • منزلقات (sliders) للزاوية الصغرى/العظمى/المركز، تبثّ {"cal":"servo","id":1,"angle":X}
    حيّاً ليرى المستخدم الحركة دون كسر الميكانيك.
  • عند الرضا → {"cfg":"servo","id":1,"min":..,"max":..,"center":..,"invert":..}

الخطوة 3 — حفظ:
  • {"cfg":"save"}
```

### 7.3 أحداث SocketIO المقترحة في app.py

| الحدث (من الواجهة) | الإجراء |
|---|---|
| `calib_run_port` `{port,spd,ms}` | `bt_manager.send_json({"cal":"port",...})` |
| `calib_set_map` `{FL,FR,RL,RR}` | `send_json({"cfg":"map",...})` |
| `calib_test_dir` `{wheel,spd,ms}` | `send_json({"cal":"dir",...})` |
| `calib_set_invert` `{wheel,invert}` | `send_json({"cfg":"inv",...})` |
| `calib_move_servo` `{id,angle}` | `send_json({"cal":"servo",...})` |
| `calib_set_servo` `{id,min,max,center,invert}` | `send_json({"cfg":"servo",...})` |
| `calib_save` | `send_json({"cfg":"save"})` |
| `calib_get` | `send_json({"cfg":"get"})` ثم عرض الـ `dump` الوارد |
| `calib_reset` | `send_json({"cfg":"reset"})` |

> ملاحظة: استقبال `{"cfg":"dump"...}` في `bluetooth._data_reader_loop` يجب أن يُوجَّه كحدث
> `calib_config` للواجهة (ليس كحساس) — أضِف هذا للتوجيه في `04_json_protocol.md §3`.

---

## 8. تعديلات مطلوبة على الملفات

| الملف | التعديل |
|---|---|
| `robot_controller.ino` | إضافة `#include <EEPROM.h>` + struct + load/save/checksum + handleCfg/handleCal + dumpConfig + استخدام cfg في driveSides/servo |
| `modules/bluetooth.py` | توجيه `{"cfg":"dump"}` و`{"cfg":"saved"}`/`reset_done` كحدث `calib_*` للواجهة |
| `app.py` | أحداث SocketIO الواردة في §7.3 |
| `templates/settings.html` | تبويبة "ضبط المحركات والسيرفو" + معالج الأسئلة |
| `static/js/` (إن وُجد) | منطق المعالج خطوة بخطوة |

---

## 9. قائمة تحقق

- [ ] أول رفعة: EEPROM فارغة → يكتب الافتراضي (تحقّق عبر `{"cfg":"get"}`).
- [ ] `{"cal":"port","port":1}` يحرّك منفذاً واحداً فقط.
- [ ] تعيين الربط `{"cfg":"map",...}` ثم `dir` يحرّك العجلة المنطقية الصحيحة.
- [ ] `{"cfg":"inv",...}` يعكس الاتجاه فعلاً.
- [ ] حدود السيرفو تمنع تجاوز min/max.
- [ ] `{"cfg":"save"}` → بعد فصل الكهرباء وإعادتها تبقى الإعدادات (loadConfig يرجع true).
- [ ] checksum يكتشف الفساد (غيّر بايتاً يدوياً → يرجع للافتراضي).
- [ ] لا إعادة برمجة مطلوبة لأي تعديل بعد الرفعة الأولى.

---

## 10. ملاحظات ذاكرة (Uno)

- `sizeof(RobotConfig)` ≈ 25 بايت → لا مشكلة في EEPROM (1024 بايت).
- struct + دوال المعايرة تزيد استهلاك Flash/SRAM قليلاً؛ راقب تحذير الذاكرة (انظر `02 §A8`).
- استخدم `EEPROM.put` (يكتب فقط البايتات المتغيّرة) لتقليل التآكل.
- لا تحفظ تلقائياً؛ فقط عند `{"cfg":"save"}` صريح.
