#!/usr/bin/env python3
"""
Offline Map Tile Downloader for GPS Application
Downloads OpenStreetMap tiles for offline use
"""
import os
import requests
import math
import time
from pathlib import Path

def deg2num(lat_deg, lon_deg, zoom):
    """Convert lat/lon to tile numbers"""
    lat_rad = math.radians(lat_deg)
    n = 2.0 ** zoom
    xtile = int((lon_deg + 180.0) / 360.0 * n)
    ytile = int((1.0 - math.asinh(math.tan(lat_rad)) / math.pi) / 2.0 * n)
    return (xtile, ytile)

def download_tiles(lat, lon, zoom_levels, radius_km=5):
    """Download tiles for a specific area"""
    
    # Create tiles directory
    tiles_dir = Path("tiles")
    tiles_dir.mkdir(exist_ok=True)
    
    # Calculate tile bounds
    lat_offset = radius_km / 111.0  # Rough km to degrees
    lon_offset = radius_km / (111.0 * math.cos(math.radians(lat)))
    
    north = lat + lat_offset
    south = lat - lat_offset
    east = lon + lon_offset
    west = lon - lon_offset
    
    total_tiles = 0
    downloaded = 0
    
    for zoom in zoom_levels:
        print(f"Downloading zoom level {zoom}...")
        
        # Get tile bounds
        x_min, y_max = deg2num(north, west, zoom)
        x_max, y_min = deg2num(south, east, zoom)
        
        zoom_dir = tiles_dir / str(zoom)
        zoom_dir.mkdir(exist_ok=True)
        
        for x in range(x_min, x_max + 1):
            x_dir = zoom_dir / str(x)
            x_dir.mkdir(exist_ok=True)
            
            for y in range(y_min, y_max + 1):
                tile_path = x_dir / f"{y}.png"
                total_tiles += 1
                
                if tile_path.exists():
                    continue  # Skip if already downloaded
                
                # Download tile
                url = f"https://tile.openstreetmap.org/{zoom}/{x}/{y}.png"
                
                try:
                    response = requests.get(url, timeout=10)
                    if response.status_code == 200:
                        with open(tile_path, 'wb') as f:
                            f.write(response.content)
                        downloaded += 1
                        print(f"Downloaded: {zoom}/{x}/{y}.png")
                    else:
                        print(f"Failed: {zoom}/{x}/{y}.png (HTTP {response.status_code})")
                except Exception as e:
                    print(f"Error downloading {zoom}/{x}/{y}.png: {e}")
                
                # Be nice to the tile server
                time.sleep(0.1)
    
    print(f"\nDownload complete!")
    print(f"Total tiles: {total_tiles}")
    print(f"Downloaded: {downloaded}")
    print(f"Tiles stored in: {tiles_dir.absolute()}")

def create_offline_map_html():
    """Create HTML page that uses local tiles"""
    
    html_content = '''<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>GPS Offline Map</title>
  <link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css" crossorigin=""/>
  <script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js" crossorigin=""></script>
  <style>
    html, body { height: 100%; margin: 0; }
    #map { height: 100%; width: 100%; }
    .pulse-marker {
      background-color: rgba(0, 136, 255, 0.8);
      width: 14px; height: 14px; border-radius: 50%;
      border: 2px solid #fff;
      box-shadow: 0 0 0 rgba(0, 136, 255, 0.7);
      animation: pulse 1.5s infinite;
    }
    @keyframes pulse {
      0% { box-shadow: 0 0 0 0 rgba(0, 136, 255, 0.7); }
      70% { box-shadow: 0 0 0 18px rgba(0, 136, 255, 0); }
      100% { box-shadow: 0 0 0 0 rgba(0, 136, 255, 0); }
    }
    .info {
      position: absolute; top: 10px; left: 10px; z-index: 1000;
      background: rgba(255,255,255,0.9); padding: 8px 12px;
      border-radius: 4px; box-shadow: 0 1px 3px rgba(0,0,0,0.2);
      font-family: sans-serif;
    }
    .bad { color: #b00020; }
    .good { color: #006400; }
  </style>
</head>
<body>
  <div id="map"></div>
  <div class="info" id="info">Offline GPS Map - Waiting for fix…</div>
  <script>
    const map = L.map('map').setView([0,0], 2);
    
    // Use local tile server
    L.tileLayer('/tiles/{z}/{x}/{y}.png', {
      maxZoom: 18,
      attribution: '&copy; OpenStreetMap contributors (Offline)'
    }).addTo(map);
    
    const pulseIcon = L.divIcon({ className: 'pulse-marker' });
    let marker = L.marker([0,0], { icon: pulseIcon }).addTo(map);
    let hasCentered = false;
    
    async function fetchLocation() {
      try {
        const resp = await fetch('/location');
        if (!resp.ok) throw new Error('HTTP ' + resp.status);
        const data = await resp.json();
        const info = document.getElementById('info');
        
        if (data && data.valid && typeof data.lat === 'number' && typeof data.lon === 'number') {
          const latlng = [data.lat, data.lon];
          marker.setLatLng(latlng);
          if (!hasCentered) { map.setView(latlng, 16); hasCentered = true; }
          info.innerHTML = `<span class="good">OFFLINE MAP</span> | Lat: ${data.lat.toFixed(6)} Lon: ${data.lon.toFixed(6)} | Speed: ${data.speed_kmh.toFixed(1)} km/h`;
        } else {
          info.innerHTML = '<span class="bad">NO GPS</span> | Waiting for valid GPS data…';
        }
      } catch (e) {
        console.error(e);
      }
    }
    
    setInterval(fetchLocation, 2000);
    fetchLocation();
  </script>
</body>
</html>'''
    
    with open('offline_map_tiles.html', 'w') as f:
        f.write(html_content)
    
    print("Created offline_map_tiles.html")

def main():
    print("🗺️ Offline Map Tile Downloader")
    print("=" * 40)
    
    # Get location from user
    try:
        lat = float(input("Enter latitude (e.g., 45.5017): "))
        lon = float(input("Enter longitude (e.g., -73.5673): "))
        radius = float(input("Enter radius in km (e.g., 5): ") or "5")
    except ValueError:
        print("Invalid input. Using Montreal, Canada as default.")
        lat, lon, radius = 45.5017, -73.5673, 5
    
    # Download tiles for zoom levels 10-18
    zoom_levels = list(range(10, 19))
    
    print(f"\nDownloading tiles for:")
    print(f"Location: {lat}, {lon}")
    print(f"Radius: {radius} km")
    print(f"Zoom levels: {zoom_levels}")
    print("\nThis may take several minutes...")
    
    download_tiles(lat, lon, zoom_levels, radius)
    create_offline_map_html()
    
    print("\n✅ Setup complete!")
    print("To use offline maps:")
    print("1. Modify your GPS application to serve tiles from /tiles/")
    print("2. Use offline_map_tiles.html instead of the online version")

if __name__ == '__main__':
    main()