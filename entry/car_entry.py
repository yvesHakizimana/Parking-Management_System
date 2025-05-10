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

# Initialize Redis Connection
redis_client = redis.Redis(host='localhost', port=6379, db=0, decode_responses=True)

MODEL_PATH = os.path.expanduser("../models/best.pt")
model = YOLO(MODEL_PATH)

# BUFFER & PLATE-FINDING SETUP
BUFFER_SIZE = 3
plate_buffer = deque(maxlen=BUFFER_SIZE)
plate_pattern = re.compile(r'([A-Z]{3}\d{3}[A-Z])')
entry_cooldown = 300
last_saved_plate = None
last_entry_time = 0

print("[SYSTEM] ready. Press 'q' to exit.")

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

# Initialize webcam
cap = cv2.VideoCapture(0)

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

    distance = read_distance()
    print(f"[SENSOR] Distance: {distance}")

    # 1) If we didn't get a valid distance, skip processing
    if distance is None:
        cv2.imshow('Webcam Feed', frame)
        if cv2.waitKey(1) & 0xFF == ord('q'):
            break
        continue

    # 2) Only run the heavy YOLO + OCR pipeline if we’re close enough
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
                        now = time.time()

                        if (most_common != last_saved_plate or
                           (now - last_entry_time) > entry_cooldown):
                            entry_id = redis_client.incr("next_entry_id")
                            timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

                            redis_client.hset(f"entry:{entry_id}", mapping={
                                "plate_number": most_common,
                                "payment_status": "0",
                                "timestamp": timestamp
                            })
                            redis_client.sadd(f"entries:{most_common}", entry_id)
                            redis_client.rpush("logs", f"{timestamp} - ENTRY - {most_common}")
                            print(f"[SAVED] {most_common} logged to Redis.")

                            if arduino:
                                threading.Thread(target=open_gate, args=(arduino,)).start()

                            last_saved_plate = most_common
                            last_entry_time = now
                        else:
                            print(f"[SKIPPED] {most_common} skipped due to cooldown.")

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