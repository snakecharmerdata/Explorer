# GPS Waveshare L76X HAT - Enhanced GUI Features

## Key Features of the Enhanced GPS GUI

### **Visual Interface**
- **Modern GUI** using tkinter with a clean, organized layout
- **Configuration Panel** to adjust GPS device, baud rate, and web port
- **Control Buttons** for easy GPS management
- **Real-time Status Display** showing GPS coordinates, speed, and connection status
- **System Log** with timestamped messages for monitoring

### **GPS Control Features**
- **Start GPS & Server** - Activates both GPS reading and web server
- **Stop GPS & Server** - Safely stops all services
- **Open Live Map** - Automatically opens the web-based map in your browser
- **Simulation Mode** - Test the interface without actual GPS hardware

### **Diagnostic Tools**
- **Run Diagnostics** - Comprehensive system checks including:
  - PySerial library availability
  - GPS device file existence and permissions
  - Raspberry Pi detection and UART configuration
  - Conflicting service detection (gpsd)
- **Restart GPS Service** - Fixes common GPS issues by restarting services

### **Real-time Monitoring**
- **Live Status Updates** every second showing:
  - Server running status
  - GPS fix validity
  - Current coordinates (latitude/longitude)
  - Speed in km/h
  - Last update time with data age indicators
- **Color-coded Status** (green/orange/red) for quick visual feedback

## How to Use

### 1. **Run the GUI**
```bash
python3 Main.py
```

### 2. **Configure Settings** (if needed)
- GPS Device: `/dev/serial0` (default)
- Baud Rate: `9600` (default)
- Web Port: `5000` (default)
- Check "Simulation Mode" for testing without hardware

### 3. **Start GPS**
- Click "Start GPS & Server"
- Monitor the system log for status messages
- Watch the status panel for real-time GPS data

### 4. **View Live Map**
- Click "Open Live Map" to launch the web interface
- The map will show your GPS location with a pulsing marker

### 5. **Troubleshoot** (if needed)
- Click "Run Diagnostics" to check system configuration
- Use "Restart GPS Service" if GPS isn't working

## Command Line Options

The GUI maintains all original functionality while adding visual controls:

- **GUI Mode** (default): `python3 Main.py`
- **Command Line Mode**: `python3 Main.py --nogui`
- **Simulation Mode**: `python3 Main.py --simulate`
- **Custom Device**: `python3 Main.py --device /dev/ttyUSB0`
- **Custom Port**: `python3 Main.py --port 8080`

## Benefits

- **User-Friendly**: No need to remember command line arguments
- **Visual Feedback**: Real-time status updates and color-coded indicators
- **Diagnostic Tools**: Built-in troubleshooting and system checks
- **Easy Access**: One-click access to live GPS map
- **Safe Operation**: Proper startup/shutdown procedures with error handling
- **Flexible**: Supports both GUI and command-line operation modes

## Technical Details

- **Framework**: Python tkinter for cross-platform GUI
- **Threading**: Non-blocking GPS reading and web server operation
- **Error Handling**: Comprehensive error checking and user notifications
- **System Integration**: Automatic detection of Raspberry Pi and GPS hardware
- **Web Interface**: Integrated web server with live map display using Leaflet.js

The interface provides everything needed to easily manage your GPS Waveshare L76X HAT with visual feedback and diagnostic tools, making it perfect for compilation into an executable later.