"""
fleet_sim.py - Adds simulated vehicles to the fleet dashboard for a demo.

    python fleet_sim.py --key mysecret
    python fleet_sim.py --key mysecret --vehicles 3 --server http://192.168.1.5:8000

Every simulated vehicle is marked "SIM" on the dashboard, so it is always
clear which vehicle is real (your laptop running main.py) and which are not.
Each one drives along a real Tamil Nadu highway and gets more tired over
time, with yawns, nods, distractions and drowsy alarms.
"""

import argparse
import copy
import random
import time

from config import load_config
from drive_context import DriveContext
from fleet_client import FleetClient
from gps import GPSReader

FLEET = [   # name, vehicle number, route, how sleepy (0 fresh .. 1 very sleepy)
    ("Arun Kumar", "TN09BX4521", "chennai_trichy", 0.85),
    ("Priya S", "TN22CK7788", "chennai_pondy", 0.15),
    ("Karthik R", "TN07AQ3310", "chennai_vellore", 0.55),
    ("Meena V", "TN58DF1209", "madurai_dindigul", 0.35),
    ("Suresh P", "TN45AZ6643", "chennai_trichy", 0.25),
]


class SimVehicle:
    def __init__(self, cfg, name, number, route, sleepy, rng):
        c = copy.deepcopy(cfg)
        c["driver"] = {"name": name, "vehicle": number}
        c["gps"]["sim_route"] = route
        self.client = FleetClient(c, sim=True)
        self.gps = GPSReader(c, "sim")
        self.gps._t0 -= rng.uniform(0, 3600)            # start somewhere along the route
        self.drive = DriveContext(c, driven_hours=rng.uniform(0.2, 1.7))
        self.rng, self.sleepy = rng, sleepy
        self.fatigue = 5 + 25 * sleepy
        self.counts = {"blinks": 0, "yawns": 0, "nods": 0, "drowsy_events": 0, "distractions": 0}
        self.state, self.state_until, self.reason = "AWAKE", 0, ""
        self.level = 0
        self.alarm_times = []
        self.t0 = time.monotonic()

    def step(self, now):
        r, s = self.rng, self.sleepy
        ctx = self.drive.update(now - self.t0, True)
        loc = self.gps.latest()
        ev = []
        self.counts["blinks"] += r.random() < 0.3
        # tiredness drifts towards a level that depends on the driver (and
        # slowly rises over the drive); events push it up for a while
        target = 12 + 55 * s + min(15, (now - self.t0) / 120)
        self.fatigue += (target - self.fatigue) * 0.015 + r.uniform(-0.8, 0.8)
        if self.state == "AWAKE" and now >= self.state_until:
            p = r.random()
            if p < 0.004 + 0.010 * s:
                ev.append(("yawn", "")); self.counts["yawns"] += 1; self.fatigue += 6
            elif p < 0.007 + 0.018 * s:
                ev.append(("nod", "")); self.counts["nods"] += 1; self.fatigue += 8
            elif p < 0.008 + 0.024 * s and self.fatigue > 55:
                self.state, self.state_until, self.reason = "DROWSY", now + r.uniform(2, 4), "Eyes closed"
                ev.append(("drowsy", self.reason)); self.counts["drowsy_events"] += 1
                self.fatigue += 12
                self.alarm_times = [t for t in self.alarm_times if now - t < 600] + [now]
                if len(self.alarm_times) == 3:
                    ev.append(("emergency", "3 drowsy alarms in 10 minutes - Telegram alert sent"))
            elif r.random() < 0.002 + 0.002 * s:            # about once every 5-8 minutes
                self.state, self.state_until, self.reason = "DISTRACTED", now + r.uniform(2.5, 4), "Looking away"
                ev.append(("distracted", self.reason)); self.counts["distractions"] += 1
        elif self.state != "AWAKE" and now >= self.state_until:
            self.state, self.reason = "AWAKE", ""
            self.state_until = now + 2
            if r.random() < 0.15 and self.fatigue > 70:      # driver takes a rest
                self.fatigue = 15
                ev.append(("break_taken", "Driver took a break"))
        self.fatigue = max(3.0, min(100.0, self.fatigue + ctx["score_bonus"] * 0.002))
        lvl = 2 if self.fatigue >= 65 else 1 if self.fatigue >= 35 else 0
        if lvl > self.level:
            ev.append(("tired" if lvl == 1 else "very_tired", "Fatigue %d" % self.fatigue))
        self.level = lvl
        for k in ctx["events"]:
            if k in ("long_drive", "night"):
                ev.append((k, ""))
        st = dict(self.counts, status=self.state,
                  level=3 if self.state == "DROWSY" else lvl, fatigue=self.fatigue,
                  perclos=min(0.4, self.fatigue / 400), drive_time=ctx["drive_time"],
                  risk_hours=ctx["risk_hours"], drowsy_reason=self.reason if self.state == "DROWSY" else "",
                  distract_reason=self.reason if self.state == "DISTRACTED" else "")
        self.client.update(st, loc, {"method": "SIM", "lang": "-"})
        for k, d in ev:
            self.client.event(k, d, st, loc)


def main():
    cfg = load_config()
    p = argparse.ArgumentParser(description="Simulated vehicles for the fleet dashboard demo")
    p.add_argument("--server", default="http://localhost:8000")
    p.add_argument("--key", default=cfg["fleet"]["key"])
    p.add_argument("--vehicles", type=int, default=4, help="how many (max %d)" % len(FLEET))
    p.add_argument("--seed", type=int, default=None)
    args = p.parse_args()
    cfg["fleet"].update(enabled=True, server=args.server, key=args.key, update_seconds=2)
    rng = random.Random(args.seed)
    fleet = [SimVehicle(cfg, *f, rng=random.Random(rng.random())) for f in FLEET[:args.vehicles]]
    print("Simulating %d vehicles -> %s  (Ctrl+C to stop)" % (len(fleet), args.server))
    for v in fleet:
        print("  SIM  %-11s %-12s %s" % (v.client.vehicle, v.client.driver, v.gps.cfg["sim_route"]))
    try:
        while True:
            now = time.monotonic()
            for v in fleet:
                v.step(now)
            time.sleep(1)
    except KeyboardInterrupt:
        for v in fleet:
            v.client.close()
        print("Stopped.")


if __name__ == "__main__":
    main()
