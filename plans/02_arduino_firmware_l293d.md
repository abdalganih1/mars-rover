# 02 — إعادة كتابة كود الأردوينو (L293D Shield Firmware)

الملف الهدف: `arduino/robot_controller/robot_controller.ino`
الوضع الحالي: L298N بأرجل مباشرة + محركان + سيرفو على 3/11 + HC-05 على Serial العتادي + LM35/ضوء/غاز.
المطلوب: شيلد L293D (AFMotor) + 4 محركات + سيرفو على 9/10 + HC-05 على SoftwareSerial + DHT/MQ2/Ultrasonic/Rain.

> هذه إعادة كتابة شبه كاملة. نفّذها كاستبدال للملف، ووثّقها في `Reports/REP_02_*.md`.

---

## A. قائمة الإصلاحات الذرّية (كل بند = تقرير محتمل)

### A1 — استبدال محرّكات L298N بمكتبة AFMotor (4 محركات)
**الحالي (أسطر 22–29, 82–117):** `#define M1_ENA 5 ...` + `setMotor1/2` بـ `digitalWrite/analogWrite`.
**المطلوب:** حذفها كلياً واستخدام:
```cpp
#include <AFMotor.h>
AF_DCMotor motor1(1);   // منفذ M1 بالشيلد
AF_DCMotor motor2(2);   // M2
AF_DCMotor motor3(3);   // M3
AF_DCMotor motor4(4);   // M4

void setMotorRaw(AF_DCMotor &m, int speed) {   // speed: -255..255
  speed = constrain(speed, -255, 255);
  if (speed > 0)      { m.setSpeed(speed);  m.run(FORWARD); }
  else if (speed < 0) { m.setSpeed(-speed); m.run(BACKWARD); }
  else                { m.setSpeed(0);      m.run(RELEASE); }
}
```

### A2 — نقل السيرفو إلى أرجل الشيلد الصحيحة
**الحالي (أسطر 32–33):** `#define SERVO1_PIN 3` و `#define SERVO2_PIN 11` ← **خطأ** (محجوزة للشيلد).
**المطلوب:**
```cpp
#include <Servo.h>
Servo servo1;  // SER1
Servo servo2;  // SER2
// في setup():
servo1.attach(9);
servo2.attach(10);
```

### A3 — HC-05 على SoftwareSerial (وإبقاء USB Serial للبرمجة)
**الحالي:** كل التبادل عبر `Serial` العتادي (يتعارض مع البرمجة/USB).
**المطلوب:**
```cpp
#include <SoftwareSerial.h>
SoftwareSerial btSerial(A5, A4);   // RX=A5 (من HC-05 TX) ، TX=A4 (إلى HC-05 RX عبر divider)
// setup():
Serial.begin(9600);     // USB — تشخيص فقط
btSerial.begin(9600);   // HC-05
```
ثم **استبدال كل `Serial.read()/print()/println()` الخاصة بالبروتوكول بـ `btSerial.*`**
(انظر دالة الحلقة بالأسفل). أبقِ `Serial.print` فقط لرسائل التشخيص.

### A4 — استبدال الحساسات
**الحالي (أسطر 38–40, 190–204):** LM35 (A0)، ضوء (A1)، غاز (A2).
**المطلوب:**
- **DHT** على D2 (حرارة T + رطوبة H).
- **MQ2** على A1 (غاز G).
- **Rain** على A0 (مطر R).
- **HC-SR04** على TRIG=A3 / ECHO=A2 (مسافة D) — أبقِه لكن انتبه لتعارض SoftwareSerial.
- احذف حساس الضوء L (غير مطلوب) أو أبقه إن رغبت على رجل حرّة (لا يوجد فائض كبير).

