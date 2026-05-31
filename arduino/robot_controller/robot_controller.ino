/*
 * robot_controller.ino
 * Arduino Robot Controller - Receives JSON commands via Bluetooth HC-05
 * Controls: 2 DC motors (L298N) + 2 Servo motors + reads sensors
 * 
 * JSON command format: {"m1":0,"m2":0,"s1":90,"s2":90}
 *   m1, m2: DC motor speed -255 to 255 (negative = reverse)
 *   s1, s2: Servo angle 0-180
 * 
 * Direction commands: {"direction":"F","speed":100}
 *   F=Forward, B=Backward, L=Left, R=Right, S=Stop
 *   FL=Forward-Left, FR=Forward-Right, BL=Backward-Left, BR=Backward-Right
 *   SPIN_L=Spin-Left, SPIN_R=Spin-Right
 * 
 * Sensor readings sent as: {"T":25.5,"H":60,"G":0.3,"D":30}
 *   T=Temperature, H=Humidity, G=Gas, D=Distance, L=Light, P=Pressure
 */

#include <Servo.h>
#include <ArduinoJson.h>

// ==================== PIN CONFIGURATION ====================
// DC Motor pins (L298N)
#define M1_ENA    5     // PWM speed control Motor 1
#define M1_IN1    6     // Direction Motor 1
#define M1_IN2    7     // Direction Motor 1
#define M2_ENB    10    // PWM speed control Motor 2
#define M2_IN3    8     // Direction Motor 2
#define M2_IN4    9     // Direction Motor 2

// Servo pins
#define SERVO1_PIN  3
#define SERVO2_PIN  11

// Sensor pins
#define TRIG_PIN    12    // Ultrasonic sensor trigger
#define ECHO_PIN    13    // Ultrasonic sensor echo
#define TEMP_PIN    A0    // Temperature sensor (analog)
#define LIGHT_PIN   A1    // Light sensor (analog)
#define GAS_PIN     A2    // Gas sensor (analog)

// LED indicators
#define LED_CONN    4     // Connection indicator LED
#define LED_STATUS  2     // Status LED (built-in on some boards)

// ==================== CONSTANTS ====================
#define MAX_SPEED       255
#define MIN_SPEED       -255
#define SERVO_CENTER    90
#define SERIAL_BAUD     9600
#define SENSOR_INTERVAL 500   // ms between sensor readings
#define HEARTBEAT_INTERVAL 2000  // ms between heartbeat signals
#define JSON_BUFFER_SIZE 256
#define CMD_BUFFER_SIZE  128

// ==================== GLOBAL OBJECTS ====================
Servo servo1;
Servo servo2;

// Motor state
int m1_speed = 0;
int m2_speed = 0;
int s1_angle = SERVO_CENTER;
int s2_angle = SERVO_CENTER;

// Sensor values
float temperature = 0;
int humidity = 0;
float gas_level = 0;
int distance_cm = 0;
int light_level = 0;

// Timing
unsigned long last_sensor_read = 0;
unsigned long last_heartbeat = 0;

// Command buffer
char cmd_buffer[CMD_BUFFER_SIZE];
int cmd_index = 0;
bool cmd_complete = false;

// ==================== MOTOR CONTROL ====================
void setMotor1(int speed) {
    speed = constrain(speed, MIN_SPEED, MAX_SPEED);
    m1_speed = speed;
    
    if (speed > 0) {
        digitalWrite(M1_IN1, HIGH);
        digitalWrite(M1_IN2, LOW);
    } else if (speed < 0) {
        digitalWrite(M1_IN1, LOW);
        digitalWrite(M1_IN2, HIGH);
        speed = -speed;
    } else {
        digitalWrite(M1_IN1, LOW);
        digitalWrite(M1_IN2, LOW);
    }
    analogWrite(M1_ENA, speed);
}

