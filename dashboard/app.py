from flask import Flask, request, jsonify, render_template, redirect, url_for
from flask_cors import CORS
import sqlite3
import threading
import time
from datetime import datetime, timedelta
import serial
import json
import os
import logging

# Ensure 'logs' directory exists in 'dashboard'
# When app.py is run from dashboard/, 'logs' will be dashboard/logs
os.makedirs('logs', exist_ok=True)

# Configure logging
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO) # Set global minimum log level

# File Handler for logs/app.log in the dashboard/ directory
fh = logging.FileHandler('logs/app.log') # Path relative to where app.py is run
fh.setLevel(logging.INFO) # Log INFO and above to file

# Console Handler
ch = logging.StreamHandler()
ch.setLevel(logging.INFO) # Log INFO and above to console

# Formatter
formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(module)s - %(funcName)s - L%(lineno)d - %(message)s')
fh.setFormatter(formatter)
ch.setFormatter(formatter)

# Add Handlers to Logger
logger.addHandler(fh)
logger.addHandler(ch)

logger.info("Logging initialized. All modules imported successfully.")


app = Flask(__name__, static_folder='static', template_folder='templates')
CORS(app)

# Serial Port Configuration
POSSIBLE_PORTS = ["/dev/serial0", "/dev/ttyAMA0", "/dev/ttyAMA10", "/dev/ttyACM0", "/dev/ttyUSB0"]
BAUD_RATE = 115200
serial_connection = None
SERIAL_PORT = None

# Ensure 'data' directory exists in 'dashboard'
# When app.py is run from dashboard/, 'data' will be dashboard/data
os.makedirs('data', exist_ok=True) # For SQLite DB and other data
DATABASE_PATH = "data/sensor_data.db" # Path relative to where app.py is run

# Available sensor types and their units
SENSOR_TYPES = {
    "temperature": "°C", "humidity": "%", "light": "lux", "soil_moisture": "%",
    "distance": "cm", "pressure": "hPa", "co2": "ppm", "magnetic_field": "µT"
}

