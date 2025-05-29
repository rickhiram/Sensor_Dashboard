# Sensor_Dashboard

This project implements a web-based dashboard for displaying sensor readings. It can connect to a device like an Arduino via a serial port to acquire live sensor data, but can also operate without a connected serial device, allowing for data management and viewing even if live acquisition is not active.

## Project Structure

The main components of this project are now organized within the `dashboard/` subdirectory:

*   `dashboard/app.py`: The main Flask application file.
*   `dashboard/static/`: Contains static assets like CSS (`styles.css`) and JavaScript (`dashboard.js`).
*   `dashboard/templates/`: Contains HTML templates (`dashboard.html`).
*   `dashboard/data/`: Stores data, primarily the SQLite database (`sensor_data.db`). This directory is created by `app.py` if it doesn't exist.
*   `dashboard/logs/`: Contains application log files (e.g., `app.log`). This directory is created by `app.py` if it doesn't exist.
*   `dashboard/requirements.txt`: Lists the Python dependencies required for the project.

## Features

*   Web-based dashboard for visualizing sensor data.
*   Project-based organization of sensors.
*   **Optional Serial Communication**: The application can run even if no serial device is connected or if `pyserial` is not installed. In such cases, live sensor data acquisition will be disabled, but other features remain accessible.
*   SQLite database for storing sensor readings and project configurations.
*   Comprehensive logging to both console and file (`dashboard/logs/app.log`).

## Prerequisites

Before running the application, ensure you have Python 3 and `pip` installed. `pyserial` is only required if you intend to use the live sensor data acquisition feature.

## Setup and Running the Application

1.  **Clone the Repository (if you haven't already):**
    ```bash
    git clone <repository_url>
    cd <repository_name>
    ```

2.  **Navigate to the Application Directory:**
    The main application code is located in the `dashboard/` subdirectory.
    ```bash
    cd dashboard
    ```

3.  **Create a Virtual Environment (Recommended):**
    It's good practice to use a virtual environment to manage project dependencies.
    ```bash
    python3 -m venv venv
    source venv/bin/activate  # On Windows use `venv\Scripts\activate`
    ```

4.  **Install Dependencies:**
    Install the required Python packages using `requirements.txt`.
    ```bash
    pip install -r requirements.txt
    ```
    (Note: If you do not need serial communication, you can manually install only Flask and Flask-CORS, or remove `pyserial` from `requirements.txt` before this step if it causes issues on systems where it cannot be installed.)

5.  **Connect Your Sensor Device (Optional):**
    If you wish to acquire live sensor data, ensure your Arduino or other serial device is connected to your computer and configured to send data. See "Troubleshooting Serial Connections" below if you encounter issues.

6.  **Run the Application:**
    Execute the `app.py` script.
    ```bash
    python3 app.py
    ```
    The application will typically start on `http://0.0.0.0:5000/`. Open this URL in your web browser to view the dashboard.
    *   **Development Mode**: The application runs with `debug=True` by default. This enables the Flask development server's debug mode, which includes features like automatic reloading when code changes. The application is structured to handle the reloader correctly, ensuring background threads for serial communication are managed appropriately.

## Troubleshooting Serial Connections

### Troubleshooting Serial Connections

If the application has trouble connecting to your Arduino or serial device, here are some common things to check:

1.  **Device Connection:**
    *   Ensure your Arduino (or other serial device) is securely connected to your computer/Raspberry Pi via USB.
    *   Try a different USB cable or USB port if problems persist.

2.  **Serial Port Identification:**
    *   The application tries to automatically detect the serial port from a predefined list (`/dev/serial0`, `/dev/ttyAMA0`, `/dev/ttyACM0`, `/dev/ttyUSB0`, etc.).
    *   You can identify the correct port your device is using by:
        *   Checking the output of `dmesg | grep tty` in your terminal after connecting the device.
        *   Looking at the port listed in the Arduino IDE (Tools -> Port) if you have it open.
    *   If the port is consistently different, you might need to add it to the `POSSIBLE_PORTS` list in `app.py`.

3.  **Port Permissions (Linux):**
    *   Serial ports on Linux require appropriate permissions. You can check permissions with:
      ```bash
      ls -l /dev/your_port_name
      ```
      (e.g., `ls -l /dev/ttyACM0`).
    *   If you don't have read/write access, you might see errors like "Permission denied." You can grant temporary access (until next reboot) with:
      ```bash
      sudo chmod 666 /dev/your_port_name
      ```
    *   For a permanent solution, add your user to the `dialout` group (or `tty` group, depending on your Linux distribution):
      ```bash
      sudo usermod -a -G dialout your_username
      ```
      You'll need to log out and log back in for this change to take effect.

4.  **Raspberry Pi Specifics (GPIO Serial):**
    *   If you are using the Raspberry Pi's GPIO pins for serial communication (e.g., `/dev/ttyAMA0` or `/dev/serial0`):
        *   Ensure Serial is enabled in `raspi-config`: Go to `Interface Options` -> `Serial Port`.
        *   When asked "Would you like a login shell to be accessible over serial?", answer **No**.
        *   When asked "Would you like the serial port hardware to be enabled?", answer **Yes**.
        *   Reboot the Pi after these changes.

5.  **Device is Sending Data:**
    *   Confirm that your Arduino/device is actually programmed to send data over the serial connection.
    *   Use the Arduino IDE's Serial Monitor (or another serial terminal program like `minicom` or `putty`) to check if data is appearing as expected. Set the baud rate in the monitor to match the device's configuration (default in `app.py` is 115200).

6.  **Application Logs:**
    *   The `app.py` script utilizes Python's `logging` module. Detailed logs are output to both the console and to a file located at `dashboard/logs/app.log`. Check these logs for specific error messages or operational details.
