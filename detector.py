"""
detector.py - Face landmarks and eye-closure logic of "Blink to Safety"

  1. FaceEyeDetector : finds the face in a video frame (MediaPipe Face
                       Landmarker, 478 points) and measures the eyes (EAR),
                       the mouth (MAR) and the head pose.
  2. EyeStateTracker : turns each frame's eye measurement into a decision:
                       AWAKE / EYES CLOSED / DROWSY, and counts blinks.

Eye Aspect Ratio (Soukupova & Cech, 2016):

            |p2 - p6| + |p3 - p5|           p2   p3
    EAR = -------------------------      p1          p4
                 2 * |p1 - p4|               p6   p5

    Eyes open   -> EAR is roughly constant (about 0.25 - 0.35)
    Eyes closed -> EAR drops close to 0
"""

import os
import time
import urllib.request

import cv2
import numpy as np
import mediapipe as mp
from mediapipe.tasks import python as mp_python
from mediapipe.tasks.python import vision

from features import HeadPoseEstimator, mouth_aspect_ratio

# ---------------------------------------------------------------------------
# Model file (downloaded automatically the first time, about 3.6 MB)
# ---------------------------------------------------------------------------
PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))
MODEL_PATH = os.path.join(PROJECT_DIR, "models", "face_landmarker.task")
MODEL_URL = ("https://storage.googleapis.com/mediapipe-models/face_landmarker/"
             "face_landmarker/float16/1/face_landmarker.task")

# MediaPipe face-mesh landmark numbers for the 6 eye points, in the order
# p1 (outer corner), p2, p3 (upper lid), p4 (inner corner), p5, p6 (lower lid)
RIGHT_EYE = [33, 160, 158, 133, 153, 144]
LEFT_EYE = [362, 385, 387, 263, 373, 380]

# Default settings (config.json can change them)
DEFAULT_EAR_THRESHOLD = 0.21    # used only if calibration is skipped
DEFAULT_CLOSED_SECONDS = 1.5    # eyes closed this long = drowsy
CALIBRATION_SECONDS = 3.0       # time spent learning the driver's normal face
CALIBRATION_FACTOR = 0.65       # threshold = 65% of the driver's normal EAR
                                # (tuned on real webcam data: 75% gave many false
                                #  "closed" frames, 60% started missing real closures)
SLOW_BLINK_SECONDS = 0.5        # closures longer than this are "slow blinks"


def ensure_model():
    """Download the face landmark model if it is not already in models/."""
    if os.path.exists(MODEL_PATH):
        return MODEL_PATH
    os.makedirs(os.path.dirname(MODEL_PATH), exist_ok=True)
    print("Downloading face landmark model (one time only, ~3.6 MB)...")
    try:
        urllib.request.urlretrieve(MODEL_URL, MODEL_PATH)
    except Exception as exc:
        if os.path.exists(MODEL_PATH):
            os.remove(MODEL_PATH)
        raise SystemExit(
            "\nCould not download the model automatically: %s\n"
            "Download it manually from:\n  %s\n"
            "and save it as:\n  %s\n" % (exc, MODEL_URL, MODEL_PATH))
    print("Model saved to", MODEL_PATH)
    return MODEL_PATH


def eye_aspect_ratio(eye_points):
    """eye_points: array of 6 (x, y) points in the order p1..p6."""
    p1, p2, p3, p4, p5, p6 = eye_points
    vertical_1 = np.linalg.norm(p2 - p6)
    vertical_2 = np.linalg.norm(p3 - p5)
    horizontal = np.linalg.norm(p1 - p4)
    if horizontal == 0:
        return 0.0
    return float((vertical_1 + vertical_2) / (2.0 * horizontal))


def measure_face(pts, frame_w, frame_h, pose_estimator):
    """All measurements from one face's landmarks (pixel coordinates)."""
    right, left = pts[RIGHT_EYE], pts[LEFT_EYE]
    pose = pose_estimator.estimate(pts, frame_w, frame_h)
    return {
        "pts": pts,
        "eyes": (right, left),
        "ear": (eye_aspect_ratio(right) + eye_aspect_ratio(left)) / 2.0,
        "mar": mouth_aspect_ratio(pts),
        "pose": pose,                       # (pitch, yaw, roll) or None
    }


