"""
collect_eyes.py - Records labelled OPEN and CLOSED eye images from your
webcam, to train the CNN eye-state model (train_cnn.py).

    python collect_eyes.py --person P1
    python collect_eyes.py --person P1 --condition dim      (again in dim light)
    python collect_eyes.py --person P2                      (a friend)

What happens:
  1. 3 s calibration (eyes open, look at the camera)
  2. OPEN phase (20 s): keep your eyes open and look around naturally,
     like driving: road, mirrors, dashboard. Blinking is fine - blink
     frames are filtered out automatically.
  3. CLOSED phase: 6 rounds. Close your eyes at the ding, open at the next
     ding (about 4 s each). Move your head a little between rounds.

Images are saved to data/eyes/open and data/eyes/closed (32x32 grey).
EAR is used to double-check each label, so wrong frames are skipped.
More people + more lighting conditions = a better model.
"""

import argparse
import os
import time

import cv2

from alarm import Alarm
from detector import EyeStateTracker, FaceEyeDetector
from features import eye_crop
from ui import FONT, GREEN, ORANGE, WHITE, YELLOW, _centered, _panel, draw_eyes

PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))
WINDOW = "Blink to Safety - Collect eye images"


def main():
    p = argparse.ArgumentParser(description="Record open/closed eye images for the CNN")
    p.add_argument("--person", default="P1", help="name or id of the person")
    p.add_argument("--condition", default="normal", help="e.g. normal, dim, glasses")
    p.add_argument("--open-seconds", type=float, default=20)
    p.add_argument("--rounds", type=int, default=6, help="number of eyes-closed rounds")
    p.add_argument("--closed-seconds", type=float, default=4)
    p.add_argument("--camera", type=int, default=0)
    p.add_argument("--out", default=os.path.join(PROJECT_DIR, "data", "eyes"))
    p.add_argument("--model", default=None, help=argparse.SUPPRESS)
    args = p.parse_args()

    for label in ("open", "closed"):
        os.makedirs(os.path.join(args.out, label), exist_ok=True)
    backend = cv2.CAP_DSHOW if os.name == "nt" else cv2.CAP_ANY
    cap = cv2.VideoCapture(args.camera, backend)
    if not cap.isOpened():
        cap = cv2.VideoCapture(args.camera)
    if not cap.isOpened():
        raise SystemExit("Could not open webcam %d" % args.camera)

    detector = FaceEyeDetector(args.model)
    tracker = EyeStateTracker()
    sound = Alarm(enabled=False)
    stamp = time.strftime("%H%M%S")
    counts = {"open": 0, "closed": 0}

    # plan: list of (phase, seconds)
    plan = [("calibrate", None), ("ready_open", 3), ("open", args.open_seconds)]
    for _ in range(args.rounds):
        plan += [("ready_closed", 3), ("closed", args.closed_seconds), ("rest", 2)]
    step, step_start, frame_i = 0, time.monotonic(), 0
    t0 = time.monotonic()
    cv2.namedWindow(WINDOW, cv2.WINDOW_NORMAL)

    def save(frame, face, label):
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        for side, eye in zip(("R", "L"), face["eyes"]):
            crop = eye_crop(gray, eye)
            if crop is not None:
                name = "%s_%s_%s_%05d_%s.png" % (args.person, args.condition, stamp,
                                                 counts[label], side)
                cv2.imwrite(os.path.join(args.out, label, name), crop)
        counts[label] += 1

    try:
        while step < len(plan):
            ok, frame = cap.read()
            if not ok:
                break
            frame = cv2.flip(frame, 1)
            now = time.monotonic()
            face = detector.detect(frame)
            st = tracker.update(face["ear"] if face else None, now - t0)
            phase, length = plan[step]
            elapsed = now - step_start
            frame_i += 1

            if phase == "calibrate":
                done = not tracker.calibrating
            else:
                done = elapsed >= length
            # record (every 2nd frame, EAR double-checks the label)
            if face is not None and frame_i % 2 == 0 and not tracker.calibrating:
                thr = tracker.threshold
                if phase == "open" and face["ear"] > thr * 1.05:
                    save(frame, face, "open")
                elif phase == "closed" and elapsed > 0.7 and face["ear"] < thr * 0.85:
                    save(frame, face, "closed")

            # drawing (before the eyes outline, so saved crops stay clean)
            view = frame.copy()
            if face is not None:
                draw_eyes(view, face["eyes"], GREEN if not st["eyes_closed"] else ORANGE)
            h, w = view.shape[:2]
            _panel(view, 0, 0, 300, 60)
            cv2.putText(view, "Open: %d   Closed: %d" % (counts["open"], counts["closed"]),
                        (10, 24), FONT, 0.6, WHITE, 1, cv2.LINE_AA)
            cv2.putText(view, "Person %s  [%s]" % (args.person, args.condition), (10, 48),
                        FONT, 0.5, WHITE, 1, cv2.LINE_AA)
            _panel(view, 0, h - 80, w, 80)
            msg = {
                "calibrate": ("Calibrating - look at the camera, eyes open", YELLOW),
                "ready_open": ("Next: keep eyes OPEN, look around like driving", GREEN),
                "open": ("Eyes OPEN - look at road, mirrors, dashboard", GREEN),
                "ready_closed": ("Next: CLOSE eyes at the high ding, open at the low ding", ORANGE),
                "closed": ("Eyes CLOSED...", ORANGE),
                "rest": ("Open your eyes, move your head a little", WHITE),
            }[phase]
            _centered(view, msg[0], h - 45, 0.6, msg[1])
            if length:
                _centered(view, "%d" % max(0, length - elapsed + 1), h - 12, 0.6, WHITE, 1)
            cv2.imshow(WINDOW, view)
            if (cv2.waitKey(1) & 0xFF) in (ord("q"), 27):
                break

            if done:
                step += 1
                step_start = now
                if step < len(plan) and plan[step][0] == "closed":
                    sound.cue("start")
                if step < len(plan) and plan[step][0] == "rest":
                    sound.cue("end")
    finally:
        cap.release()
        detector.close()
        cv2.destroyAllWindows()

    print("Saved %d open and %d closed frames (x2 eyes) to %s" %
          (counts["open"], counts["closed"], args.out))
    print("Next: python train_cnn.py")


if __name__ == "__main__":
    main()
