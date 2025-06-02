# database/db_manager.py
import sqlite3
import redis
import json
from datetime import datetime
from typing import Dict, Optional, List, Tuple

import sqlite3
import redis
import json
import os
from datetime import datetime
from typing import Dict, Optional, List, Tuple


class DatabaseManager:
    def __init__(self):
        self.redis_client = redis.Redis(host='localhost', port=6379, db=0, decode_responses=True)
        self.sqlite_connection = None
        self.connect_sqlite()
        self.ensure_tables_exist()

    def connect_sqlite(self):
        """Establish SQLite connection"""
        try:
            # Get the directory where this script is located
            current_dir = os.path.dirname(os.path.abspath(__file__))
            # Create the database file path relative to the database folder
            db_path = os.path.join(current_dir, 'parking_system.db')

            self.sqlite_connection = sqlite3.connect(db_path)
            print(f"[✓] SQLite connection established at: {db_path}")
        except Exception as e:
            print(f"[WARNING] SQLite unavailable, running Redis-only mode: {e}")

    def ensure_tables_exist(self):
        """Create necessary SQLite tables if they don't exist"""
        if not self.sqlite_connection:
            return

        cursor = self.sqlite_connection.cursor()

        # Entries table
        cursor.execute("""
                       CREATE TABLE IF NOT EXISTS entries
                       (
                           id
                           INTEGER
                           PRIMARY
                           KEY,
                           plate_number
                           TEXT
                           NOT
                           NULL,
                           entry_timestamp
                           TIMESTAMP
                           NOT
                           NULL,
                           payment_status
                           INTEGER
                           DEFAULT
                           0,
                           exit_status
                           INTEGER
                           DEFAULT
                           0,
                           exit_timestamp
                           TIMESTAMP
                           NULL,
                           charge_amount
                           DECIMAL
                       (
                           10,
                           2
                       ) NULL,
                           payment_timestamp TIMESTAMP NULL
                           )
                       """)

        cursor.execute("CREATE INDEX IF NOT EXISTS idx_plate ON entries(plate_number)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_entry_time ON entries(entry_timestamp)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_status ON entries(payment_status, exit_status)")

        # Logs table
        cursor.execute("""
                       CREATE TABLE IF NOT EXISTS system_logs
                       (
                           id
                           INTEGER
                           PRIMARY
                           KEY
                           AUTOINCREMENT,
                           timestamp
                           TIMESTAMP
                           NOT
                           NULL,
                           log_message
                           TEXT
                           NOT
                           NULL,
                           log_type
                           TEXT
                           DEFAULT
                           'INFO'
                       )
                       """)

        cursor.execute("CREATE INDEX IF NOT EXISTS idx_timestamp ON system_logs(timestamp)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_type ON system_logs(log_type)")

        # Security alerts table
        cursor.execute("""
                       CREATE TABLE IF NOT EXISTS security_alerts
                       (
                           id
                           INTEGER
                           PRIMARY
                           KEY
                           AUTOINCREMENT,
                           timestamp
                           TIMESTAMP
                           NOT
                           NULL,
                           plate_number
                           TEXT,
                           alert_message
                           TEXT
                           NOT
                           NULL,
                           severity
                           TEXT
                           DEFAULT
                           'MEDIUM'
                       )
                       """)

        cursor.execute("CREATE INDEX IF NOT EXISTS idx_alert_timestamp ON security_alerts(timestamp)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_alert_plate ON security_alerts(plate_number)")

        self.sqlite_connection.commit()
        cursor.close()

    def write_entry(self, entry_id: int, entry_data: Dict) -> bool:
        """Write entry to both Redis and SQLite"""
        try:
            # Write to Redis (existing behavior)
            self.redis_client.hset(f"entry:{entry_id}", mapping=entry_data)
            self.redis_client.sadd(f"entries:{entry_data['plate_number']}", entry_id)

            # Write to SQLite
            if self.sqlite_connection:
                cursor = self.sqlite_connection.cursor()
                cursor.execute("""
                    INSERT OR REPLACE INTO entries 
                    (id, plate_number, entry_timestamp, payment_status,
                    exit_status, exit_timestamp, charge_amount, payment_timestamp)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    entry_id,
                    entry_data['plate_number'],
                    datetime.strptime(entry_data['entry_timestamp'], '%Y-%m-%d %H:%M:%S'),
                    int(entry_data['payment_status']),
                    int(entry_data['exit_status']),
                    datetime.strptime(entry_data['exit_timestamp'], '%Y-%m-%d %H:%M:%S') if entry_data[
                        'exit_timestamp'] else None,
                    float(entry_data['charge_amount']) if entry_data['charge_amount'] else None,
                    datetime.strptime(entry_data['payment_timestamp'], '%Y-%m-%d %H:%M:%S') if entry_data[
                        'payment_timestamp'] else None
                ))
                self.sqlite_connection.commit()
                cursor.close()

            return True
        except Exception as e:
            print(f"[ERROR] Failed to write entry {entry_id}: {e}")
            return False

    def get_entry(self, entry_id: int) -> Optional[Dict]:
        """Get entry from Redis first, fallback to SQLite"""
        try:
            # Try Redis first (fastest)
            entry_data = self.redis_client.hgetall(f"entry:{entry_id}")
            if entry_data:
                return entry_data

            # Fallback to SQLite if not in Redis
            if self.sqlite_connection:
                cursor = self.sqlite_connection.cursor()
                cursor.execute("SELECT * FROM entries WHERE id = ?", (entry_id,))
                result = cursor.fetchone()
                cursor.close()

                if result:
                    # Convert back to Redis format and cache it
                    entry_data = {
                        'plate_number': result[1],
                        'entry_timestamp': result[2],
                        'payment_status': str(result[3]),
                        'exit_status': str(result[4]),
                        'exit_timestamp': str(result[5]) if result[5] else '',
                        'charge_amount': str(result[6]) if result[6] else '',
                        'payment_timestamp': str(result[7]) if result[7] else ''
                    }

                    # Cache in Redis for future requests
                    self.redis_client.hset(f"entry:{entry_id}", mapping=entry_data)
                    return entry_data

            return None
        except Exception as e:
            print(f"[ERROR] Failed to get entry {entry_id}: {e}")
            return None

    def get_entries_for_plate(self, plate_number: str) -> List[str]:
        """Get all entry IDs for a plate number"""
        try:
            # Try Redis first
            entry_ids = self.redis_client.smembers(f"entries:{plate_number}")
            if entry_ids:
                return list(entry_ids)

            # Fallback to SQLite
            if self.sqlite_connection:
                cursor = self.sqlite_connection.cursor()
                cursor.execute("SELECT id FROM entries WHERE plate_number = ?", (plate_number,))
                results = cursor.fetchall()
                cursor.close()

                entry_ids = [str(row[0]) for row in results]
                # Cache in Redis
                if entry_ids:
                    self.redis_client.sadd(f"entries:{plate_number}", *entry_ids)
                return entry_ids

            return []
        except Exception as e:
            print(f"[ERROR] Failed to get entries for plate {plate_number}: {e}")
            return []

    def log_message(self, message: str, log_type: str = 'INFO') -> bool:
        """Log message to both Redis and SQLite"""
        try:
            # Redis (existing behavior)
            self.redis_client.rpush("logs", message)

            # SQLite (new persistent logging)
            if self.sqlite_connection:
                cursor = self.sqlite_connection.cursor()
                cursor.execute("""
                               INSERT INTO system_logs (timestamp, log_message, log_type)
                               VALUES (?, ?, ?)
                               """, (datetime.now(), message, log_type))
                self.sqlite_connection.commit()
                cursor.close()

            return True
        except Exception as e:
            print(f"[ERROR] Failed to log message: {e}")
            return False

    def log_security_alert(self, plate_number: Optional[str], alert_message: str, severity: str = 'MEDIUM') -> bool:
        """Log security alert to both Redis and SQLite"""
        try:
            # Redis
            alert_data = {
                'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                'plate_number': plate_number or '',
                'alert_message': alert_message,
                'severity': severity
            }
            self.redis_client.rpush("security_alerts", json.dumps(alert_data))

            # SQLite
            if self.sqlite_connection:
                cursor = self.sqlite_connection.cursor()
                cursor.execute("""
                               INSERT INTO security_alerts (timestamp, plate_number, alert_message, severity)
                               VALUES (?, ?, ?, ?)
                               """, (datetime.now(), plate_number, alert_message, severity))
                self.sqlite_connection.commit()
                cursor.close()

            return True
        except Exception as e:
            print(f"[ERROR] Failed to log security alert: {e}")
            return False

    def get_unpaid_entries(self) -> List[Dict]:
        """Get all unpaid entries"""
        try:
            unpaid_entries = []

            if self.sqlite_connection:
                cursor = self.sqlite_connection.cursor()
                cursor.execute("""
                               SELECT id, plate_number, entry_timestamp, charge_amount
                               FROM entries
                               WHERE payment_status = 0
                                 AND exit_status = 0
                               ORDER BY entry_timestamp ASC
                               """)
                results = cursor.fetchall()
                cursor.close()

                for row in results:
                    unpaid_entries.append({
                        'entry_id': row[0],
                        'plate_number': row[1],
                        'entry_timestamp': row[2],
                        'charge_amount': row[3]
                    })

            return unpaid_entries
        except Exception as e:
            print(f"[ERROR] Failed to get unpaid entries: {e}")
            return []

    def update_payment_status(self, entry_id: int, charge_amount: float) -> bool:
        """Update payment status for an entry"""
        try:
            payment_timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

            # Update Redis
            self.redis_client.hset(f"entry:{entry_id}", mapping={
                'payment_status': '1',
                'charge_amount': str(charge_amount),
                'payment_timestamp': payment_timestamp
            })

            # Update SQLite
            if self.sqlite_connection:
                cursor = self.sqlite_connection.cursor()
                cursor.execute("""
                               UPDATE entries
                               SET payment_status    = 1,
                                   charge_amount     = ?,
                                   payment_timestamp = ?
                               WHERE id = ?
                               """, (charge_amount, datetime.now(), entry_id))
                self.sqlite_connection.commit()
                cursor.close()

            return True
        except Exception as e:
            print(f"[ERROR] Failed to update payment status for entry {entry_id}: {e}")
            return False

    def update_exit_status(self, entry_id: int) -> bool:
        """Update exit status for an entry"""
        try:
            exit_timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

            # Update Redis
            self.redis_client.hset(f"entry:{entry_id}", mapping={
                'exit_status': '1',
                'exit_timestamp': exit_timestamp
            })

            # Update SQLite
            if self.sqlite_connection:
                cursor = self.sqlite_connection.cursor()
                cursor.execute("""
                               UPDATE entries
                               SET exit_status    = 1,
                                   exit_timestamp = ?
                               WHERE id = ?
                               """, (datetime.now(), entry_id))
                self.sqlite_connection.commit()
                cursor.close()

            return True
        except Exception as e:
            print(f"[ERROR] Failed to update exit status for entry {entry_id}: {e}")
            return False

    def get_recent_logs(self, limit: int = 100) -> List[Dict]:
        """Get recent system logs"""
        try:
            logs = []

            if self.sqlite_connection:
                cursor = self.sqlite_connection.cursor()
                cursor.execute("""
                               SELECT timestamp, log_message, log_type
                               FROM system_logs
                               ORDER BY timestamp DESC
                                   LIMIT ?
                               """, (limit,))
                results = cursor.fetchall()
                cursor.close()

                for row in results:
                    logs.append({
                        'timestamp': row[0],
                        'message': row[1],
                        'type': row[2]
                    })

            return logs
        except Exception as e:
            print(f"[ERROR] Failed to get recent logs: {e}")
            return []

    def get_recent_alerts(self, limit: int = 50) -> List[Dict]:
        """Get recent security alerts"""
        try:
            alerts = []

            if self.sqlite_connection:
                cursor = self.sqlite_connection.cursor()
                cursor.execute("""
                               SELECT timestamp, plate_number, alert_message, severity
                               FROM security_alerts
                               ORDER BY timestamp DESC
                                   LIMIT ?
                               """, (limit,))
                results = cursor.fetchall()
                cursor.close()

                for row in results:
                    alerts.append({
                        'timestamp': row[0],
                        'plate_number': row[1],
                        'message': row[2],
                        'severity': row[3]
                    })

            return alerts
        except Exception as e:
            print(f"[ERROR] Failed to get recent alerts: {e}")
            return []

    def get_statistics(self) -> Dict:
        """Get parking system statistics"""
        try:
            stats = {
                'total_entries': 0,
                'active_vehicles': 0,
                'total_revenue': 0.0,
                'unpaid_entries': 0
            }

            if self.sqlite_connection:
                cursor = self.sqlite_connection.cursor()

                # Total entries
                cursor.execute("SELECT COUNT(*) FROM entries")
                stats['total_entries'] = cursor.fetchone()[0]

                # Active vehicles (entered but not exited)
                cursor.execute("SELECT COUNT(*) FROM entries WHERE exit_status = 0")
                stats['active_vehicles'] = cursor.fetchone()[0]

                # Total revenue
                cursor.execute("SELECT SUM(charge_amount) FROM entries WHERE payment_status = 1")
                result = cursor.fetchone()[0]
                stats['total_revenue'] = float(result) if result else 0.0

                # Unpaid entries
                cursor.execute("SELECT COUNT(*) FROM entries WHERE payment_status = 0 AND exit_status = 0")
                stats['unpaid_entries'] = cursor.fetchone()[0]

                cursor.close()

            return stats
        except Exception as e:
            print(f"[ERROR] Failed to get statistics: {e}")
            return {'total_entries': 0, 'active_vehicles': 0, 'total_revenue': 0.0, 'unpaid_entries': 0}

    def cleanup_old_data(self, days_old: int = 30) -> bool:
        """Clean up old data from both Redis and SQLite"""
        try:
            cutoff_date = datetime.now() - datetime.timedelta(days=days_old)

            if self.sqlite_connection:
                cursor = self.sqlite_connection.cursor()

                # Clean up old logs
                cursor.execute("DELETE FROM system_logs WHERE timestamp < ?", (cutoff_date,))

                # Clean up old completed entries (paid and exited)
                cursor.execute("""
                               DELETE
                               FROM entries
                               WHERE payment_status = 1
                                 AND exit_status = 1
                                 AND exit_timestamp < ?
                               """, (cutoff_date,))

                # Clean up old alerts
                cursor.execute("DELETE FROM security_alerts WHERE timestamp < ?", (cutoff_date,))

                self.sqlite_connection.commit()
                cursor.close()

            # Note: Redis cleanup would require iterating through keys
            # which might be expensive, so we'll rely on Redis TTL for automatic cleanup

            return True
        except Exception as e:
            print(f"[ERROR] Failed to cleanup old data: {e}")
            return False

    def close_connections(self):
        """Close all database connections"""
        try:
            if self.sqlite_connection:
                self.sqlite_connection.close()
                print("[✓] SQLite connection closed")

            # Redis connection will be closed automatically
            print("[✓] Database connections closed")
        except Exception as e:
            print(f"[WARNING] Error closing connections: {e}")

    def __del__(self):
        """Destructor to ensure connections are closed"""
        self.close_connections()