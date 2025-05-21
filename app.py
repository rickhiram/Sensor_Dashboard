from flask import Flask, request, jsonify, render_template, redirect, url_for
from flask_cors import CORS
import sqlite3
import threading
import random
import time
from datetime import datetime, timedelta
import serial
import json
import os

app = Flask(__name__, static_url_path='', static_folder='static')
CORS(app)  # Enable CORS for all routes

# Serial Port Configuration (Change as needed)
POSSIBLE_PORTS = [
    "/dev/serial0",    # Pi Serial port
    "/dev/ttyAMA0",    # Pi UART
    "/dev/ttyAMA10",   # Your mentioned port
    "/dev/ttyACM0",    # Arduino default
    "/dev/ttyUSB0"     # USB Serial
]
BAUD_RATE = 115200

# Global variables
serial_connection = None
SERIAL_PORT = None  # Will be set during initialization

def init_serial():
    """Initialize serial connection with Arduino"""
    global serial_connection, SERIAL_PORT

    print("\nSearching for available serial ports...")
    os.system('ls -l /dev/serial*')
    os.system('ls -l /dev/tty*')

    for port in POSSIBLE_PORTS:
        try:
            print(f"\nTrying port: {port}")

            if not os.path.exists(port):
                print(f"Port {port} does not exist, skipping...")
                continue

            print(f"Port exists, checking permissions...")
            if not os.access(port, os.R_OK | os.W_OK):
                print(f"No permission to access {port}")
                print("Current permissions:")
                os.system(f'ls -l {port}')
                continue

            print("Attempting to open port...")
            # Try different serial configurations
            for flow_control in [(True, True), (False, False)]:
                try:
                    dsrdtr, rtscts = flow_control
                    serial_connection = serial.Serial(
                        port=port,
                        baudrate=BAUD_RATE,
                        timeout=1,
                        dsrdtr=dsrdtr,
                        rtscts=rtscts
                    )

                    # Try reading some data
                    print("Port opened, waiting for data...")
                    for _ in range(3):  # Try reading 3 times
                        if serial_connection.in_waiting:
                            data = serial_connection.readline().decode('utf-8').strip()
                            print(f"Data received: {data}")
                            SERIAL_PORT = port
                            print(f"\nSuccessfully connected to {port}")
                            print(f"Port settings: {serial_connection.get_settings()}")
                            return True
                        time.sleep(1)

                    print("No data received, trying next configuration...")
                    serial_connection.close()

                except Exception as e:
                    print(f"Failed with flow control {flow_control}: {e}")
                    if serial_connection:
                        serial_connection.close()

        except Exception as e:
            print(f"Error with port {port}: {e}")

    print("\nFailed to connect to any serial port")
    print("Please check:")
    print("1. Arduino is properly connected")
    print("2. Correct port permissions (try: sudo chmod 666 /dev/ttyAMA10)")
    print("3. Serial communication is enabled on the Pi (raspi-config)")
    return False

def read_serial_data():
    """Read and parse data from Arduino"""
    global serial_connection
    try:
        if serial_connection and serial_connection.is_open:
            if serial_connection.in_waiting:
                print("Data available on serial port...")
                line = serial_connection.readline().decode('utf-8').strip()
                print(f"Raw data received: {line}")
                try:
                    # Remove angle brackets and get the content
                    if line.startswith('<') and '>' in line:
                        line = line[1:line.index('>')]
                        print(f"Data after removing brackets: {line}")

                    # Remove checksum (everything after and including *)
                    json_str = line.split('*')[0]
                    print(f"Data after removing checksum: {json_str}")

                    data = json.loads(json_str)
                    print(f"Parsed JSON data: {data}")

                    # Store readings in database
                    store_sensor_readings(data)
                    print("Data successfully stored in database")
                except (json.JSONDecodeError, IndexError) as e:
                    print(f"Error parsing data: {line} - {str(e)}")
    except Exception as e:
        print(f"Error reading serial data: {e}")

