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

app = Flask(__name__, static_folder='static', template_folder='templates')
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

    print("\n[INFO] Initializing serial connection...")
    print("[INFO] Searching for available serial ports...")
    # Optional: Keep these for debugging if needed, but can be noisy.
    # os.system('ls -l /dev/serial*')
    # os.system('ls -l /dev/tty*')

    for port in POSSIBLE_PORTS:
        print(f"\n[INFO] Processing port: {port}")
        try:
            print(f"[INFO] Checking existence of port: {port}")
            if not os.path.exists(port):
                print(f"[WARN] Port {port} does not exist, skipping...")
                continue
            print(f"[INFO] Port {port} exists.")

            print(f"[INFO] Checking permissions for port: {port}")
            if not os.access(port, os.R_OK | os.W_OK):
                print(f"[WARN] No read/write permission for {port}. Current permissions:")
                os.system(f'ls -l {port}') # Log current permissions
                continue
            print(f"[INFO] Read/write permissions confirmed for port: {port}")

            # Try different serial configurations (flow control)
            for flow_control_setting in [(True, True), (False, False)]:
                dsrdtr_val, rtscts_val = flow_control_setting
                print(f"[INFO] Attempting to open port {port} with DSR/DTR={dsrdtr_val}, RTS/CTS={rtscts_val}")
                try:
                    serial_connection = serial.Serial(
                        port=port,
                        baudrate=BAUD_RATE,
                        timeout=1,
                        dsrdtr=dsrdtr_val,
                        rtscts=rtscts_val
                    )
                    print(f"[SUCCESS] Successfully opened port {port} with DSR/DTR={dsrdtr_val}, RTS/CTS={rtscts_val}")

                    print(f"[INFO] Attempting to read data from {port} for verification...")
                    data_received_successfully = False
                    for attempt in range(3): # Try reading 3 times
                        print(f"[INFO] Read attempt {attempt + 1}/3 for port {port}")
                        try:
                            if serial_connection.in_waiting:
                                line = serial_connection.readline().decode('utf-8').strip()
                                if line:
                                    print(f"[SUCCESS] Data received from {port}: {line}")
                                    SERIAL_PORT = port
                                    print(f"\n[SUCCESS] Successfully connected to {SERIAL_PORT}")
                                    print(f"[INFO] Port settings: {serial_connection.get_settings()}")
                                    data_received_successfully = True
                                    return True # Connection successful
                                else:
                                    print(f"[INFO] Empty line received from {port}.")
                            else:
                                print(f"[INFO] No data in buffer for {port}, waiting 1 second...")
                        except serial.SerialException as se:
                            print(f"[ERROR] SerialException during read attempt on {port}: {se}")
                            break # Stop trying to read from this port config
                        except IOError as ioe:
                            print(f"[ERROR] IOError during read attempt on {port}: {ioe}")
                            break # Stop trying to read from this port config
                        except Exception as e_read:
                            print(f"[ERROR] Unexpected error during read attempt on {port}: {e_read}")
                            break # Stop trying to read from this port config
                        time.sleep(1)

                    if not data_received_successfully:
                        print(f"[WARN] No data received from {port} with DSR/DTR={dsrdtr_val}, RTS/CTS={rtscts_val}. Closing port.")
                        if serial_connection and serial_connection.is_open:
                            serial_connection.close()
                        # Continue to next flow control setting

                except serial.SerialException as se:
                    print(f"[ERROR] SerialException when trying to open {port} with DSR/DTR={dsrdtr_val}, RTS/CTS={rtscts_val}: {se}")
                    if serial_connection and serial_connection.is_open:
                        serial_connection.close()
                except PermissionError as pe:
                    print(f"[ERROR] PermissionError when trying to open {port}: {pe}. This should have been caught by os.access, but good to double check.")
                    # os.system(f'ls -l {port}') # Re-log permissions if this happens
                except IOError as ioe:
                    print(f"[ERROR] IOError when trying to open or configure {port}: {ioe}")
                    if serial_connection and serial_connection.is_open:
                        serial_connection.close()
                except Exception as e_open:
                    print(f"[ERROR] Unexpected error when trying to open {port} with DSR/DTR={dsrdtr_val}, RTS/CTS={rtscts_val}: {e_open}")
                    if serial_connection and serial_connection.is_open:
                        serial_connection.close()
        except Exception as e_port_loop:
            # This catches errors in the outer loop (e.g. os.path.exists or os.access if they raise something unexpected)
            print(f"[ERROR] Unexpected error while processing port {port}: {e_port_loop}")

    print("\n[CRITICAL] Failed to connect to any serial port after trying all configurations.")
    print("[INFO] Please check the following:")
    print("1. Arduino/Device is properly connected via USB or GPIO.")
    print("2. The correct serial port is listed in POSSIBLE_PORTS in app.py.")
    print("3. Device has necessary permissions (e.g., 'sudo chmod a+rw /dev/ttyAMA10' or add user to 'dialout' group).")
    print("4. Serial communication is enabled on the Raspberry Pi (if applicable, via raspi-config).")
    print("5. The device is powered on and sending data.")
    return False

