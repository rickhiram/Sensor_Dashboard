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
import logging

# Configure logging
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# File Handler for app.log in the dashboard/ directory
# When app.py is run from dashboard/, app.log will be created in dashboard/
fh = logging.FileHandler('app.log')
fh.setLevel(logging.INFO)

# Console Handler
ch = logging.StreamHandler()
ch.setLevel(logging.INFO)

# Formatter
formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(module)s - %(funcName)s - L%(lineno)d - %(message)s')
fh.setFormatter(formatter)
ch.setFormatter(formatter)

# Add Handlers to Logger
logger.addHandler(fh)
logger.addHandler(ch)

logger.info("Logging initialized") # Initial log message to confirm setup


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
    logger.info("Entering init_serial")

    logger.info("Initializing serial connection...")
    logger.info("Searching for available serial ports...")
    # Optional: Keep these for debugging if needed, but can be noisy.
    # logger.info("Listing /dev/serial* devices:")
    # os.system('ls -l /dev/serial*') # This output goes to stdout, not logger
    # logger.info("Listing /dev/tty* devices:")
    # os.system('ls -l /dev/tty*') # This output goes to stdout, not logger

    for port in POSSIBLE_PORTS:
        logger.info(f"Processing port: {port}")
        try:
            logger.info(f"Checking existence of port: {port}")
            if not os.path.exists(port):
                logger.warning(f"Port {port} does not exist, skipping...")
                continue
            logger.info(f"Port {port} exists.")

            logger.info(f"Checking permissions for port: {port}")
            if not os.access(port, os.R_OK | os.W_OK):
                logger.warning(f"No read/write permission for {port}. Current permissions:")
                # os.system(f'ls -l {port}') # This output goes to stdout, not logger. User sees this directly.
                # If direct feedback is not needed, this os.system call could be removed or logged differently.
                # For now, assume direct feedback is desired for permissions.
                print(f"DEBUG: Permissions for {port} (run 'ls -l {port}' to check manually)") # Retain as print for now, or decide to fully remove
                continue
            logger.info(f"Read/write permissions confirmed for port: {port}")

            # Try different serial configurations (flow control)
            for flow_control_setting in [(True, True), (False, False)]:
                dsrdtr_val, rtscts_val = flow_control_setting
                logger.info(f"Attempting to open port {port} with DSR/DTR={dsrdtr_val}, RTS/CTS={rtscts_val}")
                try:
                    serial_connection = serial.Serial(
                        port=port,
                        baudrate=BAUD_RATE,
                        timeout=1,
                        dsrdtr=dsrdtr_val,
                        rtscts=rtscts_val
                    )
                    logger.info(f"Successfully opened port {port} with DSR/DTR={dsrdtr_val}, RTS/CTS={rtscts_val}")

                    logger.info(f"Attempting to read data from {port} for verification...")
                    data_received_successfully = False
                    for attempt in range(3): # Try reading 3 times
                        logger.info(f"Read attempt {attempt + 1}/3 for port {port}")
                        try:
                            if serial_connection.in_waiting:
                                line = serial_connection.readline().decode('utf-8').strip()
                                if line:
                                    logger.info(f"Data received from {port}: {line}")
                                    SERIAL_PORT = port
                                    logger.info(f"Successfully connected to {SERIAL_PORT}")
                                    logger.info(f"Port settings: {serial_connection.get_settings()}")
                                    data_received_successfully = True
                                    logger.info("Exiting init_serial (success)")
                                    return True # Connection successful
                                else:
                                    logger.info(f"Empty line received from {port}.")
                            else:
                                logger.info(f"No data in buffer for {port}, waiting 1 second...")
                        except serial.SerialException as se:
                            logger.error(f"SerialException during read attempt on {port}: {se}")
                            break # Stop trying to read from this port config
                        except IOError as ioe:
                            logger.error(f"IOError during read attempt on {port}: {ioe}")
                            break # Stop trying to read from this port config
                        except Exception as e_read:
                            logger.error(f"Unexpected error during read attempt on {port}: {e_read}")
                            break # Stop trying to read from this port config
                        time.sleep(1)

                    if not data_received_successfully:
                        logger.warning(f"No data received from {port} with DSR/DTR={dsrdtr_val}, RTS/CTS={rtscts_val}. Closing port.")
                        if serial_connection and serial_connection.is_open:
                            serial_connection.close()
                        # Continue to next flow control setting

                except serial.SerialException as se:
                    logger.error(f"SerialException when trying to open {port} with DSR/DTR={dsrdtr_val}, RTS/CTS={rtscts_val}: {se}")
                    if serial_connection and serial_connection.is_open:
                        serial_connection.close()
                except PermissionError as pe:
                    logger.error(f"PermissionError when trying to open {port}: {pe}. This should have been caught by os.access, but good to double check.")
                    # os.system(f'ls -l {port}')
                except IOError as ioe:
                    logger.error(f"IOError when trying to open or configure {port}: {ioe}")
                    if serial_connection and serial_connection.is_open:
                        serial_connection.close()
                except Exception as e_open:
                    logger.error(f"Unexpected error when trying to open {port} with DSR/DTR={dsrdtr_val}, RTS/CTS={rtscts_val}: {e_open}")
                    if serial_connection and serial_connection.is_open:
                        serial_connection.close()
        except Exception as e_port_loop:
            # This catches errors in the outer loop (e.g. os.path.exists or os.access if they raise something unexpected)
            logger.error(f"Unexpected error while processing port {port}: {e_port_loop}")

    logger.critical("Failed to connect to any serial port after trying all configurations.")
    logger.info("Please check the following:")
    logger.info("1. Arduino/Device is properly connected via USB or GPIO.")
    logger.info("2. The correct serial port is listed in POSSIBLE_PORTS in app.py.")
    logger.info("3. Device has necessary permissions (e.g., 'sudo chmod a+rw /dev/ttyAMA10' or add user to 'dialout' group).")
    logger.info("4. Serial communication is enabled on the Raspberry Pi (if applicable, via raspi-config).")
    logger.info("5. The device is powered on and sending data.")
    logger.info("Exiting init_serial (failure)")
    return False

