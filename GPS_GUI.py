#!/usr/bin/env python3
"""
GPS Waveshare L76X HAT GUI Manager
Improved version with diagnostics, reactivation, and easy-to-use interface
"""

import tkinter as tk
from tkinter import ttk, messagebox, scrolledtext
import threading
import time
import math
import json
import subprocess
import os
import sys
from typing import Optional, Dict, Any
from datetime import datetime

try:
    import serial
    SERIAL_AVAILABLE = True
except ImportError:
    SERIAL_AVAILABLE = False

class GPSManager:
    """Handles GPS communication and diagnostics"""
    
    def __init__(self):
        self.device = '/dev/serial0'
        self.baud = 9600
        self.serial_conn = None
        self.is_running = False
        self.last_fix = {
            'lat': None,
            'lon': None,
            'speed_knots': 0.0,
            'timestamp': None,
            'valid': False,
            'updated_at': 0.0,
            'satellites': 0,
            'hdop': 0.0
        }
        self.raw_data = []
        self.lock = threading.Lock()
        
    def nmea_to_decimal(self, coord: str, direction: str) -> Optional[float]:
        """Convert NMEA coordinate to decimal degrees"""
        if not coord or not direction or '.' not in coord:
            return None
        try:
            before_dot = coord.split('.', 1)[0]
            if len(before_dot) < 3:
                return None
            deg_len = len(before_dot) - 2
            deg = int(coord[:deg_len])
            minutes = float(coord[deg_len:])
            decimal = deg + minutes / 60.0
            if direction in ('S', 'W'):
                decimal = -decimal
            return decimal
        except Exception:
            return None
    
    def parse_gga(self, line: str) -> Optional[Dict]:
        """Parse GGA sentence for fix quality and satellite info"""
        if not line.startswith(('$GPGGA', '$GNGGA')):
            return None
        try:
            if '*' in line:
                line = line.split('*', 1)[0]
            parts = line.split(',')
            if len(parts) < 15:
                return None
            
            lat = self.nmea_to_decimal(parts[2], parts[3]) if parts[2] and parts[3] else None
            lon = self.nmea_to_decimal(parts[4], parts[5]) if parts[4] and parts[5] else None
            quality = int(parts[6]) if parts[6] else 0
            satellites = int(parts[7]) if parts[7] else 0
            hdop = float(parts[8]) if parts[8] else 0.0
            
            return {
                'lat': lat,
                'lon': lon,
                'quality': quality,
                'satellites': satellites,
                'hdop': hdop,
                'valid': quality > 0 and lat is not None and lon is not None
            }
        except Exception:
            return None
    
    def parse_rmc(self, line: str) -> Optional[Dict]:
        """Parse RMC sentence for basic position and speed"""
        if not line.startswith(('$GPRMC', '$GNRMC')):
            return None
        try:
            if '*' in line:
                line = line.split('*', 1)[0]
            parts = line.split(',')
            if len(parts) < 12:
                return None
            
            status = parts[2].upper() if parts[2] else 'V'
            valid = status == 'A'
            lat = self.nmea_to_decimal(parts[3], parts[4]) if parts[3] and parts[4] else None
            lon = self.nmea_to_decimal(parts[5], parts[6]) if parts[5] and parts[6] else None
            speed_knots = float(parts[7]) if parts[7] else 0.0
            timestamp = parts[1] if parts[1] else ''
            
            return {
                'lat': lat,
                'lon': lon,
                'speed_knots': speed_knots,
                'timestamp': timestamp,
                'valid': valid and lat is not None and lon is not None
            }
        except Exception:
            return None
    
    def check_serial_permissions(self) -> bool:
        """Check if we have permission to access the serial device"""
        try:
            return os.access(self.device, os.R_OK | os.W_OK)
        except:
            return False
    
    def enable_serial_interface(self) -> bool:
        """Enable serial interface via raspi-config"""
        try:
            # Check if we're on a Raspberry Pi
            if not os.path.exists('/boot/config.txt'):
                return False
            
            # Enable UART
            subprocess.run(['sudo', 'raspi-config', 'nonint', 'do_serial', '0'], 
                         check=True, capture_output=True)
            
            # Add user to dialout group
            username = os.getenv('USER', 'pi')
            subprocess.run(['sudo', 'usermod', '-a', '-G', 'dialout', username], 
                         check=True, capture_output=True)
            
            return True
        except Exception:
            return False
    
    def restart_gps_service(self) -> bool:
        """Restart GPS-related services"""
        try:
            # Stop gpsd if running
            subprocess.run(['sudo', 'systemctl', 'stop', 'gpsd'], 
                         capture_output=True)
            subprocess.run(['sudo', 'killall', 'gpsd'], 
                         capture_output=True)
            
            # Reset the serial device
            if os.path.exists(self.device):
                subprocess.run(['sudo', 'stty', '-F', self.device, 'raw', '9600'], 
                             capture_output=True)
            
            return True
        except Exception:
            return False
    
    def start_gps(self) -> bool:
        """Start GPS reading"""
        if not SERIAL_AVAILABLE:
            return False
        
        if self.is_running:
            return True
        
        try:
            self.serial_conn = serial.Serial(self.device, self.baud, timeout=1)
            self.is_running = True
            
            # Start reading thread
            self.read_thread = threading.Thread(target=self._read_gps_data, daemon=True)
            self.read_thread.start()
            
            return True
        except Exception as e:
            print(f"Failed to start GPS: {e}")
            return False
    
    def stop_gps(self):
        """Stop GPS reading"""
        self.is_running = False
        if self.serial_conn:
            try:
                self.serial_conn.close()
            except:
                pass
            self.serial_conn = None
    
    def _read_gps_data(self):
        """Read GPS data in background thread"""
        while self.is_running and self.serial_conn:
            try:
                line = self.serial_conn.readline().decode('ascii', errors='ignore').strip()
                if not line:
                    continue
                
                # Store raw data for diagnostics
                with self.lock:
                    self.raw_data.append(f"{datetime.now().strftime('%H:%M:%S')} - {line}")
                    if len(self.raw_data) > 100:  # Keep last 100 lines
                        self.raw_data.pop(0)
                
                # Parse different sentence types
                gga_data = self.parse_gga(line)
                rmc_data = self.parse_rmc(line)
                
                with self.lock:
                    if gga_data:
                        self.last_fix.update({
                            'satellites': gga_data['satellites'],
                            'hdop': gga_data['hdop'],
                            'updated_at': time.time()
                        })
                        if gga_data['valid']:
                            self.last_fix.update({
                                'lat': gga_data['lat'],
                                'lon': gga_data['lon'],
                                'valid': True
                            })
                    
                    if rmc_data:
                        self.last_fix.update({
                            'speed_knots': rmc_data['speed_knots'],
                            'timestamp': rmc_data['timestamp'],
                            'updated_at': time.time()
                        })
                        if rmc_data['valid']:
                            self.last_fix.update({
                                'lat': rmc_data['lat'],
                                'lon': rmc_data['lon'],
                                'valid': True
                            })
                            
            except Exception as e:
                print(f"GPS read error: {e}")
                time.sleep(1)
    
    def get_status(self) -> Dict[str, Any]:
        """Get current GPS status"""
        with self.lock:
            status = dict(self.last_fix)
            status['is_running'] = self.is_running
            status['serial_available'] = SERIAL_AVAILABLE
            status['device_accessible'] = self.check_serial_permissions()
            status['age'] = time.time() - status.get('updated_at', 0)
            return status
    
    def get_raw_data(self) -> list:
        """Get raw NMEA data for diagnostics"""
        with self.lock:
            return list(self.raw_data)


