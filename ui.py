"""
ui.py - Draws the on-screen display: eye and mouth outlines, measurements,
fatigue meter, warning banners and the drowsiness alert.
"""

import time

import cv2
import numpy as np

from features import mouth_outline

GREEN = (80, 200, 80)
YELLOW = (0, 220, 255)
AMBER = (25, 178, 250)
ORANGE = (0, 140, 255)
RED = (40, 40, 230)
PURPLE = (200, 80, 200)
WHITE = (255, 255, 255)
GREY = (170, 170, 170)
FONT = cv2.FONT_HERSHEY_SIMPLEX

STATUS_COLOR = {
    "AWAKE": GREEN,
    "EYES CLOSED": ORANGE,
    "DROWSY": RED,
    "CALIBRATING": YELLOW,
    "NO FACE": YELLOW,
    "DISTRACTED": PURPLE,
}
LEVEL_COLOR = [GREEN, AMBER, ORANGE, RED]
LEVEL_NAMES = ["ALERT", "TIRED", "VERY TIRED", "DROWSY"]


def _panel(frame, x, y, w, h, alpha=0.55):
    """Dark see-through box so text is readable on any background."""
    x, y = max(0, x), max(0, y)
    x2, y2 = min(frame.shape[1], x + w), min(frame.shape[0], y + h)
    if x2 <= x or y2 <= y:
        return
    roi = frame[y:y2, x:x2]
    frame[y:y2, x:x2] = (roi * (1 - alpha)).astype(np.uint8)


def _centered(frame, text, y, scale, color, thick=2):
    (tw, th), _ = cv2.getTextSize(text, FONT, scale, thick)
    x = (frame.shape[1] - tw) // 2
    cv2.putText(frame, text, (x, y), FONT, scale, (0, 0, 0), thick + 3, cv2.LINE_AA)
    cv2.putText(frame, text, (x, y), FONT, scale, color, thick, cv2.LINE_AA)


def _text(frame, s, x, y, scale=0.5, color=WHITE, thick=1):
    cv2.putText(frame, s, (x, y), FONT, scale, color, thick, cv2.LINE_AA)


def draw_eyes(frame, eyes, color):
    for eye in eyes:
        pts = eye.astype(np.int32).reshape(-1, 1, 2)
        cv2.polylines(frame, [pts], True, color, 1, cv2.LINE_AA)
        for p in eye.astype(np.int32):
            cv2.circle(frame, tuple(p), 2, color, -1, cv2.LINE_AA)