def read_serial_data():
    """Read and parse data from Arduino. Hardened for robustness."""
    global serial_connection
    line_content = None  # Initialize to None, so it's defined in case of early error

    try:
        if serial_connection and serial_connection.is_open:
            if serial_connection.in_waiting > 0: # Check if there's actually data
                # print("[DEBUG] Data available on serial port...") # Can be verbose
                line_bytes = serial_connection.readline() # Can raise SerialException
                
                try:
                    line_content = line_bytes.decode('utf-8').strip() # Can raise UnicodeDecodeError
                    # print(f"[DEBUG] Raw data received: '{line_content}'") # Can be verbose
                except UnicodeDecodeError as ude:
                    print(f"[ERROR] UnicodeDecodeError while decoding data: {type(ude).__name__} - {str(ude)}. Raw bytes: {line_bytes!r}")
                    return # Skip this problematic line, let the loop continue

                if not line_content: # If line is empty after strip, nothing to process
                    # print("[DEBUG] Empty line received or failed to decode, skipping further processing.")
                    return

                # Proceed with parsing and storing
                processed_line = line_content
                json_str = "" # Initialize json_str
                try:
                    # Remove angle brackets (if present)
                    if processed_line.startswith('<') and '>' in processed_line:
                        end_bracket_index = processed_line.index('>')
                        # Basic check to avoid issues with malformed strings like "<>"
                        if end_bracket_index > 0 : # Ensure there's content within brackets
                            processed_line = processed_line[1:end_bracket_index]
                            # print(f"[DEBUG] Data after removing brackets: '{processed_line}'")
                        else:
                            # print(f"[WARN] Malformed bracket structure (e.g., '<>') in line: '{line_content}'. Using content as is.")
                            # No change to processed_line, or could decide to return if this is critical
                            pass


                    # Remove checksum (everything after and including *)
                    checksum_index = processed_line.find('*')
                    if checksum_index != -1:
                        json_str = processed_line[:checksum_index]
                    else:
                        json_str = processed_line # No checksum found
                    # print(f"[DEBUG] Data after removing checksum (if any): '{json_str}'")

                    if not json_str.strip(): # Check if json_str is empty or just whitespace
                        print(f"[WARN] JSON string is empty after pre-processing. Original line: '{line_content}'")
                        return

                    data = json.loads(json_str) # Can raise json.JSONDecodeError
                    # print(f"[DEBUG] Parsed JSON data: {data}")

                    store_sensor_readings(data) # Can raise various exceptions if db interaction fails
                    print(f"[SUCCESS] Data processed and stored successfully from line: '{line_content}'")

                except json.JSONDecodeError as e_json:
                    print(f"[ERROR] JSONDecodeError parsing data: {type(e_json).__name__} - {str(e_json)}. Problematic JSON string: '{json_str}'. Original line: '{line_content}'")
                except IndexError as e_index: # If string manipulation (like split or indexing) goes wrong
                    print(f"[ERROR] IndexError during data processing: {type(e_index).__name__} - {str(e_index)}. Original line: '{line_content}'")
                except Exception as e_parse_store: # Catch any other errors during parsing/storing
                    print(f"[ERROR] Unexpected error processing/storing data: {type(e_parse_store).__name__} - {str(e_parse_store)}. Original line: '{line_content}'")
            # else:
                # print("[DEBUG] No data in_waiting on serial port.") 
        # else:
            # if not serial_connection:
            #     print("[WARN] read_serial_data: serial_connection is None. Thread will likely stop if not re-initialized.")
            # elif not serial_connection.is_open:
            #     print("[WARN] read_serial_data: serial_connection is not open. Waiting for it to be re-opened.")

    except serial.SerialException as se:
        print(f"[ERROR] SerialException in read_serial_data (e.g., device disconnected): {type(se).__name__} - {str(se)}. Port: {SERIAL_PORT}")
        # The loop in start_serial_thread will continue to call this function.
        # If the port is disconnected, serial_connection.is_open might become false,
        # or in_waiting/readline will consistently fail. Consider closing and setting serial_connection to None
        # if this error implies the connection is permanently lost, to allow re-initialization.
        # For now, just logging and returning. If serial_connection.is_open becomes False, the outer 'if' will prevent further action.
        # If serial_connection.readline() fails repeatedly, init_serial() might need to be called again by a higher level logic.
    except IOError as ioe: # For other I/O errors not covered by SerialException
        print(f"[ERROR] IOError in read_serial_data: {type(ioe).__name__} - {str(ioe)}. Raw line (if available): '{line_content}'")
    except Exception as e_outer:
        # This is a general catch-all for unexpected errors in the function.
        print(f"[ERROR] An unexpected error occurred in read_serial_data: {type(e_outer).__name__} - {str(e_outer)}. Raw line (if available): '{line_content}'")

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
        start_serial_thread() # init_serial() is called within start_serial_thread
        # Run on all network interfaces, port 5000
        app.run(host='0.0.0.0', port=5000, debug=True)