class GPSGUI:
    """Main GUI application"""
    
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("GPS Waveshare L76X HAT Manager")
        self.root.geometry("800x600")
        self.root.resizable(True, True)
        
        self.gps_manager = GPSManager()
        self.update_timer = None
        
        self.setup_ui()
        self.start_updates()
    
    def setup_ui(self):
        """Setup the user interface"""
        # Create notebook for tabs
        notebook = ttk.Notebook(self.root)
        notebook.pack(fill='both', expand=True, padx=10, pady=10)
        
        # Main tab
        self.main_frame = ttk.Frame(notebook)
        notebook.add(self.main_frame, text="GPS Status")
        self.setup_main_tab()
        
        # Diagnostics tab
        self.diag_frame = ttk.Frame(notebook)
        notebook.add(self.diag_frame, text="Diagnostics")
        self.setup_diagnostics_tab()
        
        # Raw Data tab
        self.raw_frame = ttk.Frame(notebook)
        notebook.add(self.raw_frame, text="Raw Data")
        self.setup_raw_data_tab()
    
    def setup_main_tab(self):
        """Setup main status tab"""
        # Control buttons frame
        control_frame = ttk.LabelFrame(self.main_frame, text="GPS Control", padding=10)
        control_frame.pack(fill='x', padx=5, pady=5)
        
        button_frame = ttk.Frame(control_frame)
        button_frame.pack(fill='x')
        
        self.start_btn = ttk.Button(button_frame, text="Start GPS", 
                                   command=self.start_gps, style="Success.TButton")
        self.start_btn.pack(side='left', padx=5)
        
        self.stop_btn = ttk.Button(button_frame, text="Stop GPS", 
                                  command=self.stop_gps, style="Danger.TButton")
        self.stop_btn.pack(side='left', padx=5)
        
        self.restart_btn = ttk.Button(button_frame, text="Restart GPS Service", 
                                     command=self.restart_gps_service)
        self.restart_btn.pack(side='left', padx=5)
        
        self.enable_serial_btn = ttk.Button(button_frame, text="Enable Serial Interface", 
                                           command=self.enable_serial_interface)
        self.enable_serial_btn.pack(side='left', padx=5)
        
        # Status frame
        status_frame = ttk.LabelFrame(self.main_frame, text="GPS Status", padding=10)
        status_frame.pack(fill='both', expand=True, padx=5, pady=5)
        
        # Create status labels
        self.status_labels = {}
        status_items = [
            ('GPS Running', 'gps_running'),
            ('Fix Valid', 'fix_valid'),
            ('Latitude', 'latitude'),
            ('Longitude', 'longitude'),
            ('Speed (km/h)', 'speed'),
            ('Satellites', 'satellites'),
            ('HDOP', 'hdop'),
            ('Last Update', 'last_update'),
            ('Data Age', 'data_age')
        ]
        
        for i, (label, key) in enumerate(status_items):
            ttk.Label(status_frame, text=f"{label}:").grid(row=i, column=0, sticky='w', padx=5, pady=2)
            self.status_labels[key] = ttk.Label(status_frame, text="N/A", foreground="gray")
            self.status_labels[key].grid(row=i, column=1, sticky='w', padx=20, pady=2)
        
        # Configure grid weights
        status_frame.columnconfigure(1, weight=1)
    
    def setup_diagnostics_tab(self):
        """Setup diagnostics tab"""
        diag_frame = ttk.LabelFrame(self.diag_frame, text="System Diagnostics", padding=10)
        diag_frame.pack(fill='both', expand=True, padx=5, pady=5)
        
        # Diagnostic buttons
        btn_frame = ttk.Frame(diag_frame)
        btn_frame.pack(fill='x', pady=(0, 10))
        
        ttk.Button(btn_frame, text="Run Diagnostics", 
                  command=self.run_diagnostics).pack(side='left', padx=5)
        ttk.Button(btn_frame, text="Clear Log", 
                  command=self.clear_diagnostics).pack(side='left', padx=5)
        
        # Diagnostic output
        self.diag_text = scrolledtext.ScrolledText(diag_frame, height=20, width=80)
        self.diag_text.pack(fill='both', expand=True)
        
        # Run initial diagnostics
        self.root.after(1000, self.run_diagnostics)
    
    def setup_raw_data_tab(self):
        """Setup raw data tab"""
        raw_frame = ttk.LabelFrame(self.raw_frame, text="Raw NMEA Data", padding=10)
        raw_frame.pack(fill='both', expand=True, padx=5, pady=5)
        
        # Control buttons
        btn_frame = ttk.Frame(raw_frame)
        btn_frame.pack(fill='x', pady=(0, 10))
        
        ttk.Button(btn_frame, text="Refresh", 
                  command=self.refresh_raw_data).pack(side='left', padx=5)
        ttk.Button(btn_frame, text="Clear", 
                  command=self.clear_raw_data).pack(side='left', padx=5)
        
        # Raw data display
        self.raw_text = scrolledtext.ScrolledText(raw_frame, height=20, width=80, 
                                                 font=('Courier', 9))
        self.raw_text.pack(fill='both', expand=True)
    
    def start_gps(self):
        """Start GPS with error handling"""
        if not SERIAL_AVAILABLE:
            messagebox.showerror("Error", 
                               "PySerial is not installed. Please install it with:\n"
                               "pip3 install pyserial")
            return
        
        if self.gps_manager.start_gps():
            messagebox.showinfo("Success", "GPS started successfully!")
        else:
            messagebox.showerror("Error", 
                               "Failed to start GPS. Check diagnostics for details.")
    
    def stop_gps(self):
        """Stop GPS"""
        self.gps_manager.stop_gps()
        messagebox.showinfo("Info", "GPS stopped.")
    
    def restart_gps_service(self):
        """Restart GPS service with confirmation"""
        if messagebox.askyesno("Confirm", 
                              "This will restart GPS services. Continue?"):
            if self.gps_manager.restart_gps_service():
                messagebox.showinfo("Success", 
                                  "GPS service restarted. You may need to restart the application.")
            else:
                messagebox.showerror("Error", "Failed to restart GPS service.")
    
    def enable_serial_interface(self):
        """Enable serial interface with confirmation"""
        if messagebox.askyesno("Confirm", 
                              "This will enable the serial interface and may require a reboot. Continue?"):
            if self.gps_manager.enable_serial_interface():
                messagebox.showinfo("Success", 
                                  "Serial interface enabled. Please reboot your system.")
            else:
                messagebox.showerror("Error", "Failed to enable serial interface.")
    
    def run_diagnostics(self):
        """Run system diagnostics"""
        self.diag_text.delete(1.0, tk.END)
        
        def add_result(test, result, details=""):
            status = "✓ PASS" if result else "✗ FAIL"
            color = "green" if result else "red"
            self.diag_text.insert(tk.END, f"{test}: {status}\n", color)
            if details:
                self.diag_text.insert(tk.END, f"  {details}\n")
            self.diag_text.insert(tk.END, "\n")
        
        # Configure text tags for colors
        self.diag_text.tag_config("green", foreground="green")
        self.diag_text.tag_config("red", foreground="red")
        
        self.diag_text.insert(tk.END, "=== GPS System Diagnostics ===\n\n")
        
        # Check PySerial
        add_result("PySerial Library", SERIAL_AVAILABLE, 
                  "Install with: pip3 install pyserial" if not SERIAL_AVAILABLE else "")
        
        # Check device file
        device_exists = os.path.exists(self.gps_manager.device)
        add_result(f"Device File ({self.gps_manager.device})", device_exists,
                  "Device file not found" if not device_exists else "")
        
        # Check permissions
        has_permissions = self.gps_manager.check_serial_permissions()
        add_result("Device Permissions", has_permissions,
                  "No read/write access to device" if not has_permissions else "")
        
        # Check if running on Raspberry Pi
        is_rpi = os.path.exists('/boot/config.txt')
        add_result("Raspberry Pi Detected", is_rpi,
                  "Not running on Raspberry Pi" if not is_rpi else "")
        
        # Check UART configuration
        uart_enabled = True
        try:
            with open('/boot/config.txt', 'r') as f:
                config = f.read()
                uart_enabled = 'enable_uart=1' in config
        except:
            uart_enabled = False
        
        add_result("UART Enabled", uart_enabled,
                  "Add 'enable_uart=1' to /boot/config.txt" if not uart_enabled else "")
        
        # Check for conflicting services
        gpsd_running = False
        try:
            result = subprocess.run(['pgrep', 'gpsd'], capture_output=True)
            gpsd_running = result.returncode == 0
        except:
            pass
        
        add_result("GPSD Service", not gpsd_running,
                  "GPSD is running and may conflict" if gpsd_running else "GPSD not running (good)")
        
        self.diag_text.insert(tk.END, "=== End Diagnostics ===\n")
        self.diag_text.see(tk.END)
    
    def clear_diagnostics(self):
        """Clear diagnostics text"""
        self.diag_text.delete(1.0, tk.END)
    
    def refresh_raw_data(self):
        """Refresh raw NMEA data display"""
        raw_data = self.gps_manager.get_raw_data()
        self.raw_text.delete(1.0, tk.END)
        
        if not raw_data:
            self.raw_text.insert(tk.END, "No raw data available. Start GPS to see NMEA sentences.\n")
        else:
            for line in raw_data[-50:]:  # Show last 50 lines
                self.raw_text.insert(tk.END, line + "\n")
        
        self.raw_text.see(tk.END)
    
    def clear_raw_data(self):
        """Clear raw data display"""
        self.raw_text.delete(1.0, tk.END)
        with self.gps_manager.lock:
            self.gps_manager.raw_data.clear()
    
    def update_status(self):
        """Update status display"""
        status = self.gps_manager.get_status()
        
        # Update status labels
        self.status_labels['gps_running'].config(
            text="Yes" if status['is_running'] else "No",
            foreground="green" if status['is_running'] else "red"
        )
        
        self.status_labels['fix_valid'].config(
            text="Yes" if status['valid'] else "No",
            foreground="green" if status['valid'] else "red"
        )
        
        if status['lat'] is not None:
            self.status_labels['latitude'].config(
                text=f"{status['lat']:.6f}°", foreground="black"
            )
        else:
            self.status_labels['latitude'].config(text="N/A", foreground="gray")
        
        if status['lon'] is not None:
            self.status_labels['longitude'].config(
                text=f"{status['lon']:.6f}°", foreground="black"
            )
        else:
            self.status_labels['longitude'].config(text="N/A", foreground="gray")
        
        speed_kmh = status['speed_knots'] * 1.852
        self.status_labels['speed'].config(
            text=f"{speed_kmh:.1f}", foreground="black"
        )
        
        self.status_labels['satellites'].config(
            text=str(status['satellites']), 
            foreground="green" if status['satellites'] >= 4 else "orange" if status['satellites'] > 0 else "red"
        )
        
        self.status_labels['hdop'].config(
            text=f"{status['hdop']:.1f}" if status['hdop'] > 0 else "N/A",
            foreground="green" if status['hdop'] < 2 else "orange" if status['hdop'] < 5 else "red"
        )
        
        if status['updated_at'] > 0:
            last_update = datetime.fromtimestamp(status['updated_at']).strftime('%H:%M:%S')
            self.status_labels['last_update'].config(text=last_update, foreground="black")
            
            age = status['age']
            if age < 5:
                age_text = f"{age:.1f}s"
                age_color = "green"
            elif age < 30:
                age_text = f"{age:.0f}s"
                age_color = "orange"
            else:
                age_text = f"{age:.0f}s (stale)"
                age_color = "red"
            
            self.status_labels['data_age'].config(text=age_text, foreground=age_color)
        else:
            self.status_labels['last_update'].config(text="Never", foreground="gray")
            self.status_labels['data_age'].config(text="N/A", foreground="gray")
    
    def start_updates(self):
        """Start periodic updates"""
        self.update_status()
        self.update_timer = self.root.after(1000, self.start_updates)
    
    def run(self):
        """Run the GUI application"""
        try:
            self.root.mainloop()
        finally:
            if self.update_timer:
                self.root.after_cancel(self.update_timer)
            self.gps_manager.stop_gps()


def main():
    """Main entry point"""
    # Check if running as root for some operations
    if os.geteuid() != 0:
        print("Note: Some diagnostic and repair functions require root privileges.")
        print("Run with 'sudo python3 GPS_GUI.py' for full functionality.")
    
    app = GPSGUI()
    app.run()


if __name__ == '__main__':
    main()