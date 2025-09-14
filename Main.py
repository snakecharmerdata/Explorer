#!/usr/bin/env python3
import argparse
import json
import sys
import threading
import time
import math
import webbrowser
import subprocess
import os
import shutil
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Optional

try:
    import requests
    REQUESTS_AVAILABLE = True
except ImportError:
    REQUESTS_AVAILABLE = False

try:
    import tkinter as tk
    from tkinter import ttk, messagebox
    GUI_AVAILABLE = True
except ImportError:
    GUI_AVAILABLE = False

try:
    import serial
except ImportError:
    serial = None

def nmea_to_decimal(coord: str, direction: str) -> Optional[float]:
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

def parse_rmc(line: str):
    if not (line.startswith('$GPRMC') or line.startswith('$GNRMC') or line.startswith('$GCRMC')):
        return None
    try:
        if '*' in line:
            line = line.split('*', 1)[0]
        parts = line.split(',')
        if len(parts) < 12:
            return None
        status = parts[2].upper() if parts[2] else 'V'
        valid = status == 'A'
        lat = nmea_to_decimal(parts[3], parts[4]) if parts[3] and parts[4] else None
        lon = nmea_to_decimal(parts[5], parts[6]) if parts[5] and parts[6] else None
        speed_knots = float(parts[7]) if parts[7] else 0.0
        ts = parts[1] if parts[1] else ''
        return lat, lon, speed_knots, ts, valid
    except Exception:
        return None

def parse_gga(line: str):
    """Parse GGA sentence for altitude, satellite count, and HDOP"""
    if not (line.startswith('$GPGGA') or line.startswith('$GNGGA')):
        return None
    try:
        if '*' in line:
            line = line.split('*', 1)[0]
        parts = line.split(',')
        if len(parts) < 15:
            return None
        
        lat = nmea_to_decimal(parts[2], parts[3]) if parts[2] and parts[3] else None
        lon = nmea_to_decimal(parts[4], parts[5]) if parts[4] and parts[5] else None
        fix_quality = int(parts[6]) if parts[6] else 0
        satellites = int(parts[7]) if parts[7] else 0
        hdop = float(parts[8]) if parts[8] else None
        altitude = float(parts[9]) if parts[9] else None
        altitude_unit = parts[10] if parts[10] else 'M'
        
        return {
            'lat': lat,
            'lon': lon,
            'fix_quality': fix_quality,
            'satellites': satellites,
            'hdop': hdop,
            'altitude': altitude,
            'altitude_unit': altitude_unit
        }
    except Exception:
        return None

def parse_gsa(line: str):
    """Parse GSA sentence for PDOP, HDOP, VDOP and fix type"""
    if not (line.startswith('$GPGSA') or line.startswith('$GNGSA')):
        return None
    try:
        if '*' in line:
            line = line.split('*', 1)[0]
        parts = line.split(',')
        if len(parts) < 18:
            return None
        
        fix_type = int(parts[2]) if parts[2] else 1  # 1=no fix, 2=2D, 3=3D
        pdop = float(parts[15]) if parts[15] else None
        hdop = float(parts[16]) if parts[16] else None
        vdop = float(parts[17]) if parts[17] else None
        
        # Satellite IDs (positions 3-14)
        satellite_ids = []
        for i in range(3, 15):
            if parts[i]:
                satellite_ids.append(int(parts[i]))
        
        return {
            'fix_type': fix_type,
            'pdop': pdop,
            'hdop': hdop,
            'vdop': vdop,
            'satellite_ids': satellite_ids
        }
    except Exception:
        return None

class GPSReader(threading.Thread):
    def __init__(self, device: str, baud: int, simulate: bool = False):
        super().__init__(daemon=True)
        self.device = device
        self.baud = baud
        self.simulate = simulate
        self._stop_event = threading.Event()
        self._lock = threading.Lock()
        self._last_fix = {
            'lat': None,
            'lon': None,
            'speed_knots': 0.0,
            'timestamp': None,
            'valid': False,
            'updated_at': 0.0,
        }
        self._ser = None

    def open_serial(self):
        if self.simulate:
            return None
        if serial is None:
            raise RuntimeError('pyserial is not installed. Install with: pip3 install pyserial')
        try:
            ser = serial.Serial(self.device, self.baud, timeout=1)
            return ser
        except Exception as e:
            raise RuntimeError(f'Failed to open serial device {self.device} @ {self.baud}: {e}')

    def run(self):
        if self.simulate:
            self._run_simulation()
            return
        try:
            self._ser = self.open_serial()
        except Exception as e:
            sys.stderr.write(str(e) + '\n')
            return

        with self._ser as ser:
            while not self._stop_event.is_set():
                try:
                    line = ser.readline().decode(errors='ignore').strip()
                except Exception:
                    line = ''
                if not line:
                    continue
                parsed = parse_rmc(line)
                if parsed:
                    lat, lon, speed_knots, ts, valid = parsed
                    with self._lock:
                        if lat is not None and lon is not None:
                            self._last_fix['lat'] = lat
                            self._last_fix['lon'] = lon
                        self._last_fix['speed_knots'] = speed_knots
                        self._last_fix['timestamp'] = ts
                        self._last_fix['valid'] = bool(valid and lat is not None and lon is not None)
                        self._last_fix['updated_at'] = time.time()

    def _run_simulation(self):
        # Montreal, Canada coordinates
        lat0, lon0 = 45.5017, -73.5673
        t0 = time.time()
        while not self._stop_event.is_set():
            t = time.time() - t0
            lat = lat0 + 0.0005 * math.sin(t / 10.0)
            lon = lon0 + 0.0005 * math.cos(t / 10.0)
            with self._lock:
                self._last_fix['lat'] = lat
                self._last_fix['lon'] = lon
                self._last_fix['speed_knots'] = 0.5
                self._last_fix['timestamp'] = time.strftime('%H%M%S', time.gmtime())
                self._last_fix['valid'] = True
                self._last_fix['updated_at'] = time.time()
            time.sleep(1.0)

    def stop(self):
        self._stop_event.set()

    def get_fix(self):
        with self._lock:
            return dict(self._last_fix)

HTML_PAGE = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>GPS Live Map</title>
  <link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css" integrity="sha256-p4NxAoJBhIIN+hmNHrzRCf9tD/miZyoHS5obTRR9BMY=" crossorigin=""/>
  <script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js" integrity="sha256-20nQCchB9co0qIjJZRGuk2/Z9VM+kNiyxNV1lvTlZBo=" crossorigin=""></script>
  <style>
    html, body { height: 100%; margin: 0; }
    #map { height: 100%; width: 100%; }
    .pulse-marker {
      background-color: rgba(0, 136, 255, 0.8);
      width: 14px;
      height: 14px;
      border-radius: 50%;
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
      position: absolute; top: 10px; left: 10px; z-index: 1000; background: rgba(255,255,255,0.9);
      padding: 8px 12px; border-radius: 4px; box-shadow: 0 1px 3px rgba(0,0,0,0.2); font-family: sans-serif;
    }
    .bad { color: #b00020; }
    .good { color: #006400; }
  </style>
</head>
<body>
  <div id="map"></div>
  <div class="info" id="info">Waiting for GPS fix…</div>
  <script>
    const map = L.map('map').setView([0,0], 2);
    L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
      maxZoom: 19,
      attribution: '&copy; OpenStreetMap contributors'
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
          info.innerHTML = `Fix: <span class="good">OK</span> | Lat: ${data.lat.toFixed(6)} Lon: ${data.lon.toFixed(6)} | Speed: ${data.speed_kmh.toFixed(1)} km/h | Updated: ${new Date(data.updated_at * 1000).toLocaleTimeString()}`;
        } else {
          info.innerHTML = 'Fix: <span class="bad">NO</span> | Waiting for valid GPS data…';
        }
      } catch (e) {
        console.error(e);
      }
    }
    setInterval(fetchLocation, 2000);
    fetchLocation();
  </script>
</body>
</html>"""

OFFLINE_HTML_PAGE = """<!doctype html>
<html lang=\"en\">
<head>
  <meta charset=\"utf-8\">
  <meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">
  <title>GPS Offline Map</title>
  <link rel=\"stylesheet\" href=\"/static/leaflet/leaflet.css\"/>
  <script src=\"/static/leaflet/leaflet.js\"></script>
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
  <div id=\"map\"></div>
  <div class=\"info\" id=\"info\">Offline Map - Waiting for GPS fix…</div>
  <script>
    const map = L.map('map').setView([0,0], 2);
    L.tileLayer('/tiles/{z}/{x}/{y}.png', {
      maxZoom: 18,
      attribution: '&copy; OpenStreetMap contributors (Offline)'
    }).addTo(map);
    let initiallyCentered = false;
    // If bbox provided in URL, center map to that extent
    try {
      const params = new URLSearchParams(location.search);
      const bboxParam = params.get('bbox');
      if (bboxParam) {
        const parts = bboxParam.split(',').map(parseFloat);
        if (parts.length === 4 && parts.every(p => !isNaN(p))) {
          const bounds = L.latLngBounds([parts[1], parts[0]], [parts[3], parts[2]]);
          map.fitBounds(bounds);
          initiallyCentered = true;
        }
      }
    } catch (e) {}
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
          if (!hasCentered && !initiallyCentered) { map.setView(latlng, 16); hasCentered = true; }
          info.innerHTML = `Offline | Lat: ${data.lat.toFixed(6)} Lon: ${data.lon.toFixed(6)} | Speed: ${data.speed_kmh.toFixed(1)} km/h`;
        } else {
          info.innerHTML = 'Offline | <span class="bad">NO FIX</span> | Waiting for valid GPS data…';
        }
      } catch (e) { console.error(e); }
    }
    setInterval(fetchLocation, 2000);
    fetchLocation();
  </script>
