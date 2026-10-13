"""
features.py - Extra face measurements used by Blink to Safety.

  * mouth_aspect_ratio()  - how wide the mouth is open (yawn detection)
  * HeadPoseEstimator     - head pitch / yaw / roll in degrees (nod detection)
  * eye_crop()            - small grey eye image for the CNN eye-state model
  * enhance_low_light()   - brightens dark frames (night driving)
"""

import cv2
import numpy as np

# ---------------------------------------------------------------- landmarks
# Inner lip points: corners and three vertical pairs
MOUTH_CORNERS = (78, 308)
MOUTH_PAIRS = [(81, 178), (13, 14), (311, 402)]

# Points used for head pose (nose tip, chin, outer eye corners, mouth corners)
NOSE_TIP, CHIN = 1, 152
EYE_OUTER = (33, 263)
MOUTH_OUTER = (61, 291)

# Average 3-D face (millimetre-like units), in camera axes:
# x to the right, y downward, z away from the camera. Nose tip is the origin.
_MODEL_NOSE = (0.0, 0.0, 0.0)
_MODEL_CHIN = (0.0, 330.0, 65.0)
_MODEL_EYE = (225.0, -170.0, 135.0)      # x sign set per side
_MODEL_MOUTH = (150.0, 150.0, 125.0)     # x sign set per side


def mouth_aspect_ratio(pts):
    """pts: all face landmarks as an (N, 2) array in pixels.
    About 0.0 - 0.1 with the mouth closed, 0.1 - 0.4 while talking,
    and above 0.5 for a wide yawn."""
    left, right = pts[MOUTH_CORNERS[0]], pts[MOUTH_CORNERS[1]]
    width = np.linalg.norm(left - right)
    if width == 0:
        return 0.0
    vertical = np.mean([np.linalg.norm(pts[a] - pts[b]) for a, b in MOUTH_PAIRS])
    return float(vertical / width)


def mouth_outline(pts):
    ids = [78, 81, 13, 311, 308, 402, 14, 178]
    return pts[ids]


class HeadPoseEstimator:
    """Estimates head rotation with OpenCV solvePnP (Perspective-n-Point):
    it finds the 3-D rotation that makes an average face model line up with
    the 6 detected 2-D points."""

    def __init__(self):
        self._rvec = None
        self._tvec = None

    def estimate(self, pts, frame_w, frame_h):
        """Returns (pitch, yaw, roll) in degrees. Pitch grows when the head
        bends DOWN, yaw when it turns, roll when it tilts sideways."""
        # assign left/right model points by image position, so it also works
        # on a mirrored (flipped) webcam image
        e1, e2 = pts[EYE_OUTER[0]], pts[EYE_OUTER[1]]
        m1, m2 = pts[MOUTH_OUTER[0]], pts[MOUTH_OUTER[1]]
        eye_l, eye_r = (e1, e2) if e1[0] < e2[0] else (e2, e1)
        mouth_l, mouth_r = (m1, m2) if m1[0] < m2[0] else (m2, m1)

        image_pts = np.array([pts[NOSE_TIP], pts[CHIN], eye_l, eye_r,
                              mouth_l, mouth_r], dtype=np.float64)
        ex, ey, ez = _MODEL_EYE
        mx, my, mz = _MODEL_MOUTH
        model_pts = np.array([_MODEL_NOSE, _MODEL_CHIN, (-ex, ey, ez), (ex, ey, ez),
                              (-mx, my, mz), (mx, my, mz)], dtype=np.float64)

        focal = float(frame_w)
        cam = np.array([[focal, 0, frame_w / 2.0],
                        [0, focal, frame_h / 2.0],
                        [0, 0, 1]], dtype=np.float64)
        dist = np.zeros((4, 1))
        if self._rvec is None:
            # start from "face looking straight at the camera" at the right
            # distance; this stops solvePnP from picking a flipped answer
            eye_px = max(1.0, float(np.linalg.norm(eye_r - eye_l)))
            z0 = focal * (2 * ex) / eye_px
            nose = image_pts[0]
            rvec0 = np.zeros((3, 1))
            tvec0 = np.array([[(nose[0] - frame_w / 2.0) * z0 / focal],
                              [(nose[1] - frame_h / 2.0) * z0 / focal], [z0]])
        else:   # start from last frame's answer: smoother and faster
            rvec0, tvec0 = self._rvec, self._tvec
        ok, rvec, tvec = cv2.solvePnP(model_pts, image_pts, cam, dist,
                                      rvec0.copy(), tvec0.copy(), True,
                                      flags=cv2.SOLVEPNP_ITERATIVE)
        if not ok or tvec[2, 0] <= 0:
            self.reset()
            return None
        self._rvec, self._tvec = rvec, tvec
        rot, _ = cv2.Rodrigues(rvec)
        pitch, yaw, roll = cv2.RQDecomp3x3(rot)[0]   # degrees about x, y, z
        return float(pitch), float(yaw), float(roll)

    def reset(self):
        self._rvec = self._tvec = None


def eye_crop(gray, eye_pts, size=32):
    """Square grey crop around one eye, resized to size x size.
    The same function is used for collecting training data and for live
    prediction, so the CNN always sees images prepared the same way."""
    cx, cy = eye_pts.mean(axis=0)
    width = np.linalg.norm(eye_pts[0] - eye_pts[3])
    half = max(4.0, width * 0.8)
    h, w = gray.shape[:2]
    x1, y1 = int(max(0, cx - half)), int(max(0, cy - half))
    x2, y2 = int(min(w, cx + half)), int(min(h, cy + half))
    if x2 - x1 < 4 or y2 - y1 < 4:
        return None
    crop = cv2.resize(gray[y1:y2, x1:x2], (size, size), interpolation=cv2.INTER_AREA)
    return cv2.equalizeHist(crop)


_clahe = cv2.createCLAHE(clipLimit=3.0, tileGridSize=(8, 8))
_gamma_lut = np.array([((i / 255.0) ** (1 / 1.6)) * 255 for i in range(256)],
                      dtype=np.uint8)


def enhance_low_light(frame, threshold=70):
    """If the frame is dark (average brightness below threshold, out of 255),
    brighten it with gamma correction + CLAHE (Contrast Limited Adaptive
    Histogram Equalization). Returns (frame, was_enhanced, brightness)."""
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    brightness = float(gray.mean())
    if brightness >= threshold:
        return frame, False, brightness
    bright = cv2.LUT(frame, _gamma_lut)
    lab = cv2.cvtColor(bright, cv2.COLOR_BGR2LAB)
    l, a, b = cv2.split(lab)
    lab = cv2.merge((_clahe.apply(l), a, b))
    return cv2.cvtColor(lab, cv2.COLOR_LAB2BGR), True, brightness
