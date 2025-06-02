from flask import Flask, render_template, request
from flask_socketio import SocketIO, emit
import redis
from datetime import datetime, timedelta
import json
import threading
import time
from collections import defaultdict
import asyncio

app = Flask(__name__)
app.config['SECRET_KEY'] = 'your-secret-key-here'
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='threading')

# Redis connection
r = redis.Redis(host='localhost', port=6379, db=0, decode_responses=True)

# Global variables for real-time data
real_time_data = {
    'stats': {},
    'recent_entries': [],
    'current_inside': [],
    'recent_logs': [],
    'system_health': {},
    'hourly_stats': []
}

# Connected clients tracking
connected_clients = set()


def get_system_statistics():
    """Get comprehensive system statistics with additional metrics"""
    stats = {}
    entry_keys = r.keys("entry:*")
    stats['total_entries'] = len(entry_keys)

    inside_count = 0
    unpaid_count = 0
    paid_not_exited = 0
    completed_exits = 0
    total_revenue = 0
    today_entries = 0
    avg_duration = 0

    # Get today's date for filtering
    today = datetime.now().strftime('%Y-%m-%d')

    for key in entry_keys:
        entry_data = r.hgetall(key)
        payment_status = entry_data.get('payment_status', '0')
        exit_status = entry_data.get('exit_status', '0')
        entry_time = entry_data.get('entry_timestamp', '')

        # Count today's entries
        if today in entry_time:
            today_entries += 1

        if payment_status == '0':
            unpaid_count += 1
            inside_count += 1
        elif payment_status == '1' and exit_status == '0':
            paid_not_exited += 1
            inside_count += 1
        elif payment_status == '1' and exit_status == '1':
            completed_exits += 1

        if entry_data.get('payment_status') == '1':
            charge = entry_data.get('charge_amount', '0')
            try:
                total_revenue += float(charge)
            except (ValueError, TypeError):
                pass

    # Calculate occupancy rate (assuming max capacity of 100)
    max_capacity = 100
    occupancy_rate = (inside_count / max_capacity) * 100 if max_capacity > 0 else 0

    stats.update({
        'cars_inside': inside_count,
        'unpaid_entries': unpaid_count,
        'paid_not_exited': paid_not_exited,
        'completed_exits': completed_exits,
        'total_revenue': total_revenue,
        'today_entries': today_entries,
        'occupancy_rate': min(occupancy_rate, 100),
        'max_capacity': max_capacity,
        'payment_rate': ((stats['total_entries'] - unpaid_count) / stats['total_entries'] * 100) if stats[
                                                                                                        'total_entries'] > 0 else 0
    })

    return stats


def get_cars_inside():
    """Get list of cars currently inside with enhanced data"""
    entries = r.keys("entry:*")
    inside_cars = []

    for entry_key in entries:
        entry_data = r.hgetall(entry_key)
        payment_status = entry_data.get('payment_status', '0')
        exit_status = entry_data.get('exit_status', '0')

        if payment_status == '0' or (payment_status == '1' and exit_status != '1'):
            # Calculate duration
            entry_time_str = entry_data.get('entry_timestamp', '')
            try:
                entry_time = datetime.strptime(entry_time_str, '%Y-%m-%d %H:%M:%S')
                duration = datetime.now() - entry_time
                duration_hours = duration.total_seconds() / 3600
            except:
                duration_hours = 0

            inside_cars.append({
                'plate': entry_data.get('plate_number', 'Unknown'),
                'entry_time': entry_data.get('entry_timestamp', 'Unknown'),
                'status': 'Paid' if payment_status == '1' else 'Unpaid',
                'charge': entry_data.get('charge_amount', 'Not calculated'),
                'entry_id': entry_key.split(':')[1],
                'duration_hours': round(duration_hours, 1),
                'priority': 'high' if duration_hours > 24 else 'medium' if duration_hours > 12 else 'normal'
            })

    return sorted(inside_cars, key=lambda x: x['entry_time'], reverse=True)


def get_recent_entries(limit=15):
    """Get recent entries with enhanced data"""
    entries = r.keys("entry:*")
    if not entries:
        return []

    recent_entries = []
    sorted_entries = sorted(entries, key=lambda x: int(x.split(':')[1]), reverse=True)

    for entry_key in sorted_entries[:limit]:
        entry_data = r.hgetall(entry_key)

        # Calculate duration if exited
        duration = "N/A"
        if entry_data.get('exit_status') == '1':
            try:
                entry_time = datetime.strptime(entry_data.get('entry_timestamp', ''), '%Y-%m-%d %H:%M:%S')
                exit_time = datetime.strptime(entry_data.get('exit_timestamp', ''), '%Y-%m-%d %H:%M:%S')
                duration = str(exit_time - entry_time)
            except:
                pass

        recent_entries.append({
            'id': entry_key.split(':')[1],
            'plate': entry_data.get('plate_number', 'Unknown'),
            'entry_time': entry_data.get('entry_timestamp', 'Unknown'),
            'exit_time': entry_data.get('exit_timestamp', 'Not exited'),
            'payment_status': 'Paid' if entry_data.get('payment_status') == '1' else 'Unpaid',
            'exit_status': 'Exited' if entry_data.get('exit_status') == '1' else 'Inside',
            'charge': entry_data.get('charge_amount', 'Not calculated'),
            'duration': duration
        })

    return recent_entries


