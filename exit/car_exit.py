import os
import sys
import time
import pytesseract
import cv2
from ultralytics import YOLO
import redis
import re
import threading
from collections import deque, Counter
from datetime import datetime
from connection.arduino_manager import ArduinoManager

# Point pytesseract at the system binary on linux
pytesseract.pytesseract.tesseract_cmd = '/usr/bin/tesseract'

# Initialize Redis connection
redis_client = redis.Redis(host='localhost', port=6379, db=0, decode_responses=True)

# Load YOLO model
MODEL_PATH = os.path.expanduser("../models/best.pt")
model = YOLO(MODEL_PATH)

# Buffer and plate-finding setup
BUFFER_SIZE = 3
plate_buffer = deque(maxlen=BUFFER_SIZE)
plate_pattern = re.compile(r'([A-Z]{3}\d{3}[A-Z])')

print("[EXIT SYSTEM] Starting up...")

# Initialize Arduino Manager
arduino_manager = ArduinoManager()
arduino_manager.detect_arduino_ports()
arduino_manager.assign_roles(['entry_exit'], {'entry_exit': '/dev/ttyACM0'})

# Connect to entry/exit Arduino
if not arduino_manager.connect_arduino('entry_exit'):
    print("[SYSTEM] Terminating program - Arduino connection required.")
    sys.exit(1)

print("[EXIT SYSTEM] Ready. Press 'q' to exit.")


def read_distance():
    """Read distance from ultrasonic sensor"""
    return arduino_manager.read_distance('entry_exit')


def open_gate(open_duration=15):
    """Open gate for specified duration"""
    return arduino_manager.open_gate('entry_exit', open_duration)


def trigger_unauthorized_alert():
    """Trigger unauthorized exit alert buzzer"""
    try:
        arduino_manager.send_command('entry_exit', 'B')
        print("[ALERT] Unauthorized exit alert triggered")
        return True
    except Exception as e:
        print(f"[ERROR] Failed to trigger unauthorized alert: {e}")
        return False


def trigger_exit_beep():
    """Trigger short beep for authorized exit"""
    try:
        arduino_manager.send_command('entry_exit', 'S')
        return True
    except Exception as e:
        print(f"[ERROR] Failed to trigger exit beep: {e}")
        return False


def has_valid_entry_for_exit(plate_number):
    """
    Check if a car has a valid entry that allows exit.
    Returns (has_entry, entry_id, message)
    """
    try:
        entry_ids = redis_client.smembers(f"entries:{plate_number}")
        if not entry_ids:
            return False, None, "No entry record found"

        # Find the most recent entry
        latest_entry_id = max(entry_ids, key=int)
        entry_data = redis_client.hgetall(f"entry:{latest_entry_id}")

        if not entry_data:
            return False, None, "Invalid entry data"

        payment_status = entry_data.get("payment_status", "0")
        exit_status = entry_data.get("exit_status", "0")

        if exit_status == "1":
            return False, None, "Already exited"

        if payment_status == "0":
            return False, None, "Payment required before exit"

        if payment_status == "1":
            return True, latest_entry_id, "Valid exit allowed"

        return False, None, "Unknown entry status"
    except Exception as e:
        print(f"[ERROR] Failed to check entry validity: {e}")
        return False, None, "System error checking entry"


def mark_as_exited(entry_id):
    """
    Mark an entry as exited with timestamp.
    """
    try:
        timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        redis_client.hset(f"entry:{entry_id}", "exit_status", "1")
        redis_client.hset(f"entry:{entry_id}", "exit_timestamp", timestamp)
        return True
    except Exception as e:
        print(f"[ERROR] Failed to mark as exited: {e}")
        return False


def is_car_inside(plate_number):
    """
    Check if a car is currently inside (has unpaid entry or paid but not exited).
    """
    try:
        entry_ids = redis_client.smembers(f"entries:{plate_number}")
        if not entry_ids:
            return False

        for entry_id in entry_ids:
            entry_data = redis_client.hgetall(f"entry:{entry_id}")
            payment_status = entry_data.get("payment_status", "0")
            exit_status = entry_data.get("exit_status", "0")

            # Car is inside if: unpaid OR (paid but not exited)
            if payment_status == "0" or (payment_status == "1" and exit_status != "1"):
                return True

        return False
    except Exception as e:
        print(f"[ERROR] Failed to check if car is inside: {e}")
        return False


