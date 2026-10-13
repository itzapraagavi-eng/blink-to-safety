"""
monitor.py - Combines all signs of tiredness into one decision.

Signs used:
  * Eye closure      (EAR or CNN)  -> long closure = DROWSY alarm
  * PERCLOS          percentage of time the eyes were closed in the last 60 s
  * Slow blinks      closures between 0.5 s and 1.5 s
  * Yawns            mouth wide open (MAR) for more than 1 s
                     (eyes squeezed shut during a yawn get 2 s extra before alarming)
  * Head nods        head dips forward and comes back up
  * Head drop        head stays down for more than 2 s with the eyes closed
                     -> DROWSY alarm (eyes open = looking down -> DISTRACTED)
  * Distraction      head turned away > 30 deg for 2 s, or face out of view
                     for 3 s -> DISTRACTED warning ("eyes on the road")
  * Time risk        night hours and long drives add to the score (drive_context.py)

Fatigue score (0 - 100):
    PERCLOS x 250        (max 50)   e.g. eyes closed 20% of the time = 50
  + 12 per yawn          (max 30)   in the last 3 minutes
  + 15 per nod           (max 30)   in the last 3 minutes
  +  5 per slow blink    (max 20)   in the last minute
  + 20 per drowsy alarm  (max 40)   in the last 5 minutes
  + 10 during night risk hours, + 5 per hour of driving beyond 2 hours (max 15)

Alert levels:
    0  ALERT       score below 35
    1  TIRED       score 35 - 64   -> soft chime + voice "please take a break"
    2  VERY TIRED  score 65+       -> stronger voice warning
    3  DROWSY      eyes closed >= 1.5 s or head down >= 2 s -> loud alarm
"""

from collections import deque

import numpy as np

from detector import CALIBRATION_SECONDS, SLOW_BLINK_SECONDS, EyeStateTracker

LEVEL_NAMES = ["ALERT", "TIRED", "VERY TIRED", "DROWSY"]


class YawnTracker:
    def __init__(self, mar_threshold=0.5, min_seconds=1.0):
        self.mar_threshold = mar_threshold
        self.min_seconds = min_seconds
        self.open_since = None
        self.counted = False
        self.count = 0

    def update(self, mar, now):
        """Returns (yawning_now, new_yawn_counted)."""
        if mar is None:
            self.open_since, self.counted = None, False
            return False, False
        if mar >= self.mar_threshold:
            if self.open_since is None:
                self.open_since, self.counted = now, False
            if not self.counted and now - self.open_since >= self.min_seconds:
                self.counted = True
                self.count += 1
                return True, True
            return self.counted, False
        if mar < self.mar_threshold * 0.8:          # small gap avoids flicker
            self.open_since, self.counted = None, False
        return self.counted, False