def get_hourly_statistics():
    """Get hourly entry statistics for the last 24 hours"""
    hourly_stats = []
    now = datetime.now()

    for i in range(24):
        hour_start = now - timedelta(hours=i + 1)
        hour_end = now - timedelta(hours=i)

        # Count entries in this hour
        entries_count = 0
        exits_count = 0
        revenue = 0

        entry_keys = r.keys("entry:*")
        for key in entry_keys:
            entry_data = r.hgetall(key)

            # Check entry time
            entry_time_str = entry_data.get('entry_timestamp', '')
            try:
                entry_time = datetime.strptime(entry_time_str, '%Y-%m-%d %H:%M:%S')
                if hour_start <= entry_time < hour_end:
                    entries_count += 1
            except:
                pass

            # Check exit time
            exit_time_str = entry_data.get('exit_timestamp', '')
            if exit_time_str and exit_time_str != 'Not exited':
                try:
                    exit_time = datetime.strptime(exit_time_str, '%Y-%m-%d %H:%M:%S')
                    if hour_start <= exit_time < hour_end:
                        exits_count += 1
                        if entry_data.get('payment_status') == '1':
                            try:
                                revenue += float(entry_data.get('charge_amount', '0'))
                            except:
                                pass
                except:
                    pass

        hourly_stats.append({
            'hour': hour_start.strftime('%H:%M'),
            'entries': entries_count,
            'exits': exits_count,
            'revenue': revenue
        })

    return list(reversed(hourly_stats))


def get_system_health():
    """Get system health metrics"""
    try:
        # Redis health
        redis_ping = r.ping()
        redis_memory = r.info()['used_memory_human']

        # Data integrity checks
        entry_keys = r.keys("entry:*")
        orphaned_entries = 0

        for key in entry_keys:
            entry_data = r.hgetall(key)
            plate = entry_data.get('plate_number')
            if plate:
                plate_entries = r.smembers(f"entries:{plate}")
                entry_id = key.split(':')[1]
                if entry_id not in plate_entries:
                    orphaned_entries += 1

        return {
            'redis_connected': redis_ping,
            'redis_memory': redis_memory,
            'total_keys': len(r.keys("*")),
            'orphaned_entries': orphaned_entries,
            'system_status': 'healthy' if orphaned_entries == 0 else 'warning',
            'last_check': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        }
    except Exception as e:
        return {
            'redis_connected': False,
            'error': str(e),
            'system_status': 'error',
            'last_check': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        }


def update_real_time_data():
    """Background thread to update real-time data and emit to clients"""
    while True:
        try:
            # Update data
            old_stats = real_time_data.get('stats', {})
            new_stats = get_system_statistics()

            real_time_data['stats'] = new_stats
            real_time_data['recent_entries'] = get_recent_entries()
            real_time_data['current_inside'] = get_cars_inside()
            real_time_data['recent_logs'] = get_recent_logs()
            real_time_data['system_health'] = get_system_health()
            real_time_data['hourly_stats'] = get_hourly_statistics()

            # Check for significant changes and emit alerts
            if old_stats:
                if new_stats['cars_inside'] != old_stats.get('cars_inside', 0):
                    socketio.emit('occupancy_change', {
                        'new_count': new_stats['cars_inside'],
                        'old_count': old_stats.get('cars_inside', 0),
                        'timestamp': datetime.now().isoformat()
                    })

                if new_stats['unpaid_entries'] > old_stats.get('unpaid_entries', 0):
                    socketio.emit('payment_alert', {
                        'unpaid_count': new_stats['unpaid_entries'],
                        'message': f"{new_stats['unpaid_entries']} vehicles need to pay",
                        'timestamp': datetime.now().isoformat()
                    })

            # Emit updated data to all connected clients
            socketio.emit('data_update', real_time_data)

            time.sleep(2)  # Update every 2 seconds
        except Exception as e:
            print(f"Error updating real-time data: {e}")
            time.sleep(5)


def get_recent_logs(limit=20):
    """Get recent system logs"""
    logs = r.lrange("logs", -limit, -1)
    return list(reversed(logs)) if logs else []


# Start background thread
data_thread = threading.Thread(target=update_real_time_data, daemon=True)
data_thread.start()


