"""
gps.py - Vehicle location for emergency messages, trip reports and the
fleet dashboard.

Sources (config.json -> "gps" -> "source", or  python main.py --gps <source>):
  nmea   a GPS module (NEO-6M on the Raspberry Pi, or any USB GPS dongle).
         Reads the standard NMEA sentences ($GPRMC / $GNRMC, $GPGGA) through
         the serial port. Needs:  pip install pyserial
  ip     approximate location (city level) from the internet connection.
         Good enough to show "near Chennai" - not for an exact position.
  fixed  a fixed latitude/longitude from config.json (e.g. the college).
  sim    a simulated drive along a real highway (demo only - clearly marked
         "SIM" everywhere it is shown).
  none   no location.

Test a GPS module:   python gps.py --source nmea
"""

import argparse
import json
import math
import threading
import time
import urllib.request

# Approximate highway waypoints (lat, lon) for the demo simulation
SIM_ROUTES = {
    "chennai_vellore": [(13.0694, 80.1948), (13.0473, 80.0945), (12.9675, 79.9419),
                        (12.9440, 79.7800), (12.9230, 79.3664), (12.9165, 79.1325)],
    "chennai_pondy": [(12.9830, 80.2594), (12.7894, 80.2526), (12.6208, 80.1945),
                      (12.5236, 80.1569), (12.1920, 79.9500), (11.9416, 79.8083)],
    "chennai_trichy": [(12.9249, 80.1000), (12.6921, 79.9762), (12.2340, 79.6550),
                       (11.9401, 79.4861), (11.6700, 79.2900), (11.2333, 78.8833),
                       (10.7905, 78.7047)],
    "madurai_dindigul": [(9.9252, 78.1198), (10.0800, 77.9600), (10.3673, 77.9803)],
}


def haversine_km(a, b):
    """Distance in km between two (lat, lon) points."""
    lat1, lon1, lat2, lon2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    h = (math.sin((lat2 - lat1) / 2) ** 2 +
         math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2)
    return 6371.0 * 2 * math.asin(math.sqrt(h))


def maps_link(lat, lon):
    return "https://maps.google.com/?q=%.6f,%.6f" % (lat, lon)


# ---------------------------------------------------------------- NMEA parsing
def _nmea_checksum_ok(line):
    if "*" not in line:
        return True
    body, cs = line[1:].split("*", 1)
    calc = 0
    for ch in body:
        calc ^= ord(ch)
    try:
        return calc == int(cs[:2], 16)
    except ValueError:
        return False


def _nmea_coord(value, hemi):
    """'1258.0500','N' -> 12.9675 (NMEA uses degrees + minutes)."""
    if not value:
        return None
    dot = value.index(".") if "." in value else len(value)
    deg = float(value[:dot - 2])
    minutes = float(value[dot - 2:])
    v = deg + minutes / 60.0
    return -v if hemi in ("S", "W") else v


def parse_nmea(line):
    """Returns a dict for RMC / GGA sentences, or None."""
    line = line.strip()
    if not line.startswith("$") or not _nmea_checksum_ok(line):
        return None
    parts = line.split("*")[0].split(",")
    kind = parts[0][3:]
    try:
        if kind == "RMC" and len(parts) >= 8:
            if parts[2] != "A":                      # A = valid fix, V = no fix
                return {"type": "RMC", "fix": False}
            return {"type": "RMC", "fix": True,
                    "lat": _nmea_coord(parts[3], parts[4]),
                    "lon": _nmea_coord(parts[5], parts[6]),
                    "speed_kmh": float(parts[7] or 0) * 1.852}   # knots -> km/h
        if kind == "GGA" and len(parts) >= 8:
            q = int(parts[6] or 0)
            return {"type": "GGA", "fix": q > 0, "satellites": int(parts[7] or 0),
                    "lat": _nmea_coord(parts[2], parts[3]) if q else None,
                    "lon": _nmea_coord(parts[4], parts[5]) if q else None}
    except (ValueError, IndexError):
        return None
    return None