</body>
</html>"""

SELECTION_HTML_PAGE = """<!doctype html>
<html lang=\"en\">
<head>
  <meta charset=\"utf-8\">
  <meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">
  <title>Select Area for Offline Maps</title>
  <link rel=\"stylesheet\" href=\"/static/leaflet/leaflet.css\"/>
  <link rel=\"stylesheet\" href=\"/static/leaflet-draw/leaflet.draw.css\"/>
  <script src=\"/static/leaflet/leaflet.js\"></script>
  <script src=\"/static/leaflet-draw/leaflet.draw.js\"></script>
  <style>
    html, body { height: 100%; margin: 0; }
    #map { height: 100%; width: 100%; }
    .panel {
      position: absolute; top: 10px; left: 10px; z-index: 1000;
      background: rgba(255,255,255,0.95); padding: 10px; border-radius: 6px; font-family: sans-serif;
      box-shadow: 0 1px 3px rgba(0,0,0,0.2);
      max-width: 420px;
    }
    .row { display: flex; gap: 6px; margin: 4px 0; align-items: center; }
    input[type=text] { padding: 6px; font-size: 13px; width: 220px; }
    button { padding: 6px 10px; font-size: 13px; cursor: pointer; }
    .small { font-size: 12px; color: #333; }
    .mono { font-family: monospace; }
    .ok { color: #006400; }
    .bad { color: #b00020; }
    .grid { display: grid; grid-template-columns: auto auto auto auto auto; gap: 6px; margin-top: 6px; }
    .list { margin-top: 6px; max-height: 120px; overflow: auto; font-size: 12px; }
  </style>
</head>
<body>
  <div id=\"map\"></div>
  <div class=\"panel\">
    <div class=\"row\">
      <b>Area name:</b>
      <input id=\"areaName\" type=\"text\" placeholder=\"e.g., Zion National Park\"/>
      <button onclick=\"saveArea()\">Save</button>
      <button onclick=\"deleteArea()\">Delete</button>
    </div>
    <div class=\"row\">
      <b>City lookup:</b>
      <input id=\"city\" type=\"text\" placeholder=\"City, Country\"/>
      <button onclick=\"geocodeCity()\">Find</button>
    </div>
    <div class=\"small\">Draw a rectangle on the map (use the rectangle tool on the left).</div>
    <div class=\"row small\">
      <b>Selected bbox:</b>
      <span id=\"bbox\" class=\"mono\">(none)</span>
    </div>
    <div class=\"row small\">
      <b>Approx area:</b>
      <span id=\"area\">0.0</span> km²
    </div>
    <div class=\"small\"><b>Zooms:</b> <span class=\"small\">(higher zoom = more detail, more tiles)</span></div>
    <div class=\"grid\">
      <label><input type=\"checkbox\" class=\"z\" value=\"12\" checked/> z12</label>
      <label><input type=\"checkbox\" class=\"z\" value=\"13\" checked/> z13</label>
      <label><input type=\"checkbox\" class=\"z\" value=\"14\" checked/> z14</label>
      <label><input type=\"checkbox\" class=\"z\" value=\"15\" checked/> z15</label>
      <label><input type=\"checkbox\" class=\"z\" value=\"16\" checked/> z16</label>
    </div>
    <div class=\"row\" style=\"margin-top:6px\">
      <button onclick=\"downloadArea()\">Download this area</button>
      <span id=\"status\" class=\"small\"></span>
    </div>
    <div class=\"row small\"><b>Saved areas:</b></div>
    <div id=\"areas\" class=\"list\"></div>
  </div>

  <script>
    let map = L.map('map').setView([20,0], 2);
    L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', { maxZoom: 19 }).addTo(map);

    // Draw controls
    const drawControl = new L.Control.Draw({
      draw: { rectangle: true, polygon: false, polyline: false, circle: false, marker: false, circlemarker: false },
      edit: false
    });
    map.addControl(drawControl);

    // Right-click and drag to draw rectangle quickly
    let rightDrag = { active: false, start: null, layer: null };
    // Suppress context menu on the map container
    map.whenReady(() => {
      map.getContainer().addEventListener('contextmenu', (e) => e.preventDefault());
    });
    map.on('mousedown', function(e) {
      if (e.originalEvent && e.originalEvent.button === 2) { // right mouse button
        rightDrag.active = true;
        rightDrag.start = e.latlng;
        if (rightDrag.layer) { try { map.removeLayer(rightDrag.layer); } catch(_){} rightDrag.layer = null; }
        // prevent map panning while right-dragging
        map.dragging.disable();
      }
    });
    map.on('mousemove', function(e) {
      if (rightDrag.active && rightDrag.start) {
        const bounds = L.latLngBounds(rightDrag.start, e.latlng);
        if (!rightDrag.layer) {
          rightDrag.layer = L.rectangle(bounds, {color:'#3388ff', weight:2});
          rightDrag.layer.addTo(map);
        } else {
          rightDrag.layer.setBounds(bounds);
        }
      }
    });
    map.on('mouseup', function(e) {
      if (rightDrag.active) {
        rightDrag.active = false;
        map.dragging.enable();
        if (rightDrag.layer) {
          const b = rightDrag.layer.getBounds();
          bbox = [b.getWest(), b.getSouth(), b.getEast(), b.getNorth()];
          document.getElementById('bbox').textContent = bbox.map(v => v.toFixed(5)).join(', ');
          const kmPerDeg = 111.0;
          const w = Math.abs(bbox[2]-bbox[0]) * kmPerDeg * Math.cos((bbox[1]+bbox[3])*Math.PI/360);
          const h = Math.abs(bbox[3]-bbox[1]) * kmPerDeg;
          document.getElementById('area').textContent = (w*h).toFixed(1);
          if (window._rectLayer) { try { map.removeLayer(window._rectLayer); } catch(_){} }
          window._rectLayer = rightDrag.layer; // promote to the main selection layer
          rightDrag.layer = null;
        }
      }
    });

    let bbox = null; // [minLon, minLat, maxLon, maxLat]

    map.on(L.Draw.Event.CREATED, function (e) {
      if (window._rectLayer) { map.removeLayer(window._rectLayer); }
      window._rectLayer = e.layer.addTo(map);
      const b = e.layer.getBounds();
      bbox = [b.getWest(), b.getSouth(), b.getEast(), b.getNorth()];
      document.getElementById('bbox').textContent = bbox.map(v => v.toFixed(5)).join(', ');
      // rough area estimate (km²)
      const kmPerDeg = 111.0;
      const w = Math.abs(bbox[2]-bbox[0]) * kmPerDeg * Math.cos((bbox[1]+bbox[3])*Math.PI/360);
      const h = Math.abs(bbox[3]-bbox[1]) * kmPerDeg;
      document.getElementById('area').textContent = (w*h).toFixed(1);
    });

    async function geocodeCity() {
      const q = document.getElementById('city').value.trim();
      if (!q) return;
      setStatus('Looking up city...');
      try {
        const r = await fetch('/api/geocode?q=' + encodeURIComponent(q));
        const j = await r.json();
        if (j && j.lat && j.lon) {
          map.setView([j.lat, j.lon], 11);
          setStatus('Centered on ' + (j.display||q));
        } else {
          setStatus('No result', true);
        }
      } catch(e) { setStatus('Geocode error', true); }
    }

    async function listAreas() {
      try {
        const r = await fetch('/api/list_areas');
        const j = await r.json();
        const el = document.getElementById('areas');
        if (!j.areas || j.areas.length === 0) { el.innerHTML = '(none)'; return; }
        el.innerHTML = j.areas.map(a => `<div><b>${a.name}</b> — z:[${a.zooms.join(',')}] bbox: <span class=\"mono\">${a.bbox.map(v=>v.toFixed(4)).join(', ')}</span></div>`).join('');
      } catch(e) {}
    }

    async function downloadArea() {
      if (!bbox) { setStatus('Draw a rectangle first', true); return; }
      const zs = Array.from(document.querySelectorAll('.z:checked')).map(x => parseInt(x.value,10));
      if (zs.length === 0) { setStatus('Select at least one zoom', true); return; }
      setStatus('Downloading tiles...');
      try {
        const r = await fetch('/api/download_tiles', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ bbox: bbox, zooms: zs, name: document.getElementById('areaName').value.trim() }) });
        const j = await r.json();
        if (r.ok) {
          setStatus(`Done. Total tiles: ${j.total}, downloaded: ${j.downloaded}`, false);
          listAreas();
        } else {
          setStatus('Download failed: ' + (j.error||r.status), true);
        }
      } catch(e) { setStatus('Error: ' + e, true); }
    }

    async function saveArea() {
      if (!bbox) { setStatus('Draw a rectangle first', true); return; }
      const name = document.getElementById('areaName').value.trim();
      if (!name) { setStatus('Enter area name', true); return; }
      const zs = Array.from(document.querySelectorAll('.z:checked')).map(x => parseInt(x.value,10));
      try {
        const r = await fetch('/api/save_area', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ name: name, bbox: bbox, zooms: zs }) });
        const j = await r.json();
        if (r.ok) { setStatus('Saved'); listAreas(); } else { setStatus('Save failed', true); }
      } catch(e) { setStatus('Save error', true); }
    }

    async function deleteArea() {
      const name = document.getElementById('areaName').value.trim();
      if (!name) { setStatus('Enter area name', true); return; }
      try {
        const r = await fetch('/api/delete_area', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ name: name }) });
        const j = await r.json();
        if (r.ok) { setStatus('Deleted'); listAreas(); } else { setStatus('Delete failed', true); }
      } catch(e) { setStatus('Delete error', true); }
    }

    function setStatus(msg, bad) {
      const el = document.getElementById('status'); el.textContent = msg; el.className = 'small ' + (bad ? 'bad' : 'ok');
    }

    listAreas();
  </script>