@app.route('/')
def dashboard():
    return '''
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Smart Parking Dashboard - WebSocket Edition</title>
    <script src="https://cdn.tailwindcss.com"></script>
    <script src="https://cdn.socket.io/4.7.4/socket.io.min.js"></script>
    <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
    <script>
        tailwind.config = {
            theme: {
                extend: {
                    animation: {
                        'fade-in': 'fadeIn 0.5s ease-in-out',
                        'slide-up': 'slideUp 0.3s ease-out',
                        'pulse-slow': 'pulse 3s infinite',
                        'bounce-gentle': 'bounceGentle 0.6s ease-in-out',
                        'scale-up': 'scaleUp 0.2s ease-out',
                    },
                    keyframes: {
                        fadeIn: {
                            '0%': { opacity: '0', transform: 'translateY(10px)' },
                            '100%': { opacity: '1', transform: 'translateY(0)' }
                        },
                        slideUp: {
                            '0%': { opacity: '0', transform: 'translateY(20px)' },
                            '100%': { opacity: '1', transform: 'translateY(0)' }
                        },
                        bounceGentle: {
                            '0%, 100%': { transform: 'scale(1)' },
                            '50%': { transform: 'scale(1.05)' }
                        },
                        scaleUp: {
                            '0%': { transform: 'scale(0.95)' },
                            '100%': { transform: 'scale(1)' }
                        }
                    }
                }
            }
        }
    </script>
    <link href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css" rel="stylesheet">
    <style>
        .notification {
            position: fixed;
            top: 20px;
            right: 20px;
            z-index: 1000;
            max-width: 400px;
        }

        .chart-container {
            position: relative;
            height: 300px;
        }

        .status-indicator {
            width: 12px;
            height: 12px;
            border-radius: 50%;
            display: inline-block;
            margin-right: 8px;
        }

        .status-healthy { background-color: #22c55e; }
        .status-warning { background-color: #f59e0b; }
        .status-error { background-color: #ef4444; }

        .connection-status {
            transition: all 0.3s ease;
        }

        .connected { color: #22c55e; }
        .disconnected { color: #ef4444; }
    </style>
</head>
<body class="bg-gradient-to-br from-blue-50 via-indigo-50 to-purple-50 min-h-screen">
    <!-- Notification Container -->
    <div id="notification-container" class="notification"></div>

    <!-- Header -->
    <header class="bg-white/70 backdrop-blur-lg border-b border-white/20 sticky top-0 z-40">
        <div class="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
            <div class="flex items-center justify-between h-16">
                <div class="flex items-center space-x-4">
                    <div class="bg-gradient-to-r from-blue-600 to-purple-600 p-2 rounded-xl">
                        <i class="fas fa-car text-white text-xl"></i>
                    </div>
                    <h1 class="text-2xl font-bold bg-gradient-to-r from-blue-600 to-purple-600 bg-clip-text text-transparent">
                        Smart Parking Dashboard
                    </h1>
                    <span class="text-xs bg-blue-100 text-blue-800 px-2 py-1 rounded-full">WebSocket</span>
                </div>
                <div class="flex items-center space-x-4">
                    <div class="connection-status" id="connection-status">
                        <span class="status-indicator" id="status-indicator"></span>
                        <span id="status-text">Connecting...</span>
                    </div>
                    <div class="text-sm text-gray-500" id="last-updated">
                        Last updated: Now
                    </div>
                </div>
            </div>
        </div>
    </header>

    <!-- Main Content -->
    <main class="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
        <!-- Enhanced Stats Grid -->
        <div class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-5 gap-6 mb-8">
            <!-- Cars Inside Card -->
            <div class="bg-white/70 backdrop-blur-lg rounded-2xl p-6 border border-white/20 shadow-xl hover:shadow-2xl transition-all duration-300 hover:-translate-y-1">
                <div class="flex items-center justify-between">
                    <div>
                        <p class="text-sm font-medium text-gray-600">Cars Inside</p>
                        <p class="text-3xl font-bold text-blue-600" id="cars-inside">0</p>
                        <p class="text-xs text-gray-500 mt-1">of <span id="max-capacity">100</span> capacity</p>
                    </div>
                    <div class="bg-blue-100 p-3 rounded-xl">
                        <i class="fas fa-car text-blue-600 text-xl"></i>
                    </div>
                </div>
                <div class="mt-4">
                    <div class="bg-blue-100 rounded-full h-2">
                        <div class="bg-blue-600 rounded-full h-2 transition-all duration-500" id="occupancy-bar" style="width: 0%"></div>
                    </div>
                    <p class="text-xs text-gray-500 mt-1"><span id="occupancy-rate">0</span>% occupancy</p>
                </div>
            </div>

            <!-- Unpaid Entries Card -->
            <div class="bg-white/70 backdrop-blur-lg rounded-2xl p-6 border border-white/20 shadow-xl hover:shadow-2xl transition-all duration-300 hover:-translate-y-1">
                <div class="flex items-center justify-between">
                    <div>
                        <p class="text-sm font-medium text-gray-600">Unpaid</p>
                        <p class="text-3xl font-bold text-red-600" id="unpaid-entries">0</p>
                        <p class="text-xs text-gray-500 mt-1">require payment</p>
                    </div>
                    <div class="bg-red-100 p-3 rounded-xl">
                        <i class="fas fa-exclamation-triangle text-red-600 text-xl"></i>
                    </div>
                </div>
                <div class="mt-4">
                    <div class="bg-red-100 rounded-full h-2">
                        <div class="bg-red-600 rounded-full h-2 transition-all duration-500" id="unpaid-bar" style="width: 0%"></div>
                    </div>
                </div>
            </div>

            <!-- Revenue Card -->
            <div class="bg-white/70 backdrop-blur-lg rounded-2xl p-6 border border-white/20 shadow-xl hover:shadow-2xl transition-all duration-300 hover:-translate-y-1">
                <div class="flex items-center justify-between">
                    <div>
                        <p class="text-sm font-medium text-gray-600">Revenue</p>
                        <p class="text-3xl font-bold text-green-600">
                            <span id="total-revenue">0</span>
                            <span class="text-sm">RWF</span>
                        </p>
                        <p class="text-xs text-gray-500 mt-1">total collected</p>
                    </div>
                    <div class="bg-green-100 p-3 rounded-xl">
                        <i class="fas fa-coins text-green-600 text-xl"></i>
                    </div>
                </div>
                <div class="mt-4">
                    <div class="bg-green-100 rounded-full h-2">
                        <div class="bg-green-600 rounded-full h-2 transition-all duration-500" id="revenue-bar" style="width: 0%"></div>
                    </div>
                </div>
            </div>

            <!-- Today's Entries Card -->
            <div class="bg-white/70 backdrop-blur-lg rounded-2xl p-6 border border-white/20 shadow-xl hover:shadow-2xl transition-all duration-300 hover:-translate-y-1">
                <div class="flex items-center justify-between">
                    <div>
                        <p class="text-sm font-medium text-gray-600">Today</p>
                        <p class="text-3xl font-bold text-purple-600" id="today-entries">0</p>
                        <p class="text-xs text-gray-500 mt-1">entries today</p>
                    </div>
                    <div class="bg-purple-100 p-3 rounded-xl">
                        <i class="fas fa-calendar-day text-purple-600 text-xl"></i>
                    </div>
                </div>
            </div>

            <!-- System Health Card -->
            <div class="bg-white/70 backdrop-blur-lg rounded-2xl p-6 border border-white/20 shadow-xl hover:shadow-2xl transition-all duration-300 hover:-translate-y-1">
                <div class="flex items-center justify-between">
                    <div>
                        <p class="text-sm font-medium text-gray-600">System</p>
                        <p class="text-sm font-bold" id="system-status">Healthy</p>
                        <p class="text-xs text-gray-500 mt-1" id="redis-memory">Memory: N/A</p>
                    </div>
                    <div class="bg-gray-100 p-3 rounded-xl">
                        <i class="fas fa-server text-gray-600 text-xl"></i>
                    </div>
                </div>
            </div>
        </div>

        <!-- Charts Section -->
        <div class="grid grid-cols-1 lg:grid-cols-2 gap-8 mb-8">
            <div class="bg-white/70 backdrop-blur-lg rounded-2xl p-6 border border-white/20 shadow-xl">
                <h3 class="text-lg font-bold text-gray-800 mb-4">Hourly Activity (Last 24h)</h3>
                <div class="chart-container">
                    <canvas id="hourlyChart"></canvas>
                </div>
            </div>

            <div class="bg-white/70 backdrop-blur-lg rounded-2xl p-6 border border-white/20 shadow-xl">
                <h3 class="text-lg font-bold text-gray-800 mb-4">Revenue Trend</h3>
                <div class="chart-container">
                    <canvas id="revenueChart"></canvas>
                </div>
            </div>
        </div>

        <!-- Main Dashboard Grid -->
        <div class="grid grid-cols-1 lg:grid-cols-3 gap-8">
            <!-- Cars Currently Inside -->
            <div class="lg:col-span-2 bg-white/70 backdrop-blur-lg rounded-2xl p-6 border border-white/20 shadow-xl">
                <div class="flex items-center justify-between mb-6">
                    <h2 class="text-xl font-bold text-gray-800 flex items-center">
                        <i class="fas fa-car mr-3 text-blue-600"></i>
                        Cars Currently Inside
                    </h2>
                    <div class="flex items-center space-x-2">
                        <div class="bg-blue-100 text-blue-800 px-3 py-1 rounded-full text-sm font-medium">
                            <span id="inside-count">0</span> Active
                        </div>
                        <button onclick="toggleAutoRefresh()" class="bg-gray-100 hover:bg-gray-200 p-2 rounded-lg transition-colors">
                            <i class="fas fa-sync-alt" id="refresh-icon"></i>
                        </button>
                    </div>
                </div>

                <!-- Search and Filter Bar -->
                <div class="mb-6 flex space-x-4">
                    <div class="flex-1 relative">
                        <input type="text" id="search-cars" placeholder="Search by plate number..." 
                               class="w-full pl-10 pr-4 py-3 bg-white/50 border border-gray-200 rounded-xl focus:ring-2 focus:ring-blue-500 focus:border-transparent transition-all duration-200">
                        <i class="fas fa-search absolute left-3 top-1/2 transform -translate-y-1/2 text-gray-400"></i>
                    </div>
                    <select id="filter-status" class="px-4 py-3 bg-white/50 border border-gray-200 rounded-xl focus:ring-2 focus:ring-blue-500">
                        <option value="all">All Status</option>
                        <option value="paid">Paid</option>
                        <option value="unpaid">Unpaid</option>
                    </select>
                    <select id="sort-by" class="px-4 py-3 bg-white/50 border border-gray-200 rounded-xl focus:ring-2 focus:ring-blue-500">
                        <option value="time">Sort by Time</option>
                        <option value="plate">Sort by Plate</option>
                        <option value="duration">Sort by Duration</option>
                    </select>
                </div>

                <!-- Cars List -->
                <div class="space-y-4 max-h-96 overflow-y-auto" id="cars-list">
                    <!-- Cars will be populated here -->
                </div>
            </div>

            <!-- Real-time Activity -->
            <div class="bg-white/70 backdrop-blur-lg rounded-2xl p-6 border border-white/20 shadow-xl">
                <div class="flex items-center justify-between mb-6">
                    <h2 class="text-xl font-bold text-gray-800 flex items-center">
                        <i class="fas fa-bolt mr-3 text-yellow-600"></i>
                        Live Activity
                    </h2>
                    <div class="bg-yellow-100 text-yellow-800 px-2 py-1 rounded-full text-xs font-medium">
                        <i class="fas fa-circle animate-pulse mr-1"></i>
                        LIVE
                    </div>
                </div>

                <div class="space-y-3 max-h-96 overflow-y-auto" id="activity-list">
                    <!-- Activity will be populated here -->
                </div>
            </div>
        </div>

        <!-- Recent Entries Table -->
        <div class="mt-8 bg-white/70 backdrop-blur-lg rounded-2xl p-6 border border-white/20 shadow-xl">
            <div class="flex items-center justify-between mb-6">
                <h2 class="text-xl font-bold text-gray-800 flex items-center">
                    <i class="fas fa-list mr-3 text-indigo-600"></i>
                    Recent Entries
                </h2>
                <button onclick="exportData()" class="bg-indigo-100 hover:bg-indigo-200 text-indigo-800 px-4 py-2 rounded-lg transition-colors">
                    <i class="fas fa-download mr-2"></i>
                    Export CSV
                </button>
            </div>

            <div class="overflow-x-auto">
                <table class="w-full">
                    <thead>
                        <tr class="border-b border-gray-200">
                            <th class="text-left py-3 px-4 font-semibold text-gray-700">ID</th>
                            <th class="text-left py-3 px-4 font-semibold text-gray-700">Plate</th>
                            <th class="text-left py-3 px-4 font-semibold text-gray-700">Entry</th>
                            <th class="text-left py-3 px-4 font-semibold text-gray-700">Exit</th>
                            <th class="text-left py-3 px-4 font-semibold text-gray-700">Duration</th>
                            <th class="text-left py-3 px-4 font-semibold text-gray-700">Payment</th>
                            <th class="text-left py-3 px-4 font-semibold text-gray-700">Status</th>
                            <th class="text-left py-3 px-4 font-semibold text-gray-700">Charge</th>
                        </tr>
                    </thead>
                    <tbody id="entries-table">
                        <!-- Entries will be populated here -->
                    </tbody>
                </table>
            </div>
        </div>
    </main>

    <script>
        // WebSocket connection
        const socket = io();
        let isConnected = false;
        let autoRefresh = true;
        let hourlyChart, revenueChart;

        // Connection status management
        socket.on('connect', function() {
            isConnected = true;
            updateConnectionStatus(true);
            showNotification('Connected to server', 'success');
        });

        socket.on('disconnect', function() {
            isConnected = false;
            updateConnectionStatus(false);
            showNotification('Disconnected from server', 'error');
        });

        socket.on('connect_error', function() {
            updateConnectionStatus(false);
            showNotification('Connection failed', 'error');
        });

        function updateConnectionStatus(connected) {
            const statusIndicator = document.getElementById('status-indicator');
            const statusText = document.getElementById('status-text');
            const connectionStatus = document.getElementById('connection-status');

            if (connected) {
                statusIndicator.className = 'status-indicator status-healthy';
                statusText.textContent = 'Connected';
                connectionStatus.className = 'connection-status connected';
            } else {
                statusIndicator.className = 'status-indicator status-error';
                statusText.textContent = 'Disconnected';
                connectionStatus.className = 'connection-status disconnected';
            }
        }

        // Real-time data updates
        socket.on('data_update', function(data) {
            if (autoRefresh) {
                updateDashboard(data);
            }
        });

        socket.on('occupancy_change', function(data) {
            showNotification(
                `Occupancy changed: ${data.old_count} → ${data.new_count} cars`, 
                'info'
            );
        });

        socket.on('payment_alert', function(data) {
            showNotification(data.message, 'warning');
        });

        // Notification system
        function showNotification(message, type = 'info') {
            const container = document.getElementById('notification-container');
            const notification = document.createElement('div');

            const colors = {
                success: 'bg-green-500',
                error: 'bg-red-500',
                warning: 'bg-yellow-500',
                info: 'bg-blue-500'
            };

            notification.className = `${colors[type]} text-white px-4 py-3 rounded-lg shadow-lg mb-2 animate-slide-up`;
            notification.innerHTML = `
                <div class="flex items-center justify-between">
                    <span>${message}</span>
                    <button onclick="this.parentElement.parentElement.remove()" class="ml-4">
                        <i class="fas fa-times"></i>
                    </button>
                </div>
            `;

            container.appendChild(notification);

            // Auto-remove after 5 seconds
            setTimeout(() => {
                if (notification.parentElement) {
                    notification.remove();
                }
            }, 5000);
        }

        let maxValues = {
            cars_inside: 1,
            unpaid_entries: 1,
            total_revenue: 1,
            total_entries: 1
        };

        function updateProgressBars(stats) {
            // Update max values
            maxValues.cars_inside = Math.max(maxValues.cars_inside, stats.cars_inside);
            maxValues.unpaid_entries = Math.max(maxValues.unpaid_entries, stats.unpaid_entries);
            maxValues.total_revenue = Math.max(maxValues.total_revenue, stats.total_revenue);

            // Update progress bars
            document.getElementById('occupancy-bar').style.width = `${stats.occupancy_rate}%`;
            document.getElementById('unpaid-bar').style.width = 
                `${(stats.unpaid_entries / maxValues.unpaid_entries) * 100}%`;
            document.getElementById('revenue-bar').style.width = 
                `${(stats.total_revenue / maxValues.total_revenue) * 100}%`;
        }

        function updateDashboard(data) {
            // Update statistics
            document.getElementById('cars-inside').textContent = data.stats.cars_inside;
            document.getElementById('unpaid-entries').textContent = data.stats.unpaid_entries;
            document.getElementById('total-revenue').textContent = Math.round(data.stats.total_revenue);
            document.getElementById('today-entries').textContent = data.stats.today_entries;
            document.getElementById('inside-count').textContent = data.stats.cars_inside;
            document.getElementById('max-capacity').textContent = data.stats.max_capacity;
            document.getElementById('occupancy-rate').textContent = Math.round(data.stats.occupancy_rate);

            // Update system health
            const systemHealth = data.system_health;
            document.getElementById('system-status').textContent = systemHealth.system_status;
            document.getElementById('redis-memory').textContent = `Memory: ${systemHealth.redis_memory || 'N/A'}`;

            // Update progress bars
            updateProgressBars(data.stats);

            // Update cars list with enhanced filtering and sorting
            updateCarsList(data.current_inside);

            // Update activity list
            updateActivityList(data.recent_logs);

            // Update entries table
            updateEntriesTable(data.recent_entries);

            // Update charts
            updateCharts(data.hourly_stats);

            // Update last updated time
            document.getElementById('last-updated').textContent = 
                `Last updated: ${new Date().toLocaleTimeString()}`;
        }

        function updateCarsList(cars) {
            const carsList = document.getElementById('cars-list');
            const searchTerm = document.getElementById('search-cars').value.toLowerCase();
            const filterStatus = document.getElementById('filter-status').value;
            const sortBy = document.getElementById('sort-by').value;

            // Filter cars
            let filteredCars = cars.filter(car => {
                const matchesSearch = car.plate.toLowerCase().includes(searchTerm);
                const matchesFilter = filterStatus === 'all' || 
                                    car.status.toLowerCase() === filterStatus;
                return matchesSearch && matchesFilter;
            });

            // Sort cars
            filteredCars.sort((a, b) => {
                switch(sortBy) {
                    case 'plate':
                        return a.plate.localeCompare(b.plate);
                    case 'duration':
                        return b.duration_hours - a.duration_hours;
                    default:
                        return new Date(b.entry_time) - new Date(a.entry_time);
                }
            });

            carsList.innerHTML = '';

            if (filteredCars.length === 0) {
                carsList.innerHTML = `
                    <div class="text-center py-8 text-gray-500">
                        <i class="fas fa-car text-4xl mb-4"></i>
                        <p>No cars match your criteria</p>
                    </div>
                `;
            } else {
                filteredCars.forEach((car, index) => {
                    const carDiv = document.createElement('div');
                    carDiv.className = 'bg-white/50 rounded-xl p-4 border border-gray-100 hover:shadow-md transition-all duration-200 animate-fade-in car-item';
                    carDiv.style.animationDelay = `${index * 0.05}s`;

                    const statusClass = car.status === 'Paid' ? 'bg-green-100 text-green-800' : 'bg-red-100 text-red-800';
                    const statusIcon = car.status === 'Paid' ? 'fas fa-check-circle' : 'fas fa-clock';
                    const priorityClass = car.priority === 'high' ? 'border-red-300' : 
                                        car.priority === 'medium' ? 'border-yellow-300' : 'border-gray-100';

                    carDiv.className += ` ${priorityClass}`;

                    carDiv.innerHTML = `
                        <div class="flex items-center justify-between">
                            <div class="flex items-center space-x-4">
                                <div class="bg-gradient-to-r from-blue-500 to-purple-500 p-2 rounded-lg text-white">
                                    <i class="fas fa-car"></i>
                                </div>
                                <div>
                                    <h3 class="font-bold text-lg text-gray-800 car-plate">${car.plate}</h3>
                                    <p class="text-sm text-gray-600">Entry: ${car.entry_time}</p>
                                    <p class="text-sm text-gray-600">Duration: ${car.duration_hours}h | Charge: ${car.charge} RWF</p>
                                </div>
                            </div>
                            <div class="text-right">
                                <span class="${statusClass} px-3 py-1 rounded-full text-sm font-medium">
                                    <i class="${statusIcon} mr-1"></i>
                                    ${car.status}
                                </span>
                                ${car.priority === 'high' ? '<div class="text-xs text-red-600 mt-1">⚠️ Long stay</div>' : ''}
                            </div>
                        </div>
                    `;
                    carsList.appendChild(carDiv);
                });
            }
        }

        function updateActivityList(logs) {
            const activityList = document.getElementById('activity-list');
            activityList.innerHTML = '';

            logs.slice(0, 15).forEach((log, index) => {
                const logDiv = document.createElement('div');
                logDiv.className = 'bg-white/50 rounded-lg p-3 border border-gray-100 animate-fade-in';
                logDiv.style.animationDelay = `${index * 0.02}s`;

                // Parse log for better display
                let logClass = 'text-gray-700';
                let logIcon = 'fas fa-info-circle';

                if (log.includes('ENTRY GRANTED')) {
                    logClass = 'text-green-700';
                    logIcon = 'fas fa-sign-in-alt';
                } else if (log.includes('EXIT GRANTED')) {
                    logClass = 'text-blue-700';
                    logIcon = 'fas fa-sign-out-alt';
                } else if (log.includes('DENIED')) {
                    logClass = 'text-red-700';
                    logIcon = 'fas fa-times-circle';
                } else if (log.includes('PAYMENT')) {
                    logClass = 'text-purple-700';
                    logIcon = 'fas fa-credit-card';
                }

                logDiv.innerHTML = `
                    <div class="flex items-start space-x-2">
                        <i class="${logIcon} ${logClass} mt-1"></i>
                        <span class="text-sm ${logClass}">${log}</span>
                    </div>
                `;
                activityList.appendChild(logDiv);
            });
        }

        function updateEntriesTable(entries) {
            const entriesTable = document.getElementById('entries-table');
            entriesTable.innerHTML = '';

            entries.forEach(entry => {
                const row = document.createElement('tr');
                row.className = 'border-b border-gray-100 hover:bg-white/50 transition-colors duration-200';

                const paymentClass = entry.payment_status === 'Paid' ? 'bg-green-100 text-green-800' : 'bg-red-100 text-red-800';
                const statusClass = entry.exit_status === 'Exited' ? 'bg-blue-100 text-blue-800' : 'bg-yellow-100 text-yellow-800';

                row.innerHTML = `
                    <td class="py-3 px-4 text-sm font-medium text-gray-900">#${entry.id}</td>
                    <td class="py-3 px-4 text-sm font-bold text-gray-900">${entry.plate}</td>
                    <td class="py-3 px-4 text-sm text-gray-600">${entry.entry_time}</td>
                    <td class="py-3 px-4 text-sm text-gray-600">${entry.exit_time}</td>
                    <td class="py-3 px-4 text-sm text-gray-600">${entry.duration}</td>
                    <td class="py-3 px-4">
                        <span class="${paymentClass} px-2 py-1 rounded-full text-xs font-medium">
                            ${entry.payment_status}
                        </span>
                    </td>
                    <td class="py-3 px-4">
                        <span class="${statusClass} px-2 py-1 rounded-full text-xs font-medium">
                            ${entry.exit_status}
                        </span>
                    </td>
                    <td class="py-3 px-4 text-sm text-gray-900">${entry.charge} RWF</td>
                `;
                entriesTable.appendChild(row);
            });
        }

        function initializeCharts() {
            // Hourly Activity Chart
            const hourlyCtx = document.getElementById('hourlyChart').getContext('2d');
            hourlyChart = new Chart(hourlyCtx, {
                type: 'bar',
                data: {
                    labels: [],
                    datasets: [{
                        label: 'Entries',
                        data: [],
                        backgroundColor: 'rgba(59, 130, 246, 0.6)',
                        borderColor: 'rgba(59, 130, 246, 1)',
                        borderWidth: 1
                    }, {
                        label: 'Exits',
                        data: [],
                        backgroundColor: 'rgba(16, 185, 129, 0.6)',
                        borderColor: 'rgba(16, 185, 129, 1)',
                        borderWidth: 1
                    }]
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    scales: {
                        y: {
                            beginAtZero: true
                        }
                    }
                }
            });

            // Revenue Chart
            const revenueCtx = document.getElementById('revenueChart').getContext('2d');
            revenueChart = new Chart(revenueCtx, {
                type: 'line',
                data: {
                    labels: [],
                    datasets: [{
                        label: 'Revenue (RWF)',
                        data: [],
                        borderColor: 'rgba(34, 197, 94, 1)',
                        backgroundColor: 'rgba(34, 197, 94, 0.1)',
                        fill: true,
                        tension: 0.4
                    }]
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    scales: {
                        y: {
                            beginAtZero: true
                        }
                    }
                }
            });
        }

        function updateCharts(hourlyStats) {
            if (!hourlyChart || !revenueChart) return;

            const labels = hourlyStats.map(stat => stat.hour);
            const entries = hourlyStats.map(stat => stat.entries);
            const exits = hourlyStats.map(stat => stat.exits);
            const revenue = hourlyStats.map(stat => stat.revenue);

            hourlyChart.data.labels = labels;
            hourlyChart.data.datasets[0].data = entries;
            hourlyChart.data.datasets[1].data = exits;
            hourlyChart.update('none');

            revenueChart.data.labels = labels;
            revenueChart.data.datasets[0].data = revenue;
            revenueChart.update('none');
        }

        function toggleAutoRefresh() {
            autoRefresh = !autoRefresh;
            const icon = document.getElementById('refresh-icon');

            if (autoRefresh) {
                icon.classList.remove('text-red-500');
                icon.classList.add('text-green-500');
                showNotification('Auto-refresh enabled', 'success');
            } else {
                icon.classList.remove('text-green-500');
                icon.classList.add('text-red-500');
                showNotification('Auto-refresh disabled', 'warning');
            }
        }

        function exportData() {
            // Request data export
            socket.emit('export_request');
            showNotification('Preparing export...', 'info');
        }

        // Event listeners
        document.getElementById('search-cars').addEventListener('input', function() {
            if (window.currentCarsData) {
                updateCarsList(window.currentCarsData);
            }
        });

        document.getElementById('filter-status').addEventListener('change', function() {
            if (window.currentCarsData) {
                updateCarsList(window.currentCarsData);
            }
        });

        document.getElementById('sort-by').addEventListener('change', function() {
            if (window.currentCarsData) {
                updateCarsList(window.currentCarsData);
            }
        });

        // Store current data globally for filtering
        socket.on('data_update', function(data) {
            window.currentCarsData = data.current_inside;
        });

        // Initialize charts when page loads
        document.addEventListener('DOMContentLoaded', function() {
            initializeCharts();
        });

        // Export functionality
        socket.on('export_ready', function(data) {
            const blob = new Blob([data.csv], { type: 'text/csv' });
            const url = window.URL.createObjectURL(blob);
            const a = document.createElement('a');
            a.href = url;
            a.download = `parking_data_${new Date().toISOString().split('T')[0]}.csv`;
            a.click();
            window.URL.revokeObjectURL(url);
            showNotification('Export completed!', 'success');
        });
    </script>
</body>
</html>
    '''