class HeadTracker:
    """Learns the driver's normal head angle, then watches for nods, head
    drops and looking away (distraction)."""

    def __init__(self, down_degrees=20, drop_seconds=2.0, min_nod_seconds=0.3,
                 away_degrees=30, distract_seconds=2.0,
                 calibration_seconds=CALIBRATION_SECONDS):
        self.down_degrees = down_degrees
        self.drop_seconds = drop_seconds
        self.min_nod_seconds = min_nod_seconds
        self.away_degrees = away_degrees
        self.distract_seconds = distract_seconds
        self.calibration_seconds = calibration_seconds
        self.start_calibration()
        self.nod_count = 0

    def start_calibration(self):
        self.baseline = None
        self.baseline_yaw = None
        self._samples = []
        self._calib_start = None
        self.down_since = None
        self.dropped = False
        self.away_since = None
        self.distracted = False

    def update(self, pose, now):
        """Returns dict: pitch_delta, yaw_delta, head_down, head_drop,
        drop_started, nod, looking_away, distracted, distract_started."""
        out = {"pitch_delta": None, "yaw_delta": None, "head_down": False,
               "head_drop": False, "drop_started": False, "nod": False,
               "looking_away": False, "distracted": False, "distract_started": False}
        if pose is None:
            self.down_since, self.dropped = None, False
            self.away_since, self.distracted = None, False
            return out
        pitch, yaw = pose[0], pose[1]
        if self.baseline is None:
            if self._calib_start is None:
                self._calib_start = now
            self._samples.append((pitch, yaw))
            if now - self._calib_start >= self.calibration_seconds and len(self._samples) >= 10:
                arr = np.array(self._samples)
                self.baseline = float(np.median(arr[:, 0]))
                self.baseline_yaw = float(np.median(arr[:, 1]))
            return out

        # ---- turning sideways: looking away from the road ----
        yaw_delta = yaw - self.baseline_yaw
        out["yaw_delta"] = yaw_delta
        if abs(yaw_delta) > self.away_degrees:
            if self.away_since is None:
                self.away_since = now
            out["looking_away"] = True
            if now - self.away_since >= self.distract_seconds:
                out["distract_started"] = not self.distracted
                self.distracted = True
        elif abs(yaw_delta) < self.away_degrees * 0.7:
            self.away_since, self.distracted = None, False
        else:
            out["looking_away"] = self.away_since is not None
        out["distracted"] = self.distracted

        # ---- bending down: nods and head drop ----
        delta = pitch - self.baseline                # + = head bent down
        out["pitch_delta"] = delta
        if delta > self.down_degrees:
            if self.down_since is None:
                self.down_since = now
            out["head_down"] = True
            if now - self.down_since >= self.drop_seconds:
                out["drop_started"] = not self.dropped
                self.dropped = True
            out["head_drop"] = self.dropped
        elif delta < self.down_degrees * 0.6:        # head came back up
            if self.down_since is not None and not self.dropped:
                if now - self.down_since >= self.min_nod_seconds:
                    self.nod_count += 1
                    out["nod"] = True
            self.down_since, self.dropped = None, False
        else:
            out["head_down"] = self.down_since is not None
            out["head_drop"] = self.dropped
        return out


class FatigueScorer:
    def __init__(self, window_seconds=60):
        self.window = window_seconds
        self.closed_hist = deque()           # (time, eyes_closed)
        self.events = {"yawn": deque(), "nod": deque(), "slow_blink": deque(),
                       "drowsy": deque()}
        self.smooth = 0.0

    def add_event(self, kind, now):
        self.events[kind].append(now)

    def _recent(self, kind, now, seconds):
        q = self.events[kind]
        while q and now - q[0] > 300:         # keep 5 minutes
            q.popleft()
        return sum(1 for t in q if now - t <= seconds)

    def update(self, eyes_closed, now, bonus=0.0):
        if eyes_closed is not None:
            self.closed_hist.append((now, eyes_closed))
        while self.closed_hist and now - self.closed_hist[0][0] > self.window:
            self.closed_hist.popleft()
        n = len(self.closed_hist)
        perclos = sum(1 for _, c in self.closed_hist if c) / n if n else 0.0
        if n:   # until a full window is collected, don't let 2 blinks look like 10%
            span = now - self.closed_hist[0][0]
            perclos *= min(1.0, max(span, 1e-6) / self.window)
        parts = {
            "perclos": min(50.0, perclos * 250),
            "yawns": min(30.0, 12.0 * self._recent("yawn", now, 180)),
            "nods": min(30.0, 15.0 * self._recent("nod", now, 180)),
            "slow_blinks": min(20.0, 5.0 * self._recent("slow_blink", now, 60)),
            "alarms": min(40.0, 20.0 * self._recent("drowsy", now, 300)),
            "time_risk": bonus,       # night hours / long drive (drive_context.py)
        }
        raw = min(100.0, sum(parts.values()))
        # smooth the display so the meter does not jump around
        self.smooth += (raw - self.smooth) * (0.08 if raw < self.smooth else 0.25)
        return self.smooth, perclos, parts


