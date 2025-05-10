import serial
import redis
import time
from datetime import datetime
import glob

# Initialize Redis connection
redis_client = redis.Redis(host='localhost', port=6379, db=0, decode_responses=True)


# Serial port configuration
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

# Parking charge rate (RWF per hour)
CHARGE_RATE = 500  # 500 RWF per hour
MINIMUM_CHARGE = 500  # Minimum charge for any stay


def calculate_charge(entry_time_str):
    """Calculate parking charge based on entry time."""
    try:
        entry_time = datetime.strptime(entry_time_str, '%Y-%m-%d %H:%M:%S')
        current_time = datetime.now()
        duration_hours = (current_time - entry_time).total_seconds() / 3600
        charge = max(MINIMUM_CHARGE, int(duration_hours * CHARGE_RATE))
        return charge
    except ValueError:
        return None


def process_transaction(plate, balance):
    """Process the transaction: check Redis, calculate charge, deduct balance."""
    # Find the latest entry for the plate
    entry_ids = redis_client.smembers(f"entries:{plate}")
    if not entry_ids:
        return False, "No entry record found"

    # Get the latest entry
    latest_entry_id = max(entry_ids, key=int)
    entry_data = redis_client.hgetall(f"entry:{latest_entry_id}")
    if not entry_data or entry_data.get("payment_status") == "1":
        return False, "No unpaid entry found"

    # Calculate charge
    charge = calculate_charge(entry_data["timestamp"])
    if charge is None:
        return False, "Invalid entry timestamp"

    balance_int = int(balance)
    if balance_int < charge:
        # Log insufficient balance
        timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        redis_client.rpush("logs", f"{timestamp} - ERROR - {plate} - Insufficient balance: {balance} < {charge}")
        return False, f"Insufficient balance: {balance} < {charge}"

    # Deduct charge and update balance
    new_balance = balance_int - charge
    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

    # Update Redis: mark payment as complete
    redis_client.hset(f"entry:{latest_entry_id}", "payment_status", "1")
    redis_client.rpush("logs", f"{timestamp} - PAYMENT - {plate} - Charged: {charge}, New Balance: {new_balance}")

    return True, str(new_balance)


def main():
    if not arduino:
        print("[ERROR] Cannot proceed without Arduino connection.")
        return

    while True:
        if arduino.in_waiting > 0:
            line = arduino.readline().decode('utf-8').strip()
            if line.startswith("PROCESS_PAYMENT:"):
                try:
                    plate, balance = line[16:].split(',')
                    print(f"[RECEIVED] Plate: {plate}, Balance: {balance}")

                    success, response = process_transaction(plate, balance)
                    if success:
                        arduino.write(f"NEW_BALANCE:{response}\n".encode())
                        print(f"[SENT] New balance: {response}")
                    else:
                        arduino.write(f"ERROR:{response}\n".encode())
                        print(f"[SENT] Error: {response}")
                except ValueError:
                    arduino.write(b"ERROR:Invalid data format\n")
                    print("[ERROR] Invalid data format received")

        time.sleep(0.1)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("[SYSTEM] Shutting down...")
        if arduino:
            arduino.close()