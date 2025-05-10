# Parking Management System

A comprehensive system for automated parking management that handles vehicle entries and exits using license plate recognition, processes payments via RFID cards, and controls access gates.

## Features

- Complete parking management solution:
  - Entry system with license plate recognition
  - Exit system with payment verification
  - Payment processing with RFID cards
  - Gate control for both entry and exit points
- Automatic license plate detection and recognition using YOLO and OCR
- Arduino integration for gate control, distance sensing, and RFID reading
- Redis-based data storage for vehicle entries, payment status, and system logs
- Cooldown mechanism to prevent duplicate entries
- Real-time payment processing with balance management on RFID cards

## Requirements

### Software
- Python 3.x with packages:
  - OpenCV
  - PyTesseract
  - Ultralytics YOLO
  - PySerial
  - Redis
  - All dependencies listed in requirements.txt
- Tesseract OCR engine
- Redis server

### Hardware
- Arduino boards (for entry gate, exit gate, and payment terminal)
- MFRC522 RFID reader module
- Ultrasonic distance sensors (HC-SR04)
- Servo motors or relays for gate control
- Webcams (for entry and exit points)
- RFID cards (Mifare Classic 1K recommended)
- Optional: LEDs and buzzers for status indication

## Setup

### 1. Software Installation

1. Clone this repository:
   ```
   git clone https://github.com/yourusername/Parking-management-system.git
   cd Parking-management-system
   ```

2. Install the required Python packages:
   ```
   pip install -r requirements.txt
   ```

3. Install Tesseract OCR on your system:
   - For Linux: `sudo apt-get install tesseract-ocr`
   - For Windows: Download and install from https://github.com/UB-Mannheim/tesseract/wiki

4. Install and start Redis server:
   - For Linux: `sudo apt-get install redis-server && sudo systemctl start redis`
   - For Windows: Download and install from https://redis.io/download

### 2. Arduino Setup

#### Entry Gate Arduino:
1. Connect the ultrasonic sensor:
   - Trig -> Digital Pin 7
   - Echo -> Digital Pin 8
   - VCC -> 5V
   - GND -> GND
2. Connect a servo or relay to Digital Pin 2 for gate control
3. Upload the `arduino/gate-controller/gate-controller.ino` sketch

#### Exit Gate Arduino:
1. Connect the ultrasonic sensor (same as entry gate)
2. Connect a servo or relay to Digital Pin 2 for gate control
3. Connect a buzzer to Digital Pin 3 (optional, for payment alerts)
4. Upload the `arduino/gate-controller/gate-controller.ino` sketch

#### Payment Terminal Arduino:
1. Connect the MFRC522 RFID reader:
   - SDA (SS) -> Digital Pin 10
   - SCK -> Digital Pin 13
   - MOSI -> Digital Pin 11
   - MISO -> Digital Pin 12
   - GND -> GND
   - RST -> Digital Pin 9
   - 3.3V -> 3.3V
2. Install the required Arduino libraries through the Arduino IDE:
   - MFRC522 by GithubCommunity
3. Upload the `arduino/payment/transact.ino` sketch

### 3. YOLO Model Setup
Ensure the YOLO model for license plate detection is in the `models` directory:
```
mkdir -p models
# Place your trained YOLO model (best.pt) in the models directory
```

### 4. System Configuration
Adjust configuration parameters in the Python files if needed:
- Entry cooldown time in `entry/car_entry.py`
- Parking rate in `payment-processing/payment.py`
- Gate open duration in both entry and exit scripts

## How It Works

The system consists of three main components that work together to provide a complete parking management solution:

### 1. Entry System (`entry/car_entry.py`)
- Detects approaching vehicles using an ultrasonic distance sensor
- Captures images from a webcam when a vehicle is detected
- Uses YOLO model to identify license plates in the images
- Applies OCR to extract the plate number
- Stores entry information in Redis with a timestamp and initial payment status of "0" (unpaid)
- Controls the entry gate via Arduino serial communication
- Implements a cooldown mechanism to prevent duplicate entries

