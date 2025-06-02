import time
from datetime import datetime
import math

import redis

from connection.arduino_manager import ArduinoManager
from database.db_manager import DatabaseManager

# Redis configuration
REDIS_HOST = 'localhost'
REDIS_PORT = 6379
REDIS_DB = 0

# Payment configuration
CHARGE_RATE = 500  # 500 RWF per hour
MINIMUM_CHARGE = 500  # Minimum charge for any stay
MIN_BALANCE = 0  # Minimum allowed balance after transaction
MAX_BALANCE = 999999999  # Maximum balance (safety check)


class PaymentProcessor:
    def __init__(self):
        self.db_manager = DatabaseManager()  # Use db_manager instead of direct Redis
        self.redis_client = self.db_manager.redis_client  # For backward compatibility
        self.arduino_manager = None
        self.connected = False

    def initialize_redis(self):
        """Initialize Redis connection"""
        try:
            self.redis_client = redis.Redis(
                host=REDIS_HOST,
                port=REDIS_PORT,
                db=REDIS_DB,
                decode_responses=True,
                socket_connect_timeout=5
            )
            # Test connection
            self.redis_client.ping()
            print("[✓] Redis connection established")
            return True
        except Exception as e:
            print(f"[✗] Redis connection failed: {e}")
            return False

    def initialize_arduino_manager(self):
        """Initialize Arduino Manager and connect to payment terminal"""
        try:
            print("[INFO] Initializing Arduino Manager...")

            # Initialize Arduino Manager
            self.arduino_manager = ArduinoManager()
            self.arduino_manager.detect_arduino_ports()
            self.arduino_manager.assign_roles(['payment'], {'payment': '/dev/ttyACM1'})

            # Connect to payment Arduino
            if not self.arduino_manager.connect_arduino('payment'):
                print("[✗] Arduino not detected on /dev/ttyACM1")
                return False
            else:
                print("[✓] Payment Arduino ready on /dev/ttyACM1")
                self.connected = True
                return True

        except Exception as e:
            print(f"[✗] Arduino Manager initialization failed: {e}")
            return False

    def validate_balance(self, balance_str):
        """Validate balance string and convert to integer"""
        try:
            if not balance_str or not balance_str.strip():
                return False, 0, "Empty balance value"

            balance_int = int(balance_str.strip())

            if balance_int < 0:
                return False, 0, "Negative balance not allowed"

            if balance_int > MAX_BALANCE:
                return False, 0, f"Balance exceeds maximum limit ({MAX_BALANCE})"

            return True, balance_int, ""

        except (ValueError, TypeError):
            return False, 0, "Invalid balance format - must be numeric"

    def calculate_charge(self, entry_time_str):
        """Calculate parking charge based on entry time"""
        try:
            entry_time = datetime.strptime(entry_time_str, '%Y-%m-%d %H:%M:%S')
            current_time = datetime.now()
            duration_hours = (current_time - entry_time).total_seconds() / 3600

            # Ensure minimum charge and round up partial hours
            charge = max(MINIMUM_CHARGE, int(math.ceil(duration_hours) * CHARGE_RATE))
            return charge

        except (ValueError, TypeError):
            return None

    def get_unpaid_entry(self, plate_number):
        """Get unpaid entry for a plate number"""
        entry_ids = self.db_manager.get_entries_for_plate(plate_number)
        for entry_id in entry_ids:
            entry_data = self.db_manager.get_entry(int(entry_id))
            if entry_data and entry_data.get('payment_status') == '0':
                return entry_id, entry_data
        return None, None

    def process_transaction(self, plate_number, balance_str):
        """Process payment transaction for a plate number"""
        try:
            # Validate balance
            is_valid, balance, error_msg = self.validate_balance(balance_str)
            if not is_valid:
                return False, f"Invalid balance: {error_msg}"

            # Get unpaid entry for this plate
            entry_id, entry_data = self.get_unpaid_entry(plate_number)
            if not entry_id or not entry_data:
                return False, "No unpaid parking session found"

            # Calculate charge
            charge = self.calculate_charge(entry_data['entry_timestamp'])
            if charge is None:
                return False, "Failed to calculate parking charge"

            # Check if balance is sufficient
            if balance < charge:
                return False, f"Insufficient balance. Required: {charge} RWF, Available: {balance} RWF"

            # Calculate new balance
            new_balance = balance - charge

            # Update payment status in database
            if self.db_manager.update_payment_status(int(entry_id), charge):
                self.db_manager.log_message(
                    f"Payment processed for {plate_number} - Amount: {charge} RWF, New balance: {new_balance} RWF",
                    "PAYMENT"
                )
                return True, str(new_balance)
            else:
                return False, "Database update failed"

        except Exception as e:
            return False, f"Transaction processing error: {str(e)}"

    def handle_payment_request(self, message):
        """Handle payment request from Arduino"""
        try:
            print(f"[REQUEST] Received: {message}")

            if not message.startswith("PROCESS_PAYMENT:"):
                return "ERROR:Invalid request format"

            data = message[16:].strip()
            if ',' not in data:
                return "ERROR:Missing comma separator in request"

            parts = data.split(',', 1)  # Split only on first comma
            if len(parts) != 2:
                return "ERROR:Invalid request format - expected PLATE,BALANCE"

            plate, balance = parts

            if not plate.strip() or not balance.strip():
                return "ERROR:Missing plate number or balance data"

            print(f"[PROCESSING] Plate: {plate}, Balance: {balance}")

            success, response = self.process_transaction(plate, balance)

            if success:
                result = f"NEW_BALANCE:{response}"
                print(f"[RESPONSE] {result}")
                return result
            else:
                result = f"ERROR:{response}"
                print(f"[RESPONSE] {result}")
                return result

        except Exception as e:
            error_result = f"ERROR:Request processing failed: {str(e)}"
            print(f"[ERROR] {error_result}")
            return error_result

    def run(self):
        """Main execution loop"""
        print("\n" + "=" * 50)
        print("    PARKING PAYMENT PROCESSING SYSTEM")
        print("=" * 50)

        # Initialize systems
        if not self.initialize_redis():
            print("[FATAL] Cannot proceed without Redis connection")
            return

        if not self.initialize_arduino_manager():
            print("[FATAL] Cannot proceed without Arduino connection")
            return

        print("\n[SYSTEM] Payment processor ready for transactions...")
        print("[INFO] Waiting for RFID card transactions on /dev/ttyACM1...")
        print("Press Ctrl+C to shutdown system\n")

        try:
            while True:
                if self.arduino_manager and self.arduino_manager.is_connected('payment'):
                    try:
                        # Read message from Arduino using ArduinoManager
                        response = self.arduino_manager.read_response('payment')

                        if response and response.startswith("PROCESS_PAYMENT:"):
                            # Process the payment request
                            result = self.handle_payment_request(response)

                            # Send response back to Arduino using ArduinoManager
                            self.arduino_manager.send_command('payment', f"{result}\n")

                        time.sleep(0.1)  # Small delay to prevent CPU overload

                    except Exception as e:
                        print(f"[ERROR] Communication error: {e}")
                        print("[INFO] Attempting to reconnect...")
                        self.initialize_arduino_manager()
                        time.sleep(2)

                else:
                    print("[ERROR] Arduino connection lost. Attempting reconnection...")
                    self.initialize_arduino_manager()
                    time.sleep(2)

        except KeyboardInterrupt:
            print("\n[SHUTDOWN] Payment system shutting down...")
        except Exception as e:
            print(f"[FATAL ERROR] System error: {e}")
        finally:
            self.cleanup()

    def cleanup(self):
        """Clean up connections"""
        if self.arduino_manager:
            try:
                self.arduino_manager.close_all_connections()
                print("[✓] Arduino connections closed")
            except Exception as e:
                print(f"[WARNING] Error closing Arduino connections: {e}")

        if self.redis_client:
            try:
                self.redis_client.close()
                print("[✓] Redis connection closed")
            except:
                pass

        print("[SYSTEM] Cleanup complete")


def main():
    processor = PaymentProcessor()
    processor.run()


if __name__ == "__main__":
    main()