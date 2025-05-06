# Parking Management System

A computer vision-based system for automated parking management that detects and logs vehicle license plates.

## Features

- Automatic license plate detection and recognition using YOLO and OCR
- Arduino integration for gate control
- Logging of vehicle entries with timestamps
- Cooldown mechanism to prevent duplicate entries

## Requirements

- Python 3.x
- OpenCV
- PyTesseract
- Ultralytics YOLO
- Arduino (for gate control)
- Webcam

## Setup

1. Install the required Python packages:
   ```
   pip install opencv-python pytesseract ultralytics pyserial
   ```

2. Install Tesseract OCR on your system:
   - For Linux: `sudo apt-get install tesseract-ocr`

3. Connect an Arduino for gate control (optional)

4. Run the application:
   ```
   python car_entry.py
   ```

## How It Works

The system uses a webcam to capture images of vehicles at the entrance. When a vehicle is detected (using an ultrasonic sensor or simulation), the YOLO model identifies the license plate in the image. OCR is then applied to extract the plate number, which is logged in a CSV file with a timestamp.

If an Arduino is connected, the system will automatically open and close the gate for recognized vehicles.

## Project Structure

- `car_entry.py`: Main application file
- `models/best.pt`: Trained YOLO model for license plate detection
- `plates/`: Directory where plate images are saved
- `plates_log.csv`: Log file for vehicle entries