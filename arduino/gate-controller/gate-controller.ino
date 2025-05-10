#include <Servo.h>

// Define the corresponding pin for SENSOR
#define TRIG_PIN 2
#define ECHO_PIN 3
// Define the corresponding pin for SERVO
#define SERVO_PIN 6
#define MAX_DISTANCE 200 // Maximum distance in cm (adjust as needed)

Servo gateServo;

void setup() {
  // Initialize serial communication at 9600 baud rate
  Serial.begin(9600);

  // Set up ultrasonic sensor pins
  pinMode(TRIG_PIN, OUTPUT);
  pinMode(ECHO_PIN, INPUT);

  // Attach servo to the defined pin and start with gate closed
  gateServo.attach(SERVO_PIN);
  gateServo.write(0); // Assuming 0 degrees is the closed position
}

void loop() {
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
    if (command == '1') {
      // Open the gate (set servo to 90 degrees)
      gateServo.write(90);
    } else if (command == '0') {
      // Close the gate (set servo to 0 degrees)
      gateServo.write(0);
    }
  }

  // Delay before the next measurement
  delay(100); // 100ms delay for 10 measurements per second
}