### A5 — منطق توجيه 4 عجلات
**الحالي (أسطر 138–175):** `moveDirection` لمحركين فقط، ومنطق L/R بنصف سرعة.
**المطلوب:** تخطيط يسار/يمين:
```cpp
void driveSides(int left, int right) {     // -255..255 لكل جهة
  setMotorRaw(motor1, left);   // أمامي يسار
  setMotorRaw(motor3, left);   // خلفي يسار
  setMotorRaw(motor2, right);  // أمامي يمين
  setMotorRaw(motor4, right);  // خلفي يمين
}
// F: driveSides(spd, spd) ; B: (-spd,-spd) ; SPIN_L: (-spd,spd) ; SPIN_R: (spd,-spd)
// L: (spd/3, spd) ; R: (spd, spd/3) ... إلخ
```
> ⚠️ قد تحتاج عكس اتجاه بعض المحركات (BACKWARD↔FORWARD) حسب تركيب العجلات فعلياً.
> أضف ثوابت `INVERT_Mx` أو اعكس الأسلاك. وثّق القيم بعد الاختبار.

### A6 — Failsafe عند انقطاع الأوامر (مهم للسلامة)
لا يوجد حالياً. أضف:
```cpp
unsigned long last_cmd_ms = 0;
const unsigned long CMD_TIMEOUT = 800;   // ms
// داخل loop(): إذا (millis() - last_cmd_ms > CMD_TIMEOUT) أوقف كل المحركات.
```
يُحدّث `last_cmd_ms` عند كل أمر حركة صالح.

### A7 — إزالة delay() المعطّلة من الحلقة
**الحالي (أسطر 306–311, 337–339):** `delay(100)` × 6 في setup (مقبول) و`delay(50)` في loop عند كل أمر (سيئ).
**المطلوب:** احذف `delay(50)` من loop؛ استخدم وميض LED غير معطّل عبر `millis()`.

### A8 — إدارة الذاكرة (Uno = 2KB SRAM)
- استخدم `JsonDocument` صغيرة (≤192 بايت للأوامر، ≤128 للإرسال).
- استخدم `F("...")` لكل السلاسل الحرفية في `Serial.print`.
- تجنّب `String`. أبقِ `char` buffers الحالية.
- AFMotor + Servo + SoftwareSerial + DHT + ArduinoJson مجتمعة ثقيلة → راقب التحذير
  "Low memory available" عند الترجمة. إن ضاقت الذاكرة فكّر بـ **Arduino Mega**.

### A9 — إصدار ArduinoJson
الكود الحالي يستخدم `StaticJsonDocument<N>` (ArduinoJson 6).
- **خيار 1 (أقل عملاً):** ثبّت ArduinoJson **6.x** وأبقِ الكود.
- **خيار 2:** رحّل إلى **7.x**: استبدل `StaticJsonDocument<N> doc;` بـ `JsonDocument doc;`
  واحذف معامل الحجم. (`deserializeJson`/`serializeJson` تبقى كما هي).

---

## B. الهيكل المرجعي للملف الجديد (مخطط)