</body>
</html>"""

# Module helpers for selection page and APIs

def ensure_static_assets():
    try:
        static_leaflet = os.path.join(os.getcwd(), 'static', 'leaflet')
        static_draw = os.path.join(os.getcwd(), 'static', 'leaflet-draw')
        os.makedirs(static_leaflet, exist_ok=True)
        os.makedirs(static_draw, exist_ok=True)
        files = [
            (os.path.join(static_leaflet, 'leaflet.js'), 'https://unpkg.com/leaflet@1.9.4/dist/leaflet.js'),
            (os.path.join(static_leaflet, 'leaflet.css'), 'https://unpkg.com/leaflet@1.9.4/dist/leaflet.css'),
            (os.path.join(static_draw, 'leaflet.draw.js'), 'https://unpkg.com/leaflet-draw@1.0.4/dist/leaflet.draw.js'),
            (os.path.join(static_draw, 'leaflet.draw.css'), 'https://unpkg.com/leaflet-draw@1.0.4/dist/leaflet.draw.css'),
        ]
        for path, url in files:
            if not os.path.exists(path):
                if not REQUESTS_AVAILABLE:
                    continue
                r = requests.get(url, timeout=20)
                if r.status_code == 200:
                    with open(path, 'wb') as f:
                        f.write(r.content)
    except Exception:
        pass


def geocode_city(city: str):
    if not REQUESTS_AVAILABLE:
        return None
    try:
        url = "https://nominatim.openstreetmap.org/search"
        params = { 'q': city, 'format': 'json', 'limit': 1, 'addressdetails': 1 }
        headers = { 'User-Agent': 'GPS-Assistant/1.0' }
        r = requests.get(url, params=params, headers=headers, timeout=10)
        j = r.json()
        if j:
            return { 'lat': float(j[0]['lat']), 'lon': float(j[0]['lon']), 'display': j[0].get('display_name', city) }
        return None
    except Exception:
        return None


def download_tiles_bbox(bbox, zoom_levels):
    """Download tiles for a bbox [minLon, minLat, maxLon, maxLat]. Returns (total, downloaded)."""
    if not REQUESTS_AVAILABLE:
        raise RuntimeError('requests not available')
    import math, time as _time
    def deg2num(lat_deg, lon_deg, zoom):
        lat_rad = math.radians(lat_deg)
        n = 2.0 ** zoom
        xtile = int((lon_deg + 180.0) / 360.0 * n)
        ytile = int((1.0 - math.asinh(math.tan(lat_rad)) / math.pi) / 2.0 * n)
        return (xtile, ytile)
    minLon, minLat, maxLon, maxLat = bbox
    tiles_root = os.path.join(os.getcwd(), 'tiles')
    os.makedirs(tiles_root, exist_ok=True)
    headers = {'User-Agent': 'L76X-Offgrid-Importer/1.0'}
    total = 0
    downloaded = 0
    for z in zoom_levels:
        x_min, y_max = deg2num(maxLat, minLon, z)
        x_max, y_min = deg2num(minLat, maxLon, z)
        for x in range(min(x_min, x_max), max(x_min, x_max) + 1):
            for y in range(min(y_min, y_max), max(y_min, y_max) + 1):
                total += 1
                out_dir = os.path.join(tiles_root, str(z), str(x))
                os.makedirs(out_dir, exist_ok=True)
                out_path = os.path.join(out_dir, f"{y}.png")
                if os.path.exists(out_path):
                    continue
                url = f"https://tile.openstreetmap.org/{z}/{x}/{y}.png"
                try:
                    r = requests.get(url, headers=headers, timeout=15)
                    if r.status_code == 200:
                        with open(out_path, 'wb') as f:
                            f.write(r.content)
                        downloaded += 1
                    else:
                        with open(out_path, 'wb') as f:
                            f.write(b'')
                except Exception:
                    _time.sleep(0.2)
                    continue
                _time.sleep(0.05)
    return total, downloaded

# Saved areas management
AREAS_FILE = os.path.join(os.getcwd(), 'tiles', 'saved_areas.json')

def _load_areas():
    """Load saved areas from JSON, accepting both list and {areas:[...]} formats."""
    try:
        if os.path.exists(AREAS_FILE):
            with open(AREAS_FILE, 'r', encoding='utf-8') as f:
                data = json.load(f)
                if isinstance(data, list):
                    return data
                if isinstance(data, dict) and isinstance(data.get('areas'), list):
                    return data.get('areas')
    except Exception:
        pass
    return []

def _save_areas(data):
    try:
        os.makedirs(os.path.dirname(AREAS_FILE), exist_ok=True)
        with open(AREAS_FILE, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        return True
    except Exception:
        return False

class RequestHandler(BaseHTTPRequestHandler):
    server_version = "GPSMap/1.0"

    def _send_json(self, data: dict, status: int = 200):
        body = json.dumps(data).encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_html(self, html: str, status: int = 200):
        body = html.encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type', 'text/html; charset=utf-8')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_file(self, file_path: str, mime: str = 'application/octet-stream', status: int = 200):
        try:
            with open(file_path, 'rb') as f:
                data = f.read()
            self.send_response(status)
            self.send_header('Content-Type', mime)
            self.send_header('Content-Length', str(len(data)))
            self.end_headers()
            self.wfile.write(data)
        except FileNotFoundError:
            self._send_json({'error': 'File not found'}, status=404)
        except Exception as e:
            self._send_json({'error': f'Failed to serve file: {e}'}, status=500)

    def do_GET(self):
        # Main online map
        if self.path == '/' or self.path.startswith('/index'):
            return self._send_html(HTML_PAGE)
        # Offline map page
        elif self.path.startswith('/offline'):
            return self._send_html(OFFLINE_HTML_PAGE)
        elif self.path.startswith('/select'):
            try:
                ensure_static_assets()
            except Exception:
                pass
            return self._send_html(SELECTION_HTML_PAGE)
        # GPS location API
        elif self.path.startswith('/location'):
            gps_reader: GPSReader = getattr(self.server, 'gps_reader', None)
            if gps_reader is None:
                return self._send_json({'error': 'GPS reader not available'}, status=503)
            fix = gps_reader.get_fix()
            stale = (time.time() - (fix.get('updated_at') or 0)) > 10
            lat = fix.get('lat')
            lon = fix.get('lon')
            speed_knots = fix.get('speed_knots') or 0.0
            speed_kmh = speed_knots * 1.852
            data = {
                'lat': lat,
                'lon': lon,
                'speed_knots': speed_knots,
                'speed_kmh': speed_kmh,
                'timestamp': fix.get('timestamp'),
                'valid': bool(fix.get('valid') and not stale and lat is not None and lon is not None),
                'updated_at': fix.get('updated_at') or 0.0,
            }
            return self._send_json(data)
        # Serve local tiles
        elif self.path.startswith('/tiles/'):
            safe_path = self.path.replace('..', '')
            local_path = os.path.join(os.getcwd(), safe_path.lstrip('/'))
            return self._send_file(local_path, mime='image/png')
        # Serve static assets (Leaflet)
        elif self.path.startswith('/static/'):
            safe_path = self.path.replace('..', '')
            local_path = os.path.join(os.getcwd(), safe_path.lstrip('/'))
            mime = 'application/octet-stream'
            if local_path.endswith('.js'):
                mime = 'application/javascript'
            elif local_path.endswith('.css'):
                mime = 'text/css'
            elif local_path.endswith('.png'):
                mime = 'image/png'
            return self._send_file(local_path, mime=mime)
        # API: geocode
        elif self.path.startswith('/api/geocode'):
            qs = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            q = (qs.get('q') or qs.get('city') or [''])[0]
            if not q:
                return self._send_json({'error': 'missing q'}, status=400)
            res = geocode_city(q)
            if res:
                return self._send_json(res)
            else:
                return self._send_json({'error': 'not found'}, status=404)
        # API: list saved areas
        elif self.path.startswith('/api/list_areas'):
            areas = _load_areas()
            return self._send_json({'areas': areas})
        else:
            return self._send_json({'error': 'Not found'}, status=404)

    def do_POST(self):
        cl = int(self.headers.get('Content-Length', '0') or '0')
        raw = self.rfile.read(cl).decode('utf-8') if cl > 0 else '{}'
        try:
            body = json.loads(raw)
        except Exception:
            body = {}
        # Save area
        if self.path == '/api/save_area':
            name = (body.get('name') or '').strip()
            bbox = body.get('bbox')
            zooms = body.get('zooms') or []
            if not name or not bbox or not isinstance(zooms, list):
                return self._send_json({'error': 'invalid payload'}, status=400)
            areas = _load_areas()
            # Update if exists
            existing = [a for a in areas if a.get('name') == name]
            if existing:
                for a in areas:
                    if a.get('name') == name:
                        a['bbox'] = bbox
                        a['zooms'] = zooms
                        a['updated_at'] = time.strftime('%Y-%m-%d %H:%M:%S')
            else:
                areas.append({ 'name': name, 'bbox': bbox, 'zooms': zooms, 'created_at': time.strftime('%Y-%m-%d %H:%M:%S') })
            if _save_areas(areas):
                return self._send_json({'ok': True})
            else:
                return self._send_json({'error': 'failed to save'}, status=500)
        # Delete area
        elif self.path == '/api/delete_area':
            name = (body.get('name') or '').strip()
            if not name:
                return self._send_json({'error': 'missing name'}, status=400)
            areas = _load_areas()
            areas = [a for a in areas if a.get('name') != name]
            if _save_areas(areas):
                return self._send_json({'ok': True})
            else:
                return self._send_json({'error': 'failed to save'}, status=500)
        # Download tiles for bbox
        elif self.path == '/api/download_tiles':
            bbox = body.get('bbox')
            zooms = body.get('zooms') or []
            name = (body.get('name') or '').strip()
            if not bbox or not isinstance(zooms, list) or len(zooms) == 0:
                return self._send_json({'error': 'invalid payload'}, status=400)
            try:
                total, downloaded = download_tiles_bbox(bbox, zooms)
                # Record import to manifest
                try:
                    tiles_dir = os.path.join(os.getcwd(), 'tiles')
                    os.makedirs(tiles_dir, exist_ok=True)
                    log_path = os.path.join(tiles_dir, 'manifest.log')
                    rec = {
                        'time': time.strftime('%Y-%m-%d %H:%M:%S'),
                        'name': name or 'bbox',
                        'bbox': bbox,
                        'zooms': zooms,
                    }
                    with open(log_path, 'a', encoding='utf-8') as f:
                        f.write(json.dumps(rec) + "\n")
                except Exception:
                    pass
                return self._send_json({'ok': True, 'total': total, 'downloaded': downloaded})
            except Exception as e:
                return self._send_json({'error': str(e)}, status=500)
        else:
            return self._send_json({'error': 'Not found'}, status=404)

    def log_message(self, format, *args):
        sys.stdout.write("%s - - [%s] %s\n" % (self.address_string(), time.strftime("%d/%b/%Y %H:%M:%S"), format % args))


class GPSGUI:
    """GUI for GPS control and monitoring"""
    
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("GPS Waveshare L76X HAT - Live Map Controller")
        self.root.geometry("600x500")
        self.root.resizable(True, True)
        
        # GPS and server components
        self.gps_reader = None
        self.server = None
        self.server_thread = None
        self.is_running = False
        
        # Configuration
        self.device = '/dev/ttyAMA0'  # Fixed: L76X HAT uses ttyAMA0, not serial0
        self.baud = 9600
        self.host = 'localhost'
        self.port = 5000
        self.simulate = False
        
        self.setup_ui()
        self.start_status_updates()
    
    def setup_ui(self):
        """Setup the user interface"""
        # Main frame
        main_frame = ttk.Frame(self.root, padding="10")
        main_frame.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))
        
        # Title
        title_label = ttk.Label(main_frame, text="GPS Waveshare L76X HAT Controller", 
                               font=('Arial', 16, 'bold'))
        title_label.grid(row=0, column=0, columnspan=2, pady=(0, 20))
        
        # Configuration frame
        config_frame = ttk.LabelFrame(main_frame, text="Configuration", padding="10")
        config_frame.grid(row=1, column=0, columnspan=2, sticky=(tk.W, tk.E), pady=(0, 10))
        
        # Device settings
        ttk.Label(config_frame, text="GPS Device:").grid(row=0, column=0, sticky=tk.W, padx=(0, 10))
        self.device_var = tk.StringVar(value=self.device)
        device_entry = ttk.Entry(config_frame, textvariable=self.device_var, width=20)
        device_entry.grid(row=0, column=1, sticky=(tk.W, tk.E), padx=(0, 20))
        
        ttk.Label(config_frame, text="Baud Rate:").grid(row=0, column=2, sticky=tk.W, padx=(0, 10))
        self.baud_var = tk.StringVar(value=str(self.baud))
        baud_entry = ttk.Entry(config_frame, textvariable=self.baud_var, width=10)
        baud_entry.grid(row=0, column=3, sticky=tk.W)
        
        # Port settings
        ttk.Label(config_frame, text="Web Port:").grid(row=1, column=0, sticky=tk.W, padx=(0, 10))
        self.port_var = tk.StringVar(value=str(self.port))
        port_entry = ttk.Entry(config_frame, textvariable=self.port_var, width=10)
        port_entry.grid(row=1, column=1, sticky=tk.W, padx=(0, 20))
        
        # Simulation mode
        self.simulate_var = tk.BooleanVar()
        simulate_check = ttk.Checkbutton(config_frame, text="Simulation Mode", 
                                        variable=self.simulate_var)
        simulate_check.grid(row=1, column=2, columnspan=2, sticky=tk.W, padx=(0, 10))
        
        # City assistance field
        ttk.Label(config_frame, text="City for GPS Assist:").grid(row=2, column=0, sticky=tk.W, padx=(0, 10))
        self.city_var = tk.StringVar(value="")  # Empty by default - users enter manually
        city_entry = ttk.Entry(config_frame, textvariable=self.city_var, width=30)
        city_entry.grid(row=2, column=1, columnspan=2, sticky=(tk.W, tk.E), padx=(0, 20))
        
        # Help text
        help_label = ttk.Label(config_frame, text="(e.g., Tokyo, Japan or New York, USA)", 
                              font=('Arial', 8), foreground="gray")
        help_label.grid(row=2, column=3, sticky=tk.W)
        
        # Control buttons frame
        control_frame = ttk.LabelFrame(main_frame, text="GPS Control", padding="10")
        control_frame.grid(row=2, column=0, columnspan=2, sticky=(tk.W, tk.E), pady=(0, 10))
        
        # Control buttons
        self.start_btn = ttk.Button(control_frame, text="Start GPS & Server", 
                                   command=self.start_gps_server)
        self.start_btn.grid(row=0, column=0, padx=(0, 10), pady=5)
        
        self.stop_btn = ttk.Button(control_frame, text="Stop GPS & Server", 
                                  command=self.stop_gps_server, state="disabled")
        self.stop_btn.grid(row=0, column=1, padx=(0, 10), pady=5)
        
        self.open_map_btn = ttk.Button(control_frame, text="Open Live Map", 
                                      command=self.open_map, state="disabled")
        self.open_map_btn.grid(row=0, column=2, padx=(0, 10), pady=5)
        
        # Emergency stop button (always enabled)
        self.force_stop_btn = ttk.Button(control_frame, text="Force Stop All", 
                                        command=self.force_stop_all)
        self.force_stop_btn.grid(row=0, column=3, padx=(0, 10), pady=5)
        
        # Offline import (area selector)
        self.offline_import_btn = ttk.Button(control_frame, text="Offline Import", 
                                            command=self.open_area_selector)
        self.offline_import_btn.grid(row=0, column=4, padx=(0, 10), pady=5)
        
        # Load saved map dialog
        self.load_saved_btn = ttk.Button(control_frame, text="Load Saved Map", 
                                         command=self.open_saved_map_dialog_listbox)
        self.load_saved_btn.grid(row=0, column=5, padx=(0, 10), pady=5)
        
        # Diagnostic buttons
        diag_btn = ttk.Button(control_frame, text="Run Diagnostics", 
                             command=self.run_diagnostics)
        diag_btn.grid(row=1, column=0, padx=(0, 10), pady=5)
        
        restart_btn = ttk.Button(control_frame, text="Restart GPS Service", 
                               command=self.restart_gps_service)
        restart_btn.grid(row=1, column=1, padx=(0, 10), pady=5)
        
        # GPS Assistance buttons
        assist_btn = ttk.Button(control_frame, text="GPS Assist (A-GPS)", 
                               command=self.gps_assist)
        assist_btn.grid(row=1, column=2, padx=(0, 10), pady=5)
        
        status_btn = ttk.Button(control_frame, text="Check GPS Status", 
                               command=self.check_gps_status)
        status_btn.grid(row=2, column=0, padx=(0, 10), pady=5)
        
        raw_data_btn = ttk.Button(control_frame, text="Show Raw GPS Data", 
                                 command=self.show_raw_gps_data)
        raw_data_btn.grid(row=2, column=1, padx=(0, 10), pady=5)
        
        # Instructions button
        instructions_btn = ttk.Button(control_frame, text="📖 Instructions (Updated)", 
                                     command=self.show_instructions)
        instructions_btn.grid(row=2, column=2, padx=(0, 10), pady=5)
        
        # Offline maps panel removed per new workflow
        
        # Status frame
        status_frame = ttk.LabelFrame(main_frame, text="GPS Status", padding="10")
        status_frame.grid(row=3, column=0, columnspan=2, sticky=(tk.W, tk.E), pady=(0, 10))
        
        # Status labels
        self.status_labels = {}
        status_items = [
            ('Server Status:', 'server_status'),
            ('GPS Status:', 'gps_status'),
            ('GPS Fix:', 'gps_fix'),
            ('Latitude:', 'latitude'),
            ('Longitude:', 'longitude'),
            ('Speed (km/h):', 'speed'),
            ('Last Update:', 'last_update')
        ]
        
        for i, (label, key) in enumerate(status_items):
            ttk.Label(status_frame, text=label).grid(row=i, column=0, sticky=tk.W, padx=(0, 10))
            self.status_labels[key] = ttk.Label(status_frame, text="N/A", foreground="gray")
            self.status_labels[key].grid(row=i, column=1, sticky=tk.W)
        
        # Log frame
        log_frame = ttk.LabelFrame(main_frame, text="System Log", padding="10")
        log_frame.grid(row=4, column=0, columnspan=2, sticky=(tk.W, tk.E, tk.N, tk.S), pady=(0, 10))
        
        # Log text area
        self.log_text = tk.Text(log_frame, height=8, width=70, wrap=tk.WORD)
        log_scrollbar = ttk.Scrollbar(log_frame, orient="vertical", command=self.log_text.yview)
        self.log_text.configure(yscrollcommand=log_scrollbar.set)
        
        self.log_text.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))
        log_scrollbar.grid(row=0, column=1, sticky=(tk.N, tk.S))
        
        # Configure grid weights
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(0, weight=1)
        main_frame.columnconfigure(1, weight=1)
        main_frame.rowconfigure(4, weight=1)
        config_frame.columnconfigure(1, weight=1)
        log_frame.columnconfigure(0, weight=1)
        log_frame.rowconfigure(0, weight=1)
        
        self.log("GPS Controller initialized. Ready to start.")
        # Offline cache init removed per new workflow
    
    def log(self, message):
        """Add message to log"""
        timestamp = time.strftime("%H:%M:%S")
        self.log_text.insert(tk.END, f"[{timestamp}] {message}\n")
        self.log_text.see(tk.END)
        self.root.update_idletasks()
    
    def start_gps_server(self):
        """Start GPS reader and web server"""
        if self.is_running:
            return
        
        try:
            # Get configuration values
            self.device = self.device_var.get()
            self.baud = int(self.baud_var.get())
            self.port = int(self.port_var.get())
            self.simulate = self.simulate_var.get()
            
            self.log(f"Starting GPS reader (Device: {self.device}, Baud: {self.baud}, Simulate: {self.simulate})")
            
            # Start GPS reader
            self.gps_reader = GPSReader(device=self.device, baud=self.baud, simulate=self.simulate)
            self.gps_reader.start()
            
            # Start web server
            self.log(f"Starting web server on port {self.port}")
            self.server = ThreadingHTTPServer((self.host, self.port), RequestHandler)
            setattr(self.server, 'gps_reader', self.gps_reader)
            
            # Run server in separate thread
            self.server_thread = threading.Thread(target=self.server.serve_forever, daemon=True)
            self.server_thread.start()
            
            self.is_running = True
            
            # Update button states
            self.start_btn.config(state="disabled")
            self.stop_btn.config(state="normal")
            self.open_map_btn.config(state="normal")
            
            self.log(f"GPS and web server started successfully!")
            self.log(f"Access the live map at: http://{self.host}:{self.port}")
            
            # Check for pyserial if not simulating
            if not self.simulate and serial is None:
                self.log("WARNING: pyserial is not installed. Install with: pip3 install pyserial")
                if GUI_AVAILABLE:
                    messagebox.showwarning("Warning", "PySerial is not installed.\nInstall with: pip3 install pyserial")
            
        except Exception as e:
            self.log(f"Error starting GPS/Server: {e}")
            if GUI_AVAILABLE:
                messagebox.showerror("Error", f"Failed to start GPS/Server:\n{e}")
            self.stop_gps_server()
    
    def stop_gps_server(self):
        """Stop GPS reader and web server"""
        if not self.is_running:
            return
        
        self.log("Stopping GPS and web server...")
        
        # Stop GPS reader
        if self.gps_reader:
            self.gps_reader.stop()
            self.gps_reader = None
        
        # Stop web server
        if self.server:
            self.server.shutdown()
            self.server = None
        
        self.is_running = False
        
        # Update button states
        self.start_btn.config(state="normal")
        self.stop_btn.config(state="disabled")
        self.open_map_btn.config(state="disabled")
        
        self.log("GPS and web server stopped.")
    
    def force_stop_all(self):
        """Force stop all GPS processes and reset state"""
        self.log("🛑 Force stopping all GPS processes...")
        
        try:
            # Kill any python processes running Main.py
            subprocess.run(['pkill', '-f', 'python3.*Main.py'], capture_output=True)
            self.log("✅ Killed any running Main.py processes")
            
            # Kill processes using port 5000
            subprocess.run(['sudo', 'fuser', '-k', '5000/tcp'], capture_output=True)
            self.log("✅ Freed port 5000")
            
            # Stop our internal processes
            if self.gps_reader:
                self.gps_reader.stop()
                self.gps_reader = None
                self.log("✅ Stopped GPS reader thread")
            
            if self.server:
                try:
                    self.server.shutdown()
                    self.server.server_close()
                except:
                    pass
                self.server = None
                self.log("✅ Stopped web server")
            
            # Reset state
            self.is_running = False
            
            # Update button states
            self.start_btn.config(state="normal")
            self.stop_btn.config(state="disabled")
            self.open_map_btn.config(state="disabled")
            
            self.log("✅ Force stop completed - all processes terminated")
            
            if GUI_AVAILABLE:
                messagebox.showinfo("Force Stop", "All GPS processes have been forcefully stopped.\nYou can now start fresh.")
                
        except Exception as e:
            self.log(f"❌ Error during force stop: {e}")
            # Even if there's an error, reset the GUI state
            self.is_running = False
            self.start_btn.config(state="normal")
            self.stop_btn.config(state="disabled")
            self.open_map_btn.config(state="disabled")
    
    def open_map(self):
        """Open the live map in web browser"""
        if self.is_running:
            url = f"http://{self.host}:{self.port}"
            self.log(f"Opening live map: {url}")
            webbrowser.open(url)
        else:
            if GUI_AVAILABLE:
                messagebox.showwarning("Warning", "GPS server is not running. Start it first.")
    
    def run_diagnostics(self):
        """Run system diagnostics"""
        self.log("Running system diagnostics...")
        
        # Check pyserial
        if serial is None:
            self.log("❌ PySerial: NOT INSTALLED (pip3 install pyserial)")
        else:
            self.log("✅ PySerial: Available")
        
        # Check device file
        if os.path.exists(self.device_var.get()):
            self.log(f"✅ Device file: {self.device_var.get()} exists")
            
            # Check permissions
            if os.access(self.device_var.get(), os.R_OK | os.W_OK):
                self.log("✅ Device permissions: Read/Write access OK")
            else:
                self.log("❌ Device permissions: No read/write access")
        else:
            self.log(f"❌ Device file: {self.device_var.get()} not found")
        
        # Check if on Raspberry Pi
        if os.path.exists('/boot/config.txt'):
            self.log("✅ Raspberry Pi: Detected")
            
            # Check UART configuration
            try:
                with open('/boot/config.txt', 'r') as f:
                    config = f.read()
                    if 'enable_uart=1' in config:
                        self.log("✅ UART: Enabled in config")
                    else:
                        self.log("❌ UART: Not enabled (add 'enable_uart=1' to /boot/config.txt)")
            except:
                self.log("❌ UART: Cannot read /boot/config.txt")
        else:
            self.log("ℹ️ Raspberry Pi: Not detected (may be running on other system)")
        
        # Check for conflicting services
        try:
            result = subprocess.run(['pgrep', 'gpsd'], capture_output=True)
            if result.returncode == 0:
                self.log("⚠️ GPSD: Running (may conflict with GPS access)")
            else:
                self.log("✅ GPSD: Not running")
        except:
            self.log("ℹ️ GPSD: Cannot check status")
        
        self.log("Diagnostics complete.")
    
    def restart_gps_service(self):
        """Restart GPS-related services"""
        if GUI_AVAILABLE and messagebox.askyesno("Confirm", "Restart GPS services? This requires sudo privileges."):
            self.log("Restarting GPS services...")
            try:
                # Stop gpsd
                subprocess.run(['sudo', 'systemctl', 'stop', 'gpsd'], capture_output=True)
                subprocess.run(['sudo', 'killall', 'gpsd'], capture_output=True)
                self.log("✅ Stopped GPSD service")
                
                # Reset serial device
                if os.path.exists(self.device_var.get()):
                    subprocess.run(['sudo', 'stty', '-F', self.device_var.get(), 'raw', '9600'], 
                                 capture_output=True)
                    self.log("✅ Reset serial device")
                
                if GUI_AVAILABLE:
                    messagebox.showinfo("Success", "GPS services restarted successfully!")
                
            except Exception as e:
                self.log(f"❌ Error restarting services: {e}")
                if GUI_AVAILABLE:
                    messagebox.showerror("Error", f"Failed to restart GPS services:\n{e}")
    
    def get_location_from_ip(self):
        """Get approximate location from IP geolocation"""
        if not REQUESTS_AVAILABLE:
            return None, None, None
        try:
            response = requests.get('http://ipapi.co/json/', timeout=5)
            data = response.json()
            return data.get('latitude'), data.get('longitude'), data.get('city')
        except:
            return None, None, None
    
    def get_location_from_city(self, city_name):
        """Get coordinates from city name using OpenStreetMap Nominatim API"""
        if not REQUESTS_AVAILABLE or not city_name.strip():
            return None, None, None
        
        try:
            # Use OpenStreetMap Nominatim API (free, no API key required)
            url = "https://nominatim.openstreetmap.org/search"
            params = {
                'q': city_name.strip(),
                'format': 'json',
                'limit': 1,
                'addressdetails': 1
            }
            headers = {
                'User-Agent': 'GPS-Assistant/1.0'  # Required by Nominatim
            }
            
            response = requests.get(url, params=params, headers=headers, timeout=10)
            data = response.json()
            
            if data and len(data) > 0:
                result = data[0]
                lat = float(result['lat'])
                lon = float(result['lon'])
                display_name = result.get('display_name', city_name)
                return lat, lon, display_name
            else:
                return None, None, None
                
        except Exception as e:
            print(f"Geocoding error: {e}")
            return None, None, None
    
    def gps_assist(self):
        """Send GPS assistance data to help with faster fix"""
        if self.simulate_var.get():
            self.log("GPS Assist not needed in simulation mode")
            return
        
        if not serial:
            self.log("❌ PySerial not available for GPS assistance")
            return
        
        self.log("🛰️ Starting GPS Assistance (A-GPS)...")
        
        # Get location assistance - try city field first, then IP, then fallback
        city_name = self.city_var.get().strip()
        assist_lat, assist_lon, location_source = None, None, None
        
        if city_name:
            self.log(f"🔍 Looking up coordinates for: {city_name}")
            city_lat, city_lon, display_name = self.get_location_from_city(city_name)
            if city_lat and city_lon:
                assist_lat, assist_lon = city_lat, city_lon
                location_source = f"City lookup: {display_name}"
                self.log(f"📍 {location_source} ({assist_lat:.4f}, {assist_lon:.4f})")
        
        if not assist_lat:
            self.log("🌐 Trying IP-based location...")
            ip_lat, ip_lon, ip_city = self.get_location_from_ip()
            if ip_lat and ip_lon:
                assist_lat, assist_lon = ip_lat, ip_lon
                location_source = f"IP-based: {ip_city}"
                self.log(f"📍 {location_source} ({assist_lat:.4f}, {assist_lon:.4f})")
        
        if not assist_lat:
            assist_lat, assist_lon = 45.5017, -73.5673
            location_source = "Fallback: Montreal, Canada"
            self.log(f"📍 {location_source} ({assist_lat:.4f}, {assist_lon:.4f})")
        
        try:
            with serial.Serial(self.device_var.get(), int(self.baud_var.get()), timeout=1) as ser:
                self.log(f"🔗 Connected to {self.device_var.get()}")
                
                # Send assistance commands
                commands = [
                    # Set approximate position
                    f"$PMTK351,1,{assist_lat:.6f},{assist_lon:.6f},0",
                    # Enable GPS+GLONASS+Galileo
                    "$PMTK353,1,1,1,0,0",
                    # Set 1Hz update rate
                    "$PMTK220,1000",
                    # Hot restart with assistance
                    "$PMTK101"
                ]
                
                for cmd in commands:
                    # Calculate NMEA checksum
                    checksum = 0
                    for c in cmd[1:]:
                        checksum ^= ord(c)
                    full_cmd = f"{cmd}*{checksum:02X}\r\n"
                    
                    ser.write(full_cmd.encode())
                    time.sleep(0.1)
                    self.log(f"📡 Sent: {cmd}")
                
                self.log("✅ GPS assistance data sent!")
                self.log("⏳ GPS should acquire fix faster now. Wait 30-60 seconds...")
                
                if GUI_AVAILABLE:
                    messagebox.showinfo("GPS Assist", 
                                      "GPS assistance data sent!\n\n"
                                      "The GPS should now:\n"
                                      "• Acquire satellites faster\n"
                                      "• Get first fix in 30-60 seconds\n"
                                      "• Work better in challenging conditions\n\n"
                                      "Make sure you're outdoors with clear sky view!")
                
        except Exception as e:
            self.log(f"❌ GPS Assist error: {e}")
            if GUI_AVAILABLE:
                messagebox.showerror("GPS Assist Error", f"Failed to send assistance data:\n{e}")
    
    def check_gps_status(self):
        """Check current GPS status and satellite information"""
        if self.simulate_var.get():
            self.log("📊 GPS Status: Simulation mode - showing fake Montreal location")
            return
        
        if not serial:
            self.log("❌ PySerial not available for GPS status check")
            return
        
        self.log("📊 Checking GPS status...")
        
        try:
            with serial.Serial(self.device_var.get(), int(self.baud_var.get()), timeout=1) as ser:
                start_time = time.time()
                has_data = False
                satellites = 0
                fix_status = "No Fix"
                
                while (time.time() - start_time) < 10:
                    line = ser.readline().decode('ascii', errors='ignore').strip()
                    if line:
                        has_data = True
                        
                        if '$GPRMC' in line or '$GNRMC' in line:
                            parts = line.split(',')
                            if len(parts) > 2:
                                status = parts[2]
                                if status == 'A':
                                    fix_status = "✅ GPS HAS FIX!"
                                    if len(parts) > 5:
                                        lat_raw, lat_dir = parts[3], parts[4]
                                        lon_raw, lon_dir = parts[5], parts[6]
                                        self.log(f"📍 Position: {lat_raw} {lat_dir}, {lon_raw} {lon_dir}")
                                else:
                                    fix_status = "⏳ Searching for satellites..."
                        
                        elif '$GPGGA' in line or '$GNGGA' in line:
                            parts = line.split(',')
                            if len(parts) > 7 and parts[7]:
                                satellites = int(parts[7])
                                self.log(f"🛰️ Satellites in use: {satellites}")
                        
                        elif '$GPGSV' in line or '$GNGSV' in line:
                            parts = line.split(',')
                            if len(parts) > 3 and parts[3]:
                                total_sats = parts[3]
                                self.log(f"👁️ Satellites in view: {total_sats}")
                
                if not has_data:
                    self.log("❌ No GPS data received - check hardware connection")
                    status_msg = "No GPS communication detected.\nCheck hardware connection."
                else:
                    status_msg = f"GPS Status: {fix_status}\nSatellites in use: {satellites}\n"
                    if satellites == 0:
                        status_msg += "\nTips:\n• Go outdoors\n• Wait 2-5 minutes\n• Check antenna connection"
                    elif satellites < 4:
                        status_msg += "\nNeed 4+ satellites for fix.\nWait a bit longer..."
                    else:
                        status_msg += "\nGood satellite coverage!"
                
                if GUI_AVAILABLE:
                    messagebox.showinfo("GPS Status", status_msg)
                
        except Exception as e:
            self.log(f"❌ GPS Status check error: {e}")
            if GUI_AVAILABLE:
                messagebox.showerror("GPS Status Error", f"Failed to check GPS status:\n{e}")
    
    def show_raw_gps_data(self):
        """Show raw NMEA data in a popup window"""
        if self.simulate_var.get():
            self.log("📡 Raw GPS Data: Not available in simulation mode")
            return
        
        if not serial:
            self.log("❌ PySerial not available for raw data display")
            return
        
        # Create popup window for raw data
        raw_window = tk.Toplevel(self.root)
        raw_window.title("Raw GPS Data (NMEA)")
        raw_window.geometry("800x400")
        
        # Text area for raw data
        raw_text = tk.Text(raw_window, wrap=tk.WORD, font=('Courier', 9))
        scrollbar = ttk.Scrollbar(raw_window, orient="vertical", command=raw_text.yview)
        raw_text.configure(yscrollcommand=scrollbar.set)
        
        raw_text.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")
        
        # Control frame
        control_frame = ttk.Frame(raw_window)
        control_frame.pack(side="bottom", fill="x", padx=5, pady=5)
        
        is_running = [True]  # Use list to allow modification in nested function
        
        def stop_raw_data():
            is_running[0] = False
            raw_window.destroy()
        
        ttk.Button(control_frame, text="Stop", command=stop_raw_data).pack(side="left")
        ttk.Label(control_frame, text="Showing live NMEA data from GPS...").pack(side="left", padx=10)
        
        def read_raw_data():
            try:
                with serial.Serial(self.device_var.get(), int(self.baud_var.get()), timeout=1) as ser:
                    line_count = 0
                    while is_running[0] and line_count < 200:  # Limit to prevent memory issues
                        try:
                            line = ser.readline().decode('ascii', errors='ignore').strip()
                            if line and is_running[0]:
                                timestamp = time.strftime("%H:%M:%S")
                                raw_text.insert(tk.END, f"[{timestamp}] {line}\n")
                                raw_text.see(tk.END)
                                raw_window.update_idletasks()
                                line_count += 1
                        except:
                            break
                    
                    if line_count == 0:
                        raw_text.insert(tk.END, "No GPS data received.\nCheck hardware connection.\n")
                    elif line_count >= 200:
                        raw_text.insert(tk.END, "\n--- Stopped after 200 lines ---\n")
                        
            except Exception as e:
                raw_text.insert(tk.END, f"Error reading GPS data: {e}\n")
        
        # Start reading in a separate thread
        threading.Thread(target=read_raw_data, daemon=True).start()
        
        self.log("📡 Opened raw GPS data window")
    
    def open_saved_map_dialog_listbox(self):
        """Open a dialog to choose a saved area and open the offline map centered on it (Listbox version)."""
        try:
            areas = _load_areas()
            win = tk.Toplevel(self.root)
            win.title("Load Saved Map")
            win.geometry("560x360")
            win.transient(self.root)
            win.grab_set()

            frame = ttk.Frame(win, padding=6)
            frame.pack(fill="both", expand=True)

            listbox = tk.Listbox(frame, height=12, exportselection=False)
            listbox.pack(side="left", fill="both", expand=True)
            sb = ttk.Scrollbar(frame, orient="vertical", command=listbox.yview)
            sb.pack(side="right", fill="y")
            listbox.configure(yscrollcommand=sb.set)

            names = []
            if not areas:
                listbox.insert(tk.END, "(no saved areas found – use Offline Import to Save one)")
                listbox.config(state="disabled")
            else:
                for a in areas:
                    name = a.get('name') or "(unnamed)"
                    bbox = a.get('bbox')
                    desc = name
                    if isinstance(bbox, list) and len(bbox) == 4:
                        desc += f"  —  bbox: {bbox[0]:.4f},{bbox[1]:.4f},{bbox[2]:.4f},{bbox[3]:.4f}"
                    zs = a.get('zooms') or []
                    if isinstance(zs, list) and zs:
                        desc += "  z:[" + ",".join(str(z) for z in zs) + "]"
                    listbox.insert(tk.END, desc)
                    names.append(a)

            def ensure_running():
                if not self.is_running:
                    try:
                        self.start_gps_server()
                    except Exception:
                        pass

            def open_selected():
                if not names:
                    return
                idxs = listbox.curselection()
                if not idxs:
                    messagebox.showinfo("Load Saved Map", "Select an area first.")
                    return
                sel = names[idxs[0]]
                bbox = sel.get('bbox')
                if not bbox or not isinstance(bbox, list) or len(bbox) != 4:
                    messagebox.showerror("Load Saved Map", "Selected entry has no valid bbox.")
                    return
                ensure_running()
                url = f"http://{self.host}:{self.port}/offline?bbox=" + ",".join(str(x) for x in bbox)
                self.log(f"Opening offline map for saved area '{sel.get('name','')}' -> {url}")
                webbrowser.open(url)
                win.destroy()

            def delete_selected():
                if not names:
                    return
                idxs = listbox.curselection()
                if not idxs:
                    messagebox.showinfo("Delete Saved", "Select an entry to delete.")
                    return
                sel = names[idxs[0]]
                if messagebox.askyesno("Delete Saved", f"Delete saved area '{sel.get('name','')}'? This cannot be undone."):
                    remain = [a for i, a in enumerate(names) if i != idxs[0]]
                    if _save_areas(remain):
                        self.log("Deleted selected saved area.")
                        win.destroy()
                        self.open_saved_map_dialog_listbox()
                    else:
                        messagebox.showerror("Delete Saved", "Failed to save changes.")

            def _dbl_open(e=None):
                open_selected()
                return "break"
            listbox.bind("<Double-Button-1>", _dbl_open)
            listbox.bind("<Return>", _dbl_open)

            btns = ttk.Frame(win)
            btns.pack(fill="x", pady=(8,0))
            ttk.Button(btns, text="Open Offline Map", command=open_selected).pack(side="left")
            ttk.Button(btns, text="Delete Selected", command=delete_selected).pack(side="right")

        except Exception as e:
            self.log(f"Load Saved Map error: {e}")
            if GUI_AVAILABLE:
                messagebox.showerror("Load Saved Map", f"An error occurred:\n{e}")

    def show_instructions_old(self):
        """Show comprehensive instructions and function benefits"""
        # Create instructions window
        instructions_window = tk.Toplevel(self.root)
        instructions_window.title("📖 GPS Application Instructions & Function Benefits")
        instructions_window.geometry("900x700")
        instructions_window.resizable(True, True)
        
        # Create notebook for tabs
        notebook = ttk.Notebook(instructions_window)
        notebook.pack(fill="both", expand=True, padx=10, pady=10)
        
        # Tab 1: Quick Start Guide
        quick_start_frame = ttk.Frame(notebook)
        notebook.add(quick_start_frame, text="🚀 Quick Start")
        
        quick_start_text = tk.Text(quick_start_frame, wrap=tk.WORD, font=('Arial', 10))
        quick_start_scroll = ttk.Scrollbar(quick_start_frame, orient="vertical", command=quick_start_text.yview)
        quick_start_text.configure(yscrollcommand=quick_start_scroll.set)
        
        quick_start_content = """🚀 QUICK START GUIDE - GPS Waveshare L76X HAT