### 2. Payment Processing (`payment-processing/payment.py`)
- Reads RFID cards presented at the payment terminal
- Retrieves license plate and current balance from the RFID card
- Calculates parking fee based on entry time and current time (500 RWF per hour)
- Checks if the card has sufficient balance
- Deducts the fee from the card balance and updates the stored value
- Updates payment status in Redis to "1" (paid)
- Logs all payment transactions with timestamps

### 3. Exit System (`exit/car_exit.py`)
- Detects approaching vehicles at the exit using an ultrasonic distance sensor
- Captures and processes license plates using the same YOLO + OCR pipeline as the entry system
- Verifies payment status in Redis for the detected license plate
- Opens the exit gate only if payment is complete
- Triggers a warning buzzer if payment is not complete
- Logs all exit attempts with timestamps

## Payment Processing Details

The payment system provides a complete solution for handling parking fees:

1. **Fee Calculation**: Automatically calculates charges based on the duration of stay at a rate of 500 RWF per hour with a minimum charge of 500 RWF (configurable in `payment-processing/payment.py`).

2. **RFID Card Management**:
   - Cards store both the license plate number and current balance
   - Balance is updated directly on the card after payment
   - Additional Arduino sketches are provided for card management:
     - `arduino/payment/read.ino`: Read card information
     - `arduino/payment/topup.ino`: Add funds to a card
     - `arduino/payment/reset.ino`: Reset or initialize a card

3. **Transaction Processing**:
   - The Arduino reads the card and sends data to the Python script
   - Python calculates the fee and checks the balance
   - If sufficient funds are available, the payment is processed
   - The new balance is written back to the card
   - The entry record is marked as paid in Redis

4. **Error Handling**:
   - Insufficient funds detection
   - Card read/write error handling
   - Invalid entry detection

To use the payment system:
```
python payment-processing/payment.py
```

## Project Structure

### Python Components
- `entry/car_entry.py`: Entry point system with license plate recognition
- `exit/car_exit.py`: Exit point system with payment verification
- `payment-processing/payment.py`: Payment processing system
- `entry/query.py`: Utility for querying entry records (optional)

### Arduino Components
- `arduino/gate-controller/gate-controller.ino`: Gate control and distance sensing
- `arduino/payment/transact.ino`: Main payment terminal functionality
- `arduino/payment/read.ino`: Utility to read RFID card data
- `arduino/payment/topup.ino`: Utility to add funds to RFID cards
- `arduino/payment/reset.ino`: Utility to initialize or reset RFID cards

### Resources
- `models/best.pt`: Trained YOLO model for license plate detection
- `requirements.txt`: Python dependencies
- `docs/`: Documentation and reference materials
  - `docs/rfid/`: RFID wiring diagrams and reference

### Data Storage
- Redis is used for all data storage:
  - Entry records with timestamps and payment status
  - Vehicle-to-entry mappings
  - System logs and transaction records

## Running the System

To run the complete parking management system, you need to start each component in a separate terminal:

1. Start the entry system:
   ```
   python entry/car_entry.py
   ```

2. Start the payment processing system:
   ```
   python payment-processing/payment.py
   ```

3. Start the exit system:
   ```
   python exit/car_exit.py
   ```

Each component will automatically detect the connected Arduino device and establish communication.

## Monitoring and Management

You can monitor the system using Redis CLI:

```
redis-cli
> LRANGE logs 0 -1  # View all system logs
> HGETALL entry:1   # View details of a specific entry
> SMEMBERS entries:ABC123D  # View all entries for a specific plate
```

## Troubleshooting

1. **Arduino Connection Issues**:
   - Check that the Arduino is properly connected
   - Verify that the correct sketch is uploaded
   - Check serial port permissions (Linux: `sudo chmod a+rw /dev/ttyACM0`)

2. **RFID Reading Problems**:
   - Ensure the MFRC522 module is properly wired
   - Check that the card is compatible (Mifare Classic 1K)
   - Use the `read.ino` sketch to test card reading

3. **License Plate Recognition Issues**:
   - Adjust lighting conditions for better image quality
   - Ensure the webcam is properly positioned
   - The system works best with standard format license plates

## License

This project is licensed under the MIT License - see the LICENSE file for details.

## Acknowledgments

- YOLO by Ultralytics
- Tesseract OCR
- MFRC522 Arduino library
- Redis database