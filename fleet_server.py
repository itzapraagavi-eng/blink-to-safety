"""
fleet_server.py - Fleet owner server + live dashboard for Blink to Safety.

Every vehicle running main.py (with fleet enabled) sends its live status,
alerts and trip reports here. The fleet owner opens the dashboard in any
browser (laptop or phone) to see all vehicles on a map, live alerts and
each driver's fatigue history.

Run:
    python fleet_server.py --key mysecret
    -> open http://localhost:8000 (or the network address it prints, on a phone
       connected to the same Wi-Fi), and enter the key.

In each vehicle (or the same laptop for the demo):
    python main.py --fleet http://<server-address>:8000 --key mysecret --driver "Ravi" --vehicle TN01AB1234

Extra demo vehicles (clearly marked SIM on the dashboard):
    python fleet_sim.py --key mysecret

Only Python's standard library is used (http.server + sqlite3).
Data is saved in fleet_data/fleet.db, trip reports in fleet_data/trips/.
"""

import argparse
import base64
import json
import mimetypes
import os
import socket
import sqlite3
import threading
import time
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))
DASH_DIR = os.path.join(PROJECT_DIR, "dashboard")
ONLINE_SECONDS = 10
POSITION_EVERY = 5          # store a trail point at most every 5 s per vehicle
KEEP_HOURS = 48