# WebSocket event handlers
@socketio.on('connect')
def handle_connect():
    connected_clients.add(request.sid)
    emit('connected', {'message': 'Connected to parking dashboard'})
    print(f"Client {request.sid} connected. Total clients: {len(connected_clients)}")


@socketio.on('disconnect')
def handle_disconnect():
    connected_clients.discard(request.sid)
    print(f"Client {request.sid} disconnected. Total clients: {len(connected_clients)}")


@socketio.on('export_request')
def handle_export_request():
    """Generate and send CSV export"""
    try:
        # Get all entries
        entry_keys = r.keys("entry:*")
        csv_data = "ID,Plate,Entry Time,Exit Time,Payment Status,Exit Status,Charge,Duration\n"

        for key in sorted(entry_keys, key=lambda x: int(x.split(':')[1])):
            entry_data = r.hgetall(key)
            entry_id = key.split(':')[1]

            # Calculate duration
            duration = "N/A"
            if entry_data.get('exit_status') == '1':
                try:
                    entry_time = datetime.strptime(entry_data.get('entry_timestamp', ''), '%Y-%m-%d %H:%M:%S')
                    exit_time = datetime.strptime(entry_data.get('exit_timestamp', ''), '%Y-%m-%d %H:%M:%S')
                    duration = str(exit_time - entry_time)
                except:
                    pass

            csv_data += f"{entry_id},{entry_data.get('plate_number', '')},{entry_data.get('entry_timestamp', '')},{entry_data.get('exit_timestamp', 'Not exited')},{entry_data.get('payment_status', '0')},{entry_data.get('exit_status', '0')},{entry_data.get('charge_amount', 'Not calculated')},{duration}\n"

        emit('export_ready', {'csv': csv_data})
    except Exception as e:
        emit('export_error', {'error': str(e)})


if __name__ == '__main__':
    print("🚀 Starting Smart Parking Dashboard with WebSockets...")
    print("📱 Access the dashboard at: http://localhost:5000")
    print("🔄 Real-time WebSocket updates")
    print("🎨 Enhanced Tailwind CSS styling")
    print("📊 Interactive charts and analytics")
    socketio.run(app, debug=True, host='0.0.0.0', port=5000,allow_unsafe_werkzeug=True)