def draw_fatigue_meter(frame, score, level):
    h, w = frame.shape[:2]
    x1, x2, y1, y2 = w - 46, w - 22, 70, h - 150
    _panel(frame, x1 - 16, y1 - 42, x2 - x1 + 32, y2 - y1 + 84)
    _text(frame, "FATIGUE", x1 - 14, y1 - 26, 0.4, WHITE)
    # zones: 0-35 green, 35-65 amber, 65-100 red (drawn faint)
    def y_of(v):
        return int(y2 - (y2 - y1) * v / 100.0)
    for lo, hi, col in ((0, 35, GREEN), (35, 65, AMBER), (65, 100, RED)):
        cv2.rectangle(frame, (x1, y_of(hi)), (x2, y_of(lo)),
                      tuple(int(c * 0.35) for c in col), -1)
    fill = LEVEL_COLOR[min(level, 3)]
    cv2.rectangle(frame, (x1, y_of(score)), (x2, y2), fill, -1)
    cv2.rectangle(frame, (x1, y1), (x2, y2), GREY, 1)
    _text(frame, "%d" % round(score), x1 - 2 if score < 100 else x1 - 8, y1 - 8, 0.55, WHITE, 2)
    name = LEVEL_NAMES[min(level, 3)]
    (tw, _), _ = cv2.getTextSize(name, FONT, 0.38, 1)
    _text(frame, name, min((x1 + x2) // 2 - tw // 2, w - tw - 4), y2 + 20, 0.38, fill, 1)


def draw_overlay(frame, st, face=None, fps=0.0, closed_seconds=1.5,
                 blinks_per_min=0.0, muted=False, help_text=True,
                 method="EAR", low_light=False, alert_info=None, lang="EN",
                 location=None, gps_status=None, fleet_state=None):
    status = st["status"]
    color = STATUS_COLOR.get(status, WHITE)
    h, w = frame.shape[:2]
    alert_info = alert_info or {}

    if face is not None:
        draw_eyes(frame, face["eyes"], color)
        if st.get("yawning"):
            m = mouth_outline(face["pts"]).astype(np.int32).reshape(-1, 1, 2)
            cv2.polylines(frame, [m], True, ORANGE, 2, cv2.LINE_AA)

    # ---- information panel (top-left) ----
    _panel(frame, 0, 0, 262, 216)
    _text(frame, "Blink to Safety", 10, 22, 0.62, WHITE, 2)
    ear = st["ear"]
    _text(frame, ("EAR %.3f" % ear if ear is not None else "EAR --") +
          "  (limit %.3f)" % st["threshold"], 10, 44, 0.45)
    mar = st.get("mar")
    head = st.get("head") or {}
    pd, yd = head.get("pitch_delta"), head.get("yaw_delta")
    _text(frame, "MAR %s  Pitch %s  Yaw %s" % (
        "%.2f" % mar if mar is not None else "--",
        "%+.0f" % pd if pd is not None else "--",
        "%+.0f" % yd if yd is not None else "--"), 10, 64, 0.43)
    _text(frame, "Status: " + status, 10, 88, 0.58, color, 2)
    _text(frame, "Blinks %d (%.0f/min)" % (st["blinks"], blinks_per_min), 10, 110, 0.45)
    _text(frame, "Yawns %d   Nods %d   Alarms %d" % (st.get("yawns", 0), st.get("nods", 0),
                                                    st.get("drowsy_events", 0)), 10, 130, 0.45)
    _text(frame, "Distracted %d   PERCLOS %.0f%%" % (st.get("distractions", 0),
                                                  100 * st.get("perclos", 0.0)), 10, 150, 0.45)
    dt = int(st.get("drive_time", 0))
    spd = ""
    if location and location.get("speed_kmh") is not None:
        spd = "  %d km/h" % round(location["speed_kmh"])
    _text(frame, "Drive %d:%02d:%02d%s" % (dt // 3600, (dt % 3600) // 60, dt % 60, spd),
          10, 170, 0.45)
    tag = "%s %s FPS %.0f%s" % (method, lang, fps, " MUTED" if muted else "")
    _text(frame, tag, 10, 190, 0.4, GREY)
    (tw, _), _ = cv2.getTextSize(tag, FONT, 0.4, 1)
    x = 10 + tw + 8
    if gps_status and gps_status != "off":   # GPS indicator
        ok = gps_status in ("ok", "fixed", "sim", "approx") and location is not None
        label = "GPS" + {"sim": " SIM", "approx": "~"}.get(gps_status, "")
        _text(frame, label, x, 190, 0.4, GREEN if ok else YELLOW)
        x += cv2.getTextSize(label, FONT, 0.4, 1)[0][0] + 8
    if fleet_state is not None:              # fleet server connection
        _text(frame, "FLEET", x, 190, 0.4, GREEN if fleet_state else RED)


    # eyes-closed timer bar: fills up towards the drowsy limit
    frac = min(1.0, st["closed_for"] / closed_seconds) if closed_seconds > 0 else 0
    cv2.rectangle(frame, (10, 200), (250, 209), GREY, 1)
    if frac > 0:
        cv2.rectangle(frame, (10, 200), (10 + int(240 * frac), 209),
                      RED if frac >= 1 else ORANGE, -1)

    if status not in ("CALIBRATING",):
        draw_fatigue_meter(frame, st.get("fatigue", 0.0), st.get("level", 0))

    # ---- small indicators (top centre) ----
    tags = []
    if st.get("yawning"):
        tags.append(("YAWNING", ORANGE))
    if head.get("head_down"):
        tags.append(("HEAD DOWN", ORANGE))
    if head.get("looking_away"):
        tags.append(("LOOKING AWAY", PURPLE))
    if st.get("risk_hours"):
        tags.append(("NIGHT", PURPLE))
    if low_light:
        tags.append(("LOW LIGHT", YELLOW))
    x = 275
    for t, c in tags:
        (tw, _), _ = cv2.getTextSize(t, FONT, 0.5, 2)
        _panel(frame, x - 6, 8, tw + 12, 26, 0.6)
        _text(frame, t, x, 27, 0.5, c, 2)
        x += tw + 22

    # ---- special screens ----
    if alert_info.get("alcohol"):
        _panel(frame, 0, 44, w - 70, 40, 0.6)
        _centered(frame, "ALCOHOL DETECTED - DO NOT DRIVE", 72, 0.7, PURPLE, 2)

    if status == "CALIBRATING":
        prog = st.get("calibration_progress", 0.0)
        _panel(frame, 0, h // 2 - 50, w, 90)
        _centered(frame, "Calibrating... look at the screen normally",
                  h // 2 - 15, 0.7, YELLOW)
        cv2.rectangle(frame, (w // 4, h // 2 + 5), (3 * w // 4, h // 2 + 20), GREY, 1)
        cv2.rectangle(frame, (w // 4, h // 2 + 5),
                      (w // 4 + int(w // 2 * prog), h // 2 + 20), YELLOW, -1)

    elif status == "NO FACE":
        _centered(frame, "Face not detected", h - 50, 0.8, YELLOW)

    elif status == "DROWSY":
        if int(time.time() * 4) % 2 == 0:          # flashing red border
            cv2.rectangle(frame, (0, 0), (w - 1, h - 1), RED, 18)
        top = h - 150                               # lower third: face stays visible
        _panel(frame, 0, top, w, 105, alpha=0.5)
        _centered(frame, "DROWSINESS ALERT!", top + 48, 1.3, RED, 3)
        reason = st.get("drowsy_reason", "")
        _centered(frame, "WAKE UP!" + ("   (%s)" % reason if reason else ""), top + 88, 0.8, WHITE, 2)

    elif status == "DISTRACTED":
        if int(time.time() * 3) % 2 == 0:
            cv2.rectangle(frame, (0, 0), (w - 1, h - 1), PURPLE, 12)
        top = h - 140
        _panel(frame, 0, top, w, 95, alpha=0.5)
        _centered(frame, "EYES ON THE ROAD!", top + 45, 1.2, PURPLE, 3)
        _centered(frame, "(%s)" % st.get("distract_reason", ""), top + 80, 0.7, WHITE, 2)

    elif alert_info.get("banner"):
        lvl = st.get("level", 0)
        _panel(frame, 0, h - 100, w, 52, alpha=0.6)
        _centered(frame, alert_info["banner"], h - 66, 0.6,
                  ORANGE if lvl >= 2 else AMBER, 2)

    if help_text:
        _panel(frame, 0, h - 30, w, 30, alpha=0.6)
        _text(frame, "q: quit   c: recalibrate   m: mute   v: voice on/off", 10, h - 10, 0.45)
    return frame