class FaceEyeDetector:
    """Finds the face and measures eyes, mouth and head in each video frame."""

    def __init__(self, model_path=None):
        model_path = model_path or ensure_model()
        options = vision.FaceLandmarkerOptions(
            base_options=mp_python.BaseOptions(model_asset_path=model_path),
            running_mode=vision.RunningMode.VIDEO,
            num_faces=1,
            min_face_detection_confidence=0.5,
            min_face_presence_confidence=0.5,
            min_tracking_confidence=0.5,
        )
        self.landmarker = vision.FaceLandmarker.create_from_options(options)
        self.pose = HeadPoseEstimator()
        self._start = time.monotonic()
        self._last_ts = -1

    def detect(self, frame_bgr):
        """Returns a dict (see measure_face) or None if no face is found."""
        # MediaPipe VIDEO mode needs strictly increasing timestamps (ms)
        ts = int((time.monotonic() - self._start) * 1000)
        if ts <= self._last_ts:
            ts = self._last_ts + 1
        self._last_ts = ts

        rgb = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)
        image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)
        result = self.landmarker.detect_for_video(image, ts)
        if not result.face_landmarks:
            self.pose.reset()
            return None

        h, w = frame_bgr.shape[:2]
        pts = np.array([[lm.x * w, lm.y * h] for lm in result.face_landmarks[0]])
        return measure_face(pts, w, h, self.pose)

    def close(self):
        self.landmarker.close()


class EyeStateTracker:
    """
    Decides the eye state from each frame.

    States:
      CALIBRATING  - learning this driver's normal open-eye EAR
      AWAKE        - eyes open
      EYES CLOSED  - eyes closed, but not yet long enough to be drowsy (a blink)
      DROWSY       - eyes closed for >= closed_seconds  -> raise alarm
      NO FACE      - face not visible
    """

    def __init__(self, ear_threshold=None, closed_seconds=DEFAULT_CLOSED_SECONDS,
                 calibrate=True, calibration_seconds=CALIBRATION_SECONDS):
        self.closed_seconds = closed_seconds
        self.calibration_seconds = calibration_seconds
        self.fixed_threshold = ear_threshold
        self.threshold = ear_threshold or DEFAULT_EAR_THRESHOLD
        self.baseline_ear = None
        self.calibrating = calibrate and ear_threshold is None
        self._calib_samples = []
        self._calib_start = None
        self.reset()

    # -- control -----------------------------------------------------------
    def reset(self):
        """Clear blink / drowsy state (keeps the calibrated threshold)."""
        self.closed_since = None
        self.drowsy = False
        self.blink_count = 0
        self.monitor_start = None

    def start_calibration(self):
        if self.fixed_threshold is None:
            self.calibrating = True
            self._calib_samples = []
            self._calib_start = None

    # -- main update -------------------------------------------------------
    def update(self, ear, now=None, closed=None, thr_scale=1.0):
        """
        Feed one frame's EAR (or None if no face). `closed` can override the
        EAR test (used when the CNN model decides open/closed). Returns a
        dict describing the eye state. `now` is a time in seconds.
        """
        now = time.monotonic() if now is None else now

        if ear is None:
            # Face lost: do not raise alarm, just report it
            self.closed_since = None
            self.drowsy = False
            return self._state("NO FACE", ear, 0.0)

        if self.calibrating:
            if self._calib_start is None:
                self._calib_start = now
            self._calib_samples.append(ear)
            elapsed = now - self._calib_start
            if elapsed >= self.calibration_seconds and len(self._calib_samples) >= 10:
                # median ignores the few frames where the driver blinked
                self.baseline_ear = float(np.median(self._calib_samples))
                self.threshold = float(np.clip(
                    self.baseline_ear * CALIBRATION_FACTOR, 0.12, 0.28))
                self.calibrating = False
                self.reset()
            st = self._state("CALIBRATING", ear, 0.0)
            st["calibration_progress"] = min(1.0, elapsed / self.calibration_seconds)
            return st

        if self.monitor_start is None:
            self.monitor_start = now

        # thr_scale < 1 when the driver looks down: the eyelids naturally
        # lower then, which must not count as closed eyes
        eyes_closed = (ear < self.threshold * thr_scale) if closed is None else bool(closed)
        if eyes_closed:
            if self.closed_since is None:
                self.closed_since = now
            closed_for = now - self.closed_since
            started = False
            if closed_for >= self.closed_seconds and not self.drowsy:
                self.drowsy = started = True
            st = self._state("DROWSY" if self.drowsy else "EYES CLOSED", ear, closed_for)
            st["drowsy_started"] = started
            return st

        # eyes are open
        blink_dur = None
        if self.closed_since is not None and not self.drowsy:
            self.blink_count += 1          # short closure = blink
            blink_dur = now - self.closed_since
        self.closed_since = None
        self.drowsy = False
        st = self._state("AWAKE", ear, 0.0)
        st["blink_duration"] = blink_dur
        return st

    def blinks_per_minute(self, now=None):
        if self.monitor_start is None:
            return 0.0
        now = time.monotonic() if now is None else now
        minutes = max((now - self.monitor_start) / 60.0, 1e-6)
        return self.blink_count / minutes if minutes > 0.25 else 0.0

    def _state(self, status, ear, closed_for):
        return {
            "status": status,
            "ear": ear,
            "threshold": self.threshold,
            "closed_for": closed_for,
            "eyes_closed": status in ("EYES CLOSED", "DROWSY"),
            "drowsy": status == "DROWSY",
            "drowsy_started": False,
            "blink_duration": None,
            "blinks": self.blink_count,
        }
