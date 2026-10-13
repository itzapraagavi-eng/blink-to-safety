"""
main.py - Live demo of "Blink to Safety: Preventing Road Accidents Using
AI-Based Fatigue Detection".

Run:
    python main.py                    # laptop webcam, EAR method
    python main.py --method cnn       # use the trained CNN eye model
    python main.py --method hybrid    # EAR + CNN together
    python main.py --camera 1         # external USB webcam
    python main.py --video demo.mp4   # recorded video (backup for demo day)
    python main.py --pi               # Raspberry Pi: buzzer, LED, alcohol sensor
    python main.py --lang ta          # Tamil voice alerts (hi = Hindi, en = English)
    python main.py --clock 02:30 --driven 2   # demo: pretend 2:30 AM, 2 hours driven
    python main.py --gps nmea         # GPS module (also: ip, fixed, sim)
    python main.py --fleet http://SERVER:8000 --key KEY --driver "Ravi" --vehicle TN01AB1234
                                      # send live status to the fleet owner dashboard

Keys while running:
    q = quit   c = recalibrate   m = mute alarm   v = voice on/off

When you quit, a trip report (results/trip_report_*.png) and an EAR log
(logs/session_*.csv) are saved automatically.
"""

import argparse
import csv
import os
import time
from datetime import datetime

import cv2

from alarm import Alarm
from alerts import AlertManager
from config import PROJECT_DIR, load_config
from detector import FaceEyeDetector
from drive_context import DriveContext
from emergency import EmergencyAlert
from fleet_client import FleetClient
from gps import GPSReader
from eye_cnn import EyeCNN, decide_closed
from features import enhance_low_light
from monitor import LEVEL_NAMES, DriverMonitor
from pi_hardware import PiHardware
from trip_report import make_trip_report, print_summary
from ui import draw_overlay
from voice import Voice

WINDOW = "Blink to Safety - Driver Drowsiness Detection"
LOG_FIELDS = ["time_s", "ear", "mar", "pitch_delta", "yaw_delta", "p_closed", "threshold",
              "status", "level", "fatigue", "perclos", "blinks", "drive_time",
              "lat", "lon", "speed_kmh", "events"]


def parse_args():
    p = argparse.ArgumentParser(description="Real-time driver drowsiness detection")
    p.add_argument("--camera", type=int, default=0, help="webcam number (default 0)")
    p.add_argument("--video", help="use a video file instead of the webcam")
    p.add_argument("--method", choices=["ear", "cnn", "hybrid"], default=None,
                   help="eye open/closed method (default from config.json: ear)")
    p.add_argument("--threshold", type=float, default=None,
                   help="fixed EAR threshold (skips auto calibration), e.g. 0.21")
    p.add_argument("--seconds", type=float, default=None,
                   help="eyes closed this many seconds = drowsy (default 1.5)")
    p.add_argument("--width", type=int, default=640, help="camera width (default 640)")
    p.add_argument("--height", type=int, default=480, help="camera height (default 480)")
    p.add_argument("--mute", action="store_true", help="start with alarm muted")
    p.add_argument("--no-voice", action="store_true", help="turn off spoken alerts")
    p.add_argument("--lang", choices=["en", "ta", "hi"], default=None,
                   help="voice language: en English, ta Tamil, hi Hindi")
    p.add_argument("--clock", default=None,
                   help="demo: pretend the time is HH:MM (e.g. 02:30 for night risk)")
    p.add_argument("--driven", type=float, default=0.0,
                   help="demo: hours already driven (e.g. 2 for a break reminder)")
    p.add_argument("--gps", choices=["none", "nmea", "ip", "fixed", "sim"], default=None,
                   help="location source (default from config.json)")
    p.add_argument("--fleet", default=None, metavar="URL",
                   help="fleet server address, e.g. http://192.168.1.5:8000")
    p.add_argument("--key", default=None, help="fleet server access key")
    p.add_argument("--driver", default=None, help="driver name (fleet + emergency)")
    p.add_argument("--vehicle", default=None, help="vehicle number, e.g. TN01AB1234")
    p.add_argument("--pi", action="store_true", help="enable Raspberry Pi hardware")
    p.add_argument("--picam", action="store_true", help="use the Raspberry Pi camera module")
    p.add_argument("--headless", action="store_true", help="no video window (in-car Pi box)")
    p.add_argument("--no-log", action="store_true", help="do not save logs / trip report")
    p.add_argument("--config", default=None, help="settings file (default config.json)")
    p.add_argument("--model", default=None, help=argparse.SUPPRESS)
    return p.parse_args()


