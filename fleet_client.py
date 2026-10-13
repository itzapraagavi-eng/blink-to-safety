"""
fleet_client.py - Sends this vehicle's live status, alerts and trip report
to the fleet server (fleet_server.py).

Everything runs in a background thread, so a slow or lost internet
connection never freezes the camera. Alerts that cannot be sent are kept
(up to 500) and delivered when the connection comes back.
"""

import base64
import json
import threading
import time
import urllib.request
from collections import deque


class FleetClient:
    def __init__(self, cfg, sim=False):
        f = cfg["fleet"]
        self.enabled = bool(f.get("enabled"))
        self.server = f["server"].rstrip("/")
        self.key = f["key"]
        self.interval = float(f.get("update_seconds", 2))
        self.upload_report = f.get("upload_trip_report", True)
        self.vehicle = cfg["driver"]["vehicle"] or "VEHICLE"
        self.driver = cfg["driver"]["name"] or "Driver"
        self.sim = sim
        self.online = False
        self.last_error = ""
        self._status = None
        self._events = deque(maxlen=500)
        self._lock = threading.Lock()
        self._stop = threading.Event()
        if self.enabled:
            threading.Thread(target=self._loop, daemon=True).start()

    # ---- called from main.py ------------------------------------------
    def update(self, st, location=None, extra=None):
        if not self.enabled:
            return
        loc = location or {}
        d = {
            "vehicle": self.vehicle, "driver": self.driver, "sim": self.sim,
            "status": st.get("status"), "level": st.get("level", 0),
            "fatigue": round(st.get("fatigue", 0.0), 1),
            "perclos": round(st.get("perclos", 0.0), 3),
            "blinks": st.get("blinks", 0), "yawns": st.get("yawns", 0),
            "nods": st.get("nods", 0), "alarms": st.get("drowsy_events", 0),
            "distractions": st.get("distractions", 0),
            "drive_time": round(st.get("drive_time", 0.0)),
            "risk_hours": bool(st.get("risk_hours")),
            "reason": st.get("drowsy_reason") or st.get("distract_reason") or "",
            "lat": loc.get("lat"), "lon": loc.get("lon"),
            "speed_kmh": None if loc.get("speed_kmh") is None else round(loc["speed_kmh"], 1),
            "gps_source": loc.get("source"),
        }
        if extra:
            d.update(extra)
        with self._lock:
            self._status = d

    def event(self, kind, detail="", st=None, location=None):
        if not self.enabled:
            return
        loc = location or {}
        with self._lock:
            self._events.append({
                "vehicle": self.vehicle, "driver": self.driver, "sim": self.sim,
                "kind": kind, "detail": detail, "ts": time.time(),
                "lat": loc.get("lat"), "lon": loc.get("lon"),
                "fatigue": None if st is None else round(st.get("fatigue", 0.0), 1)})

    def upload_trip(self, summary, png_path=None, start_ts=None, end_ts=None):
        """Called once at the end of the drive (waits up to ~10 s)."""
        if not self.enabled:
            return False
        self._flush_events()
        body = {"vehicle": self.vehicle, "driver": self.driver, "sim": self.sim,
                "start_ts": start_ts, "end_ts": end_ts or time.time(), "summary": summary}
        if png_path and self.upload_report:
            try:
                with open(png_path, "rb") as f:
                    body["png_b64"] = base64.b64encode(f.read()).decode()
            except OSError:
                pass
        try:
            self._post("/api/trip", body, timeout=10)
            return True
        except Exception as exc:
            print("[fleet] could not upload trip report:", exc)
            return False

    def close(self):
        if not self.enabled:
            return
        self._stop.set()
        self._flush_events()

    # ---- background ---------------------------------------------------
    def _post(self, path, body, timeout=4):
        req = urllib.request.Request(self.server + path, data=json.dumps(body).encode(),
                                     headers={"Content-Type": "application/json",
                                              "X-Fleet-Key": self.key})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode() or "{}")

    def _flush_events(self):
        with self._lock:
            batch = list(self._events)
        if not batch:
            return True
        try:
            self._post("/api/event", batch)
            with self._lock:
                for _ in range(len(batch)):
                    self._events.popleft()
            return True
        except Exception as exc:
            self._fail(exc)
            return False

    def _fail(self, exc):
        msg = str(getattr(exc, "reason", exc))
        if "401" in str(exc):
            msg = "wrong key"
        if self.online or msg != self.last_error:
            print("[fleet] server not reachable (%s) - will keep trying" % msg)
        self.online = False
        self.last_error = msg

    def _loop(self):
        wait = self.interval
        while not self._stop.is_set():
            with self._lock:
                status = self._status
            ok = True
            if status is not None:
                try:
                    self._post("/api/status", status)
                    if not self.online:
                        print("[fleet] connected to", self.server)
                    self.online = True
                except Exception as exc:
                    self._fail(exc)
                    ok = False
            if ok:
                ok = self._flush_events()
            wait = self.interval if ok else min(30.0, wait * 2)   # back off when offline
            self._stop.wait(wait)