def init_db():
    logger.info("Entering init_db")
    try:
        logger.info(f"Initializing database at {DATABASE_PATH}...")
        conn = sqlite3.connect(DATABASE_PATH)
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS projects (
                id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT UNIQUE NOT NULL,
                description TEXT, created_at TEXT
            )
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS sensors (
                id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, type TEXT NOT NULL,
                project_id INTEGER, enabled INTEGER DEFAULT 1, min_value REAL, max_value REAL,
                created_at TEXT, FOREIGN KEY (project_id) REFERENCES projects (id) ON DELETE CASCADE
            )
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS readings (
                id INTEGER PRIMARY KEY AUTOINCREMENT, sensor_id INTEGER NOT NULL,
                value REAL NOT NULL, timestamp TEXT,
                FOREIGN KEY (sensor_id) REFERENCES sensors (id) ON DELETE CASCADE
            )
        """)
        conn.commit()
        conn.close()
        logger.info("Database initialized successfully!")
    except Exception as e:
        logger.error(f"Database initialization error: {e}", exc_info=True)
    logger.info("Exiting init_db")

def init_serial():
    global serial_connection, SERIAL_PORT
    logger.info("Entering init_serial")
    logger.info("Initializing serial connection...")
    for port in POSSIBLE_PORTS:
        logger.info(f"Processing port: {port}")
        try:
            if not os.path.exists(port):
                logger.warning(f"Port {port} does not exist, skipping...")
                continue
            if not os.access(port, os.R_OK | os.W_OK):
                logger.warning(f"No read/write permission for {port}. Check permissions or run with sudo.")
                continue
            
            for dsrdtr_val, rtscts_val in [(True, True), (False, False)]:
                logger.info(f"Attempting to open port {port} with DSR/DTR={dsrdtr_val}, RTS/CTS={rtscts_val}")
                try:
                    temp_serial_connection = serial.Serial(
                        port=port, baudrate=BAUD_RATE, timeout=1,
                        dsrdtr=dsrdtr_val, rtscts=rtscts_val
                    )
                    logger.info(f"Successfully opened port {port}. Verifying data stream...")
                    time.sleep(1.5) # Allow time for device to send initial data
                    
                    if temp_serial_connection.in_waiting > 0:
                        line = temp_serial_connection.readline().decode('utf-8', errors='ignore').strip()
                        if line:
                            logger.info(f"Verification data received from {port}: {line}")
                            serial_connection = temp_serial_connection
                            SERIAL_PORT = port
                            logger.info(f"Successfully connected to {SERIAL_PORT}. Settings: {serial_connection.get_settings()}")
                            logger.info("Exiting init_serial (success)")
                            return True
                        else:
                            logger.info(f"Empty line received from {port}, closing.")
                            temp_serial_connection.close()
                    else:
                        logger.info(f"No data received from {port} for verification, closing.")
                        temp_serial_connection.close()
                except serial.SerialException as se:
                    logger.error(f"SerialException with {port} (DSR/DTR={dsrdtr_val}, RTS/CTS={rtscts_val}): {se}")
                except Exception as e:
                    logger.error(f"Unexpected error with {port} (DSR/DTR={dsrdtr_val}, RTS/CTS={rtscts_val}): {e}", exc_info=True)
        except Exception as e_outer:
            logger.error(f"Outer loop error processing port {port}: {e_outer}", exc_info=True)

    logger.critical("Failed to connect to any serial port.")
    logger.info("Exiting init_serial (failure)")
    return False

def read_serial_data():
    global serial_connection
    line_content = None
    try:
        if serial_connection and serial_connection.is_open and serial_connection.in_waiting > 0:
            logger.debug("Data available on serial port...")
            line_bytes = serial_connection.readline()
            try:
                line_content = line_bytes.decode('utf-8', errors='ignore').strip()
                logger.debug(f"Raw data received: '{line_content}'")
            except UnicodeDecodeError as ude:
                logger.error(f"UnicodeDecodeError: {ude}. Raw bytes: {line_bytes!r}")
                return

            if not line_content:
                logger.debug("Empty line received, skipping.")
                return

            processed_line = line_content
            json_str = ""
            try:
                if processed_line.startswith('<') and '>' in processed_line:
                    end_bracket_index = processed_line.index('>')
                    if end_bracket_index > 0:
                        processed_line = processed_line[1:end_bracket_index]
                
                checksum_index = processed_line.find('*')
                json_str = processed_line[:checksum_index] if checksum_index != -1 else processed_line

                if not json_str.strip():
                    logger.warning(f"Empty JSON string after pre-processing. Original: '{line_content}'")
                    return
                
                data = json.loads(json_str)
                logger.debug(f"Parsed JSON data: {data}")
                store_sensor_readings(data)
                logger.info(f"Data processed and stored: '{line_content}'")
            except (json.JSONDecodeError, IndexError) as e_parse:
                logger.error(f"Parsing error: {e_parse}. Data: '{json_str}'. Original: '{line_content}'")
            except Exception as e_inner:
                logger.error(f"Inner processing error: {e_inner}. Original: '{line_content}'", exc_info=True)
    except serial.SerialException as se:
        logger.error(f"SerialException in read_serial_data: {se}. Port: {SERIAL_PORT}", exc_info=True)
    except IOError as ioe:
        logger.error(f"IOError in read_serial_data: {ioe}. Raw line: '{line_content}'", exc_info=True)
    except Exception as e_outer:
        logger.error(f"Outer error in read_serial_data: {e_outer}. Raw line: '{line_content}'", exc_info=True)

def store_sensor_readings(data):
    logger.debug(f"Entering store_sensor_readings with data: {data}")
    try:
        conn = sqlite3.connect(DATABASE_PATH)
        cursor = conn.cursor()
        timestamp = datetime.now().isoformat()
        for sensor_type, value in data.items():
            cursor.execute("SELECT id FROM sensors WHERE type = ? AND enabled = 1", (sensor_type,))
            sensors = cursor.fetchall()
            logger.debug(f"Found {len(sensors)} enabled sensors for type {sensor_type}")
            for sensor_tuple in sensors:
                sensor_id = sensor_tuple[0]
                try:
                    cursor.execute("INSERT INTO readings (sensor_id, value, timestamp) VALUES (?, ?, ?)",
                                   (sensor_id, float(value), timestamp))
                    logger.info(f"Stored reading {value} for sensor {sensor_id} ({sensor_type})")
                except ValueError:
                    logger.warning(f"Could not convert value '{value}' to float for sensor {sensor_id}.")
                except Exception as e_insert:
                    logger.error(f"Error storing reading for sensor {sensor_id}: {e_insert}", exc_info=True)
        conn.commit()
        conn.close()
    except Exception as e_db:
        logger.error(f"Database error in store_sensor_readings: {e_db}", exc_info=True)
    logger.debug("Exiting store_sensor_readings")

@app.route('/')
def dashboard_route(): # Renamed to avoid conflict with any 'dashboard' variable/module
    logger.info("Entering dashboard route")
    conn = sqlite3.connect(DATABASE_PATH)
    cursor = conn.cursor()
    projects = []
    sensors = []
    active_project_id = None
    try:
        cursor.execute("SELECT id, name, description FROM projects ORDER BY name")
        projects = [dict(zip(['id', 'name', 'description'], row)) for row in cursor.fetchall()]
        active_project_id = request.args.get('project', type=int)
        if not active_project_id and projects:
            active_project_id = projects[0]['id']
        
        if active_project_id:
            cursor.execute("SELECT id, name, type, enabled FROM sensors WHERE project_id = ? ORDER BY name", (active_project_id,))
            sensors = [dict(zip(['id', 'name', 'type', 'enabled'], row)) for row in cursor.fetchall()]
        logger.info(f"Dashboard: ActiveProjectID={active_project_id}, Projects={len(projects)}, Sensors={len(sensors)}")
    except Exception as e:
        logger.error(f"Error loading dashboard data: {e}", exc_info=True)
    finally:
        if conn: conn.close()
    logger.info("Exiting dashboard route")
    return render_template('dashboard.html', projects=projects, active_project_id=active_project_id,
                           sensors=sensors, sensor_types=SENSOR_TYPES)

@app.route('/api/projects', methods=['GET'])
def get_projects():
    logger.info("Entering get_projects API")
    projects = []
    try:
        conn = sqlite3.connect(DATABASE_PATH)
        cursor = conn.cursor()
        cursor.execute("SELECT id, name, description FROM projects ORDER BY name")
        projects = [dict(zip(['id', 'name', 'description'], row)) for row in cursor.fetchall()]
        conn.close()
        logger.info(f"Returning {len(projects)} projects.")
    except Exception as e:
        logger.error(f"Error in get_projects: {e}", exc_info=True)
        return jsonify({"error": str(e)}), 500
    logger.info("Exiting get_projects API")
    return jsonify(projects)

@app.route('/api/projects', methods=['POST'])
def create_project():
    logger.info("Entering create_project API")
    data = request.json
    logger.info(f"Request data: {data}")
    if not data or 'name' not in data:
        logger.warning("Project name missing.")
        return jsonify({"error": "Project name is required"}), 400
    project_id = None
    try:
        conn = sqlite3.connect(DATABASE_PATH)
        cursor = conn.cursor()
        cursor.execute("INSERT INTO projects (name, description, created_at) VALUES (?, ?, ?)",
                       (data['name'], data.get('description', ''), datetime.now().isoformat()))
        project_id = cursor.lastrowid
        if 'sensors' in data and isinstance(data['sensors'], list):
            for sensor_type in data['sensors']:
                if sensor_type in SENSOR_TYPES:
                    cursor.execute("INSERT INTO sensors (name, type, project_id, created_at) VALUES (?, ?, ?, ?)",
                                   (f"{sensor_type.replace('_', ' ').title()} Sensor", sensor_type,
                                    project_id, datetime.now().isoformat()))
        conn.commit()
        conn.close()
        logger.info(f"Project '{data['name']}' created with ID: {project_id}")
        return jsonify({"success": True, "id": project_id}), 201
    except sqlite3.IntegrityError: # Handles UNIQUE constraint for project name
        logger.warning(f"Project name '{data['name']}' already exists.")
        return jsonify({"error": f"Project name '{data['name']}' already exists."}), 409
    except Exception as e:
        logger.error(f"Error creating project: {e}", exc_info=True)
        return jsonify({"error": str(e)}), 500

@app.route('/api/sensors/available', methods=['GET'])
def get_available_sensors():
    logger.info("Entering get_available_sensors API")
    try:
        available_sensors = [{'id': f'new_{stype}', 'name': f'{stype.replace("_", " ").title()} Sensor',
                              'type': stype, 'unit': SENSOR_TYPES[stype]} for stype in SENSOR_TYPES]
        logger.info(f"Returning {len(available_sensors)} available sensor types.")
        return jsonify(available_sensors)
    except Exception as e:
        logger.error(f"Error in get_available_sensors: {e}", exc_info=True)
        return jsonify({"error": "Failed to get available sensors"}), 500

@app.route('/api/sensors/<int:sensor_id>/toggle', methods=['POST'])
def toggle_sensor(sensor_id):
    logger.info(f"Entering toggle_sensor API for sensor ID: {sensor_id}")
    data = request.json
    logger.info(f"Request data: {data}")
    if data is None or 'enabled' not in data:
        logger.warning("Enabled state not provided.")
        return jsonify({"error": "Enabled state not provided"}), 400
    try:
        conn = sqlite3.connect(DATABASE_PATH)
        cursor = conn.cursor()
        cursor.execute("UPDATE sensors SET enabled = ? WHERE id = ?", (1 if data['enabled'] else 0, sensor_id))
        updated_rows = cursor.rowcount
        conn.commit()
        conn.close()
        if updated_rows == 0:
            logger.warning(f"Sensor ID {sensor_id} not found for toggle.")
            return jsonify({"error": "Sensor not found"}), 404
        logger.info(f"Sensor {sensor_id} enabled state set to {data['enabled']}.")
        return jsonify({"success": True, "id": sensor_id, "enabled": data['enabled']})
    except Exception as e:
        logger.error(f"Error toggling sensor {sensor_id}: {e}", exc_info=True)
        return jsonify({"error": "Failed to toggle sensor"}), 500

@app.route('/api/sensors/<int:sensor_id>/data')
def get_sensor_data(sensor_id):
    logger.info(f"Entering get_sensor_data API for sensor ID: {sensor_id}")
    minutes = request.args.get('minutes', default=60, type=int)
    logger.info(f"Fetching data for last {minutes} minutes.")
    sensor_data = {}
    try:
        conn = sqlite3.connect(DATABASE_PATH)
        cursor = conn.cursor()
        cursor.execute("SELECT type, min_value, max_value FROM sensors WHERE id = ?", (sensor_id,))
        sensor_info = cursor.fetchone()
        if not sensor_info:
            conn.close()
            logger.warning(f"Sensor ID {sensor_id} not found for data retrieval.")
            return jsonify({"error": "Sensor not found"}), 404
        
        time_filter = (datetime.now() - timedelta(minutes=minutes)).isoformat()
        cursor.execute("SELECT timestamp, value FROM readings WHERE sensor_id = ? AND timestamp > ? ORDER BY timestamp ASC LIMIT 1000",
                       (sensor_id, time_filter))
        readings = cursor.fetchall()
        conn.close()
        
        sensor_data = {
            "type": sensor_info[0], "unit": SENSOR_TYPES.get(sensor_info[0], ""),
            "data": [[ts, val] for ts, val in readings],
            "min_value": sensor_info[1], "max_value": sensor_info[2]
        }
        logger.info(f"Returning {len(readings)} readings for sensor {sensor_id}.")
    except Exception as e:
        logger.error(f"Error getting sensor data for {sensor_id}: {e}", exc_info=True)
        return jsonify({"error": "Failed to get sensor data"}), 500
    return jsonify(sensor_data)

def start_serial_thread():
    logger.info("Entering start_serial_thread")
    def read_loop():
        logger.info("Entering read_loop (serial reading thread)")
        while True:
            read_serial_data()
            time.sleep(0.1)
    
    if init_serial(): # This function now returns True/False
        thread = threading.Thread(target=read_loop, daemon=True)
        thread.start()
        logger.info("Serial reading thread started successfully.")
    else:
        logger.warning("Failed to start serial reading thread as init_serial() returned False.")
    logger.info("Exiting start_serial_thread")

if __name__ == '__main__':
    if os.environ.get("WERKZEUG_RUN_MAIN") == "true":
        try:
            logger.info("Application starting in main execution block.")
            init_db()
            start_serial_thread()
            logger.info("Starting Flask development server on host=0.0.0.0, port=5000.")
            app.run(host='0.0.0.0', port=5000, debug=True)
        except Exception as e:
            logger.critical(f"Critical error during application startup: {e}", exc_info=True)
            # Optionally, re-raise the exception if you want the script to exit with an error code
            # raise
    else:
        # This block is executed by the Flask auto-reloader process.
        # We don't want to duplicate startup tasks here.
        logger.info("Flask auto-reloader process started. Main app execution deferred to primary process.")
