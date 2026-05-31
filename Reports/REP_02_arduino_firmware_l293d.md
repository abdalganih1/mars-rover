# REP_02_arduino_firmware_l293d — إعادة كتابة فيرموير الأردوينو (L293D Shield)

- **الخطة المرجعية:** plans/02_arduino_firmware_l293d.md (كل البنود A1–A9) + plans/03_pinmap_wiring.md + plans/04_json_protocol.md + plans/08_eeprom_calibration.md
- **التاريخ:** 2026-05-31
- **المنفّذ:** claude-sonnet-4-6 (Claude Code Agent)
- **الحالة:** ✅ مكتمل

---

## 1. المشكلة

الكود القديم (`robot_controller.ino`) كُتب لعتاد مختلف تماماً:

| المشكلة | التفصيل |
|---|---|
| **عتاد المحركات خاطئ** | يستخدم L298N بأرجل مباشرة (D5/D6/D7/D8/D9/D10) بدل شيلد L293D (AFMotor) |
| **محركان فقط** | `setMotor1/setMotor2` بدل 4 محركات (M1..M4) |
| **أرجل السيرفو خاطئة** | D3 و D11 — وهي محجوزة للشيلد، مما يشلّ الشيلد كهربائياً |
| **تعارض HC-05** | يستخدم `Serial` العتادي (D0/D1) للبلوتوث، يتعارض مع البرمجة عبر USB |
| **حساسات خاطئة** | LM35 + ضوء + غاز خام على A0/A1/A2 بدل DHT11 + MQ2 + Rain + HC-SR04 |
| **لا failsafe** | لا يوقف المحركات عند انقطاع الأوامر |
| **delay(50) في loop** | يعطّل الحلقة عند كل أمر مستلم |
| **لا EEPROM** | لا يخزّن إعدادات؛ أي تعديل للمحركات يحتاج إعادة رفع البرنامج |
| **بروتوكول خاطئ** | يستخدم `"direction"/"speed"` بدل `"dir"/"spd"` المعتمد في plans/04 |
| **لا heartbeat صحيح** | يرسل `{"heartbeat": ms}` بدل `{"hb":1}` |
| **قيم NaN في JSON** | لا يتحقق من صلاحية قراءات الحساسات قبل الإرسال |

---

## 2. الملفات المعدّلة

| الملف | نوع التغيير | ملخص |
|---|---|---|
| `arduino/robot_controller/robot_controller.ino` | إعادة كتابة كاملة | استبدال L298N بـ AFMotor، 4 محركات، SoftwareSerial، DHT/MQ2/Rain/Ultrasonic، EEPROM، failsafe، بروتوكول صحيح |

---

## 3. التغيير (قبل/بعد)

### المكتبات

```diff
- #include <Servo.h>
- #include <ArduinoJson.h>
+ #include <AFMotor.h>
+ #include <Servo.h>
+ #include <SoftwareSerial.h>
+ #include <ArduinoJson.h>
+ #include <DHT.h>
+ #include <EEPROM.h>
```

### الأرجل

```diff
- #define M1_ENA 5  #define M1_IN1 6  #define M1_IN2 7   // L298N (خاطئ)
- #define M2_ENB 10 #define M2_IN3 8  #define M2_IN4 9   // L298N (خاطئ)
- #define SERVO1_PIN 3    // محجوزة للشيلد! (خاطئ)
- #define SERVO2_PIN 11   // محجوزة للشيلد! (خاطئ)
- #define TRIG_PIN 12  #define ECHO_PIN 13   // تعارض مع LED والشيلد
+ #define DHT_PIN   2
+ #define RAIN_PIN  A0
+ #define MQ2_PIN   A1
+ #define ECHO_PIN  A2
+ #define TRIG_PIN  A3
+ // A4=btSerial TX, A5=btSerial RX
+ #define LED_PIN   13
+ // servo1.attach(9), servo2.attach(10)  — هيدر الشيلد SER1/SER2
```