def read_serial_data():
    """Read and parse data from Arduino. Hardened for robustness."""
    global serial_connection
    # logger.debug("Entering read_serial_data") # Potentially too verbose for every 0.1s call
    line_content = None  # Initialize to None, so it's defined in case of early error

    try:
        if serial_connection and serial_connection.is_open:
            if serial_connection.in_waiting > 0: # Check if there's actually data
                logger.debug("Data available on serial port...")
                line_bytes = serial_connection.readline() # Can raise SerialException
                
                try:
                    line_content = line_bytes.decode('utf-8').strip() # Can raise UnicodeDecodeError
                    logger.debug(f"Raw data received: '{line_content}'")
                except UnicodeDecodeError as ude:
                    logger.error(f"UnicodeDecodeError while decoding data: {type(ude).__name__} - {str(ude)}. Raw bytes: {line_bytes!r}")
                    # logger.debug("Exiting read_serial_data (UnicodeDecodeError)")
                    return # Skip this problematic line, let the loop continue

                if not line_content: # If line is empty after strip, nothing to process
                    logger.debug("Empty line received or failed to decode, skipping further processing.")
                    # logger.debug("Exiting read_serial_data (empty line)")
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
                            logger.debug(f"Data after removing brackets: '{processed_line}'")
                        else:
                            logger.warning(f"Malformed bracket structure (e.g., '<>') in line: '{line_content}'. Using content as is.")
                            pass


                    # Remove checksum (everything after and including *)
                    checksum_index = processed_line.find('*')
                    if checksum_index != -1:
                        json_str = processed_line[:checksum_index]
                    else:
                        json_str = processed_line # No checksum found
                    logger.debug(f"Data after removing checksum (if any): '{json_str}'")

                    if not json_str.strip(): # Check if json_str is empty or just whitespace
                        logger.warning(f"JSON string is empty after pre-processing. Original line: '{line_content}'")
                        # logger.debug("Exiting read_serial_data (empty JSON string)")
                        return

                    data = json.loads(json_str) # Can raise json.JSONDecodeError
                    logger.debug(f"Parsed JSON data: {data}")

                    store_sensor_readings(data) # Can raise various exceptions if db interaction fails
                    logger.info(f"Data processed and stored successfully from line: '{line_content}'")

                except json.JSONDecodeError as e_json:
                    logger.error(f"JSONDecodeError parsing data: {type(e_json).__name__} - {str(e_json)}. Problematic JSON string: '{json_str}'. Original line: '{line_content}'")
                except IndexError as e_index: # If string manipulation (like split or indexing) goes wrong
                    logger.error(f"IndexError during data processing: {type(e_index).__name__} - {str(e_index)}. Original line: '{line_content}'")
                except Exception as e_parse_store: # Catch any other errors during parsing/storing
                    logger.error(f"Unexpected error processing/storing data: {type(e_parse_store).__name__} - {str(e_parse_store)}. Original line: '{line_content}'")
            # else:
                # logger.debug("No data in_waiting on serial port.") 
        # else:
            # if not serial_connection:
            #     logger.warning("read_serial_data: serial_connection is None.")
            # elif not serial_connection.is_open:
            #     logger.warning("read_serial_data: serial_connection is not open.")

    except serial.SerialException as se:
        logger.error(f"SerialException in read_serial_data (e.g., device disconnected): {type(se).__name__} - {str(se)}. Port: {SERIAL_PORT}")
    except IOError as ioe: # For other I/O errors not covered by SerialException
        logger.error(f"IOError in read_serial_data: {type(ioe).__name__} - {str(ioe)}. Raw line (if available): '{line_content}'")
    except Exception as e_outer:
        # This is a general catch-all for unexpected errors in the function.
        logger.error(f"An unexpected error occurred in read_serial_data: {type(e_outer).__name__} - {str(e_outer)}. Raw line (if available): '{line_content}'")
    # logger.debug("Exiting read_serial_data (end of function)") # Potentially too verbose