📋 BEFORE YOU BEGIN:
• Ensure GPS HAT is properly connected to Raspberry Pi GPIO pins
• Connect GPS antenna to the HAT (essential for GPS reception)
• Make sure you're OUTDOORS with clear sky view (GPS won't work indoors!)

⚡ GETTING STARTED (5 Easy Steps):

1️⃣ ENTER YOUR CITY
   • In "City for GPS Assist" field, enter your location
   • Examples: "Tokyo, Japan", "London, UK", "New York, USA"
   • This dramatically speeds up GPS acquisition (30-60 seconds vs 15+ minutes!)

2️⃣ START THE GPS SYSTEM
   • Click "Start GPS & Server" button
   • Wait for "GPS and web server started successfully!" message
   • Status should show "Server Status: Running"

3️⃣ USE GPS ASSISTANCE (RECOMMENDED)
   • Click "GPS Assist (A-GPS)" button
   • This sends your city coordinates to GPS for faster satellite lock
   • Essential for quick GPS acquisition!

4️⃣ GO OUTDOORS & WAIT
   • GPS MUST be used outdoors with clear sky view
   • Wait 30-60 seconds (with GPS Assist) or 2-15 minutes (without)
   • Watch "GPS Status" for "GPS Fix: Valid" (green text)

5️⃣ VIEW YOUR LOCATION
   • Click "Open Live Map" to see real-time location
   • Watch yourself move on the interactive map!
   • Speed and coordinates update automatically