class DriverMonitor:
    """One update() per video frame -> full driver state."""

    def __init__(self, cfg):
        det, yawn, head, fat = cfg["detection"], cfg["yawn"], cfg["head"], cfg["fatigue"]
        self.closed_seconds = det["closed_seconds"]
        self.eyes = EyeStateTracker(ear_threshold=det["ear_threshold"],
                                    closed_seconds=det["closed_seconds"])
        self.yawn = YawnTracker(yawn["mar_threshold"], yawn["min_seconds"])
        self.yawn_eye_grace = yawn.get("eye_grace_seconds", 2.0)
        self._last_mouth_open = -1e9
        self.head = HeadTracker(head["down_degrees"], head["drop_seconds"],
                                head["min_nod_seconds"], head["away_degrees"],
                                head["distract_seconds"])
        self.face_lost_seconds = head["face_lost_seconds"]
        self.ear_unreliable_yaw = head.get("ear_unreliable_yaw", 45)
        self._hd_frames = self._hd_closed = 0
        self.scorer = FatigueScorer(fat["window_seconds"])
        self.tired_level = fat["tired_level"]
        self.very_tired_level = fat["very_tired_level"]
        self.level = 0
        self.drowsy_events = 0
        self.distractions = 0
        self._was_drowsy = False
        self._was_distracted = False
        self._no_face_since = None
        self._hd_frames = self._hd_closed = 0

    def recalibrate(self):
        self.eyes.start_calibration()
        self.head.start_calibration()

    def reset_events(self):
        """Fresh start for a new test trial (keeps calibration)."""
        self.eyes.reset()
        self.head.down_since, self.head.dropped = None, False
        self.head.away_since, self.head.distracted = None, False
        self.yawn.open_since, self.yawn.counted = None, False
        self._was_drowsy = False
        self._was_distracted = False
        self._no_face_since = None
        self._hd_frames = self._hd_closed = 0

    @property
    def calibrating(self):
        return self.eyes.calibrating

    def update(self, face, now, eyes_closed_override=None, ctx=None):
        """ctx: result of DriveContext.update() (night risk, drive time) or None."""
        ctx = ctx or {}
        # at night the eye-closure limit is shorter (more sensitive)
        self.eyes.closed_seconds = self.closed_seconds * ctx.get("closed_factor", 1.0)
        ear = face["ear"] if face else None
        head = self.head.update(face["pose"] if face else None, now)
        # looking down lowers the eyelids a little: lower the limit a bit
        # (by up to 30%) so a glance at the speedometer is not "eyes closed"
        pd = head.get("pitch_delta")
        thr_scale = 1.0
        if pd is not None and pd > 8:
            thr_scale = max(0.7, 1.0 - 0.012 * (pd - 8))
        st = self.eyes.update(ear, now, closed=eyes_closed_override, thr_scale=thr_scale)
        events = list(ctx.get("events", []))
        yawning, new_yawn = self.yawn.update(face["mar"] if face else None, now)

        if st["status"] == "CALIBRATING":
            # head angle is learned at the same time (HeadTracker skips its
            # checks until it has a baseline)
            st.update(level=0, fatigue_level=0, fatigue=0.0, perclos=0.0,
                      yawning=False, head=head, events=events, drowsy_reason="",
                      yawns=self.yawn.count, nods=self.head.nod_count,
                      drowsy_events=self.drowsy_events, distracted=False,
                      distract_reason="", distractions=self.distractions,
                      drive_time=ctx.get("drive_time", 0.0),
                      risk_hours=ctx.get("risk_hours", False),
                      mar=face["mar"] if face else None, score_parts={})
            return st

        if new_yawn:
            events.append("yawn"); self.scorer.add_event("yawn", now)
        if head["nod"]:
            events.append("nod"); self.scorer.add_event("nod", now)
        bd = st.get("blink_duration")
        if bd is not None and bd >= SLOW_BLINK_SECONDS:
            events.append("slow_blink"); self.scorer.add_event("slow_blink", now)

        # People often squeeze their eyes shut while yawning. Eye closure that
        # happens during (or right after) a yawn gets extra time before it
        # counts as drowsy - the yawn itself already raises the fatigue score.
        mouth_open = self.yawn.open_since is not None
        if mouth_open:
            self._last_mouth_open = now
        near_yawn = now - self._last_mouth_open <= 1.0
        if (st["drowsy"] and near_yawn
                and st["closed_for"] < self.eyes.closed_seconds + self.yawn_eye_grace):
            st["drowsy"] = False
            st["status"] = "EYES CLOSED"
        # Only with the head turned very far (more than 45 degrees) is the eye
        # shape unreliable. (Real data: eyes closed with the head turned 27
        # degrees must still raise the alarm.)
        yd = head.get("yaw_delta")
        if st["drowsy"] and yd is not None and abs(yd) > self.ear_unreliable_yaw:
            st["drowsy"] = False
            st["status"] = "EYES CLOSED"

        # ---- head down: asleep (eyes closed) or looking down (eyes open)? ----
        if head["head_down"]:
            self._hd_frames += 1
            self._hd_closed += int(st["eyes_closed"])
        else:
            self._hd_frames = self._hd_closed = 0
        head_drop_asleep = head_drop_looking = False
        if head["head_drop"]:
            if self._hd_closed >= 0.5 * max(1, self._hd_frames):
                head_drop_asleep = True      # dozing off: head down AND eyes closed
            else:
                head_drop_looking = True     # eyes open: looking down at phone/lap

        # ---- distraction: looking away, looking down, or face out of view ----
        distract_reason = ""
        if head["distracted"]:
            distract_reason = "Looking away"
        elif head_drop_looking:
            distract_reason = "Looking down"
        if face is None and st["status"] == "NO FACE" and not self.eyes.calibrating:
            if self._no_face_since is None:
                self._no_face_since = now
            gone = now - self._no_face_since
            # only for a short while: after a minute the driver has probably left the seat
            if self.face_lost_seconds <= gone < 60:
                distract_reason = "Face not visible"
        else:
            self._no_face_since = None
        distracted = bool(distract_reason)
        if distracted and not self._was_distracted:
            self.distractions += 1
            events.append("distracted")
        self._was_distracted = distracted

        # final drowsy decision: long eye closure OR head dropped
        reasons = []
        if st["drowsy"]:
            reasons.append("Eyes closed")
        if head_drop_asleep:
            reasons.append("Head drop")
        reason = " + ".join(reasons)
        drowsy = bool(reason)
        if drowsy and not self._was_drowsy:
            self.drowsy_events += 1
            events.append("drowsy")
            self.scorer.add_event("drowsy", now)
        self._was_drowsy = drowsy
        if drowsy:
            st["status"] = "DROWSY"
            st["drowsy"] = True
        elif distracted:
            st["status"] = "DISTRACTED"

        fatigue, perclos, parts = self.scorer.update(st["eyes_closed"] if face else None, now,
                                                     ctx.get("score_bonus", 0.0))

        # level with hysteresis (needs to drop 5 points below to go down)
        lvl = 0
        if fatigue >= self.very_tired_level:
            lvl = 2
        elif fatigue >= self.tired_level:
            lvl = 1
        if lvl < self.level:
            limits = {1: self.tired_level, 2: self.very_tired_level}
            if fatigue > limits[self.level] - 5:
                lvl = self.level
        if lvl > self.level:
            events.append("level_up")
        self.level = lvl

        st.update(level=3 if drowsy else lvl, fatigue_level=lvl, fatigue=fatigue, perclos=perclos,
                  yawning=yawning, head=head, events=events, drowsy_reason=reason,
                  yawns=self.yawn.count, nods=self.head.nod_count,
                  drowsy_events=self.drowsy_events, distracted=distracted,
                  distract_reason=distract_reason, distractions=self.distractions,
                  drive_time=ctx.get("drive_time", 0.0),
                  risk_hours=ctx.get("risk_hours", False),
                  mar=face["mar"] if face else None, score_parts=parts)
        return st