class Store:
    def __init__(self, data_dir):
        self.dir = data_dir
        os.makedirs(os.path.join(data_dir, "trips"), exist_ok=True)
        self.db = sqlite3.connect(os.path.join(data_dir, "fleet.db"), check_same_thread=False)
        self.lock = threading.Lock()
        with self.lock:
            self.db.executescript("""
            CREATE TABLE IF NOT EXISTS events (id INTEGER PRIMARY KEY AUTOINCREMENT,
                vehicle TEXT, driver TEXT, ts REAL, kind TEXT, detail TEXT,
                lat REAL, lon REAL, fatigue REAL, sim INTEGER);
            CREATE TABLE IF NOT EXISTS positions (vehicle TEXT, ts REAL, lat REAL, lon REAL,
                speed REAL, fatigue REAL, status TEXT);
            CREATE TABLE IF NOT EXISTS trips (id INTEGER PRIMARY KEY AUTOINCREMENT,
                vehicle TEXT, driver TEXT, start_ts REAL, end_ts REAL, summary TEXT,
                has_png INTEGER, sim INTEGER);
            CREATE INDEX IF NOT EXISTS ev_v ON events(vehicle, ts);
            CREATE INDEX IF NOT EXISTS pos_v ON positions(vehicle, ts);
            """)
            self.db.commit()
        self.live = {}                       # vehicle -> latest status dict
        self._last_pos = {}
        self.prune()

    def prune(self):
        cut = time.time() - KEEP_HOURS * 3600
        with self.lock:
            self.db.execute("DELETE FROM positions WHERE ts < ?", (cut,))
            self.db.commit()

    # ---- writes -------------------------------------------------------
    def status(self, d):
        v = str(d.get("vehicle") or "unknown")[:40]
        now = time.time()
        d["vehicle"] = v
        d["last_seen"] = now
        self.live[v] = d
        if now - self._last_pos.get(v, 0) >= POSITION_EVERY:
            self._last_pos[v] = now
            with self.lock:
                self.db.execute("INSERT INTO positions VALUES (?,?,?,?,?,?,?)",
                                (v, now, d.get("lat"), d.get("lon"), d.get("speed_kmh"),
                                 d.get("fatigue"), d.get("status")))
                self.db.commit()

    def event(self, d):
        with self.lock:
            cur = self.db.execute(
                "INSERT INTO events (vehicle, driver, ts, kind, detail, lat, lon, fatigue, sim) "
                "VALUES (?,?,?,?,?,?,?,?,?)",
                (str(d.get("vehicle"))[:40], str(d.get("driver", ""))[:60], self._ts(d.get("ts")),
                 str(d.get("kind"))[:30], str(d.get("detail", ""))[:200], d.get("lat"),
                 d.get("lon"), d.get("fatigue"), int(bool(d.get("sim")))))
            self.db.commit()
            return cur.lastrowid

    @staticmethod
    def _ts(ts):
        """Use the vehicle's own time for the event (events sent late after a
        network drop keep their real time), unless its clock looks wrong."""
        now = time.time()
        try:
            ts = float(ts)
        except (TypeError, ValueError):
            return now
        return ts if abs(now - ts) < 86400 else now

    def trip(self, d):
        png = d.pop("png_b64", None)
        with self.lock:
            cur = self.db.execute(
                "INSERT INTO trips (vehicle, driver, start_ts, end_ts, summary, has_png, sim) "
                "VALUES (?,?,?,?,?,?,?)",
                (str(d.get("vehicle"))[:40], str(d.get("driver", ""))[:60], d.get("start_ts"),
                 d.get("end_ts"), json.dumps(d.get("summary", {})), int(bool(png)),
                 int(bool(d.get("sim")))))
            self.db.commit()
            tid = cur.lastrowid
        if png:
            with open(os.path.join(self.dir, "trips", "%d.png" % tid), "wb") as f:
                f.write(base64.b64decode(png))
        return tid

    # ---- reads --------------------------------------------------------
    def fleet(self):
        now = time.time()
        midnight = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0).timestamp()
        with self.lock:
            rows = self.db.execute(
                "SELECT vehicle, kind, COUNT(*) FROM events WHERE ts >= ? GROUP BY vehicle, kind",
                (midnight,)).fetchall()
        today = {}
        for v, k, n in rows:
            today.setdefault(v, {})[k] = n
        out = []
        for v, d in self.live.items():
            item = dict(d)
            item["online"] = now - d["last_seen"] <= ONLINE_SECONDS
            item["seen_ago"] = round(now - d["last_seen"], 1)
            item["today"] = today.get(v, {})
            out.append(item)
        out.sort(key=lambda x: (not x["online"], -(x.get("level") or 0), x["vehicle"]))
        return {"server_time": now, "vehicles": out}

    def events(self, since=0, limit=100, vehicle=None):
        q = "SELECT id, vehicle, driver, ts, kind, detail, lat, lon, fatigue, sim FROM events WHERE id > ?"
        args = [since]
        if vehicle:
            q += " AND vehicle = ?"
            args.append(vehicle)
        q += " ORDER BY id DESC LIMIT ?"
        args.append(limit)
        with self.lock:
            rows = self.db.execute(q, args).fetchall()
        keys = ["id", "vehicle", "driver", "ts", "kind", "detail", "lat", "lon", "fatigue", "sim"]
        return [dict(zip(keys, r)) for r in rows]

    def vehicle(self, v):
        now = time.time()
        with self.lock:
            trail = self.db.execute(
                "SELECT ts, lat, lon, speed, fatigue, status FROM positions "
                "WHERE vehicle = ? AND ts >= ? ORDER BY ts", (v, now - 3600)).fetchall()
            trips = self.db.execute(
                "SELECT id, start_ts, end_ts, summary, has_png FROM trips WHERE vehicle = ? "
                "ORDER BY id DESC LIMIT 10", (v,)).fetchall()
        return {
            "state": self.live.get(v),
            "trail": [[r[0], r[1], r[2], r[3], r[4], r[5]] for r in trail],
            "events": self.events(0, 60, v),
            "trips": [{"id": t[0], "start_ts": t[1], "end_ts": t[2],
                       "summary": json.loads(t[3] or "{}"), "has_png": bool(t[4])} for t in trips],
        }