# ---------------------------------------------------------------- reader
class GPSReader:
    def __init__(self, cfg, source=None):
        g = cfg["gps"]
        self.source = source or g["source"]
        self.cfg = g
        self._lock = threading.Lock()
        self._pos = None              # latest dict
        self.status = "off"
        self.distance_km = 0.0
        self._last_pt = None
        self._running = True
        self.satellites = 0
        if self.source == "fixed":
            self._set(g["fixed_lat"], g["fixed_lon"], 0.0)
            self.status = "fixed"
        elif self.source == "sim":
            route = SIM_ROUTES.get(g.get("sim_route"), SIM_ROUTES["chennai_vellore"])
            self._route = route
            self._legs = [haversine_km(route[i], route[i + 1]) for i in range(len(route) - 1)]
            self._t0 = time.monotonic()
            self.status = "sim"
            self._tick_sim()
        elif self.source in ("nmea", "ip"):
            self.status = "searching"
            target = self._run_nmea if self.source == "nmea" else self._run_ip
            threading.Thread(target=target, daemon=True).start()

    # -- public --------------------------------------------------------
    @property
    def enabled(self):
        return self.source != "none"

    def latest(self):
        """{'lat', 'lon', 'speed_kmh', 'source', 'age_s'} or None."""
        if self.source == "sim":
            self._tick_sim()
        with self._lock:
            if self._pos is None:
                return None
            p = dict(self._pos)
        p["age_s"] = time.monotonic() - p.pop("_t")
        if self.source == "nmea" and p["age_s"] > 10:
            self.status = "lost"
        return p

    def close(self):
        self._running = False

    # -- internal ------------------------------------------------------
    def _set(self, lat, lon, speed, moving_filter=True):
        if lat is None or lon is None:
            return
        with self._lock:
            pt = (lat, lon)
            if self._last_pt is not None and self.source in ("nmea", "sim"):
                d = haversine_km(self._last_pt, pt)
                # ignore GPS jitter while parked
                if not moving_filter or speed is None or speed > 3 or d > 0.02:
                    if d < 2.0:                     # ignore impossible jumps
                        self.distance_km += d
                    self._last_pt = pt
            else:
                self._last_pt = pt
            self._pos = {"lat": lat, "lon": lon, "speed_kmh": speed,
                         "source": self.source, "_t": time.monotonic()}

    def _tick_sim(self):
        """Moves along the route at a realistic, slowly changing speed."""
        t = time.monotonic() - self._t0
        speed = 62 + 10 * math.sin(t / 23.0) + 4 * math.sin(t / 7.0)      # km/h
        # distance driven: integral of the speed (closed form of the sines)
        km = (62 * t - 10 * 23.0 * (math.cos(t / 23.0) - 1) - 4 * 7.0 * (math.cos(t / 7.0) - 1)) / 3600.0
        total = sum(self._legs)
        km = km % total if total else 0
        for (a, b), leg in zip(zip(self._route, self._route[1:]), self._legs):
            if km <= leg:
                f = km / leg if leg else 0
                self._set(a[0] + (b[0] - a[0]) * f, a[1] + (b[1] - a[1]) * f, speed,
                          moving_filter=False)
                return
            km -= leg

    def _open_serial(self):
        import serial
        from serial.tools import list_ports
        port = self.cfg.get("port", "auto")
        if port and port != "auto":
            candidates = [port]
        else:
            candidates = ["/dev/serial0", "/dev/ttyAMA0", "/dev/ttyUSB0", "/dev/ttyACM0"]
            candidates += [p.device for p in list_ports.comports()]
        for c in candidates:
            try:
                s = serial.Serial(c, self.cfg.get("baud", 9600), timeout=1)
                deadline = time.monotonic() + 3
                while time.monotonic() < deadline:   # is it really a GPS?
                    line = s.readline().decode("ascii", "ignore")
                    if line.startswith("$G"):
                        print("[gps] GPS module found on", c)
                        return s
                s.close()
            except Exception:
                continue
        return None

    def _run_nmea(self):
        try:
            import serial  # noqa: F401
        except ImportError:
            print("[gps] pyserial missing: pip install pyserial")
            self.status = "error"
            return
        ser = None
        while self._running:
            if ser is None:
                ser = self._open_serial()
                if ser is None:
                    self.status = "no module"
                    time.sleep(5)
                    continue
            try:
                line = ser.readline().decode("ascii", "ignore")
            except Exception:
                ser = None
                self.status = "lost"
                continue
            d = parse_nmea(line)
            if not d:
                continue
            if d["type"] == "GGA":
                self.satellites = d["satellites"]
            if d["type"] == "RMC":
                if d["fix"]:
                    self._set(d["lat"], d["lon"], d["speed_kmh"])
                    self.status = "ok"
                else:
                    self.status = "searching"

    def _run_ip(self):
        urls = ["https://ipapi.co/json/", "http://ip-api.com/json/"]
        while self._running:
            for u in urls:
                try:
                    req = urllib.request.Request(u, headers={"User-Agent": "BlinkToSafety/1.0"})
                    with urllib.request.urlopen(req, timeout=8) as r:
                        j = json.loads(r.read().decode())
                    lat = j.get("latitude", j.get("lat"))
                    lon = j.get("longitude", j.get("lon"))
                    if lat is not None and lon is not None:
                        self._set(float(lat), float(lon), None)
                        self.status = "approx"
                        break
                except Exception:
                    continue
            else:
                self.status = "offline"
            for _ in range(600):                     # refresh every 10 minutes
                if not self._running:
                    return
                time.sleep(1)


if __name__ == "__main__":
    from config import load_config
    ap = argparse.ArgumentParser(description="Test the GPS")
    ap.add_argument("--source", default=None, choices=["nmea", "ip", "fixed", "sim"])
    a = ap.parse_args()
    g = GPSReader(load_config(), a.source)
    print("Source:", g.source, "(Ctrl+C to stop)")
    try:
        while True:
            p = g.latest()
            if p:
                spd = "%.0f km/h" % p["speed_kmh"] if p["speed_kmh"] is not None else "-"
                print("%-9s %.5f, %.5f  %s  sats %d  driven %.2f km  %s" % (
                    g.status, p["lat"], p["lon"], spd, g.satellites, g.distance_km,
                    maps_link(p["lat"], p["lon"])))
            else:
                print(g.status, "... waiting for a fix (go near a window / outside)")
            time.sleep(2)
    except KeyboardInterrupt:
        pass