🎯 SUCCESS INDICATORS:
✅ "GPS Fix: Valid" (green) - GPS is working!
✅ Latitude/Longitude showing numbers - coordinates acquired
✅ Live map shows your actual location - ready to use!

⚠️ TROUBLESHOOTING:
❌ "GPS Fix: No Fix" (red) - Go outdoors, wait longer, use GPS Assist
❌ No coordinates - Check antenna connection, ensure outdoors
❌ Can't start - Click "Force Stop All", then try again
"""
        
        quick_start_text.insert("1.0", quick_start_content)
        quick_start_text.config(state="disabled")
        quick_start_text.pack(side="left", fill="both", expand=True)
        quick_start_scroll.pack(side="right", fill="y")
        
        # Tab 2: Function Benefits
        functions_frame = ttk.Frame(notebook)
        notebook.add(functions_frame, text="🔧 Function Benefits")
        
        functions_text = tk.Text(functions_frame, wrap=tk.WORD, font=('Arial', 10))
        functions_scroll = ttk.Scrollbar(functions_frame, orient="vertical", command=functions_text.yview)
        functions_text.configure(yscrollcommand=functions_scroll.set)
        
        functions_content = """🔧 FUNCTION BENEFITS & DETAILED EXPLANATIONS

🎛️ CONFIGURATION SECTION:

📍 City for GPS Assist:
   BENEFIT: Reduces GPS acquisition time from 15+ minutes to 30-60 seconds
   HOW IT WORKS: Sends approximate coordinates to GPS module for faster satellite lock
   RESILIENCE: 3-tier fallback system (City → IP location → Montreal fallback)
   GLOBAL: Works worldwide - enter any city (Tokyo, London, Cairo, etc.)

🔧 Simulation Mode:
   BENEFIT: Test application without GPS hardware
   EDUCATIONAL: Learn GPS concepts with simulated Montreal coordinates
   DEVELOPMENT: Perfect for indoor testing and demonstrations

⚙️ CONTROL FUNCTIONS:

🚀 Start GPS & Server:
   BENEFIT: Activates GPS reader and web server simultaneously
   CREATES: Real-time GPS data stream and web interface
   ENABLES: Live map viewing and coordinate tracking

🛑 Stop GPS & Server:
   BENEFIT: Clean shutdown of all GPS processes
   SAFETY: Properly closes serial connections and web server
   RESOURCE: Frees system resources when done

🌐 Open Live Map:
   BENEFIT: Interactive real-time GPS visualization
   FEATURES: Pulsing location marker, speed display, coordinate tracking
   EDUCATIONAL: Visual understanding of GPS positioning and movement

🆘 Force Stop All:
   BENEFIT: Emergency recovery from stuck processes
   RESILIENCE: Always available even when normal stop fails
   TROUBLESHOOTING: Kills all GPS processes and resets application state

🔍 DIAGNOSTIC FUNCTIONS:

🏥 Run Diagnostics:
   BENEFIT: Comprehensive system health check
   CHECKS: Hardware detection, permissions, UART config, conflicting services
   EDUCATIONAL: Learn about GPS system requirements and configuration