def make_handler(store, key):
    class Handler(BaseHTTPRequestHandler):
        server_version = "BlinkFleet/1.0"

        def log_message(self, fmt, *args):     # keep the console quiet
            pass

        def _send(self, code, body, ctype="application/json"):
            if isinstance(body, (dict, list)):
                body = json.dumps(body).encode()
            elif isinstance(body, str):
                body = body.encode()
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def _authed(self, query):
            given = self.headers.get("X-Fleet-Key") or (query.get("key") or [""])[0]
            return given == key

        def do_GET(self):
            url = urlparse(self.path)
            q = parse_qs(url.query)
            path = url.path
            if path in ("/", "/index.html"):
                path = "/index.html"
            if not path.startswith("/api/"):
                return self._static(path)
            if not self._authed(q):
                return self._send(401, {"error": "wrong key"})
            if path == "/api/fleet":
                return self._send(200, store.fleet())
            if path == "/api/events":
                return self._send(200, store.events(int((q.get("since") or ["0"])[0]),
                                                    min(200, int((q.get("limit") or ["100"])[0])),
                                                    (q.get("vehicle") or [None])[0]))
            if path == "/api/vehicle":
                return self._send(200, store.vehicle((q.get("id") or [""])[0]))
            if path == "/api/trip_png":
                p = os.path.join(store.dir, "trips", "%d.png" % int((q.get("id") or ["0"])[0]))
                if os.path.exists(p):
                    with open(p, "rb") as f:
                        return self._send(200, f.read(), "image/png")
                return self._send(404, {"error": "not found"})
            return self._send(404, {"error": "unknown"})

        def do_POST(self):
            url = urlparse(self.path)
            if not self._authed(parse_qs(url.query)):
                return self._send(401, {"error": "wrong key"})
            n = int(self.headers.get("Content-Length") or 0)
            if n > 8 * 1024 * 1024:
                return self._send(413, {"error": "too large"})
            try:
                data = json.loads(self.rfile.read(n).decode() or "{}")
            except json.JSONDecodeError:
                return self._send(400, {"error": "bad json"})
            if url.path == "/api/status":
                store.status(data)
                return self._send(200, {"ok": True})
            if url.path == "/api/event":
                items = data if isinstance(data, list) else [data]
                ids = [store.event(d) for d in items]
                return self._send(200, {"ok": True, "ids": ids})
            if url.path == "/api/trip":
                return self._send(200, {"ok": True, "id": store.trip(data)})
            return self._send(404, {"error": "unknown"})

        def _static(self, path):
            full = os.path.normpath(os.path.join(DASH_DIR, path.lstrip("/")))
            if not full.startswith(DASH_DIR + os.sep) or not os.path.isfile(full):
                return self._send(404, "not found", "text/plain")
            ctype = mimetypes.guess_type(full)[0] or "application/octet-stream"
            with open(full, "rb") as f:
                self._send(200, f.read(), ctype)
    return Handler


def lan_address():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return None


def main():
    from config import load_config
    cfg = load_config()
    p = argparse.ArgumentParser(description="Blink to Safety fleet server + dashboard")
    p.add_argument("--port", type=int, default=8000)
    p.add_argument("--key", default=cfg["fleet"]["key"], help="access key for vehicles and dashboard")
    p.add_argument("--data", default=os.path.join(PROJECT_DIR, "fleet_data"))
    args = p.parse_args()
    store = Store(args.data)
    srv = ThreadingHTTPServer(("0.0.0.0", args.port), make_handler(store, args.key))
    ip = lan_address()
    print("Blink to Safety - Fleet server running")
    print("  Dashboard on this computer : http://localhost:%d" % args.port)
    if ip:
        print("  Dashboard on phone / Wi-Fi : http://%s:%d" % (ip, args.port))
    print("  Access key                 : %s" % args.key)
    print("  Vehicles connect with      : python main.py --fleet http://%s:%d --key %s"
          % (ip or "localhost", args.port, args.key))
    print("Press Ctrl+C to stop.")

    def housekeeping():
        while True:
            time.sleep(3600)
            store.prune()
    threading.Thread(target=housekeeping, daemon=True).start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")


if __name__ == "__main__":
    main()
