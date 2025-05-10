import os
import time
import glob
import serial
import serial.tools.list_ports
import pytesseract
import cv2
from ultralytics import YOLO
import redis
import re
import threading
from collections import deque, Counter
from datetime import datetime

# Point pytesseract at the system binary on linux
pytesseract.pytesseract.tesseract_cmd = '/usr/bin/tesseract'

# Initialize Redis connection
redis_client = redis.Redis(host='localhost', port=6379, db=0, decode_responses=True)

# Load YOLO model (same as car_entry.py)
MODEL_PATH = os.path.expanduser("../models/best.pt")
model = YOLO(MODEL_PATH)

# Buffer and plate-finding setup
BUFFER_SIZE = 3
plate_buffer = deque(maxlen=BUFFER_SIZE)
plate_pattern = re.compile(r'([A-Z]{3}\d{3}[A-Z])')

print("[EXIT SYSTEM] Ready. Press 'q' to quit.")

# ===== Auto-detect Arduino Serial Port =====
def detect_arduino_port():
    for dev in glob.glob("/dev/ttyACM*") + glob.glob("/dev/ttyUSB*"):
        return dev
    for port in serial.tools.list_ports.comports():
        desc = port.description.lower()
        if 'arduino' in desc or 'usb-serial' in desc:
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

# ===== Read Distance from Arduino =====
def read_distance():
    """
    Reads a distance (float) value from the Arduino via serial.
    Returns the float if valid, or None if invalid/empty.
    """
    if arduino and arduino.in_waiting > 0:
        try:
            line = arduino.readline().decode('utf-8').strip()
            return float(line)
        except ValueError:
            return None
    return None

# ===== Gate Control =====
def open_gate(arduino_conn, open_duration=15):
    arduino_conn.write(b'1')
    print("[GATE] Opening gate")
    time.sleep(open_duration)
    arduino_conn.write(b'0')
    print("[GATE] Closing gate")

# ===== Check Payment Status in Redis =====
def is_payment_complete(plate_number):
    entry_ids = redis_client.smembers(f"entries:{plate_number}")
    if not entry_ids:
        return False
    latest_entry_id = max(entry_ids, key=int)
    entry_data = redis_client.hgetall(f"entry:{latest_entry_id}")
    return entry_data.get("payment_status") == "1"

# ===== Webcam and Main Loop =====
cap = cv2.VideoCapture(0)

while True:
    ret, frame = cap.read()
    if not ret:
        break

    distance = read_distance()
    print(f"[SENSOR] Distance: {distance}")

    # Skip processing if no valid distance
    if distance is None:
        cv2.imshow('Webcam Feed', frame)
        if cv2.waitKey(1) & 0xFF == ord('q'):
            break
        continue

    # Process plates if vehicle is close enough
    if distance <= 50:
        results = model(frame)
        for result in results:
            for box in result.boxes:
                x1, y1, x2, y2 = map(int, box.xyxy[0])
                plate_img = frame[y1:y2, x1:x2]

                gray = cv2.cvtColor(plate_img, cv2.COLOR_BGR2GRAY)
                blur = cv2.GaussianBlur(gray, (5, 5), 0)
                thresh = cv2.threshold(
                    blur, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU
                )[1]

                plate_text = pytesseract.image_to_string(
                    thresh,
                    config='--psm 8 --oem 3 '
                           '-c tessedit_char_whitelist=ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789'
                ).strip().replace(" ", "")

                match = plate_pattern.search(plate_text)
                if match:
                    plate = match.group(1)
                    print(f"[VALID] Plate Detected: {plate}")
                    plate_buffer.append(plate)

                    if len(plate_buffer) == BUFFER_SIZE:
                        most_common, _ = Counter(plate_buffer).most_common(1)[0]
                        plate_buffer.clear()

                        if is_payment_complete(most_common):
                            print(f"[ACCESS GRANTED] Payment complete for {most_common}")
                            timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                            redis_client.rpush("logs", f"{timestamp} - EXIT - {most_common} - Payment complete")
                            if arduino:
                                threading.Thread(target=open_gate, args=(arduino,)).start()
                        else:
                            print(f"[ACCESS DENIED] Payment NOT complete for {most_common}")
                            timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                            redis_client.rpush("logs", f"{timestamp} - EXIT - {most_common} - Payment incomplete")
                            if arduino:
                                arduino.write(b'2')  # Trigger warning buzzer
                                print("[ALERT] Buzzer triggered (sent '2')")

                cv2.imshow("Plate", plate_img)
                cv2.imshow("Processed", thresh)
                time.sleep(0.5)

        annotated_frame = results[0].plot()
    else:
        annotated_frame = frame

    cv2.imshow('Webcam Feed', annotated_frame)
    if cv2.waitKey(1) & 0xFF == ord('q'):
        break

cap.release()
if arduino:
    arduino.close()
cv2.destroyAllWindows()