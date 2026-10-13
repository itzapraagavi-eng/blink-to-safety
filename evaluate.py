"""
evaluate.py - Measures the ACCURACY of the system with a guided test.
This gives you the real numbers for the Results section of your paper,
and proves an ALERT driver does NOT get false alarms.

Trial types (random order). A voice tells you what to do. A HIGH double ding starts
each trial, a LOW ding ends it:
  DROWSY      close your eyes from the high ding to the low ding (4 s) -> should alarm
  HEAD DROP   drop your head forward with eyes closed, like dozing (5 s) -> should alarm
  AWAKE       normal driving actions (6 s)                          -> should NOT alarm
              blink normally / talk / smile / check left & right
              mirrors / glance at speedometer
  YAWN        yawn or open mouth wide (4 s)  -> yawn should be detected, NO alarm
  DISTRACT    turn your head to the side window (4 s) -> distraction alert, NO alarm

Run (ideally a few times, with different people and lighting):
    python evaluate.py --person P1 --condition "normal light"
    python evaluate.py --person P1 --condition "dim light"
    python evaluate.py --person P2 --condition "with glasses"
    python evaluate.py --person P1 --method cnn       (compare methods)
    python evaluate.py --quick                        (eyes only: drowsy + awake)

Press q to stop early (completed trials are still saved).
"""

import argparse
import csv
import os
import random
import time
from datetime import datetime

import cv2

from alarm import Alarm
from config import load_config
from detector import FaceEyeDetector
from eye_cnn import EyeCNN, decide_closed
from features import enhance_low_light
from monitor import DriverMonitor
from report import RESULTS_CSV, FIELDS, load_trials, make_report
from ui import FONT, GREEN, ORANGE, PURPLE, WHITE, YELLOW, _centered, _panel, draw_overlay
from voice import Voice

WINDOW = "Blink to Safety - Accuracy Test"
READY_SECONDS = 4.0      # countdown before each trial (the instruction is spoken here)
REST_SECONDS = 2.0       # pause after each trial

AWAKE_ACTIVITIES = [
    "Look ahead, blink normally",
    "TALK out loud (count 1 to 10)",
    "SMILE and laugh",
    "Look at the LEFT mirror for 1 second, then back",
    "Look at the RIGHT mirror for 1 second, then back",
    "Glance DOWN at the speedometer for 1 second, then back",
]
KIND_INFO = {   # instruction, colour, expected alarm
    "DROWSY": ("At the high ding CLOSE your eyes, open at the low ding", ORANGE, True),
    "HEAD_DROP": ("At the high ding DROP your head forward with eyes CLOSED (dozing)", ORANGE, True),
    "AWAKE": (None, GREEN, False),
    "YAWN": ("At the high ding YAWN (or open your mouth wide) for 2-3 s", YELLOW, False),
    "DISTRACT": ("At the high ding TURN YOUR HEAD to look out of the side window", PURPLE, False),
}


# Spoken instructions, because you cannot read the screen with your eyes
# closed or your head turned:  (before the trial, at the start, at the end)
SPEAK = {
    "DROWSY": ("Next. Close your eyes at the beep.", "Close your eyes.", "Open your eyes."),
    "HEAD_DROP": ("Next. Head down, eyes closed, like falling asleep.",
                  "Head down, eyes closed.", "Head up. Open your eyes."),
    "YAWN": ("Next. Yawn, or open your mouth wide.", "Yawn now.", "Stop."),
    "DISTRACT": ("Next. Turn your head to look out of the side window.",
                 "Turn your head away now.", "Look back at the screen."),
}
SPEAK_AWAKE = {
    "Look ahead, blink normally": "Next. Look ahead and blink normally.",
    "TALK out loud (count 1 to 10)": "Next. Count out loud from one to ten.",
    "SMILE and laugh": "Next. Smile and laugh.",
    "Look at the LEFT mirror for 1 second, then back": "Next. Glance at the left mirror for one second.",
    "Look at the RIGHT mirror for 1 second, then back": "Next. Glance at the right mirror for one second.",
    "Glance DOWN at the speedometer for 1 second, then back": "Next. Glance down at the speedometer for one second.",
}


def parse_args():
    p = argparse.ArgumentParser(description="Guided accuracy test")
    p.add_argument("--condition", default="normal light",
                   help='test condition label, e.g. "dim light" or "with glasses"')
    p.add_argument("--person", default="P1", help="tester name or id, e.g. P1, P2")
    p.add_argument("--trials", type=int, default=10,
                   help="number of DROWSY and of AWAKE trials (default 10 each)")
    p.add_argument("--extra", type=int, default=5,
                   help="number of HEAD DROP, YAWN and DISTRACT trials (default 5 each)")
    p.add_argument("--quick", action="store_true", help="only DROWSY and AWAKE trials")
    p.add_argument("--method", choices=["ear", "cnn", "hybrid"], default=None)
    p.add_argument("--close-time", type=float, default=4.0)
    p.add_argument("--head-time", type=float, default=5.0)
    p.add_argument("--awake-time", type=float, default=6.0)
    p.add_argument("--yawn-time", type=float, default=4.0)
    p.add_argument("--distract-time", type=float, default=4.0)
    p.add_argument("--camera", type=int, default=0)
    p.add_argument("--no-voice", action="store_true", help="no spoken instructions")
    p.add_argument("--config", default=None)
    p.add_argument("--model", default=None, help=argparse.SUPPRESS)
    return p.parse_args()