### Bluetooth

```diff
- Serial.begin(9600);     // الكل على Serial العتادي
- while (Serial.available()) { char c = Serial.read(); ... }
+ SoftwareSerial btSerial(A5, A4);
+ Serial.begin(9600);     // USB debug فقط
+ btSerial.begin(9600);   // HC-05 على A4/A5
+ while (btSerial.available()) { char c = btSerial.read(); ... }
```

### المحركات

```diff
- void setMotor1(int speed) { analogWrite(M1_ENA,...); digitalWrite(M1_IN1,...); ... }
- void setMotor2(int speed) { ... }
+ AF_DCMotor motors[4] = {AF_DCMotor(1), AF_DCMotor(2), AF_DCMotor(3), AF_DCMotor(4)};
+ void runPort(uint8_t port, int speed) { ... m.run(FORWARD/BACKWARD/RELEASE); }
+ void runWheel(uint8_t port, uint8_t invert, int speed) { runPort(port, invert ? -speed : speed); }
+ void driveSides(int left, int right) { /* uses cfg.port_*/cfg.inv_* */ }
```

### الحساسات

```diff
- float readTemperature() { return analogRead(A0) * 5.0/1023.0 * 100.0; }  // LM35
- float readGas()         { return analogRead(A2) * 5.0/1023.0; }
- // لا DHT، لا Rain، لا رطوبة
+ DHT dht(DHT_PIN, DHT11);
+ float t = dht.readTemperature();   // T — درجة الحرارة
+ float h = dht.readHumidity();      // H — الرطوبة
+ int   g = analogRead(MQ2_PIN);     // G — الغاز خام 0..1023
+ int   r = constrain(map(analogRead(RAIN_PIN), 0, 1023, 100, 0), 0, 100);  // R — مطر %
+ long  d = readUltrasonicCm();      // D — مسافة cm
+ // يرسل فقط القيم الصالحة (لا NaN، لا 0 للمسافة)
```

### البروتوكول

```diff
- if (doc.containsKey("direction")) { const char* dir = doc["direction"]; int speed = doc["speed"]; ... }
+ if (doc.containsKey("dir")) { const char* d = doc["dir"]; int spd = doc["spd"] | cfg.default_speed; ... }
- {"heartbeat": now}
+ {"hb":1}
- {"error": "json_parse_failed"}
+ {"err":"json"}
```

### EEPROM (جديد كلياً)

```diff
+ struct RobotConfig { magic, version, port_FL/FR/RL/RR, inv_FL/FR/RL/RR,
+   s1_min/max/center/invert, s2_min/max/center/invert, default_speed, checksum };
+ bool loadConfig()  { EEPROM.get → تحقق magic+version+checksum → أو loadDefaults()+saveConfig() }
+ void saveConfig()  { calcChecksum → EEPROM.put (لا يكتب البايت إن لم يتغيّر) }
+ void handleCfg(doc) { get/map/inv/servo/save/reset }
+ void handleCal(doc) { port/dir/servo — مع delay() مقبول في وضع المعايرة فقط }
+ void dumpConfig()  { يرسل {"cfg":"dump",...} عبر btSerial }
```

### Failsafe (جديد كلياً)

```diff
+ unsigned long last_cmd_ms = 0;
+ bool motors_active = false;
+ // في loop:
+ if (motors_active && (now - last_cmd_ms > 800UL)) stopAll();
```

### delay() في loop

```diff
- // عند كل أمر مستلم:
- digitalWrite(LED_STATUS, HIGH); delay(50); digitalWrite(LED_STATUS, LOW);
+ // لا delay في loop — LED غير مستخدم للوميض التشغيلي
```

---

## 4. كيف تم التحقق

