#!/bin/bash
# GPS Waveshare L76X HAT Setup Script

echo "Setting up GPS Waveshare L76X HAT GUI..."

# Install Python dependencies
echo "Installing Python dependencies..."
pip3 install -r requirements.txt

# Make the GUI script executable
chmod +x GPS_GUI.py

# Check if running on Raspberry Pi
if [ -f /boot/config.txt ]; then
    echo "Raspberry Pi detected."
    
    # Check if UART is enabled
    if ! grep -q "enable_uart=1" /boot/config.txt; then
        echo "UART not enabled. You may need to enable it manually."
        echo "Add 'enable_uart=1' to /boot/config.txt and reboot."
    fi
    
    # Add user to dialout group if not already added
    if ! groups $USER | grep -q dialout; then
        echo "Adding user to dialout group..."
        sudo usermod -a -G dialout $USER
        echo "Please log out and log back in for group changes to take effect."
    fi
    
    # Stop conflicting services
    echo "Stopping potentially conflicting services..."
    sudo systemctl stop gpsd 2>/dev/null || true
    sudo systemctl disable gpsd 2>/dev/null || true
fi

echo "Setup complete!"
echo "Run the GUI with: python3 GPS_GUI.py"
echo "For full functionality, run with: sudo python3 GPS_GUI.py"