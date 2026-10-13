"""
eye_cnn.py - Uses the trained CNN (models/eye_cnn.onnx) to decide whether
the eyes are open or closed. Runs with OpenCV only (no PyTorch needed).

Train the model first:
    python collect_eyes.py      (record your own open / closed eye images)
    python train_cnn.py         (train and export models/eye_cnn.onnx)
"""

import os

import cv2
import numpy as np

from features import eye_crop

IMG_SIZE = 32
CLASSES = ["open", "closed"]


class EyeCNN:
    def __init__(self, model_path):
        if not os.path.exists(model_path):
            raise SystemExit(
                "CNN model not found: %s\n"
                "Train it first:  python collect_eyes.py  then  python train_cnn.py\n"
                "Or run with --method ear" % model_path)
        self.net = cv2.dnn.readNetFromONNX(model_path)

    def prob_closed_crop(self, crop):
        blob = (crop.astype(np.float32) / 255.0).reshape(1, 1, IMG_SIZE, IMG_SIZE)
        self.net.setInput(blob)
        logits = self.net.forward().reshape(-1)
        e = np.exp(logits - logits.max())
        return float(e[1] / e.sum())

    def prob_closed(self, frame_bgr, face):
        """Average probability (0-1) that the eyes are closed."""
        gray = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2GRAY)
        probs = []
        for eye in face["eyes"]:
            crop = eye_crop(gray, eye, IMG_SIZE)
            if crop is not None:
                probs.append(self.prob_closed_crop(crop))
        return float(np.mean(probs)) if probs else None


def decide_closed(method, ear, threshold, p_closed):
    """Combine EAR and CNN according to the chosen method.
    Returns True/False, or None to let the EAR rule decide."""
    if method == "ear" or p_closed is None:
        return None
    if method == "cnn":
        return p_closed > 0.5
    # hybrid: both agree, or one of them is very sure
    ear_closed = ear < threshold
    return (ear_closed and p_closed > 0.4) or p_closed > 0.85 or ear < 0.6 * threshold