def store_sensor_readings(data):
    """Store sensor readings in the database"""
    logger.debug(f"Entering store_sensor_readings with data: {data}")
    try:
        conn = sqlite3.connect("data/sensor_data.db")
        cursor = conn.cursor()
        timestamp = datetime.now().isoformat()
        logger.debug(f"Generated timestamp: {timestamp}")

        for sensor_type, value in data.items():
            logger.debug(f"Processing sensor_type: {sensor_type}, value: {value}")
            # Find all enabled sensors of this type across all projects
            cursor.execute("""
                SELECT id FROM sensors
                WHERE type = ? AND enabled = 1
            """, (sensor_type,))

            sensors = cursor.fetchall()
            logger.info(f"Found {len(sensors)} enabled sensors for type {sensor_type}")

            for sensor in sensors:
                try:
                    logger.debug(f"Storing reading for sensor_id: {sensor[0]}, value: {value}, timestamp: {timestamp}")
                    cursor.execute("""
                        INSERT INTO readings (sensor_id, value, timestamp)
                        VALUES (?, ?, ?)
                    """, (sensor[0], float(value), timestamp))
                    logger.info(f"Stored reading {value} for sensor {sensor[0]}")
                except Exception as e:
                    logger.error(f"Error storing reading for sensor {sensor[0]}: {e}")

        conn.commit()
        logger.info("All readings stored successfully in database.")
        conn.close()
    except Exception as e:
        logger.error(f"Error storing readings in database: {e}")
    logger.debug("Exiting store_sensor_readings")

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
# This runs at import time, so it's fine as is, or could be moved into init_db
# For now, keeping it as is, as it's a one-time setup.
# If it were to use logger, logger might not be fully configured at import time.
# The current location is fine.
os.makedirs('data', exist_ok=True)