void setMotor2(int speed) {
    speed = constrain(speed, MIN_SPEED, MAX_SPEED);
    m2_speed = speed;
    
    if (speed > 0) {
        digitalWrite(M2_IN3, HIGH);
        digitalWrite(M2_IN4, LOW);
    } else if (speed < 0) {
        digitalWrite(M2_IN3, LOW);
        digitalWrite(M2_IN4, HIGH);
        speed = -speed;
    } else {
        digitalWrite(M2_IN3, LOW);
        digitalWrite(M2_IN4, LOW);
    }
    analogWrite(M2_ENB, speed);
}

void setServo1(int angle) {
    angle = constrain(angle, 0, 180);
    s1_angle = angle;
    servo1.write(angle);
}

void setServo2(int angle) {
    angle = constrain(angle, 0, 180);
    s2_angle = angle;
    servo2.write(angle);
}

void emergencyStop() {
    setMotor1(0);
    setMotor2(0);
    setServo1(SERVO_CENTER);
    setServo2(SERVO_CENTER);
}

// ==================== DIRECTION MOVEMENT ====================
void moveDirection(const char* dir, int speed) {
    speed = constrain(abs(speed), 0, MAX_SPEED);
    
    if (strcmp(dir, "F") == 0) {
        setMotor1(speed);
        setMotor2(speed);
    } else if (strcmp(dir, "B") == 0) {
        setMotor1(-speed);
        setMotor2(-speed);
    } else if (strcmp(dir, "L") == 0) {
        setMotor1(-speed / 2);
        setMotor2(speed);
    } else if (strcmp(dir, "R") == 0) {
        setMotor1(speed);
        setMotor2(-speed / 2);
    } else if (strcmp(dir, "FL") == 0) {
        setMotor1(speed / 2);
        setMotor2(speed);
    } else if (strcmp(dir, "FR") == 0) {
        setMotor1(speed);
        setMotor2(speed / 2);
    } else if (strcmp(dir, "BL") == 0) {
        setMotor1(-speed / 2);
        setMotor2(-speed);
    } else if (strcmp(dir, "BR") == 0) {
        setMotor1(-speed);
        setMotor2(-speed / 2);
    } else if (strcmp(dir, "SPIN_L") == 0) {
        setMotor1(-speed);
        setMotor2(speed);
    } else if (strcmp(dir, "SPIN_R") == 0) {
        setMotor1(speed);
        setMotor2(-speed);
    } else if (strcmp(dir, "S") == 0) {
        emergencyStop();
    }
}

// ==================== SENSOR READING ====================
int readUltrasonic() {
    digitalWrite(TRIG_PIN, LOW);
    delayMicroseconds(2);
    digitalWrite(TRIG_PIN, HIGH);
    delayMicroseconds(10);
    digitalWrite(TRIG_PIN, LOW);
    
    long duration = pulseIn(ECHO_PIN, HIGH, 30000); // 30ms timeout
    if (duration == 0) return -1;
    return duration * 0.034 / 2;
}

float readTemperature() {
    // LM35 or similar: 10mV per degree C
    int raw = analogRead(TEMP_PIN);
    float voltage = raw * (5.0 / 1023.0);
    return voltage * 100.0; // LM35: 10mV/°C
}

int readLight() {
    return analogRead(LIGHT_PIN);
}

float readGas() {
    int raw = analogRead(GAS_PIN);
    return raw * (5.0 / 1023.0);
}

void readAllSensors() {
    distance_cm = readUltrasonic();
    temperature = readTemperature();
    light_level = readLight();
    gas_level = readGas();
}

void sendSensorData() {
    StaticJsonDocument<200> doc;
    doc["T"] = round(temperature * 10) / 10.0;
    doc["D"] = distance_cm;
    doc["G"] = round(gas_level * 100) / 100.0;
    doc["L"] = light_level;
    
    serializeJson(doc, Serial);
    Serial.println();
}