def build_trials(args):
    trials = [("DROWSY", "")] * args.trials
    trials += [("AWAKE", AWAKE_ACTIVITIES[i % len(AWAKE_ACTIVITIES)]) for i in range(args.trials)]
    if not args.quick:
        trials += [("HEAD_DROP", "")] * args.extra + [("YAWN", "")] * args.extra
        trials += [("DISTRACT", "")] * args.extra
    random.shuffle(trials)
    return trials


def main():
    args = parse_args()
    cfg = load_config(args.config)
    method = args.method or cfg["detection"]["method"]
    backend = cv2.CAP_DSHOW if os.name == "nt" else cv2.CAP_ANY
    cap = cv2.VideoCapture(args.camera, backend)
    if not cap.isOpened():
        cap = cv2.VideoCapture(args.camera)
    if not cap.isOpened():
        raise SystemExit("Could not open webcam %d" % args.camera)

    detector = FaceEyeDetector(args.model)
    cnn = EyeCNN(cfg["detection"]["cnn_model"]) if method in ("cnn", "hybrid") else None
    monitor = DriverMonitor(cfg)
    sound = Alarm(enabled=False)          # alarm muted; only the cue dings play
    voice = Voice(enabled=not args.no_voice, rate=170, lang="en")
    voice.say("Accuracy test. Look at the screen normally for a few seconds.")
    trials = build_trials(args)
    lengths = {"DROWSY": args.close_time, "HEAD_DROP": args.head_time,
               "AWAKE": args.awake_time, "YAWN": args.yawn_time,
               "DISTRACT": args.distract_time}

    results = []
    idx = 0
    # every trial is saved the moment it ends, so stopping early loses nothing
    os.makedirs(os.path.dirname(RESULTS_CSV), exist_ok=True)

    def save_trial(row):
        new_file = not os.path.exists(RESULTS_CSV)
        with open(RESULTS_CSV, "a", newline="") as f:
            w = csv.DictWriter(f, fieldnames=FIELDS)
            if new_file:
                w.writeheader()
            w.writerow(row)

    # frame-by-frame log of the test (to check any wrong trial afterwards)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    frames_path = os.path.join(os.path.dirname(RESULTS_CSV), "eval_frames_%s_%s.csv" % (
        args.person, stamp))
    frames_f = open(frames_path, "w", newline="")
    frames = csv.writer(frames_f)
    frames.writerow(["time_s", "trial", "kind", "phase", "ear", "threshold", "status",
                     "pitch_delta", "yaw_delta", "mar", "reason"])
    phase = "calibrate"            # calibrate -> ready -> trial -> rest -> ready ...
    phase_start = time.monotonic()
    ts = {}
    said_ready = False
    t0 = time.monotonic()
    cv2.namedWindow(WINDOW, cv2.WINDOW_NORMAL)
    print("Method %s | %d trials (about %d min)" % (method.upper(), len(trials),
                                                   round(len(trials) * 10 / 60)))

    try:
        while idx < len(trials):
            ok, frame = cap.read()
            if not ok:
                break
            frame = cv2.flip(frame, 1)
            frame, low, _ = enhance_low_light(frame, cfg["detection"]["low_light_threshold"])
            now = time.monotonic()
            face = detector.detect(frame)
            override = None
            if cnn is not None and face is not None:
                p_closed = cnn.prob_closed(frame, face)
                override = decide_closed(method, face["ear"], monitor.eyes.threshold, p_closed)
            st = monitor.update(face, now - t0, override)
            h, w = frame.shape[:2]
            kind, activity = trials[idx]
            elapsed = now - phase_start

            if phase == "calibrate":
                if not monitor.calibrating and (monitor.head.baseline is not None or elapsed > 10):
                    phase, phase_start = "ready", now
                    said_ready = False

            elif phase == "ready":
                if not said_ready:
                    voice.say(SPEAK[kind][0] if kind in SPEAK else SPEAK_AWAKE.get(activity, "Next. " + activity))
                    said_ready = True
                if elapsed >= READY_SECONDS:
                    sound.cue("start")
                    voice.say(SPEAK[kind][1] if kind in SPEAK else "Go.", urgent=True)
                    monitor.reset_events()
                    phase, phase_start = "trial", now
                    ts = {"first_sign": None, "alert_at": None, "reason": "", "yawn": False,
                          "distract": False}

            elif phase == "trial":
                head = st.get("head") or {}
                if ts["first_sign"] is None and (st.get("eyes_closed") or head.get("head_down")):
                    ts["first_sign"] = now
                if st["drowsy"] and ts["alert_at"] is None:
                    ts["alert_at"], ts["reason"] = now, st.get("drowsy_reason", "")
                if "yawn" in st.get("events", []):
                    ts["yawn"] = True
                if st.get("distracted"):
                    ts["distract"] = True
                if elapsed >= lengths[kind]:
                    sound.cue("end")
                    voice.say(SPEAK[kind][2] if kind in SPEAK else "Stop.", urgent=True)
                    expected = KIND_INFO[kind][2]
                    predicted = "DROWSY" if ts["alert_at"] else "AWAKE"
                    actual = "DROWSY" if expected else "AWAKE"
                    delay = ""
                    if ts["alert_at"] and ts["first_sign"]:
                        delay = round(ts["alert_at"] - ts["first_sign"], 3)
                    row = {
                        "date": datetime.now().strftime("%Y-%m-%d %H:%M"),
                        "person": args.person, "condition": args.condition,
                        "method": method.upper(), "trial": idx + 1, "kind": kind,
                        "activity": activity, "actual": actual, "predicted": predicted,
                        "correct": int(predicted == actual), "alert_delay_s": delay,
                        "reason": ts["reason"],
                        "yawn_detected": int(ts["yawn"]) if kind == "YAWN" else "",
                        "distract_detected": int(ts["distract"]),
                    }
                    results.append(row)
                    save_trial(row)
                    mark = "correct" if predicted == actual else "WRONG"
                    extra = ""
                    if kind == "YAWN":
                        extra = "  yawn %s" % ("detected" if ts["yawn"] else "MISSED")
                    if kind == "DISTRACT":
                        extra = "  distraction %s" % ("detected" if ts["distract"] else "MISSED")
                    elif kind == "AWAKE" and ts["distract"]:
                        extra = "  (distraction alert)"
                    alarm = ("yes (%s)" % ts["reason"]) if ts["alert_at"] else "no"
                    print("Trial %2d/%d  %-9s %-44s alarm=%-20s %s%s" % (
                        idx + 1, len(trials), kind, activity[:44], alarm, mark, extra))
                    phase, phase_start = "rest", now

            elif phase == "rest":
                if elapsed >= REST_SECONDS:
                    idx += 1
                    phase, phase_start = "ready", now
                    said_ready = False

            head_d = st.get("head") or {}
            frames.writerow([round(now - t0, 3), idx + 1, kind, phase,
                             "" if face is None else round(face["ear"], 4),
                             round(st["threshold"], 4), st["status"],
                             "" if head_d.get("pitch_delta") is None else round(head_d["pitch_delta"], 1),
                             "" if head_d.get("yaw_delta") is None else round(head_d["yaw_delta"], 1),
                             "" if face is None else round(face["mar"], 3),
                             st.get("drowsy_reason") or st.get("distract_reason") or ""])

            # ---------------- drawing ----------------
            draw_overlay(frame, st, face, 0, cfg["detection"]["closed_seconds"],
                         help_text=False, method=method.upper(), low_light=low)
            if phase != "calibrate" and idx < len(trials):
                instr, col, _ = KIND_INFO[kind]
                instr = instr or ("Keep eyes OPEN: " + activity)
                _panel(frame, 0, h - 120, w, 120)
                cv2.putText(frame, "Trial %d / %d   [%s | %s]" % (idx + 1, len(trials),
                            args.condition, method.upper()), (10, h - 92), FONT, 0.55,
                            WHITE, 1, cv2.LINE_AA)
                if phase == "ready":
                    _centered(frame, "Next: " + instr, h - 55, 0.55, col)
                    _centered(frame, "Starting in %d" % (READY_SECONDS - elapsed + 1),
                              h - 20, 0.7, YELLOW)
                elif phase == "trial":
                    _centered(frame, instr, h - 40, 0.6, col)
                elif phase == "rest":
                    _centered(frame, "Open your eyes, sit normally", h - 40, 0.75, WHITE)
            cv2.imshow(WINDOW, frame)
            key = cv2.waitKey(1) & 0xFF
            if key in (ord("q"), 27):
                print("Stopped early.")
                break
    except KeyboardInterrupt:
        print("\nStopped early (Ctrl+C). Completed trials are saved.")
    finally:
        voice.say("Test finished.")
        time.sleep(1.5)
        voice.close()
        frames_f.close()
        cap.release()
        detector.close()
        cv2.destroyAllWindows()

    if not results:
        print("No trials completed.")
        return

    print("Frame log for this test: %s" % frames_path)
    print("\nThis run (%s, %s, %s):" % (args.person, args.condition, method.upper()))
    make_report(results, save=False)
    print("\nAll runs so far (results/trials.csv):")
    make_report(load_trials(), save=True)


if __name__ == "__main__":
    main()