def init_db():
    """Initialize the database and create the necessary tables if they don't exist."""
    logger.info("Entering init_db")
    try:
        logger.info("Initializing database...")
        conn = sqlite3.connect("data/sensor_data.db")
        cursor = conn.cursor()

        # Create projects table
        logger.debug("Creating projects table if not exists.")
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS projects (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT UNIQUE NOT NULL,
                description TEXT,
                created_at TEXT
            )
        """)

        # Create sensors table
        logger.debug("Creating sensors table if not exists.")
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
        logger.debug("Creating readings table if not exists.")
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
        logger.info("Database initialized successfully!")
    except Exception as e:
        logger.error(f"Database initialization error: {e}")
    logger.info("Exiting init_db")

@app.route('/')
def dashboard():
    """Render the dashboard template."""
    logger.info("Entering dashboard route")
    conn = sqlite3.connect("data/sensor_data.db")
    cursor = conn.cursor()
    logger.debug("Database connection established for dashboard.")

    # Get all projects
    logger.debug("Fetching all projects from database.")
    cursor.execute("""
        SELECT id, name, description
        FROM projects
        ORDER BY name
    """)
    projects = [dict(zip(['id', 'name', 'description'], row)) for row in cursor.fetchall()]
    logger.info(f"Found {len(projects)} projects.")

    # Get active project (first project if none specified)
    active_project_id = request.args.get('project', type=int)
    logger.debug(f"Active project ID from request args: {active_project_id}")
    if not active_project_id and projects:
        active_project_id = projects[0]['id']
        logger.info(f"No active project in args, defaulting to first project ID: {active_project_id}")
    
    logger.info(f"Using active project ID: {active_project_id}")

    # Get sensors for active project
    sensors = []
    if active_project_id:
        logger.debug(f"Fetching sensors for active project ID: {active_project_id}")
        cursor.execute("""
            SELECT id, name, type, enabled
            FROM sensors
            WHERE project_id = ?
            ORDER BY name
        """, (active_project_id,))
        sensors = [dict(zip(['id', 'name', 'type', 'enabled'], row)) for row in cursor.fetchall()]
        logger.info(f"Found {len(sensors)} sensors for active project.")
    else:
        logger.info("No active project ID, so no sensors fetched.")

    conn.close()
    logger.debug("Database connection closed for dashboard.")
    logger.info("Exiting dashboard route, rendering template.")
    return render_template('dashboard.html',
                         projects=projects,
                         active_project_id=active_project_id,
                         sensors=sensors,
                         sensor_types=SENSOR_TYPES)

@app.route('/api/projects', methods=['GET'])
def get_projects():
    """Get all projects."""
    logger.info("Entering get_projects API route")
    conn = sqlite3.connect("data/sensor_data.db")
    cursor = conn.cursor()
    logger.debug("Database connection established for get_projects.")
    cursor.execute("SELECT id, name, description FROM projects ORDER BY name")
    projects = [dict(zip(['id', 'name', 'description'], row)) for row in cursor.fetchall()]
    conn.close()
    logger.debug("Database connection closed for get_projects.")
    logger.info(f"Returning {len(projects)} projects via API.")
    logger.info("Exiting get_projects API route")
    return jsonify(projects)

@app.route('/api/projects', methods=['POST'])
def create_project():
    """Create a new project with sensors."""
    logger.info("Entering create_project API route")
    data = request.json
    logger.info(f"Received data for new project: {data}")

    if not data or 'name' not in data:
        logger.warning("Project name missing in request data.")
        logger.info("Exiting create_project API route (bad request)")
        return jsonify({"error": "Project name is required"}), 400

    try:
        conn = sqlite3.connect("data/sensor_data.db")
        cursor = conn.cursor()
        logger.debug("Database connection established for create_project.")

        # Create project
        logger.info(f"Creating project with name: {data['name']}, description: {data.get('description', '')}")
        cursor.execute("""
            INSERT INTO projects (name, description, created_at)
            VALUES (?, ?, ?)
        """, (data['name'], data.get('description', ''), datetime.now().isoformat()))

        project_id = cursor.lastrowid
        logger.info(f"Project created with ID: {project_id}")

        # Add sensors if provided
        if 'sensors' in data and isinstance(data['sensors'], list):
            logger.info(f"Adding sensors to project {project_id}: {data['sensors']}")
            for sensor_type in data['sensors']:
                if sensor_type in SENSOR_TYPES:
                    logger.debug(f"Adding sensor of type {sensor_type} to project {project_id}")
                    cursor.execute("""
                        INSERT INTO sensors (name, type, project_id, created_at)
                        VALUES (?, ?, ?, ?)
                    """, (f"{sensor_type.replace('_', ' ').title()} Sensor",
                         sensor_type,
                         project_id,
                         datetime.now().isoformat()))
                else:
                    logger.warning(f"Unknown sensor type '{sensor_type}' provided for project {project_id}, skipping.")
        else:
            logger.info(f"No sensors provided for new project {project_id}.")

        conn.commit()
        conn.close()
        logger.debug("Database connection closed for create_project.")
        logger.info(f"Successfully created project {project_id}.")
        logger.info("Exiting create_project API route (success)")
        return jsonify({"success": True, "id": project_id})
    except Exception as e:
        logger.error(f"Error creating project: {e}")
        logger.info("Exiting create_project API route (server error)")
        return jsonify({"error": str(e)}), 500

@app.route('/api/sensors/available', methods=['GET'])
def get_available_sensors():
    """Get all available sensor types that can be added to a project."""
    logger.info("Entering get_available_sensors API route")
    try:
        available_sensors = []
        for sensor_type, unit in SENSOR_TYPES.items():
            available_sensors.append({
                'id': f'new_{sensor_type}',  # Temporary ID for new sensors
                'name': f'{sensor_type.replace("_", " ").title()} Sensor',
                'type': sensor_type,
                'unit': unit
            })
        logger.info(f"Returning {len(available_sensors)} available sensor types.")
        logger.info("Exiting get_available_sensors API route (success)")
        return jsonify(available_sensors)
    except Exception as e:
        logger.error(f"Error getting available sensors: {e}")
        logger.info("Exiting get_available_sensors API route (server error)")
        return jsonify({'error': 'Failed to get available sensors'}), 500

@app.route('/api/sensors/<int:sensor_id>/toggle', methods=['POST'])
def toggle_sensor(sensor_id):
    """Toggle a sensor's enabled state."""
    logger.info(f"Entering toggle_sensor API route for sensor_id: {sensor_id}")
    try:
        data = request.json
        logger.info(f"Received data for toggling sensor {sensor_id}: {data}")
        if data is None:
            logger.warning(f"No data provided for toggling sensor {sensor_id}.")
            logger.info("Exiting toggle_sensor API route (bad request)")
            return jsonify({"error": "No data provided"}), 400

        enabled = data.get('enabled')
        if enabled is None:
            logger.warning(f"Enabled state not provided for toggling sensor {sensor_id}.")
            logger.info("Exiting toggle_sensor API route (bad request)")
            return jsonify({"error": "Enabled state not provided"}), 400
        
        logger.info(f"Attempting to set sensor {sensor_id} enabled state to: {enabled}")

        conn = sqlite3.connect("data/sensor_data.db")
        cursor = conn.cursor()
        logger.debug(f"Database connection established for toggling sensor {sensor_id}.")

        # Update sensor enabled state
        cursor.execute("""
            UPDATE sensors
            SET enabled = ?
            WHERE id = ?
        """, (1 if enabled else 0, sensor_id))

        if cursor.rowcount == 0:
            conn.close()
            logger.warning(f"Sensor with ID {sensor_id} not found for toggling.")
            logger.info("Exiting toggle_sensor API route (not found)")
            return jsonify({"error": "Sensor not found"}), 404

        conn.commit()
        conn.close()
        logger.debug(f"Database connection closed for toggling sensor {sensor_id}.")
        logger.info(f"Successfully toggled sensor {sensor_id} enabled state to {enabled}.")
        logger.info("Exiting toggle_sensor API route (success)")
        return jsonify({"success": True, "id": sensor_id, "enabled": enabled})
    except Exception as e:
        logger.error(f"Error toggling sensor {sensor_id}: {e}")
        logger.info("Exiting toggle_sensor API route (server error)")
        return jsonify({"error": "Failed to toggle sensor"}), 500

