"""
drive_context.py - Time-based risk.

  * Drive time    : how long the current driver has been driving.
                    After 2 hours -> "please take a short break" (then every 30 min).
                    If the driver is away from the seat for 10 minutes, that
                    counts as a break and the timer starts again.
  * Risk hours    : sleep-related crashes peak in the early morning hours,
                    when the body clock pushes us to sleep. Between 00:00 and
                    06:00 (changeable) the system becomes more sensitive:
                    eye-closure limit 1.5 s -> 1.2 s, and +10 on the fatigue score.

For demos:  python main.py --clock 02:30 --driven 2
            (pretend it is 2:30 AM and you have already driven 2 hours)
"""

from datetime import datetime, timedelta


def parse_clock(hhmm):
    h, m = hhmm.split(":")
    now = datetime.now()
    target = now.replace(hour=int(h), minute=int(m), second=0, microsecond=0)
    return target - now


class DriveContext:
    def __init__(self, cfg, clock=None, driven_hours=0.0):
        d = cfg["drive"]
        self.break_after = d["break_reminder_minutes"] * 60
        self.repeat = d["reminder_repeat_minutes"] * 60
        self.break_reset = d["break_reset_minutes"] * 60
        self.risk_hours = d["risk_hours"]
        self.closed_factor = d["risk_closed_seconds_factor"]
        self.risk_bonus = d["risk_score_bonus"]
        self.clock_delta = parse_clock(clock) if clock else timedelta(0)
        self.offset = driven_hours * 3600.0
        self.drive_start = None
        self.absent_since = None
        self.next_reminder = self.break_after
        self._announced_risk = False
        self.reminders = 0

    def clock(self):
        return datetime.now() + self.clock_delta

    def in_risk_hours(self):
        c = self.clock()
        h = c.hour + c.minute / 60.0
        for a, b in self.risk_hours:
            if (a <= h < b) if a <= b else (h >= a or h < b):   # also handles 22 -> 4
                return True
        return False

    def drive_time(self, now):
        if self.drive_start is None:
            return self.offset
        return now - self.drive_start + self.offset

    def update(self, now, face_present):
        events = []
        if face_present:
            if self.absent_since is not None and now - self.absent_since >= self.break_reset:
                # driver was away long enough: a break was taken
                self.drive_start, self.offset = now, 0.0
                self.next_reminder = self.break_after
                events.append("break_taken")
            self.absent_since = None
            if self.drive_start is None:
                self.drive_start = now
        elif self.absent_since is None:
            self.absent_since = now

        dt = self.drive_time(now)
        if face_present and dt >= self.next_reminder:
            events.append("long_drive")
            self.reminders += 1
            while self.next_reminder <= dt:
                self.next_reminder += self.repeat

        risk = self.in_risk_hours()
        if risk and not self._announced_risk and face_present:
            events.append("night")
            self._announced_risk = True
        if not risk:
            self._announced_risk = False

        bonus = self.risk_bonus if risk else 0
        extra_hours = max(0.0, (dt - self.break_after) / 3600.0)
        bonus += min(15.0, 5.0 * extra_hours)       # +5 per hour beyond 2 hours
        return {"drive_time": dt, "risk_hours": risk, "events": events,
                "score_bonus": bonus,
                "closed_factor": self.closed_factor if risk else 1.0}