def store_sensor_readings(data):
    """Store sensor readings in the database"""
    try:
        conn = sqlite3.connect("data/sensor_data.db")
        cursor = conn.cursor()
        timestamp = datetime.now().isoformat()

        for sensor_type, value in data.items():
            # Find all enabled sensors of this type across all projects
            cursor.execute("""
                SELECT id FROM sensors
                WHERE type = ? AND enabled = 1
            """, (sensor_type,))

            sensors = cursor.fetchall()
            print(f"Found {len(sensors)} enabled sensors for type {sensor_type}")

            for sensor in sensors:
                try:
                    cursor.execute("""
                        INSERT INTO readings (sensor_id, value, timestamp)
                        VALUES (?, ?, ?)
                    """, (sensor[0], float(value), timestamp))
                    print(f"Stored reading {value} for sensor {sensor[0]}")
                except Exception as e:
                    print(f"Error storing reading for sensor {sensor[0]}: {e}")

        conn.commit()
        conn.close()
        print("All readings stored successfully")
    except Exception as e:
        print(f"Error storing readings: {e}")

# Available sensor types and their units
SENSOR_TYPES = {
    "temperature": "°C",
    "humidity": "%",
    "light": "lux",
    "soil_moisture": "%",
    "distance": "cm",
    "pressure": "hPa",
    "co2": "ppm",
    "magnetic_field": "µT"
}

# Create data directory if it doesn't exist
os.makedirs('data', exist_ok=True)

def init_db():
    """Initialize the database and create the necessary tables if they don't exist."""
    try:
        print("Initializing database...")
        conn = sqlite3.connect("data/sensor_data.db")
        cursor = conn.cursor()

        # Create projects table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS projects (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT UNIQUE NOT NULL,
                description TEXT,
                created_at TEXT
            )
        """)

        # Create sensors table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS sensors (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                type TEXT NOT NULL,
                project_id INTEGER,
                enabled INTEGER DEFAULT 1,
                min_value REAL,
                max_value REAL,
                created_at TEXT,
                FOREIGN KEY (project_id) REFERENCES projects (id) ON DELETE CASCADE
            )
        """)

        # Create readings table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS readings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                sensor_id INTEGER NOT NULL,
                value REAL NOT NULL,
                timestamp TEXT,
                FOREIGN KEY (sensor_id) REFERENCES sensors (id) ON DELETE CASCADE
            )
        """)

        conn.commit()
        conn.close()
        print("Database initialized successfully!")
    except Exception as e:
        print(f"Database initialization error: {e}")

@app.route('/')
def dashboard():
    """Render the dashboard template."""
    conn = sqlite3.connect("data/sensor_data.db")
    cursor = conn.cursor()

    # Get all projects
    cursor.execute("""
        SELECT id, name, description
        FROM projects
        ORDER BY name
    """)
    projects = [dict(zip(['id', 'name', 'description'], row)) for row in cursor.fetchall()]

    # Get active project (first project if none specified)
    active_project_id = request.args.get('project', type=int)
    if not active_project_id and projects:
        active_project_id = projects[0]['id']

    # Get sensors for active project
    sensors = []
    if active_project_id:
        cursor.execute("""
            SELECT id, name, type, enabled
            FROM sensors
            WHERE project_id = ?
            ORDER BY name
        """, (active_project_id,))
        sensors = [dict(zip(['id', 'name', 'type', 'enabled'], row)) for row in cursor.fetchall()]

    conn.close()

    return render_template('dashboard.html',
                         projects=projects,
                         active_project_id=active_project_id,
                         sensors=sensors,
                         sensor_types=SENSOR_TYPES)

@app.route('/api/projects', methods=['GET'])
def get_projects():
    """Get all projects."""
    conn = sqlite3.connect("data/sensor_data.db")
    cursor = conn.cursor()
    cursor.execute("SELECT id, name, description FROM projects ORDER BY name")
    projects = [dict(zip(['id', 'name', 'description'], row)) for row in cursor.fetchall()]
    conn.close()
    return jsonify(projects)

@app.route('/api/projects', methods=['POST'])
def create_project():
    """Create a new project with sensors."""
    data = request.json
    if not data or 'name' not in data:
        return jsonify({"error": "Project name is required"}), 400

    try:
        conn = sqlite3.connect("data/sensor_data.db")
        cursor = conn.cursor()

        # Create project
        cursor.execute("""
            INSERT INTO projects (name, description, created_at)
            VALUES (?, ?, ?)
        """, (data['name'], data.get('description', ''), datetime.now().isoformat()))

        project_id = cursor.lastrowid

        # Add sensors if provided
        if 'sensors' in data and isinstance(data['sensors'], list):
            for sensor_type in data['sensors']:
                if sensor_type in SENSOR_TYPES:
                    cursor.execute("""
                        INSERT INTO sensors (name, type, project_id, created_at)
                        VALUES (?, ?, ?, ?)
                    """, (f"{sensor_type.replace('_', ' ').title()} Sensor",
                         sensor_type,
                         project_id,
                         datetime.now().isoformat()))

        conn.commit()
        conn.close()

        return jsonify({"success": True, "id": project_id})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/sensors/available', methods=['GET'])
def get_available_sensors():
    """Get all available sensor types that can be added to a project."""
    try:
        available_sensors = []
        for sensor_type, unit in SENSOR_TYPES.items():
            available_sensors.append({
                'id': f'new_{sensor_type}',  # Temporary ID for new sensors
                'name': f'{sensor_type.replace("_", " ").title()} Sensor',
                'type': sensor_type,
                'unit': unit
            })
        return jsonify(available_sensors)
    except Exception as e:
        print(f"Error getting available sensors: {e}")
        return jsonify({'error': 'Failed to get available sensors'}), 500

@app.route('/api/sensors/<int:sensor_id>/toggle', methods=['POST'])
def toggle_sensor(sensor_id):
    """Toggle a sensor's enabled state."""
    try:
        data = request.json
        if data is None:
            return jsonify({"error": "No data provided"}), 400

        enabled = data.get('enabled')
        if enabled is None:
            return jsonify({"error": "Enabled state not provided"}), 400

        conn = sqlite3.connect("data/sensor_data.db")
        cursor = conn.cursor()

        # Update sensor enabled state
        cursor.execute("""
            UPDATE sensors
            SET enabled = ?
            WHERE id = ?
        """, (1 if enabled else 0, sensor_id))

        if cursor.rowcount == 0:
            conn.close()
            return jsonify({"error": "Sensor not found"}), 404

        conn.commit()
        conn.close()

        return jsonify({"success": True, "id": sensor_id, "enabled": enabled})
    except Exception as e:
        print(f"Error toggling sensor: {e}")
        return jsonify({"error": "Failed to toggle sensor"}), 500