@app.route('/api/sensors/<int:sensor_id>/data')
def get_sensor_data(sensor_id):
    """Get sensor data for charting."""
    logger.info(f"Entering get_sensor_data API route for sensor_id: {sensor_id}")
    try:
        # Get parameters
        minutes = request.args.get('minutes', default=60, type=int)
        logger.info(f"Fetching data for sensor {sensor_id} for the last {minutes} minutes.")

        conn = sqlite3.connect("data/sensor_data.db")
        cursor = conn.cursor()
        logger.debug(f"Database connection established for get_sensor_data for sensor {sensor_id}.")

        # Get sensor info
        logger.debug(f"Fetching sensor info for sensor_id: {sensor_id}")
        cursor.execute("SELECT type, min_value, max_value FROM sensors WHERE id = ?", (sensor_id,))
        sensor = cursor.fetchone()
        if not sensor:
            conn.close()
            logger.warning(f"Sensor with ID {sensor_id} not found for data retrieval.")
            logger.info("Exiting get_sensor_data API route (not found)")
            return jsonify({"error": "Sensor not found"}), 404

        sensor_type, min_value, max_value = sensor
        logger.info(f"Sensor {sensor_id} identified as type: {sensor_type}, min_value: {min_value}, max_value: {max_value}")

        # Get readings for last n minutes
        time_filter = (datetime.now() - timedelta(minutes=minutes)).isoformat()
        logger.debug(f"Fetching readings for sensor {sensor_id} after timestamp: {time_filter}")
        cursor.execute("""
            SELECT timestamp, value
            FROM readings
            WHERE sensor_id = ?
            AND timestamp > ?
            ORDER BY timestamp ASC
            LIMIT 100
        """, (sensor_id, time_filter))

        readings = cursor.fetchall()
        logger.info(f"Retrieved {len(readings)} readings for sensor {sensor_id}")
        conn.close()
        logger.debug(f"Database connection closed for get_sensor_data for sensor {sensor_id}.")

        # Format data for charting
        formatted_data = [[ts, val] for ts, val in readings]
        if formatted_data:
             logger.debug(f"Last 3 readings for sensor {sensor_id}: {formatted_data[-3:]}")
        else:
            logger.debug(f"No data for sensor {sensor_id}")


        data = {
            "type": sensor_type,
            "unit": SENSOR_TYPES.get(sensor_type, ""),
            "data": formatted_data,
            "min_value": min_value,
            "max_value": max_value
        }
        logger.info(f"Returning data for sensor {sensor_id}.")
        logger.info("Exiting get_sensor_data API route (success)")
        return jsonify(data)
    except Exception as e:
        logger.error(f"Error getting sensor data for sensor {sensor_id}: {e}")
        logger.info("Exiting get_sensor_data API route (server error)")
        return jsonify({"error": "Failed to get sensor data"}), 500

