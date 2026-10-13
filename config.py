"""
config.py - Loads settings from config.json (missing values use these defaults).
Edit config.json to change thresholds, turn voice on/off, set up the
emergency Telegram alert or the Raspberry Pi hardware.
"""

import copy
import json
import os

PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(PROJECT_DIR, "config.json")

DEFAULTS = {
    "detection": {
        "method": "ear",              # "ear", "cnn" or "hybrid"
        "closed_seconds": 1.5,        # eyes closed this long = drowsy alarm
        "ear_threshold": None,        # null = auto calibrate for each driver
        "cnn_model": "models/eye_cnn.onnx",
        "low_light_threshold": 70,    # brightness (0-255) below which frames are enhanced
    },
    "yawn": {
        "mar_threshold": 0.5,         # mouth aspect ratio for "mouth wide open"
        "min_seconds": 1.0,           # open this long = a yawn (talking is shorter)
        "eye_grace_seconds": 2.0,     # extra time for eyes squeezed shut during a yawn
    },
    "head": {
        "down_degrees": 20,           # head bent down more than this = head down
        "drop_seconds": 2.0,          # head down this long = drowsy alarm
        "min_nod_seconds": 0.3,       # shorter dips are ignored
        "away_degrees": 30,           # head turned more than this = looking away
        "distract_seconds": 2.0,      # looking away this long = distraction alert
        "face_lost_seconds": 3.0,     # face out of view this long = distraction alert
        "ear_unreliable_yaw": 45,     # head turned more than this: eye shape not trusted
    },
    "fatigue": {
        "tired_level": 35,            # fatigue score for level-1 warning
        "very_tired_level": 65,       # fatigue score for strong warning
        "window_seconds": 60,         # PERCLOS time window
    },
    "alerts": {
        "voice": True,
        "language": "en",             # "en" English, "ta" Tamil, "hi" Hindi
        "voice_rate": 165,            # words per minute
        "warning_cooldown_seconds": 45,
    },
    "drive": {
        "break_reminder_minutes": 120,   # remind to take a break after this long
        "reminder_repeat_minutes": 30,   # then remind again every ...
        "break_reset_minutes": 10,       # driver away this long = break taken, timer resets
        "risk_hours": [[0, 6]],          # night hours (24 h clock) with higher crash risk
        "risk_closed_seconds_factor": 0.8,  # 1.5 s eye-closure limit becomes 1.2 s at night
        "risk_score_bonus": 10,          # added to the fatigue score during risk hours
    },
    "driver": {
        "name": "Driver",             # shown on the fleet dashboard and in emergency messages
        "vehicle": "TN01AB1234",      # vehicle number (unique id on the dashboard)
    },
    "gps": {
        "source": "none",             # "none", "nmea" (GPS module), "ip" (approximate),
                                      # "fixed" (lat/lon below) or "sim" (demo route)
        "port": "auto",               # serial port of the GPS module, e.g. COM5 or /dev/serial0
        "baud": 9600,
        "fixed_lat": 13.0827,         # used when source = "fixed"
        "fixed_lon": 80.2707,
        "sim_route": "chennai_vellore",  # chennai_vellore, chennai_pondy, chennai_trichy, madurai_dindigul
    },
    "fleet": {
        "enabled": False,
        "server": "http://localhost:8000",   # address of fleet_server.py
        "key": "change-me",           # must match the server's key
        "update_seconds": 2,
        "upload_trip_report": True,
    },
    "emergency": {
        "enabled": False,
        "telegram_bot_token": "",
        "telegram_chat_id": "",
        "alarms_before_alert": 3,     # this many drowsy alarms...
        "window_minutes": 10,         # ...within this many minutes sends the alert
        "send_photo": True,
        "send_location": True,        # adds a map link and a location pin (needs GPS)
    },
    "raspberry_pi": {
        "enabled": False,
        "buzzer_pin": 17,
        "led_pin": 27,
        "alcohol_sensor_pin": 22,
        "alcohol_active_low": True,   # most MQ-3 modules pull DO low when alcohol is sensed
    },
}


def _merge(base, extra):
    for key, value in extra.items():
        if key.startswith("_"):
            continue                   # "_comment" keys are notes for humans
        if isinstance(value, dict) and isinstance(base.get(key), dict):
            _merge(base[key], value)
        else:
            base[key] = value
    return base


def load_config(path=None):
    cfg = copy.deepcopy(DEFAULTS)
    path = path or CONFIG_PATH
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            try:
                _merge(cfg, json.load(f))
            except json.JSONDecodeError as exc:
                raise SystemExit("config.json has a mistake (%s). Fix it or delete it "
                                 "to use the default settings." % exc)
    model = cfg["detection"]["cnn_model"]
    if not os.path.isabs(model):
        cfg["detection"]["cnn_model"] = os.path.join(PROJECT_DIR, model)
    return cfg