@app.route('/api/sensors/<int:sensor_id>/data')
def get_sensor_data(sensor_id):
    """Get sensor data for charting."""
    try:
        # Get parameters
        minutes = request.args.get('minutes', default=60, type=int)

        conn = sqlite3.connect("data/sensor_data.db")
        cursor = conn.cursor()

        # Get sensor info
        cursor.execute("SELECT type, min_value, max_value FROM sensors WHERE id = ?", (sensor_id,))
        sensor = cursor.fetchone()
        if not sensor:
            conn.close()
            return jsonify({"error": "Sensor not found"}), 404

        sensor_type, min_value, max_value = sensor

        # Get readings for last n minutes
        cursor.execute("""
            SELECT timestamp, value
            FROM readings
            WHERE sensor_id = ?
            AND timestamp > ?
            ORDER BY timestamp ASC
            LIMIT 100
        """, (sensor_id, (datetime.now() - timedelta(minutes=minutes)).isoformat()))

        readings = cursor.fetchall()
        print(f"Retrieved {len(readings)} readings for sensor {sensor_id}")
        conn.close()

        # Format data for charting
        formatted_data = [[ts, val] for ts, val in readings]
        print(f"Last 3 readings for sensor {sensor_id}: {formatted_data[-3:] if formatted_data else 'No data'}")

        data = {
            "type": sensor_type,
            "unit": SENSOR_TYPES.get(sensor_type, ""),
            "data": formatted_data,
            "min_value": min_value,
            "max_value": max_value
        }

        return jsonify(data)
    except Exception as e:
        print(f"Error getting sensor data: {e}")
        return jsonify({"error": "Failed to get sensor data"}), 500

def start_serial_thread():
    """Start a thread to continuously read serial data"""
    def read_loop():
        while True:
            read_serial_data()
            time.sleep(0.1)  # Small delay to prevent CPU overuse

    if init_serial():
        thread = threading.Thread(target=read_loop, daemon=True)
        thread.start()
        print("Serial reading thread started")
    else:
        print("Failed to start serial reading thread")

if __name__ == '__main__':
    # Only run this once (avoids double-thread issue)
    if os.environ.get("WERKZEUG_RUN_MAIN") == "true":
        init_db()
        init_serial()
        # Run on all network interfaces, port 5000
        app.run(host='0.0.0.0', port=5000, debug=True)
