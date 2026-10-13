"""
alerts.py - Decides WHICH alert to give, based on the driver state.

Two fatigue levels:
  Level 1 (early warning)  - tired / very tired fatigue score:
                             gentle chime + calm voice message + LED on
  Level 2 (danger)         - DROWSY (eyes closed >= 1.5 s or head dropped):
                             loud looping alarm + "Wake up!" voice + buzzer
Plus:
  Distraction              - looking away / face out of view: repeating chime
                             + "Please keep your eyes on the road"
  Long drive               - "take a short break" after 2 hours
  Night risk               - one notice when driving in high-risk hours
  Emergency message        - Telegram alert after repeated drowsy alarms
  Alcohol warning          - only with the Raspberry Pi MQ-3 sensor

Spoken messages (English / Tamil / Hindi) are in messages.py.
"""

SCREEN = {   # short on-screen text (the screen font supports English only)
    "tired": "You seem tired - take a break soon",
    "very_tired": "High fatigue - please stop and rest",
    "long_drive": "Long drive - please take a short break",
    "night": "Night driving - drowsiness risk is high",
    "break_taken": "Break detected - drive timer reset",
    "emergency": "Emergency alert sent to contact",
}


class AlertManager:
    def __init__(self, cfg, alarm, voice, emergency, pi):
        self.alarm, self.voice, self.emergency, self.pi = alarm, voice, emergency, pi
        self.cooldown = cfg["alerts"]["warning_cooldown_seconds"]
        self._last_warn = -1e9
        self._last_wake = -1e9
        self._last_distract_voice = -1e9
        self._last_distract_chime = -1e9
        self.banner = ""            # text shown on screen for warnings
        self._banner_until = 0.0
        self.alcohol = False
        self.emergency_sent = 0
        self._pending_warning = False
        self._last_warn_level = 0

    def _show(self, key, now, seconds=8):
        self.banner, self._banner_until = SCREEN[key], now + seconds

    def handle(self, st, frame, now, location=None):
        level = st.get("level", 0)
        events = st.get("events", [])

        # ---- level 2: drowsy -> loud alarm ----
        if st.get("drowsy"):
            self.alarm.start()
            self.pi.alarm(True)
            if now - self._last_wake >= 5.0:              # repeat every 5 s
                self.voice.say("wake_up", urgent=True)
                self._last_wake = now
            if "drowsy" in events and self.emergency.record_alarm(now, frame, st.get("fatigue"), location):
                self.emergency_sent += 1
                self._show("emergency", now, 6)
        else:
            self.alarm.stop()
            self.pi.alarm(False)
            self._last_wake = -1e9

        # ---- distraction: eyes off the road ----
        if st.get("distracted") and not st.get("drowsy"):
            if now - self._last_distract_chime >= 1.5:
                self.alarm.warn()
                self.pi.beep()
                self._last_distract_chime = now
            if now - self._last_distract_voice >= 6.0:
                self.voice.say("distracted", urgent=True)
                self._last_distract_voice = now
        else:
            self._last_distract_voice = self._last_distract_chime = -1e9

        # ---- level 1: early fatigue warning ----
        # (if it happens during a loud alarm, it is given right after)
        fat_level = st.get("fatigue_level", 0)
        if "level_up" in events:
            self._pending_warning = True
        escalated = fat_level > self._last_warn_level      # tired -> very tired: no waiting
        if (self._pending_warning and not st.get("drowsy") and fat_level in (1, 2)
                and (escalated or now - self._last_warn >= self.cooldown)):
            self._pending_warning = False
            self._last_warn = now
            self._last_warn_level = fat_level
            self.alarm.warn()
            key = "tired" if fat_level == 1 else "very_tired"
            self.voice.say(key)
            self._show(key, now)
        elif fat_level == 0:
            self._pending_warning = False
            self._last_warn_level = 0
        self.pi.warning_light(level)

        # ---- time-based notices ----
        if "night" in events:
            self.voice.say("night")
            self._show("night", now)
        if "long_drive" in events:
            self.alarm.warn()
            self.voice.say("long_drive")
            self._show("long_drive", now, 10)
        if "break_taken" in events:
            self._show("break_taken", now, 5)

        # ---- alcohol sensor (Raspberry Pi only) ----
        alc = self.pi.alcohol_detected()
        if alc and not self.alcohol:
            self.voice.say("alcohol")
            self.alarm.warn()
            self.emergency.alcohol_alert(now, frame, location)
        self.alcohol = alc

        if now > self._banner_until:
            self.banner = ""
        return {"banner": self.banner, "alcohol": self.alcohol}

    def stop(self):
        self.alarm.stop()
        self.pi.alarm(False)