// ==================== JSON COMMAND PARSING ====================
void processJsonCommand(const char* json_str) {
    StaticJsonDocument<JSON_BUFFER_SIZE> doc;
    DeserializationError error = deserializeJson(doc, json_str);
    
    if (error) {
        // Send error response
        StaticJsonDocument<100> err;
        err["error"] = "json_parse_failed";
        serializeJson(err, Serial);
        Serial.println();
        return;
    }
    
    // Check if it's a direction command
    if (doc.containsKey("direction")) {
        const char* dir = doc["direction"];
        int speed = doc.containsKey("speed") ? doc["speed"] : 150;
        moveDirection(dir, speed);
        return;
    }
    
    // Direct motor/servo control
    if (doc.containsKey("m1")) {
        setMotor1(doc["m1"]);
    }
    if (doc.containsKey("m2")) {
        setMotor2(doc["m2"]);
    }
    if (doc.containsKey("s1")) {
        setServo1(doc["s1"]);
    }
    if (doc.containsKey("s2")) {
        setServo2(doc["s2"]);
    }
    
    // Emergency stop
    if (doc.containsKey("stop") && doc["stop"] == true) {
        emergencyStop();
    }
    
    // Send current state back
    StaticJsonDocument<150> state;
    state["m1"] = m1_speed;
    state["m2"] = m2_speed;
    state["s1"] = s1_angle;
    state["s2"] = s2_angle;
    serializeJson(state, Serial);
    Serial.println();
}

// ==================== SETUP ====================
void setup() {
    // Motor pins
    pinMode(M1_ENA, OUTPUT);
    pinMode(M1_IN1, OUTPUT);
    pinMode(M1_IN2, OUTPUT);
    pinMode(M2_ENB, OUTPUT);
    pinMode(M2_IN3, OUTPUT);
    pinMode(M2_IN4, OUTPUT);
    
    // Servo pins
    servo1.attach(SERVO1_PIN);
    servo2.attach(SERVO2_PIN);
    servo1.write(SERVO_CENTER);
    servo2.write(SERVO_CENTER);
    
    // Sensor pins
    pinMode(TRIG_PIN, OUTPUT);
    pinMode(ECHO_PIN, INPUT);
    
    // LED pins
    pinMode(LED_CONN, OUTPUT);
    pinMode(LED_STATUS, OUTPUT);
    
    // Start serial (HC-05 default baud)
    Serial.begin(SERIAL_BAUD);
    
    // Initialize motors to stopped
    emergencyStop();
    
    // Blink LED to indicate ready
    for (int i = 0; i < 3; i++) {
        digitalWrite(LED_STATUS, HIGH);
        delay(100);
        digitalWrite(LED_STATUS, LOW);
        delay(100);
    }
}

// ==================== MAIN LOOP ====================
void loop() {
    // Read serial data character by character
    while (Serial.available()) {
        char c = Serial.read();
        
        if (c == '\n' || c == '\r') {
            if (cmd_index > 0) {
                cmd_buffer[cmd_index] = '\0';
                cmd_complete = true;
            }
        } else if (cmd_index < CMD_BUFFER_SIZE - 1) {
            cmd_buffer[cmd_index++] = c;
        }
    }
    
    // Process complete command
    if (cmd_complete) {
        processJsonCommand(cmd_buffer);
        cmd_index = 0;
        cmd_complete = false;
        
        // Flash status LED
        digitalWrite(LED_STATUS, HIGH);
        delay(50);
        digitalWrite(LED_STATUS, LOW);
    }
    
    // Periodic sensor readings
    unsigned long now = millis();
    if (now - last_sensor_read >= SENSOR_INTERVAL) {
        readAllSensors();
        sendSensorData();
        last_sensor_read = now;
    }
    
    // Heartbeat signal
    if (now - last_heartbeat >= HEARTBEAT_INTERVAL) {
        StaticJsonDocument<50> hb;
        hb["heartbeat"] = now;
        serializeJson(hb, Serial);
        Serial.println();
        last_heartbeat = now;
        
        // Connection LED on
        digitalWrite(LED_CONN, HIGH);
    }
}