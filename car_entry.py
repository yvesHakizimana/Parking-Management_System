#!/usr/bin/env python3
import os
import time
import glob
import serial
import serial.tools.list_ports
import pytesseract
import cv2
from ultralytics import YOLO
import csv
import re
import threading
from collections import deque, Counter
# … your other imports …

# Point pytesseract at the system binary on Linux
pytesseract.pytesseract.tesseract_cmd = '/usr/bin/tesseract'


MODEL_PATH = os.path.expanduser("models/best.pt")
model = YOLO(MODEL_PATH)

# Plate save directory
save_dir = 'plates'
os.makedirs(save_dir, exist_ok=True)

# CSV log file
csv_file = 'plates_log.csv'
if not os.path.exists(csv_file):
    with open(csv_file, 'w', newline='') as f:
        writer = csv.writer(f)
        writer.writerow(['Plate Number', 'Payment Status', 'Timestamp'])

# ===== Linux-style Auto-detect Arduino Serial Port =====
def detect_arduino_port():
    # Method 1: scan known device patterns
    for dev in glob.glob('/dev/ttyACM*') + glob.glob('/dev/ttyUSB*'):
        return dev

    # Method 2: fall back to pyserial descriptions
    for port in serial.tools.list_ports.comports():
        desc = port.description.lower()
        if 'arduino' in desc or 'usb serial' in desc:
            return port.device
    return None

arduino_port = detect_arduino_port()
if arduino_port:
    print(f"[CONNECTED] Arduino on {arduino_port}")
    arduino = serial.Serial(arduino_port, 9600, timeout=1)
    time.sleep(2)
else:
    print("[ERROR] Arduino not detected.")
    arduino = None

# ===== Ultrasonic Sensor Setup =====
import random
def mock_ultrasonic_distance():
    return random.choice([random.randint(10, 40)] + [random.randint(60, 150)] * 10)

# Initialize webcam
import csv
from collections import Counter

cap = cv2.VideoCapture(0)
# BUFFER & PLATE‐FINDING SETUP (place near top of file)
BUFFER_SIZE = 3
plate_buffer = deque(maxlen=BUFFER_SIZE)
# Matches exactly 3 uppercase letters + 3 digits + 1 uppercase letter
plate_pattern = re.compile(r'([A-Z]{3}\d{3}[A-Z])')
entry_cooldown = 300  # 5 minutes
last_saved_plate = None
last_entry_time = 0

print("[SYSTEM] Ready. Press 'q' to exit.")

def open_gate(arduino_conn, open_duration=15):
    arduino_conn.write(b'1')
    print("[GATE] Opening gate")
    time.sleep(open_duration)
    arduino_conn.write(b'0')
    print("[GATE] Closing gate")

while True:
    ret, frame = cap.read()
    if not ret:
        break

    distance = mock_ultrasonic_distance()
    print(f"[SENSOR] Distance: {distance} cm")

    if distance <= 50:
        results = model(frame)

        for result in results:
            for box in result.boxes:
                x1, y1, x2, y2 = map(int, box.xyxy[0])
                plate_img = frame[y1:y2, x1:x2]

                # Plate Image Processing
                gray = cv2.cvtColor(plate_img, cv2.COLOR_BGR2GRAY)
                blur = cv2.GaussianBlur(gray, (5, 5), 0)
                thresh = cv2.threshold(blur, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)[1]

                # OCR Extraction
                plate_text = pytesseract.image_to_string(
                    thresh, config='--psm 8 --oem 3 -c tessedit_char_whitelist=ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789'
                ).strip().replace(" ", "")

                # OCR Extraction → plate_text …
                match = plate_pattern.search(plate_text)
                if match:
                    plate = match.group(1)
                    print(f"[VALID] Plate Detected: {plate}")
                    plate_buffer.append(plate)

                    # Once we have 3 candidates, do a majority vote
                    if len(plate_buffer) == BUFFER_SIZE:
                        most_common, _ = Counter(plate_buffer).most_common(1)[0]
                        plate_buffer.clear()
                        now = time.time()

                        # Only log / open if it’s new or cooldown expired
                        if most_common != last_saved_plate or (now - last_entry_time) > entry_cooldown:
                            with open(csv_file, 'a', newline='') as f:
                                writer = csv.writer(f)
                                writer.writerow([most_common, 0, time.strftime('%Y-%m-%d %H:%M:%S')])
                            print(f"[SAVED] {most_common} logged to CSV.")

                            # fire gate operation on background thread
                            if arduino:
                                threading.Thread(target=open_gate, args=(arduino,)).start()

                            last_saved_plate = most_common
                            last_entry_time = now
                        else:
                            print("[SKIPPED] Duplicate within cooldown.")

                cv2.imshow("Plate", plate_img)
                cv2.imshow("Processed", thresh)
                time.sleep(0.5)

    annotated_frame = results[0].plot() if distance <= 50 else frame
    cv2.imshow('Webcam Feed', annotated_frame)

    if cv2.waitKey(1) & 0xFF == ord('q'):
        break

cap.release()
if arduino:
    arduino.close()
cv2.destroyAllWindows()