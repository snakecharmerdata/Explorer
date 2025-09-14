#!/usr/bin/env python3
"""
GPS Debug Tool - Shows raw NMEA data and satellite information
"""
import serial
import time
import sys

def debug_gps(device='/dev/serial0', baud=9600, duration=30):
    print(f"GPS Debug Tool - Monitoring {device} at {baud} baud")
    print(f"Will monitor for {duration} seconds...")
    print("=" * 60)
    
    try:
        with serial.Serial(device, baud, timeout=1) as ser:
            start_time = time.time()
            line_count = 0
            gga_count = 0
            rmc_count = 0
            satellites_seen = set()
            
            while (time.time() - start_time) < duration:
                try:
                    line = ser.readline().decode('ascii', errors='ignore').strip()
                    if line:
                        line_count += 1
                        timestamp = time.strftime("%H:%M:%S")
                        
                        # Count different sentence types
                        if line.startswith('$GPGGA') or line.startswith('$GNGGA'):
                            gga_count += 1
                            # Parse satellite count from GGA
                            parts = line.split(',')
                            if len(parts) > 7 and parts[7]:
                                sat_count = parts[7]
                                print(f"[{timestamp}] GGA - Satellites: {sat_count}")
                        
                        elif line.startswith('$GPRMC') or line.startswith('$GNRMC'):
                            rmc_count += 1
                            parts = line.split(',')
                            if len(parts) > 2:
                                status = parts[2]
                                if status == 'A':
                                    print(f"[{timestamp}] RMC - GPS FIX ACTIVE!")
                                else:
                                    print(f"[{timestamp}] RMC - No fix (status: {status})")
                        
                        elif line.startswith('$GPGSV') or line.startswith('$GNGSV'):
                            # Satellites in view
                            parts = line.split(',')
                            if len(parts) > 3:
                                total_sats = parts[3] if parts[3] else "0"
                                print(f"[{timestamp}] GSV - Satellites in view: {total_sats}")
                        
                        # Show all raw data for first 10 seconds
                        if (time.time() - start_time) < 10:
                            print(f"[{timestamp}] RAW: {line}")
                        
                except Exception as e:
                    print(f"Error reading line: {e}")
                    continue
            
            print("=" * 60)
            print(f"Summary after {duration} seconds:")
            print(f"Total NMEA sentences: {line_count}")
            print(f"GGA sentences (position): {gga_count}")
            print(f"RMC sentences (recommended minimum): {rmc_count}")
            
            if line_count == 0:
                print("❌ NO GPS DATA RECEIVED - Check hardware connection!")
            elif gga_count == 0 and rmc_count == 0:
                print("⚠️  GPS data received but no position sentences")
            else:
                print("✅ GPS is communicating")
                
    except Exception as e:
        print(f"❌ Error opening GPS device: {e}")
        print("Possible issues:")
        print("- GPS HAT not properly connected")
        print("- Wrong device path")
        print("- Permission issues (try with sudo)")

if __name__ == '__main__':
    print("GPS Hardware Debug Tool")
    print("This will show raw GPS data and help diagnose issues")
    print("Press Ctrl+C to stop early")
    print()
    
    try:
        debug_gps()
    except KeyboardInterrupt:
        print("\nStopped by user")
    except Exception as e:
        print(f"Error: {e}")