def start_serial_thread():
    """Start a thread to continuously read serial data"""
    logger.info("Entering start_serial_thread")
    def read_loop():
        logger.info("Entering read_loop (serial reading thread)")
        while True:
            read_serial_data()
            time.sleep(0.1)  # Small delay to prevent CPU overuse
        # Note: This loop doesn't have an explicit exit log as it's a `while True` daemon thread.
        # It will exit when the main process exits.

    if init_serial():
        thread = threading.Thread(target=read_loop, daemon=True)
        thread.start()
        logger.info("Serial reading thread started")
    else:
        logger.warning("Failed to start serial reading thread because init_serial() returned False.")
    logger.info("Exiting start_serial_thread")

if __name__ == '__main__':
    # Only run this once (avoids double-thread issue)
    # No direct logging here, but functions called (init_db, start_serial_thread) have logging.
    # Flask's own logger will also output startup messages.
    if os.environ.get("WERKZEUG_RUN_MAIN") == "true":
        try:
            init_db()
            start_serial_thread() # init_serial() is called within start_serial_thread
            # Run on all network interfaces, port 5000
            logger.info("Starting Flask development server.")
            app.run(host='0.0.0.0', port=5000, debug=True)
        except Exception as e:
            logger.critical(f"Critical error during application startup: {e}", exc_info=True)
```
