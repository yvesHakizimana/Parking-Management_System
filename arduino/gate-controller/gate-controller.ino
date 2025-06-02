#include <Servo.h>

// Define the corresponding pin for SENSOR
#define TRIG_PIN 2
#define ECHO_PIN 3
// Define the corresponding pins for LEDs
#define RED_LED_PIN 4
#define BLUE_LED_PIN 5
// Define the corresponding pin for SERVO
#define SERVO_PIN 6
// Define hardcoded ground pins
#define GROUND_PIN_1 7
#define GROUND_PIN_2 8
// Define the corresponding pin for BUZZER
#define BUZZER_PIN 12
#define MAX_DISTANCE 200 // Maximum distance in cm (adjust as needed)

Servo gateServo;
bool gateOpen = false;
unsigned long gateOpenTime = 0;
const unsigned long GATE_OPEN_DURATION = 15000; // 15 seconds

void setup() {
  // Initialize serial communication at 9600 baud rate
  Serial.begin(9600);

  // Set up ultrasonic sensor pins
  pinMode(TRIG_PIN, OUTPUT);
  pinMode(ECHO_PIN, INPUT);

  // Set up LED pins
  pinMode(RED_LED_PIN, OUTPUT);
  pinMode(BLUE_LED_PIN, OUTPUT);

  // Set up buzzer pin
  pinMode(BUZZER_PIN, OUTPUT);

  // Set up hardcoded ground pins
  pinMode(GROUND_PIN_1, OUTPUT);
  pinMode(GROUND_PIN_2, OUTPUT);
  digitalWrite(GROUND_PIN_1, LOW); // Set as ground
  digitalWrite(GROUND_PIN_2, LOW); // Set as ground

  // Attach servo to the defined pin and start with gate closed
  gateServo.attach(SERVO_PIN);
  gateServo.write(0); // Assuming 0 degrees is the closed position
  gateOpen = false;

  // Startup sequence: Red LED on and buzzer for 2 seconds
  digitalWrite(RED_LED_PIN, HIGH);
  digitalWrite(BLUE_LED_PIN, LOW);

  // Startup buzzer sequence
  for(int i = 0; i < 7; i++) {
    digitalWrite(BUZZER_PIN, HIGH);
    delay(700);
    digitalWrite(BUZZER_PIN, LOW);
    delay(200);
  }

  Serial.println("Gate controller initialized - Gate closed");
}

void loop() {
  // Check if gate should auto-close after 15 seconds
  if (gateOpen && (millis() - gateOpenTime >= GATE_OPEN_DURATION)) {
    closeGate();
  }

  // Measure distance using the ultrasonic sensor
  digitalWrite(TRIG_PIN, LOW);
  delayMicroseconds(2);
  digitalWrite(TRIG_PIN, HIGH);
  delayMicroseconds(10);
  digitalWrite(TRIG_PIN, LOW);

  // Read the echo pulse with a timeout (30ms)
  long duration = pulseIn(ECHO_PIN, HIGH, 30000);
  float distance;

  if (duration == 0) {
    // No echo received, assume maximum distance
    distance = MAX_DISTANCE;
  } else {
    // Calculate distance in cm
    distance = (duration / 2.0) / 29.1;
    if (distance > MAX_DISTANCE) {
      distance = MAX_DISTANCE;
    }
  }

  // Send the distance value via serial to Python
  Serial.println(distance);

  // Check for incoming serial commands from Python
  if (Serial.available() > 0) {
    char command = Serial.read();

    switch(command) {
      case '1':
        // Open the gate
        openGate();
        break;

      case '0':
        // Close the gate
        closeGate();
        break;

      case 'B':
        // Unauthorized exit alert - loud continuous buzzer
        unauthorizedExitAlert();
        break;

      case 'S':
        // Short beep for regular exit
        shortBeep();
        break;

      default:
        // Unknown command
        break;
    }
  }

  // Delay before the next measurement
  delay(100); // 100ms delay for 10 measurements per second
}

void openGate() {
  gateServo.write(90); // Open position
  digitalWrite(BLUE_LED_PIN, HIGH); // Turn on blue LED when gate opens
  digitalWrite(RED_LED_PIN, LOW);   // Turn off red LED
  gateOpen = true;
  gateOpenTime = millis();

  // Short beep to indicate gate opening
  digitalWrite(BUZZER_PIN, HIGH);
  delay(100);
  digitalWrite(BUZZER_PIN, LOW);

  Serial.println("Gate opened");
}

void closeGate() {
  gateServo.write(0); // Closed position
  digitalWrite(RED_LED_PIN, HIGH);  // Turn on red LED when gate closes
  digitalWrite(BLUE_LED_PIN, LOW);  // Turn off blue LED
  gateOpen = false;

  // Double beep to indicate gate closing
  for(int i = 0; i < 3; i++) {
    digitalWrite(BUZZER_PIN, HIGH);
    delay(150);
    digitalWrite(BUZZER_PIN, LOW);
    delay(100);
  }

  Serial.println("Gate closed");
}

void unauthorizedExitAlert() {
  // Continuous loud buzzer for unauthorized exit attempt
  for(int i = 0; i < 25; i++) {
    digitalWrite(BUZZER_PIN, HIGH);
    delay(400);
    digitalWrite(BUZZER_PIN, LOW);
    delay(200);
  }
  Serial.println("Unauthorized exit alert triggered");
}

void shortBeep() {
  // Single short beep for regular exit
  digitalWrite(BUZZER_PIN, HIGH);
  delay(1000);
  digitalWrite(BUZZER_PIN, LOW);
  Serial.println("Exit beep");
}