```cpp
#include <AFMotor.h>
#include <Servo.h>
#include <SoftwareSerial.h>
#include <ArduinoJson.h>
#include <DHT.h>
// #include <NewPing.h>   // موصى به للـ ultrasonic

// ---- pins ----
#define DHT_PIN   2
#define DHT_TYPE  DHT11        // أو DHT22
#define RAIN_PIN  A0
#define MQ2_PIN   A1
#define TRIG_PIN  A3
#define ECHO_PIN  A2
#define LED_PIN   13

SoftwareSerial btSerial(A5, A4);   // RX=A5, TX=A4
DHT dht(DHT_PIN, DHT_TYPE);
AF_DCMotor motor1(1), motor2(2), motor3(3), motor4(4);
Servo servo1, servo2;

// ---- state ----
int s1_angle = 90, s2_angle = 90;
unsigned long last_cmd_ms = 0, last_sensor_ms = 0, last_hb_ms = 0;
const unsigned long CMD_TIMEOUT = 800, SENSOR_INTERVAL = 1000, HB_INTERVAL = 2000;
char cmd_buffer[128]; int cmd_index = 0;

void setMotorRaw(AF_DCMotor &m, int speed) { /* A1 */ }
void driveSides(int left, int right)       { /* A5 */ }
void stopAll() { driveSides(0,0); }

void processJson(const char* s) {
  JsonDocument doc;                        // أو StaticJsonDocument<192>
  if (deserializeJson(doc, s)) { btSerial.println(F("{\"err\":\"json\"}")); return; }

  if (doc["dir"].is<const char*>()) {      // أمر اتجاه
    const char* d = doc["dir"];
    int spd = doc["spd"] | 200;
    // طبّق driveSides حسب d ...
    last_cmd_ms = millis();
    return;
  }
  // تحكم مباشر بالمحركات
  bool moved = false;
  if (doc["m1"].is<int>()) { setMotorRaw(motor1, doc["m1"]); moved = true; }
  if (doc["m2"].is<int>()) { setMotorRaw(motor2, doc["m2"]); moved = true; }
  if (doc["m3"].is<int>()) { setMotorRaw(motor3, doc["m3"]); moved = true; }
  if (doc["m4"].is<int>()) { setMotorRaw(motor4, doc["m4"]); moved = true; }
  if (doc["s1"].is<int>()) { s1_angle = constrain((int)doc["s1"],0,180); servo1.write(s1_angle); }
  if (doc["s2"].is<int>()) { s2_angle = constrain((int)doc["s2"],0,180); servo2.write(s2_angle); }
  if (doc["stop"] | false) { stopAll(); }
  if (moved) last_cmd_ms = millis();
}

void readAndSendSensors() {
  float t = dht.readTemperature();
  float h = dht.readHumidity();
  int g = analogRead(MQ2_PIN);
  int rain = analogRead(RAIN_PIN);
  long d = readUltrasonicCm();              // pulseIn أو NewPing
  JsonDocument out;                          // ≤128
  if (!isnan(t)) out["T"] = t;
  if (!isnan(h)) out["H"] = h;
  out["G"] = g;                              // أو ppm تقريبية
  out["D"] = d;
  out["R"] = map(rain, 0, 1023, 100, 0);     // % تقريبية (اعكس حسب الموديول)
  serializeJson(out, btSerial);
  btSerial.println();
}

void setup() {
  Serial.begin(9600);          // USB تشخيص
  btSerial.begin(9600);        // HC-05
  dht.begin();
  pinMode(TRIG_PIN, OUTPUT); pinMode(ECHO_PIN, INPUT);
  pinMode(LED_PIN, OUTPUT);
  servo1.attach(9); servo2.attach(10);
  servo1.write(90); servo2.write(90);
  stopAll();
}

void loop() {
  while (btSerial.available()) {            // اقرأ من HC-05 (ليس Serial)
    char c = btSerial.read();
    if (c=='\n' || c=='\r') {
      if (cmd_index>0) { cmd_buffer[cmd_index]='\0'; processJson(cmd_buffer); cmd_index=0; }
    } else if (cmd_index < 127) cmd_buffer[cmd_index++]=c;
  }
  unsigned long now = millis();
  if (now - last_cmd_ms   > CMD_TIMEOUT)     { stopAll(); }       // A6 failsafe
  if (now - last_sensor_ms> SENSOR_INTERVAL) { readAndSendSensors(); last_sensor_ms=now; }
  if (now - last_hb_ms    > HB_INTERVAL)     { btSerial.println(F("{\"hb\":1}")); last_hb_ms=now; }
}
```

> ملاحظة: `doc["x"].is<int>()` أسلوب ArduinoJson 7؛ في 6.x استخدم `doc.containsKey("x")`.

---

## C. قائمة تحقق الترجمة/التشغيل

- [ ] يترجم بدون أخطاء (مع المكتبات المثبّتة بالمرحلة 0).
- [ ] لا تحذير "low memory" خطير (< 75% SRAM مستخدم مبدئياً).
- [ ] حقن `{"dir":"F","spd":150}` عبر Serial Monitor (مؤقتاً على Serial للاختبار) يحرّك العجلات.
- [ ] فصل البلوتوث → المحركات تقف خلال < 1s (failsafe).
- [ ] التيليمتري يخرج `{"T":..,"H":..,"G":..,"D":..,"R":..}` كل ثانية.
