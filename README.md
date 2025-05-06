# Parking Management System

A comprehensive system for automated parking management that detects and logs vehicle entries using both RFID tags and license plate recognition.

## Features

- Dual identification methods:
  - RFID tag reading using MFRC522 module
  - Automatic license plate detection and recognition using YOLO and OCR
- Arduino integration for gate control and RFID reading
- Logging of vehicle entries with timestamps and entry method
- Cooldown mechanism to prevent duplicate entries
- JSON-based communication between Arduino and Python

## Requirements

- Python 3.x
- OpenCV
- PyTesseract
- Ultralytics YOLO
- PySerial
- Arduino with MFRC522 RFID reader module
- Arduino libraries: MFRC522, ArduinoJson
- Webcam

## Setup

1. Install the required Python packages:
   ```
   pip install opencv-python pytesseract ultralytics pyserial
   ```

2. Install Tesseract OCR on your system:
   - For Linux: `sudo apt-get install tesseract-ocr`

3. Arduino Setup:
   - Connect the MFRC522 RFID reader to your Arduino:
     - SDA (SS) -> Digital Pin 10
     - SCK -> Digital Pin 13
     - MOSI -> Digital Pin 11
     - MISO -> Digital Pin 12
     - GND -> GND
     - RST -> Digital Pin 9
     - 3.3V -> 3.3V
   - Connect a relay or LED to Digital Pin 2 for gate control
   - Install the required Arduino libraries through the Arduino IDE:
     - MFRC522 by GithubCommunity
     - ArduinoJson by Benoit Blanchon
   - Upload the `arduino_rfid_reader.ino` sketch to your Arduino

4. Run the application:
   ```
   python parking_system.py
   ```

   For RFID-only functionality, you can also run:
   ```
   python rfid_reader.py
   ```

## How It Works

The system supports two methods of vehicle identification:

1. **RFID Tag Reading**: When an RFID tag is presented to the MFRC522 reader connected to the Arduino, the tag data (including license plate and amount) is read and sent to the Python application via serial communication in JSON format. The system logs the entry and controls the gate accordingly.

2. **License Plate Recognition**: If no RFID tag is detected, the system uses a webcam to capture images of vehicles. When a vehicle is detected (using an ultrasonic sensor or simulation), the YOLO model identifies the license plate in the image. OCR is then applied to extract the plate number, which is logged in a CSV file with a timestamp.

All entries are logged with the method used (RFID or camera) and a timestamp. The system includes a cooldown mechanism to prevent duplicate entries within a specified time period.

## Payment Processing

The system includes an automated payment processing module that:

1. **Calculates Parking Fees**: Automatically calculates charges based on the duration of stay at a rate of 200 RWF per hour (configurable).
2. **Processes Payments**: Handles payment transactions via RFID cards with stored balance.
3. **Updates Records**: Marks entries as paid in the system logs after successful payment.
4. **Balance Management**: Checks if the user has sufficient balance and updates it after payment.
5. **Transaction Logging**: Records all payment activities with timestamps in payment_log.txt.

To use the payment system:
```
python transact.py
```

The payment module communicates with the Arduino via serial connection to process payments when an RFID card is scanned. It supports error handling for insufficient funds and other payment processing issues.

## Project Structure

- `parking_system.py`: Main application file that integrates both RFID and camera-based identification
- `rfid_reader.py`: Module for RFID tag reading functionality
- `arduino_rfid_reader/arduino_rfid_reader.ino`: Arduino sketch for MFRC522 RFID reader
- `car_entry.py`: Original camera-based license plate recognition system
- `models/best.pt`: Trained YOLO model for license plate detection
- `plates/`: Directory where plate images are saved
- `plates_log.csv`: Log file for vehicle entries
- `transact.py`: Payment processing module for calculating and handling parking fees
- `payment_log.txt`: Transaction log for payment activities