🔄 Restart GPS Service:
   BENEFIT: Fixes GPS communication issues
   RESOLVES: Serial port conflicts, stuck GPS states
   REQUIRES: Sudo privileges for system service management

🛰️ GPS Assist (A-GPS):
   BENEFIT: Assisted GPS for 95% faster satellite acquisition
   TECHNOLOGY: Sends location hints and satellite constellation data
   RESILIENCE: Works in challenging conditions (urban, cloudy weather)
   GLOBAL: Uses your city input for worldwide compatibility

📊 Check GPS Status:
   BENEFIT: Real-time satellite and fix information
   DISPLAYS: Satellite count, fix status, signal quality
   EDUCATIONAL: Understand GPS signal acquisition process
   TROUBLESHOOTING: Diagnose GPS reception issues

📡 Show Raw GPS Data:
   BENEFIT: View live NMEA sentences from GPS module
   EDUCATIONAL: Learn GPS communication protocol (NMEA 0183)
   DEBUGGING: See actual GPS data stream for troubleshooting
   TECHNICAL: Understand $GPRMC, $GPGGA, $GPGSV sentence formats

📖 Instructions:
   BENEFIT: Comprehensive help system (this window!)
   EDUCATIONAL: Complete learning resource for GPS technology
   REFERENCE: Always available guidance for all functions

🎯 STATUS MONITORING:

📈 GPS Status Panel:
   BENEFIT: Real-time system monitoring
   DISPLAYS: Server status, GPS fix, coordinates, speed, last update
   COLOR-CODED: Green (good), Red (problem), Orange (warning)
   EDUCATIONAL: Understand GPS system states and data quality

📝 System Log:
   BENEFIT: Detailed activity tracking and troubleshooting
   RECORDS: All GPS operations, errors, and status changes
   DEBUGGING: Trace problems and understand system behavior
   LEARNING: See exactly what happens during GPS operations

🌍 GLOBAL COMPATIBILITY:
• Works in any country worldwide
• Supports any city name for GPS assistance
• Automatic timezone and coordinate system handling
• Multi-constellation support (GPS, GLONASS, Galileo)
"""
        
        functions_text.insert("1.0", functions_content)
        functions_text.config(state="disabled")
        functions_text.pack(side="left", fill="both", expand=True)
        functions_scroll.pack(side="right", fill="y")
        
        # Tab 3: Technical Details
        technical_frame = ttk.Frame(notebook)
        notebook.add(technical_frame, text="🔬 Technical Details")
        
        technical_text = tk.Text(technical_frame, wrap=tk.WORD, font=('Arial', 10))
        technical_scroll = ttk.Scrollbar(technical_frame, orient="vertical", command=technical_text.yview)
        technical_text.configure(yscrollcommand=technical_scroll.set)
        
        technical_content = """🔬 TECHNICAL DETAILS & GPS SCIENCE

🛰️ GPS TECHNOLOGY OVERVIEW:

📡 How GPS Works:
   • 24+ satellites orbiting Earth at 20,200 km altitude
   • Each satellite broadcasts time and position signals
   • GPS receiver calculates position using 4+ satellite signals
   • Triangulation determines exact latitude, longitude, altitude

⏱️ GPS Acquisition Process:
   COLD START: 15+ minutes (no assistance data)
   WARM START: 2-5 minutes (some satellite data cached)
   HOT START: 30-60 seconds (recent satellite data available)
   A-GPS: 30-60 seconds (assisted with location hints)

🔧 WAVESHARE L76X HAT SPECIFICATIONS:

📊 Technical Specs:
   • Chip: Quectel L76X GPS module
   • Constellations: GPS, GLONASS, Galileo
   • Channels: 33 tracking, 99 acquisition
   • Sensitivity: -165 dBm (tracking), -148 dBm (acquisition)
   • Accuracy: 2.5m CEP (Circular Error Probable)
   • Update Rate: 1Hz (configurable up to 10Hz)
   • Communication: UART at 9600 baud (default)

🔌 Hardware Interface:
   • Device: /dev/ttyAMA0 (Raspberry Pi UART)
   • Protocol: NMEA 0183 standard
   ��� Power: 3.3V from GPIO pins
   • Antenna: External active antenna required

📋 NMEA SENTENCE FORMATS:

$GPRMC (Recommended Minimum):
   • Position, speed, course, date/time
   • Status: A=Active (valid), V=Void (invalid)
   • Most important sentence for basic positioning

$GPGGA (Global Positioning System Fix Data):
   • Position, altitude, satellite count, HDOP
   • Fix quality indicator (0=invalid, 1=GPS, 2=DGPS)
   • Essential for 3D positioning

$GPGSV (Satellites in View):
   • Satellite count, signal strength (SNR)
   • Satellite identification numbers
   • Useful for signal quality assessment

🌐 COORDINATE SYSTEMS:

📍 WGS84 Datum:
   • World Geodetic System 1984
   • Global standard for GPS coordinates
   • Latitude: -90° to +90° (South to North)
   • Longitude: -180° to +180° (West to East)

🎯 Accuracy Factors:
   HDOP (Horizontal Dilution of Precision): <2 = Excellent, 2-5 = Good, >5 = Poor
   Satellite Count: 4+ required for 2D fix, 5+ for 3D fix with altitude
   Signal Strength: >35 dBHz = Strong, 25-35 = Moderate, <25 = Weak

⚡ A-GPS TECHNOLOGY:

🚀 Assisted GPS Benefits:
   • Downloads satellite orbital data (ephemeris) from internet
   • Provides approximate location for faster satellite search
   • Reduces Time To First Fix (TTFF) by 95%
   • Works better in challenging environments (urban canyons)

🔄 Implementation:
   • City geocoding via OpenStreetMap Nominatim API
   • IP geolocation fallback via ipapi.co
   • PMTK commands sent to L76X module:
     - $PMTK351: Set approximate position
     - $PMTK353: Enable multi-constellation
     - $PMTK220: Set update rate
     - $PMTK101: Hot restart with assistance

🌍 GLOBAL COMPATIBILITY:

🗺️ Worldwide Operation:
   • Works in all countries and territories
   • Automatic coordinate system handling
   • Multi-language city name support
   • Timezone-independent operation

🛰️ Satellite Constellations:
   GPS (USA): 31 satellites, global coverage
   GLONASS (Russia): 24 satellites, enhanced polar coverage
   Galileo (EU): 22+ satellites, improved accuracy
   Combined: Better coverage, faster acquisition, higher accuracy

🔧 TROUBLESHOOTING TECHNICAL ISSUES:

⚠️ Common Problems:
   • Indoor use: GPS signals cannot penetrate buildings
   • Antenna issues: Poor connection or damaged antenna
   • Serial conflicts: Bluetooth using same UART port
   • Permissions: User not in dialout group
   • UART disabled: enable_uart=1 not set in config.txt

🔍 Diagnostic Commands:
   • lsof /dev/ttyAMA0: Check port usage
   • dmesg | grep uart: Check UART initialization
   • stty -F /dev/ttyAMA0: Configure serial port
   • systemctl status bluetooth: Check conflicting services

📚 EDUCATIONAL VALUE:

🎓 Learning Outcomes:
   • Understand GPS satellite technology
   • Learn NMEA protocol and data parsing
   • Experience real-time data processing
   • Explore coordinate systems and mapping
   • Practice hardware interfacing and troubleshooting
   • Gain experience with serial communication
   • Understand the importance of location services in modern technology
"""
        
        technical_text.insert("1.0", technical_content)
        technical_text.config(state="disabled")
        technical_text.pack(side="left", fill="both", expand=True)
        technical_scroll.pack(side="right", fill="y")
        
        # Tab 4: Troubleshooting
        troubleshooting_frame = ttk.Frame(notebook)
        notebook.add(troubleshooting_frame, text="🔧 Troubleshooting")
        
        troubleshooting_text = tk.Text(troubleshooting_frame, wrap=tk.WORD, font=('Arial', 10))
        troubleshooting_scroll = ttk.Scrollbar(troubleshooting_frame, orient="vertical", command=troubleshooting_text.yview)
        troubleshooting_text.configure(yscrollcommand=troubleshooting_scroll.set)
        
        troubleshooting_content = """🔧 TROUBLESHOOTING GUIDE

❌ PROBLEM: "No GPS Fix" or coordinates not appearing

🔍 DIAGNOSIS STEPS:
1. Check "GPS Status" panel - is it showing "No Fix" (red)?
2. Look at System Log for error messages
3. Verify you're OUTDOORS with clear sky view
4. Check if GPS antenna is properly connected

✅ SOLUTIONS:
• Go outdoors - GPS CANNOT work indoors reliably
• Wait 2-15 minutes for satellite acquisition
• Use "GPS Assist (A-GPS)" with your city name
• Click "Check GPS Status" to see satellite count
• Try "Show Raw GPS Data" to verify GPS communication
• Use "Run Diagnostics" to check hardware

❌ PROBLEM: Cannot start GPS server

🔍 DIAGNOSIS STEPS:
1. Check System Log for specific error messages
2. Look for "Permission denied" or "Device busy" errors
3. Check if another process is using the GPS

✅ SOLUTIONS:
• Click "Force Stop All" to clear any stuck processes
• Use "Run Diagnostics" to check for conflicts
• Try "Restart GPS Service" to reset system services
• Ensure user is in dialout group: sudo usermod -a -G dialout $USER
• Reboot Raspberry Pi if problems persist

❌ PROBLEM: GPS very slow to get first fix

🔍 DIAGNOSIS STEPS:
1. Check if you entered city in "City for GPS Assist"
2. Verify you're outdoors with clear sky view
3. Look at satellite count in "Check GPS Status"

✅ SOLUTIONS:
• Enter your city name (e.g., "Tokyo, Japan") for A-GPS
• Click "GPS Assist (A-GPS)" to send location hints
• Wait in open area away from buildings and trees
• Check antenna connection is secure
• Try different outdoor location with better sky view

❌ PROBLEM: "Show Raw GPS Data" shows no data

🔍 DIAGNOSIS STEPS:
1. Check if GPS HAT is properly seated on GPIO pins
2. Verify antenna is connected to GPS HAT
3. Look for hardware detection in diagnostics

✅ SOLUTIONS:
• Power off Pi, reseat GPS HAT firmly on all GPIO pins
• Check antenna connection to GPS HAT
• Use "Run Diagnostics" to verify hardware detection
• Try different antenna if available
• Check for loose connections

❌ PROBLEM: Live map not opening or showing location

🔍 DIAGNOSIS STEPS:
1. Check if GPS server is running (green status)
2. Verify GPS has valid fix (coordinates showing)
3. Check web browser and internet connection

✅ SOLUTIONS:
• Ensure "Start GPS & Server" was clicked first
• Wait for GPS fix before opening map
• Try different web browser
• Check firewall settings (port 5000)
• Manually navigate to http://localhost:5000

❌ PROBLEM: Bluetooth conflicts with GPS

🔍 DIAGNOSIS STEPS:
1. Check "Run Diagnostics" for Bluetooth service status
2. Look for "Device busy" errors in System Log
3. Check if /dev/serial0 is being used by Bluetooth

✅ SOLUTIONS:
• Disable Bluetooth: sudo systemctl disable bluetooth
• Stop Bluetooth service: sudo systemctl stop bluetooth
• Add to /boot/firmware/config.txt: dtoverlay=disable-bt
• Reboot after making changes
• Use "Restart GPS Service" to reset serial port

❌ PROBLEM: Permission denied errors

🔍 DIAGNOSIS STEPS:
1. Check user permissions in diagnostics
2. Look for "Permission denied" in System Log
3. Verify user is in dialout group

✅ SOLUTIONS:
• Add user to dialout group: sudo usermod -a -G dialout $USER
• Log out and log back in (or reboot)
• Check device permissions: ls -la /dev/ttyAMA0
• Try running with sudo (temporary test only)

❌ PROBLEM: GPS works but coordinates are wrong

🔍 DIAGNOSIS STEPS:
1. Check if using simulation mode
2. Verify GPS has valid satellite fix
3. Compare with known location or other GPS device

✅ SOLUTIONS:
• Disable "Simulation Mode" checkbox
• Wait for more satellites (4+ needed for accuracy)
• Check HDOP value in raw GPS data (<5 is good)
• Verify antenna has clear sky view
• Wait longer for GPS to stabilize

🆘 EMERGENCY RECOVERY PROCEDURES:

🔄 Complete Reset:
1. Click "Force Stop All"
2. Close application
3. Reboot Raspberry Pi
4. Restart application
5. Try again with fresh start

🔧 Hardware Reset:
1. Power off Raspberry Pi
2. Remove GPS HAT
3. Check all GPIO pin connections
4. Reseat HAT firmly
5. Reconnect antenna
6. Power on and test

📞 GETTING HELP:

🔍 Information to Collect:
• System Log contents (copy/paste)
• Output from "Run Diagnostics"
• Raspberry Pi model and OS version
• GPS HAT model and antenna type
• Specific error messages
• Steps that led to the problem

