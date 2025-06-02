import os
import time
import pytesseract
import cv2
from ultralytics import YOLO
import redis
import re
import threading
import sys
from collections import deque, Counter
from datetime import datetime
from connection.arduino_manager import ArduinoManager

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

print("[ENTRY SYSTEM] Starting up...")

# Initialize Arduino Manager
arduino_manager = ArduinoManager()
arduino_manager.detect_arduino_ports()
arduino_manager.assign_roles(['entry_exit'], {'entry_exit': '/dev/ttyACM0'})

# Connect to entry/exit Arduino
if not arduino_manager.connect_arduino('entry_exit'):
    print("[SYSTEM] Terminating program - Arduino connection required.")
    sys.exit(1)

print("[ENTRY SYSTEM] Ready. Press 'q' to exit.")

def read_distance():
    """Read distance from ultrasonic sensor"""
    return arduino_manager.read_distance('entry_exit')

def open_gate(open_duration=15):
    """Open gate for specified duration"""
    return arduino_manager.open_gate('entry_exit', open_duration)

def is_car_inside(plate_number):
    """
    Check if a car is currently inside the parking lot.
    Returns True if there's any unpaid and non-exited entry.
    """
    entry_ids = redis_client.smembers(f"entries:{plate_number}")
    if not entry_ids:
        return False

    for entry_id in entry_ids:
        entry_data = redis_client.hgetall(f"entry:{entry_id}")
        # Car is inside if payment is pending OR paid but not exited
        if (entry_data.get("payment_status") == "0" or
                (entry_data.get("payment_status") == "1" and entry_data.get("exit_status") != "1")):
            return True
    return False

def get_active_entry_id(plate_number):
    """
    Get the active entry ID for a plate (unpaid or paid but not exited).
    Returns entry_id if found, None otherwise.
    """
    entry_ids = redis_client.smembers(f"entries:{plate_number}")
    if not entry_ids:
        return None

    for entry_id in entry_ids:
        entry_data = redis_client.hgetall(f"entry:{entry_id}")
        if (entry_data.get("payment_status") == "0" or
                (entry_data.get("payment_status") == "1" and entry_data.get("exit_status") != "1")):
            return entry_id
    return None

# Initialize webcam
cap = cv2.VideoCapture(0)

def preprocess_plate_image(plate_img):
    """Enhanced image preprocessing for better OCR"""
    gray = cv2.cvtColor(plate_img, cv2.COLOR_BGR2GRAY)
    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
    gray = clahe.apply(gray)
    gray = cv2.medianBlur(gray, 3)
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (3, 3))
    gray = cv2.morphologyEx(gray, cv2.MORPH_CLOSE, kernel)
    return gray

try:
    while True:
        ret, frame = cap.read()
        if not ret:
            break

        distance = read_distance()
        if distance is not None:
            print(f"[SENSOR] Distance: {distance}")

        # Skip processing if no valid distance
        if distance is None:
            cv2.imshow('Webcam Feed', frame)
            if cv2.waitKey(1) & 0xFF == ord('q'):
                break
            continue

        # Only run the heavy YOLO + OCR pipeline if we're close enough
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
                        print(f"[DETECTED] Plate: {plate}")
                        plate_buffer.append(plate)

                        if len(plate_buffer) == BUFFER_SIZE:
                            most_common, _ = Counter(plate_buffer).most_common(1)[0]
                            plate_buffer.clear()
                            now = time.time()

                            # Enhanced validation checks
                            if is_car_inside(most_common):
                                print(f"[ACCESS DENIED] {most_common} is already inside")
                                timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                                redis_client.rpush("logs",
                                                   f"{timestamp} - ENTRY DENIED - {most_common} - Already inside")
                                continue

                            if (most_common == last_saved_plate and
                                    (now - last_entry_time) <= entry_cooldown):
                                print(f"[COOLDOWN] {most_common} entry blocked due to cooldown")
                                continue

                            # Create new entry with enhanced tracking
                            entry_id = redis_client.incr("next_entry_id")
                            timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

                            # Enhanced entry data structure
                            entry_data = {
                                "plate_number": most_common,
                                "entry_timestamp": timestamp,
                                "payment_status": "0",  # 0=unpaid, 1=paid
                                "exit_status": "0",  # 0=inside, 1=exited
                                "exit_timestamp": "",
                                "charge_amount": "",
                                "payment_timestamp": ""
                            }

                            redis_client.hset(f"entry:{entry_id}", mapping=entry_data)
                            redis_client.sadd(f"entries:{most_common}", entry_id)
                            redis_client.rpush("logs",
                                               f"{timestamp} - ENTRY GRANTED - {most_common} - Entry ID: {entry_id}")
                            print(f"[ENTRY GRANTED] {most_common} logged with ID: {entry_id}")

                            threading.Thread(target=open_gate).start()

                            last_saved_plate = most_common
                            last_entry_time = now

                    cv2.imshow("Plate", plate_img)
                    cv2.imshow("Processed", thresh)
                    time.sleep(0.5)

            annotated_frame = results[0].plot()
        else:
            annotated_frame = frame

        cv2.imshow('Webcam Feed', annotated_frame)
        if cv2.waitKey(1) & 0xFF == ord('q'):
            break

except KeyboardInterrupt:
    print("\n[SYSTEM] Program interrupted by user")
except Exception as e:
    print(f"[ERROR] Unexpected error: {e}")
finally:
    print("[SYSTEM] Cleaning up...")
    cap.release()
    arduino_manager.close_all_connections()
    cv2.destroyAllWindows()
    print("[SYSTEM] Program terminated")