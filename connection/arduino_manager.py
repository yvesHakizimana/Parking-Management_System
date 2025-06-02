import glob
import serial
import serial.tools.list_ports
import time


class ArduinoManager:
    def __init__(self):
        self.arduino_ports = {}
        self.connections = {}
        self.role_assignments = {}

    def detect_arduino_ports(self):
        """Detect all available Arduino ports"""
        arduino_ports = []

        # Check for common Arduino port patterns (Linux/Mac)
        for dev in glob.glob("/dev/ttyACM*") + glob.glob("/dev/ttyUSB*"):
            arduino_ports.append(dev)

        # Check for Arduino ports by description (cross-platform)
        for port in serial.tools.list_ports.comports():
            desc = port.description.lower()
            if 'arduino' in desc or 'usb-serial' in desc:
                if port.device not in arduino_ports:  # Avoid duplicates
                    arduino_ports.append(port.device)

        self.arduino_ports = sorted(arduino_ports) if arduino_ports else []
        return self.arduino_ports

    def assign_roles(self, roles=None, specific_assignments=None):
        """Assign roles to detected Arduino ports"""
        if not self.arduino_ports:
            print("No Arduino devices detected.")
            return False

        # If specific assignments are provided, use them
        if specific_assignments:
            self.role_assignments = {}
            for role, port in specific_assignments.items():
                if port in self.arduino_ports:
                    self.role_assignments[role] = port
                    print(f"{role.replace('_', '/').title()} assigned to: {port}")
                else:
                    print(f"Port {port} not available for {role}")
            return len(self.role_assignments) > 0

        # Default role assignment if none provided
        if roles is None:
            roles = ['payment', 'entry_exit']

        self.role_assignments = {}

        for i, role in enumerate(roles):
            if i < len(self.arduino_ports):
                self.role_assignments[role] = self.arduino_ports[i]
                print(f"{role.replace('_', '/').title()} assigned to: {self.arduino_ports[i]}")
            else:
                print(f"No port available for {role.replace('_', '/').title()}.")

        return len(self.role_assignments) > 0

    def connect_arduino(self, role, baud_rate=9600, timeout=1):
        """Establish connection to Arduino for specific role"""
        if role not in self.role_assignments:
            print(f"No port assigned for role: {role}")
            return False

        port = self.role_assignments[role]

        try:
            # Close existing connection if any
            if role in self.connections and self.connections[role].is_open:
                self.connections[role].close()

            self.connections[role] = serial.Serial(port, baud_rate, timeout=timeout)
            time.sleep(2)  # Give Arduino time to initialize
            print(f"[CONNECTED] {role.replace('_', '/').title()} Arduino on {port}")
            return True
        except serial.SerialException as e:
            print(f"[ERROR] Failed to connect to {role} Arduino on {port}: {e}")
            return False

    def is_connected(self, role):
        """Check if Arduino for specific role is connected"""
        return (role in self.connections and
                self.connections[role] is not None and
                self.connections[role].is_open)

    def reconnect(self, role, baud_rate=9600, timeout=1):
        """Attempt to reconnect Arduino for specific role"""
        print(f"[RECONNECT] Attempting to reconnect {role} Arduino...")
        return self.connect_arduino(role, baud_rate, timeout)

    def send_command(self, role, command, max_retries=3):
        """Send command to Arduino with automatic retry and reconnection"""
        retry_count = 0

        while retry_count < max_retries:
            if not self.is_connected(role):
                if not self.reconnect(role):
                    retry_count += 1
                    print(f"[RETRY] Reconnection failed for {role}, retry {retry_count}/{max_retries}")
                    time.sleep(1)
                    continue

            try:
                if isinstance(command, str):
                    self.connections[role].write(command.encode())
                else:
                    self.connections[role].write(command)
                return True
            except serial.SerialException as e:
                print(f"[ERROR] Command failed for {role}: {e}")
                if role in self.connections:
                    self.connections[role].close()
                retry_count += 1
                time.sleep(1)

        print(f"[ERROR] Failed to send command to {role} after {max_retries} retries")
        return False

    def read_response(self, role, max_retries=3):
        """Read response from Arduino with automatic retry"""
        retry_count = 0

        while retry_count < max_retries:
            if not self.is_connected(role):
                if not self.reconnect(role):
                    retry_count += 1
                    continue

            try:
                if self.connections[role].in_waiting > 0:
                    response = self.connections[role].readline().decode('utf-8').strip()
                    return response
                return None
            except serial.SerialException as e:
                print(f"[ERROR] Read failed for {role}: {e}")
                if role in self.connections:
                    self.connections[role].close()
                retry_count += 1
                time.sleep(1)

        return None

    def communicate(self, role, command, baud_rate=9600):
        """Send command and read response (legacy compatibility)"""
        if self.send_command(role, command):
            time.sleep(0.1)  # Small delay for response
            return self.read_response(role)
        return None

    def open_gate(self, role='entry_exit', open_duration=15):
        """Open gate for specified duration"""
        if self.send_command(role, b'1'):
            print(f"[GATE] Opening gate via {role}")
            time.sleep(open_duration)
            if self.send_command(role, b'0'):
                print(f"[GATE] Closing gate via {role}")
                return True
        print(f"[GATE ERROR] Failed to operate gate via {role}")
        return False

    def trigger_buzzer(self, role='entry_exit'):
        """Trigger warning buzzer"""
        if self.send_command(role, b'2'):
            print(f"[ALERT] Buzzer triggered via {role}")
            return True
        print(f"[BUZZER ERROR] Failed to trigger buzzer via {role}")
        return False

    def read_distance(self, role='entry_exit'):
        """Read distance from ultrasonic sensor"""
        try:
            response = self.read_response(role)
            if response:
                return float(response)
        except (ValueError, TypeError):
            pass
        return None

    def close_all_connections(self):
        """Close all Arduino connections"""
        for role, connection in self.connections.items():
            if connection and connection.is_open:
                connection.close()
                print(f"[CLOSED] {role.replace('_', '/').title()} Arduino connection")
        self.connections.clear()

    def get_connection_status(self):
        """Get status of all connections"""
        status = {}
        for role in self.role_assignments:
            status[role] = {
                'port': self.role_assignments[role],
                'connected': self.is_connected(role)
            }
        return status


# Convenience functions for backward compatibility
def detect_arduino_ports():
    manager = ArduinoManager()
    return manager.detect_arduino_ports()


def assign_arduino_roles(ports):
    if not ports:
        print("No Arduino devices detected.")
        return None, None

    entry_exit_port = ports[0] if len(ports) >= 1 else None
    payment_port = ports[1] if len(ports) >= 2 else None

    if entry_exit_port:
        print(f"Entry/Exit assigned to: {entry_exit_port}")
    else:
        print("No port available for Entry/Exit.")

    if payment_port:
        print(f"Payment assigned to: {payment_port}")
    else:
        print("No port available for Payment.")

    return entry_exit_port, payment_port


def communicate_with_arduino(port, command, baud_rate=9600):
    try:
        ser = serial.Serial(port, baud_rate, timeout=1)
        ser.write(command.encode())
        response = ser.readline().decode().strip()
        print(f"Response from {port}: {response}")
        ser.close()
        return response
    except serial.SerialException as e:
        print(f"Error communicating with {port}: {e}")
        return None