📧 Support Resources:
• Waveshare GPS HAT documentation
• Raspberry Pi GPS troubleshooting guides
• NMEA protocol specifications
• GPS technology educational resources

Remember: GPS requires patience! First fix can take 15+ minutes outdoors without assistance. Use A-GPS for much faster results!
"""
        
        troubleshooting_text.insert("1.0", troubleshooting_content)
        troubleshooting_text.config(state="disabled")
        troubleshooting_text.pack(side="left", fill="both", expand=True)
        troubleshooting_scroll.pack(side="right", fill="y")
        
        # Close button
        close_frame = ttk.Frame(instructions_window)
        close_frame.pack(fill="x", padx=10, pady=5)
        
        ttk.Button(close_frame, text="Close Instructions", 
                  command=instructions_window.destroy).pack(side="right")
        
        self.log("📖 Opened comprehensive instructions window")
    
    def show_instructions(self):
        """Show concise, updated instructions for the current features and workflow"""
        win = tk.Toplevel(self.root)
        win.title("📖 Instructions (Updated)")
        win.geometry("820x640")
        win.resizable(True, True)

        frame = ttk.Frame(win, padding=10)
        frame.pack(fill="both", expand=True)

        text = tk.Text(frame, wrap=tk.WORD, font=('Arial', 10))
        scroll = ttk.Scrollbar(frame, orient="vertical", command=text.yview)
        text.configure(yscrollcommand=scroll.set)
        text.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")

        content = """
UPDATED USER GUIDE — Waveshare L76X HAT GPS GUI

Quick start (online or offline-ready)
1) Hardware: Seat the L76X HAT firmly and attach the GPS antenna. Go outdoors for best signal.
2) Start: Click “Start GPS & Server”. When running, the Server Status shows active and the Open Live Map button enables.
3) Faster fix (optional but recommended): Enter your city in “City for GPS Assist”, then click “GPS Assist (A‑GPS)”. This hints the receiver for quicker TTFF.
4) Live view (online tiles): Click “Open Live Map” to see real‑time position and speed.

Offline workflow (plan at home → use in the field)
A) Plan & download tiles (requires internet):
   • Click “Offline Import” → the Area Selector opens in your browser.
   • Find your destination (City lookup), draw a rectangle (toolbar or right‑click‑drag), choose zooms (z12–z16), and click “Download this area”.
   • Optional: Give the area a name and click Save. Your tiles are written under ./tiles and metadata in tiles/saved_areas.json.
B) Use in the field (no internet needed):
   • Start the app and click “Load Saved Map”. Choose the saved area → Open Offline Map.
   • The offline map centers to your saved bbox and serves tiles locally from ./tiles while showing live GPS location.

Main controls and benefits
• Start GPS & Server
  - Starts the serial reader (e.g., /dev/ttyAMA0 @ 9600) and launches the local web server for map pages
  - Enables Live Map and offline map endpoints

• Stop GPS & Server
  - Cleanly shuts down serial reading and the embedded web server to free resources/ports

• Open Live Map
  - Opens an interactive online map using OSM tiles; shows live location with a pulsing marker and speed

• Offline Import (Area Selector)
  - Visual tool to define exact coverage rectangles, choose zoom levels, and download tiles for offline use
  - Right‑click and drag to draw quickly, or use the rectangle tool; saved areas are persisted in tiles/saved_areas.json

• Load Saved Map
  - Lists your saved areas; selecting one opens the offline map centered to that bbox
  - Uses only local tiles from ./tiles — works fully without internet

• GPS Assist (A‑GPS)
  - Uses your city (or IP fallback) to send assistance commands (PMTK) for faster satellite acquisition
  - Benefit: Dramatically reduces Time To First Fix (often 30–60s outdoors)

• Check GPS Status
  - Reads live NMEA and reports Fix status and satellites in use/view
  - Benefit: Quick diagnosis of reception and fix progress

• Show Raw GPS Data
  - Displays raw NMEA sentences for inspection and debugging ($GPRMC, $GPGGA, $GPGSV)

• Run Diagnostics
  - Verifies pyserial, device existence and permissions, UART config, and gpsd conflicts
  - Benefit: One‑click health check for common setup issues

• Restart GPS Service
  - Stops gpsd and resets serial parameters (requires sudo); useful if the serial port gets stuck or busy

• Force Stop All
  - Kills lingering Main.py and frees port 5000, stops internal threads; last‑resort recovery

Tips
• Outdoor usage: GPS generally needs clear sky; first fix can take minutes without assistance.
• Device: Default set to /dev/ttyAMA0 at 9600; adjust in Configuration if needed.
• Permissions: Ensure your user is in the dialout group if you see permission errors.
• Offline completeness: If blank areas appear, download additional tiles/zooms for that bbox.