def log_unauthorized_attempt(plate_number, reason):
    """Log unauthorized exit attempt with alert status"""
    try:
        timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        alert_msg = f"{timestamp} - UNAUTHORIZED EXIT ATTEMPT - {plate_number} - {reason} - ALERT TRIGGERED"
        redis_client.rpush("security_alerts", alert_msg)
        redis_client.rpush("logs", alert_msg)
        print(f"[SECURITY ALERT] {alert_msg}")
    except Exception as e:
        print(f"[ERROR] Failed to log unauthorized attempt: {e}")


def log_to_redis(message):
    """Safely log messages to Redis with error handling"""
    try:
        redis_client.rpush("logs", message)
    except Exception as e:
        print(f"[ERROR] Failed to log to Redis: {e}")


# Initialize webcam with error handling
try:
    cap = cv2.VideoCapture(0)
    if not cap.isOpened():
        print("[ERROR] Failed to open webcam")
        sys.exit(1)
except Exception as e:
    print(f"[ERROR] Webcam initialization failed: {e}")
    sys.exit(1)

exit_cooldown = 60  # Prevent rapid exit attempts
last_exit_plate = None
last_exit_time = 0
alert_cooldown = 30  # Prevent spam alerts for same plate
last_alert_plate = None
last_alert_time = 0

try:
    while True:
        ret, frame = cap.read()
        if not ret:
            print("[ERROR] Failed to read from webcam")
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

        # Process plates if vehicle is close enough
        if distance <= 50:
            try:
                results = model(frame)
                for result in results:
                    for box in result.boxes:
                        x1, y1, x2, y2 = map(int, box.xyxy[0])
                        plate_img = frame[y1:y2, x1:x2]

                        if plate_img.size == 0:  # Skip empty plate images
                            continue

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

                                # Exit cooldown check
                                if (most_common == last_exit_plate and
                                        (now - last_exit_time) <= exit_cooldown):
                                    print(f"[COOLDOWN] {most_common} exit blocked due to cooldown")
                                    continue

                                # Check if car is inside parking lot
                                if not is_car_inside(most_common):
                                    print(f"[UNAUTHORIZED ACCESS] {most_common} attempting to exit but not inside")

                                    # Check alert cooldown to prevent spam
                                    if not (most_common == last_alert_plate and (
                                            now - last_alert_time) <= alert_cooldown):
                                        threading.Thread(target=trigger_unauthorized_alert).start()
                                        log_unauthorized_attempt(most_common, "Vehicle not registered as inside")
                                        last_alert_plate = most_common
                                        last_alert_time = now
                                    continue

                                # Check entry validity for exit
                                has_entry, entry_id, message = has_valid_entry_for_exit(most_common)

                                if has_entry:
                                    # Grant authorized exit
                                    print(f"[ACCESS GRANTED] {most_common} - {message}")
                                    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

                                    # Mark as exited
                                    if mark_as_exited(entry_id):
                                        # Log successful exit
                                        log_to_redis(
                                            f"{timestamp} - EXIT GRANTED - {most_common} - Entry ID: {entry_id}")

                                        # Open gate and trigger exit beep
                                        threading.Thread(target=open_gate).start()
                                        threading.Thread(target=trigger_exit_beep).start()

                                        last_exit_plate = most_common
                                        last_exit_time = now
                                        print(f"[SUCCESS] {most_common} exit completed successfully")
                                    else:
                                        print(f"[ERROR] Failed to mark {most_common} as exited")

                                else:
                                    # Deny exit - unauthorized attempt
                                    print(f"[UNAUTHORIZED ACCESS] {most_common} - {message}")

                                    # Check alert cooldown to prevent spam
                                    if not (most_common == last_alert_plate and (
                                            now - last_alert_time) <= alert_cooldown):
                                        threading.Thread(target=trigger_unauthorized_alert).start()
                                        log_unauthorized_attempt(most_common, message)
                                        last_alert_plate = most_common
                                        last_alert_time = now

                        try:
                            cv2.imshow("Plate", plate_img)
                            cv2.imshow("Processed", thresh)
                        except cv2.error:
                            pass  # Skip display if image is invalid
                        time.sleep(0.5)

                annotated_frame = results[0].plot()
            except Exception as e:
                print(f"[ERROR] Processing error: {e}")
                annotated_frame = frame
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