class PiCamera:
    """Raspberry Pi camera module through picamera2 (same read() as OpenCV)."""

    def __init__(self, w, h):
        from picamera2 import Picamera2
        self.cam = Picamera2()
        self.cam.configure(self.cam.create_preview_configuration(
            main={"format": "RGB888", "size": (w, h)}))   # gives BGR order for OpenCV
        self.cam.start()

    def isOpened(self):
        return True

    def read(self):
        return True, self.cam.capture_array()

    def get(self, prop):
        return 0

    def release(self):
        self.cam.stop()


def open_source(args):
    if args.video:
        cap = cv2.VideoCapture(args.video)
        if not cap.isOpened():
            raise SystemExit("Could not open video file: " + args.video)
        return cap
    if args.picam:
        return PiCamera(args.width, args.height)
    # CAP_DSHOW opens webcams much faster on Windows
    backend = cv2.CAP_DSHOW if os.name == "nt" else cv2.CAP_ANY
    cap = cv2.VideoCapture(args.camera, backend)
    if not cap.isOpened():
        cap = cv2.VideoCapture(args.camera)
    if not cap.isOpened():
        raise SystemExit("Could not open webcam %d. Try --camera 1" % args.camera)
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, args.width)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, args.height)
    return cap


def main():
    args = parse_args()
    cfg = load_config(args.config)
    det = cfg["detection"]
    if args.method:
        det["method"] = args.method
    if args.seconds:
        det["closed_seconds"] = args.seconds
    if args.threshold:
        det["ear_threshold"] = args.threshold
    if args.no_voice:
        cfg["alerts"]["voice"] = False
    if args.lang:
        cfg["alerts"]["language"] = args.lang
    if args.pi:
        cfg["raspberry_pi"]["enabled"] = True
    if args.gps:
        cfg["gps"]["source"] = args.gps
    if args.fleet:
        cfg["fleet"].update(enabled=True, server=args.fleet)
    if args.key:
        cfg["fleet"]["key"] = args.key
    if args.driver:
        cfg["driver"]["name"] = args.driver
    if args.vehicle:
        cfg["driver"]["vehicle"] = args.vehicle.upper().replace(" ", "")
    method = det["method"]
    show = not args.headless

    cap = open_source(args)
    video_fps = cap.get(cv2.CAP_PROP_FPS) if args.video else 0
    if args.video and (not video_fps or video_fps <= 1):
        video_fps = 30.0

    detector = FaceEyeDetector(args.model)
    cnn = EyeCNN(det["cnn_model"]) if method in ("cnn", "hybrid") else None
    monitor = DriverMonitor(cfg)
    alarm = Alarm(enabled=not args.mute)
    lang = cfg["alerts"]["language"]
    voice = Voice(cfg["alerts"]["voice"], cfg["alerts"]["voice_rate"], lang)
    drive = DriveContext(cfg, args.clock, args.driven)
    emergency = EmergencyAlert(cfg)
    pi = PiHardware(cfg)
    alerts = AlertManager(cfg, alarm, voice, emergency, pi)
    gps = GPSReader(cfg)
    fleet = FleetClient(cfg)
    trip_start = time.time()
    fleet.event("trip_start", "Monitoring started")
    prev_emergency, prev_alcohol = 0, False

    log_rows = []
    prev_status, prev_level = None, 0
    frame_no = 0
    t_start = time.monotonic()
    fps, fps_t, fps_n = 0.0, time.monotonic(), 0

    if show:
        cv2.namedWindow(WINDOW, cv2.WINDOW_NORMAL)
    print("Method: %s | Voice: %s (%s) | Emergency alert: %s | Raspberry Pi: %s" % (
        method.upper(), "on" if voice.enabled else "off", lang,
        "on" if emergency.enabled else "off", "on" if pi.enabled else "off"))
    print("Driver: %s (%s) | GPS: %s | Fleet: %s" % (
        cfg["driver"]["name"], cfg["driver"]["vehicle"], gps.source,
        cfg["fleet"]["server"] if fleet.enabled else "off"))
    print("Look at the camera with your eyes open for 3 seconds to calibrate.")
    try:
        while True:
            ok, frame = cap.read()
            if not ok:
                break
            if not args.video:
                frame = cv2.flip(frame, 1)       # mirror image feels natural

            # time in seconds: real clock for camera, frame time for video files
            now = frame_no / video_fps if args.video else time.monotonic() - t_start
            frame_no += 1

            frame, low_light, _ = enhance_low_light(frame, det["low_light_threshold"])
            face = detector.detect(frame)

            p_closed, override = None, None
            if cnn is not None and face is not None:
                p_closed = cnn.prob_closed(frame, face)
                override = decide_closed(method, face["ear"], monitor.eyes.threshold, p_closed)

            ctx = drive.update(now, face is not None)
            st = monitor.update(face, now, override, ctx)
            loc = gps.latest()
            info = alerts.handle(st, frame, now, loc)

            # ---- send to the fleet owner dashboard ----
            fleet.update(st, loc, {"method": method.upper(), "lang": lang.upper(),
                                   "gps_status": gps.status})
            for e in st.get("events", []):
                if e == "drowsy":
                    fleet.event("drowsy", st["drowsy_reason"], st, loc)
                elif e == "distracted":
                    fleet.event("distracted", st["distract_reason"], st, loc)
                elif e == "level_up":
                    fleet.event("tired" if st.get("fatigue_level") == 1 else "very_tired",
                                "Fatigue %d" % st["fatigue"], st, loc)
                elif e in ("yawn", "nod", "long_drive", "night", "break_taken"):
                    fleet.event(e, "", st, loc)
            if alerts.emergency_sent > prev_emergency:
                fleet.event("emergency", "Telegram alert sent to contact", st, loc)
                prev_emergency = alerts.emergency_sent
            if info.get("alcohol") and not prev_alcohol:
                fleet.event("alcohol", "MQ-3 sensor", st, loc)
            prev_alcohol = info.get("alcohol", False)

            if st["drowsy"] and prev_status != "DROWSY":
                print("[%6.1fs] DROWSY (%s) - alarm on" % (now, st["drowsy_reason"]))
            fl = st.get("fatigue_level", 0)
            if fl > prev_level:
                print("[%6.1fs] Fatigue %d -> %s" % (now, st["fatigue"], LEVEL_NAMES[fl]))
            for e in st.get("events", []):
                if e in ("yawn", "nod"):
                    print("[%6.1fs] %s detected" % (now, e))
                elif e == "distracted":
                    print("[%6.1fs] DISTRACTED (%s)" % (now, st["distract_reason"]))
                elif e == "long_drive":
                    print("[%6.1fs] Break reminder (driving %.1f h)" % (now, st["drive_time"] / 3600))
                elif e == "night":
                    print("[%6.1fs] Night risk hours: higher sensitivity" % now)
                elif e == "break_taken":
                    print("[%6.1fs] Break detected - drive timer reset" % now)
            prev_status, prev_level = st["status"], fl

            head = st.get("head") or {}
            log_rows.append([
                round(now, 3), "" if face is None else round(face["ear"], 4),
                "" if face is None else round(face["mar"], 3),
                "" if head.get("pitch_delta") is None else round(head["pitch_delta"], 1),
                "" if head.get("yaw_delta") is None else round(head["yaw_delta"], 1),
                "" if p_closed is None else round(p_closed, 3),
                round(st["threshold"], 4), st["status"], st.get("level", 0),
                round(st.get("fatigue", 0.0), 1), round(st.get("perclos", 0.0), 3),
                st["blinks"], round(st.get("drive_time", 0.0)),
                "" if not loc else round(loc["lat"], 6), "" if not loc else round(loc["lon"], 6),
                "" if not loc or loc["speed_kmh"] is None else round(loc["speed_kmh"], 1),
                "|".join(st.get("events", []))])

            fps_n += 1
            if time.monotonic() - fps_t >= 1.0:
                fps = fps_n / (time.monotonic() - fps_t)
                fps_t, fps_n = time.monotonic(), 0

            if not show:
                continue
            draw_overlay(frame, st, face, fps, det["closed_seconds"],
                         monitor.eyes.blinks_per_minute(now), muted=not alarm.enabled,
                         method=method.upper(), low_light=low_light, alert_info=info,
                         lang=lang.upper(), location=loc, gps_status=gps.status,
                         fleet_state=(fleet.online if fleet.enabled else None))
            cv2.imshow(WINDOW, frame)
            key = cv2.waitKey(1) & 0xFF
            if key in (ord("q"), 27):
                break
            if key == ord("c"):
                monitor.recalibrate()
            if key == ord("m"):
                alarm.toggle_mute()
            if key == ord("v"):
                voice.enabled = not voice.enabled
            if cv2.getWindowProperty(WINDOW, cv2.WND_PROP_VISIBLE) < 1:
                break
    except KeyboardInterrupt:
        pass
    finally:
        alerts.stop()
        voice.close()
        gps.close()
        pi.close()
        cap.release()
        detector.close()
        if show:
            cv2.destroyAllWindows()

    print("\n--- Session summary ---")
    if monitor.eyes.baseline_ear:
        print("Normal EAR      : %.3f  ->  threshold %.3f" % (monitor.eyes.baseline_ear,
                                                            monitor.eyes.threshold))
    print("Blinks counted  : %d" % monitor.eyes.blink_count)
    if alerts.emergency_sent:
        print("Emergency alerts: %d" % alerts.emergency_sent)

    if not args.no_log and log_rows:
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        os.makedirs(os.path.join(PROJECT_DIR, "logs"), exist_ok=True)
        path = os.path.join(PROJECT_DIR, "logs", "session_%s.csv" % stamp)
        with open(path, "w", newline="") as f:
            w = csv.writer(f)
            w.writerow(LOG_FIELDS)
            w.writerows(log_rows)
        rows = [dict(zip(LOG_FIELDS, [str(v) for v in r])) for r in log_rows]
        out = os.path.join(PROJECT_DIR, "results", "trip_report_%s.png" % stamp)
        s = make_trip_report(rows, out,
                             os.path.join(PROJECT_DIR, "results", "trip_events_%s.csv" % stamp),
                             "%s  |  method: %s  |  voice: %s%s" % (
                                 drive.clock().strftime("%d %b %Y, %I:%M %p"), method.upper(),
                                 lang.upper(), "  |  night risk hours" if drive.in_risk_hours() else ""))
        if s:
            print_summary(s)
            print("Trip report     : %s" % out)
            if fleet.enabled:
                summary = {k: s[k] for k in ("duration", "alarms", "yawns", "nods", "distractions",
                                             "avg_fatigue", "max_fatigue", "perclos", "distance_km")
                           if k in s}
                ok = fleet.upload_trip(summary, out, trip_start, time.time())
                print("Fleet dashboard : %s" % ("trip report uploaded" if ok else "upload failed"))
        print("Session log     : %s" % path)
    fleet.event("trip_end", "Monitoring stopped")
    fleet.close()


if __name__ == "__main__":
    main()