Endpoints (for reference)
• Live map:     http://localhost:{port}
• Offline map:  http://localhost:{port}/offline (supports ?bbox=minLon,minLat,maxLon,maxLat)
• Area selector: http://localhost:{port}/select
""".format(port=self.port)

        text.insert("1.0", content)
        text.config(state="disabled")

        btnbar = ttk.Frame(win)
        btnbar.pack(fill="x", padx=10, pady=6)
        ttk.Button(btnbar, text="Close", command=win.destroy).pack(side="right")

        self.log("📖 Opened updated instructions window")

    def offgrid_import(self):
        """Download offline map tiles for a named area with selected coverage."""
        if not REQUESTS_AVAILABLE:
            self.log("❌ Requests library not available. Install with: pip3 install requests")
            if GUI_AVAILABLE:
                messagebox.showerror("Error", "Requests library not available. Install with:\n pip3 install requests")
            return
        area = self.offgrid_area_var.get().strip()
        if not area:
            self.log("❌ Please enter an area name (e.g., park or reserve)")
            if GUI_AVAILABLE:
                messagebox.showwarning("Missing Area", "Enter an area name (e.g., Banff National Park)")
            return
        # Determine radius from coverage selection (A = pi r^2)
        size = self.offgrid_size_var.get()
        area_km2 = 50.0 if '50' in size else 100.0
        radius_km = max(1.0, (area_km2 / 3.14159) ** 0.5)
        self.log(f"🔍 Geocoding area: {area} (radius ~ {radius_km:.1f} km)")
        lat, lon, display_name = self.get_location_from_city(area)
        if not lat or not lon:
            self.log("❌ Could not find the specified area")
            if GUI_AVAILABLE:
                messagebox.showerror("Geocoding Failed", "Could not geocode the specified area.")
            return
        self.log(f"📍 Found: {display_name} ({lat:.5f}, {lon:.5f})")
        # Ensure Leaflet assets are local
        self._ensure_local_leaflet_assets()
        # Download tiles
        try:
            zoom_levels = [12, 13, 14, 15, 16]
            total, downloaded = self._download_tiles(lat, lon, radius_km, zoom_levels)
            # Record and report
            self._record_offgrid_import(display_name or area, lat, lon, radius_km, zoom_levels)
            msg = f"✅ Offline tiles ready. Total tiles: {total}, downloaded now: {downloaded}.\nOpen Offline Map from the button."
            self.log(msg)
            if GUI_AVAILABLE:
                messagebox.showinfo("Off Grid Import Complete", msg)
            # Refresh UI info
            try:
                self.refresh_offgrid_stats()
                self._load_offgrid_log()
            except Exception:
                pass
        except Exception as e:
            self.log(f"❌ Tile download failed: {e}")
            if GUI_AVAILABLE:
                messagebox.showerror("Download Error", f"Failed to download tiles:\n{e}")

    def open_offline_map(self):
        """Open the offline map page"""
        url = f"http://{self.host}:{self.port}/offline"
        self.log(f"Opening offline map: {url}")
        webbrowser.open(url)

    def open_area_selector(self):
        """Open the area selection page"""
        url = f"http://{self.host}:{self.port}/select"
        self.log(f"Opening area selector: {url}")
        webbrowser.open(url)

    def open_saved_map_dialog(self):
        """Open a dialog with checkbox options for saved areas; pick and open offline map.
        Single-click to toggle a checkbox; Click Open to load that area. Auto-start server if needed.
        """
        try:
            win = tk.Toplevel(self.root)
            win.title("Load Saved Offline Map")
            win.geometry("620x460")

            # Load saved areas
            areas = _load_areas()
            if isinstance(areas, dict) and isinstance(areas.get('areas'), list):
                areas = areas.get('areas')
            if not isinstance(areas, list):
                areas = []
            areas = [a for a in areas if isinstance(a, dict)]

            frame = ttk.Frame(win, padding=10)
            frame.pack(fill="both", expand=True)

            ttk.Label(frame, text="Saved Areas (tick to choose):").pack(anchor="w")

            # Scrollable checklist container
            canvas = tk.Canvas(frame, borderwidth=0, highlightthickness=0)
            scroll = ttk.Scrollbar(frame, orient="vertical", command=canvas.yview)
            list_holder = ttk.Frame(canvas)
            list_holder.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
            canvas.create_window((0, 0), window=list_holder, anchor="nw")
            canvas.configure(yscrollcommand=scroll.set)
            canvas.pack(side="left", fill="both", expand=True)
            scroll.pack(side="right", fill="y")

            checks = []  # [(var, area_dict, cb_widget)]

            if not areas:
                row = ttk.Frame(list_holder)
                ttk.Label(row, text="(no saved areas found – use Offline Import to Save one)", foreground="#666").pack(anchor="w")
                row.pack(fill="x", pady=2)
            else:
                for idx, a in enumerate(areas):
                    var = tk.BooleanVar(value=False)
                    row = ttk.Frame(list_holder)
                    cb = tk.Checkbutton(row, variable=var, onvalue=True, offvalue=False, indicatoron=True)
                    cb.pack(side="left")
                    # Only bind right/middle clicks to toggle; let default left-click behavior handle itself
                    def _invoke(e=None, w=cb):
                        try:
                            w.invoke()
                        finally:
                            return "break"
                    cb.bind("<Button-2>", _invoke)
                    cb.bind("<Button-3>", _invoke)
                    name = a.get('name', '(unnamed)')
                    bbox = a.get('bbox')
                    zooms = a.get('zooms')
                    text_main = f"{name}"
                    text_sub = f"bbox: {bbox}  |  zooms: {zooms}"
                    left = ttk.Frame(row)
                    ttk.Label(left, text=text_main).pack(anchor="w")
                    ttk.Label(left, text=text_sub, foreground="#555").pack(anchor="w")
                    left.pack(side="left", padx=(6,0))
                    # Clicking the label toggles the checkbox (invoke)
                    def make_invoke(w=cb):
                        def handler(e=None):
                            try:
                                w.invoke()
                            finally:
                                return "break"
                        return handler
                    left.bind("<Button-1>", make_invoke(cb))
                    left.bind("<Button-3>", make_invoke(cb))
                    left.bind("<Button-2>", make_invoke(cb))
                    for child in left.winfo_children():
                        child.bind("<Button-1>", make_invoke(cb))
                        child.bind("<Button-3>", make_invoke(cb))
                        child.bind("<Button-2>", make_invoke(cb))
                    row.pack(fill="x", pady=2)
                    checks.append((var, a, cb))

            info_var = tk.StringVar(value="Tick one option and click Open")
            ttk.Label(frame, textvariable=info_var, wraplength=580, justify='left').pack(anchor="w", pady=(8,6))

            btns = ttk.Frame(frame)
            btns.pack(fill="x", pady=(4,0))

            def get_first_checked():
                for v, a, _ in checks:
                    if v.get():
                        return a
                return None

            def clear_all():
                for v, _, _ in checks:
                    v.set(False)

            def delete_checked():
                to_keep = []
                any_checked = False
                for v, a, _ in checks:
                    if v.get():
                        any_checked = True
                    else:
                        to_keep.append(a)
                if not any_checked:
                    return
                if GUI_AVAILABLE and not messagebox.askyesno("Confirm", "Delete all checked saved areas?"):
                    return
                try:
                    _save_areas(to_keep)
                    win.destroy()
                    self.open_saved_map_dialog()
                except Exception as e:
                    self.log(f"Delete saved areas failed: {e}")
                    if GUI_AVAILABLE:
                        messagebox.showerror("Error", f"Failed to delete:\n{e}")

            def open_selected():
                a = get_first_checked()
                if not a:
                    if GUI_AVAILABLE:
                        messagebox.showwarning("Pick an Area", "Tick a saved area first.")
                    return
                bbox = a.get('bbox')
                if (not isinstance(bbox, (list, tuple))) or len(bbox) != 4:
                    if GUI_AVAILABLE:
                        messagebox.showerror("Invalid Area", "Saved area is missing a valid bounding box.")
                    return
                try:
                    parts = [float(x) for x in bbox]
                except Exception:
                    if GUI_AVAILABLE:
                        messagebox.showerror("Invalid Area", "Bounding box values are not numbers.")
                    return
                if not self.is_running:
                    try:
                        self.start_gps_server()
                    except Exception as e:
                        self.log(f"Auto-start server failed: {e}")
                bbox_str = ','.join(str(x) for x in parts)
                url = f"http://{self.host}:{self.port}/offline?bbox={bbox_str}"
                self.log(f"Opening offline map for saved area '{a.get('name')}' → {url}")
                webbrowser.open(url)
                try:
                    win.destroy()
                except Exception:
                    pass

            ttk.Button(btns, text="Open Offline Map", command=open_selected).pack(side="left")
            ttk.Button(btns, text="Clear All", command=clear_all).pack(side="left", padx=(8,0))
            ttk.Button(btns, text="Delete Checked", command=delete_checked).pack(side="right")
        except Exception as e:
            self.log(f"Load Saved Map error: {e}")
            if GUI_AVAILABLE:
                messagebox.showerror("Load Saved Map", f"An error occurred:\n{e}")

    def refresh_offgrid_stats(self):
        """Compute and display offline tiles/cache statistics."""
        stats = self._get_tiles_stats()
        self.tiles_stats_label.config(text=f"Tiles: {stats['count']} files, Size: {self._format_bytes(stats['size'])}")
        if stats['zooms']:
            zs = sorted(stats['zooms'])
            self.tiles_zooms_label.config(text=f"Zooms: {','.join(map(str, zs))}")
        else:
            self.tiles_zooms_label.config(text="Zooms: -")
        leaflet_js = os.path.join(os.getcwd(), 'static', 'leaflet', 'leaflet.js')
        leaflet_present = os.path.exists(leaflet_js)
        self.leaflet_cache_label.config(text=f"Leaflet cache: {'present' if leaflet_present else 'not present'}")

    def delete_offline_tiles(self):
        """Delete all offline tiles to free disk space (keeps Leaflet cache)."""
        if GUI_AVAILABLE and not messagebox.askyesno("Confirm", "Delete ALL offline tiles in ./tiles?\nThis frees disk space and cannot be undone."):
            return
        tiles_dir = os.path.join(os.getcwd(), 'tiles')
        try:
            if os.path.isdir(tiles_dir):
                shutil.rmtree(tiles_dir)
                self.log("🗑️ Deleted offline tiles cache (./tiles)")
            os.makedirs(tiles_dir, exist_ok=True)
            # Also clear manifest/log
            man = os.path.join(tiles_dir, 'manifest.log')
            if os.path.exists(man):
                try:
                    os.remove(man)
                except Exception:
                    pass
        except Exception as e:
            self.log(f"❌ Failed to delete tiles: {e}")
            if GUI_AVAILABLE:
                messagebox.showerror("Error", f"Failed to delete tiles:\n{e}")
        finally:
            self.refresh_offgrid_stats()
            try:
                self._load_offgrid_log()
            except Exception:
                pass

    def _get_tiles_stats(self):
        """Return dict with size (bytes), count (.png files), and zoom levels present."""
        tiles_root = os.path.join(os.getcwd(), 'tiles')
        size = 0
        count = 0
        zooms = set()
        try:
            if os.path.isdir(tiles_root):
                # Collect zooms from first-level dirs
                for entry in os.listdir(tiles_root):
                    if entry.isdigit():
                        zooms.add(int(entry))
                for root, _dirs, files in os.walk(tiles_root):
                    for fn in files:
                        if fn.endswith('.png'):
                            count += 1
                            try:
                                size += os.path.getsize(os.path.join(root, fn))
                            except Exception:
                                pass
        except Exception:
            pass
        return {'size': size, 'count': count, 'zooms': zooms}

    def _format_bytes(self, n: int) -> str:
        for unit in ['B','KB','MB','GB','TB']:
            if n < 1024.0:
                return f"{n:.1f} {unit}"
            n /= 1024.0
        return f"{n:.1f} PB"

    def _record_offgrid_import(self, name: str, lat: float, lon: float, radius_km: float, zoom_levels):
        """Append a record of the import to tiles/manifest.log (for user visibility)."""
        try:
            tiles_dir = os.path.join(os.getcwd(), 'tiles')
            os.makedirs(tiles_dir, exist_ok=True)
            log_path = os.path.join(tiles_dir, 'manifest.log')
            rec = {
                'time': time.strftime('%Y-%m-%d %H:%M:%S'),
                'name': name,
                'lat': round(lat, 6),
                'lon': round(lon, 6),
                'radius_km': round(radius_km, 2),
                'zooms': zoom_levels,
            }
            with open(log_path, 'a', encoding='utf-8') as f:
                f.write(json.dumps(rec) + "\n")
        except Exception as e:
            self.log(f"⚠️ Could not write import log: {e}")

    def _load_offgrid_log(self):
        """Load last few import records into the offline panel text box."""
        try:
            tiles_dir = os.path.join(os.getcwd(), 'tiles')
            log_path = os.path.join(tiles_dir, 'manifest.log')
            lines = []
            if os.path.exists(log_path):
                with open(log_path, 'r', encoding='utf-8') as f:
                    lines = f.readlines()[-5:]
            display = []
            for ln in lines:
                try:
                    rec = json.loads(ln.strip())
                    display.append(f"{rec['time']} - {rec['name']} ({rec['radius_km']} km radius) z:{','.join(map(str, rec['zooms']))}")
                except Exception:
                    continue
            self.offgrid_log.configure(state='normal')
            self.offgrid_log.delete('1.0', tk.END)
            self.offgrid_log.insert('1.0', "\n".join(display) if display else "(no recent imports)")
            self.offgrid_log.configure(state='disabled')
        except Exception as e:
            self.log(f"⚠️ Could not load import log: {e}")

    def _ensure_local_leaflet_assets(self):
        """Download Leaflet JS/CSS to local static directory if missing."""
        try:
            static_dir = os.path.join(os.getcwd(), 'static', 'leaflet')
            os.makedirs(static_dir, exist_ok=True)
            files = {
                'leaflet.js': 'https://unpkg.com/leaflet@1.9.4/dist/leaflet.js',
                'leaflet.css': 'https://unpkg.com/leaflet@1.9.4/dist/leaflet.css',
            }
            for fname, url in files.items():
                fpath = os.path.join(static_dir, fname)
                if not os.path.exists(fpath):
                    self.log(f"⬇️ Downloading {fname}...")
                    r = requests.get(url, timeout=20)
                    r.raise_for_status()
                    with open(fpath, 'wb') as f:
                        f.write(r.content)
        except Exception as e:
            self.log(f"⚠️ Could not ensure local Leaflet assets: {e}")

    def _download_tiles(self, lat, lon, radius_km, zoom_levels):
        """Download OSM tiles to local tiles/ directory for given center/radius."""
        import math, time as _time
        def deg2num(lat_deg, lon_deg, zoom):
            lat_rad = math.radians(lat_deg)
            n = 2.0 ** zoom
            xtile = int((lon_deg + 180.0) / 360.0 * n)
            ytile = int((1.0 - math.asinh(math.tan(lat_rad)) / math.pi) / 2.0 * n)
            return (xtile, ytile)
        tiles_root = os.path.join(os.getcwd(), 'tiles')
        os.makedirs(tiles_root, exist_ok=True)
        lat_offset = radius_km / 111.0
        lon_offset = radius_km / (111.0 * math.cos(math.radians(lat)))
        north = lat + lat_offset
        south = lat - lat_offset
        east = lon + lon_offset
        west = lon - lon_offset
        headers = {'User-Agent': 'L76X-Offgrid-Importer/1.0'}
        total = 0
        downloaded = 0
        for z in zoom_levels:
            x_min, y_max = deg2num(north, west, z)
            x_max, y_min = deg2num(south, east, z)
            for x in range(min(x_min, x_max), max(x_min, x_max) + 1):
                for y in range(min(y_min, y_max), max(y_min, y_max) + 1):
                    total += 1
                    out_dir = os.path.join(tiles_root, str(z), str(x))
                    os.makedirs(out_dir, exist_ok=True)
                    out_path = os.path.join(out_dir, f"{y}.png")
                    if os.path.exists(out_path):
                        continue
                    url = f"https://tile.openstreetmap.org/{z}/{x}/{y}.png"
                    try:
                        r = requests.get(url, headers=headers, timeout=15)
                        if r.status_code == 200:
                            with open(out_path, 'wb') as f:
                                f.write(r.content)
                            downloaded += 1
                            if downloaded % 25 == 0:
                                self.log(f"Downloaded {downloaded} tiles…")
                        else:
                            # create small placeholder to avoid re-fetch loops
                            with open(out_path, 'wb') as f:
                                f.write(b'')
                    except Exception:
                        # backoff and continue
                        _time.sleep(0.2)
                        continue
                    _time.sleep(0.1)
        return total, downloaded

    def update_status(self):
        """Update status display"""
        # Server status
        if self.is_running:
            self.status_labels['server_status'].config(text="Running", foreground="green")
        else:
            self.status_labels['server_status'].config(text="Stopped", foreground="red")
        
        # GPS status and data
        if self.gps_reader and self.is_running:
            self.status_labels['gps_status'].config(text="Active", foreground="green")
            
            fix = self.gps_reader.get_fix()
            
            # GPS fix status
            if fix.get('valid'):
                self.status_labels['gps_fix'].config(text="Valid", foreground="green")
            else:
                self.status_labels['gps_fix'].config(text="No Fix", foreground="red")
            
            # Coordinates
            lat = fix.get('lat')
            lon = fix.get('lon')
            if lat is not None and lon is not None:
                self.status_labels['latitude'].config(text=f"{lat:.6f}°", foreground="black")
                self.status_labels['longitude'].config(text=f"{lon:.6f}°", foreground="black")
            else:
                self.status_labels['latitude'].config(text="N/A", foreground="gray")
                self.status_labels['longitude'].config(text="N/A", foreground="gray")
            
            # Speed
            speed_knots = fix.get('speed_knots', 0)
            speed_kmh = speed_knots * 1.852
            self.status_labels['speed'].config(text=f"{speed_kmh:.1f}", foreground="black")
            
            # Last update
            updated_at = fix.get('updated_at', 0)
            if updated_at > 0:
                last_update = time.strftime("%H:%M:%S", time.localtime(updated_at))
                age = time.time() - updated_at
                if age < 5:
                    color = "green"
                elif age < 30:
                    color = "orange"
                else:
                    color = "red"
                self.status_labels['last_update'].config(text=f"{last_update} ({age:.0f}s ago)", 
                                                        foreground=color)
            else:
                self.status_labels['last_update'].config(text="Never", foreground="gray")
        else:
            self.status_labels['gps_status'].config(text="Inactive", foreground="gray")
            self.status_labels['gps_fix'].config(text="N/A", foreground="gray")
            self.status_labels['latitude'].config(text="N/A", foreground="gray")
            self.status_labels['longitude'].config(text="N/A", foreground="gray")
            self.status_labels['speed'].config(text="N/A", foreground="gray")
            self.status_labels['last_update'].config(text="N/A", foreground="gray")
    
    def start_status_updates(self):
        """Start periodic status updates"""
        self.update_status()
        self.root.after(1000, self.start_status_updates)
    
    def on_closing(self):
        """Handle window closing"""
        if self.is_running:
            self.stop_gps_server()
        self.root.destroy()
    
    def run(self):
        """Run the GUI"""
        self.root.protocol("WM_DELETE_WINDOW", self.on_closing)
        self.root.mainloop()


def main():
    parser = argparse.ArgumentParser(description='Live GPS Map for Waveshare L76X')
    parser.add_argument('--device', default='/dev/serial0', help='Serial device for GPS')
    parser.add_argument('--baud', type=int, default=9600, help='Baud rate')
    parser.add_argument('--host', default='0.0.0.0', help='HTTP host to bind')
    parser.add_argument('--port', type=int, default=5000, help='HTTP port')
    parser.add_argument('--simulate', action='store_true', help='Run without hardware')
    parser.add_argument('--nogui', action='store_true', help='Run without GUI (command line mode)')
    args = parser.parse_args()
    
    # Check if GUI should be used
    if not args.nogui and GUI_AVAILABLE:
        # Run with GUI
        print("Starting GPS Controller with GUI...")
        app = GPSGUI()
        app.run()
    else:
        # Run in command line mode (original behavior)
        if not GUI_AVAILABLE:
            print("GUI not available (tkinter not installed). Running in command line mode.")
        
        gps_reader = GPSReader(device=args.device, baud=args.baud, simulate=args.simulate)
        gps_reader.start()
        server = ThreadingHTTPServer((args.host, args.port), RequestHandler)
        setattr(server, 'gps_reader', gps_reader)
        print(f"Serving GPS map on http://{args.host}:{args.port} ...")
        if not args.simulate and serial is None:
            print('ERROR: pyserial is required. Install with: pip3 install pyserial', file=sys.stderr)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass
        finally:
            print("Shutting down server…")
            server.shutdown()
            gps_reader.stop()
            try:
                gps_reader.join(timeout=2.0)
            except Exception:
                pass

if __name__ == '__main__':
    main()