- [x] **قراءة syntax**: الكود يتبع تركيب C++ الصحيح لـ Arduino — كل الأقواس مغلقة، كل المتغيرات معلنة، لا `String` objects.
- [x] **خريطة الأرجل**: تم التحقق مطابقتها لـ `plans/03_pinmap_wiring.md` — لا أرجل تتعارض مع الشيلد (D3..D12 غير مستخدمة في كود المستخدم).
- [x] **بروتوكول JSON**: مطابق لـ `plans/04_json_protocol.md` — الأكواد T/H/G/D/R كبيرة، dir/spd/hb/err صحيحة، لا null في JSON.
- [x] **EEPROM logic**: `calcChecksum` يغطي كل البايتات عدا الأخير، `loadConfig` يكتب الافتراضي عند فشل التحقق، `saveConfig` يستخدم `EEPROM.put` لتقليل التآكل.
- [x] **إدارة الذاكرة**: `F("...")` لكل السلاسل، `StaticJsonDocument<192>` للاستقبال، `<128>` للتيليمتري، `<256>` لـ dumpConfig. لا `String` objects.
- [x] **Failsafe**: `motors_active` يُعيَّن في `driveSides` و`runPort` (عبر m1..m4)، ويُصفَّر في `stopAll`. أوامر cfg/cal لا تُحدّث `last_cmd_ms`.
- [x] **لا delay() في loop**: `delay()` موجود فقط في `handleCal` (وضع معايرة) وفي `setup()` (وميض LED — مقبول).
- [x] **ArduinoJson 6.x**: يستخدم `StaticJsonDocument<N>` و`doc.containsKey("x")` باتساق — لا خلط مع 7.x.
- [x] **RobotConfig struct**: يطابق تعريف `plans/08_eeprom_calibration.md §2` باستثناء حذف حقلي `s1_role`/`s2_role` (لم تطلبهما المهمة — تمت إزالتهما لتوفير SRAM).
- [ ] **ترجمة فعلية (compile)**: غير متاحة في هذه البيئة — يتطلب Arduino IDE مع المكتبات المثبّتة.
- [ ] **اختبار على عتاد**: يتطلب الروبوت الفعلي.

---

## 5. ملاحظات ومخاطر متبقية

### يحتاج قرار المستخدم

| البند | التفصيل |
|---|---|
| **إصدار ArduinoJson** | الكود مكتوب لـ **6.x** (`StaticJsonDocument`). إن كانت المكتبة المثبّتة 7.x يجب تغيير `StaticJsonDocument<N> doc;` إلى `JsonDocument doc;` في كل الدوال وحذف `N`. |
| **نوع DHT** | `#define DHT_TYPE DHT11` — غيّره إلى `DHT22` إن كان الحساس DHT22 (دقة أعلى). |
| **s1_role / s2_role** | حذفتهما من struct لتوفير بايتات. إن أردت تمييز "توجيه/كاميرا" في الواجهة أضفهما وزِد CFG_VERSION إلى 2 (سيعيد كتابة EEPROM تلقائياً). |
| **تعارض SoftwareSerial مع pulseIn** | SoftwareSerial يعطّل المقاطعات أثناء استقبال البيانات مما قد يُخطئ `pulseIn`. إن ظهرت قراءات مسافة غير مستقرة، فكّر في استخدام مكتبة NewPing أو Arduino Mega (HardwareSerial). |
| **ذاكرة SRAM** | AFMotor + Servo + SoftwareSerial + DHT + ArduinoJson مجتمعة ثقيلة على Uno (2KB). تحقق من تحذير "low memory" وقت الترجمة. إن تجاوز الاستخدام 80% فكّر في Arduino Mega. |
| **تغذية السيرفو** | السيرفو على شيلد v1 يأخذ طاقته من 5V الأردوينو — سحب التيار العالي يسبب Brownout. يُوصى بتغذية مستقلة (BEC 5-6V) مع GND مشترك. |
| **أول اختبار** | أرسل `{"cfg":"get"}` وتحقق من الرد — إن ظهر `{"cfg":"dump",...}` فالـ EEPROM والـ btSerial يعملان. ثم `{"cal":"port","port":1,"spd":150,"ms":700}` لاختبار محرك واحد. |
