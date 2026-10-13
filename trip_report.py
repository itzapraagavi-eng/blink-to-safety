"""
trip_report.py - End-of-trip summary for the driver / fleet owner.

main.py calls make_trip_report() automatically when you quit. It saves:
  results/trip_report_<date_time>.png   one-page report with charts
  results/trip_events_<date_time>.csv   every yawn, nod, slow blink and alarm

You can also rebuild a report from any saved session log:
    python trip_report.py logs/session_20261009_201500.csv
"""

import csv
import glob
import os
import sys

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))
BLUE, ORANGE, AQUA, VIOLET = "#2a78d6", "#eb6834", "#1baf7a", "#4a3aa7"
CRITICAL, WARNING, SERIOUS = "#d03b3b", "#fab219", "#ec835a"
INK, INK_2, MUTED, GRID = "#0b0b0b", "#52514e", "#898781", "#e6e5e1"
EVENT_STYLE = {   # label, colour, marker
    "yawn": ("Yawn", ORANGE, "^"),
    "nod": ("Head nod", AQUA, "s"),
    "slow_blink": ("Slow blink", VIOLET, "o"),
    "distracted": ("Distraction", "#eda100", "D"),
}


def _fmt_time(sec):
    sec = int(round(sec))
    return "%d:%02d" % (sec // 60, sec % 60) if sec < 3600 else \
        "%d:%02d:%02d" % (sec // 3600, (sec % 3600) // 60, sec % 60)


def load_session(path):
    rows = []
    with open(path, newline="") as f:
        for r in csv.DictReader(f):
            rows.append(r)
    return rows


def route_stats(rows):
    """Distance and speeds from the GPS columns (if the drive had GPS)."""
    from gps import haversine_km
    pts = []
    for r in rows:
        try:
            pts.append((float(r["lat"]), float(r["lon"]),
                        float(r["speed_kmh"]) if r.get("speed_kmh") not in (None, "") else None))
        except (KeyError, TypeError, ValueError):
            continue
    if len(pts) < 2:
        return {}
    dist, last = 0.0, pts[0]
    for p in pts[1:]:
        d = haversine_km(last[:2], p[:2])
        if d > 0.01 or (p[2] or 0) > 3:      # ignore jitter while parked
            if d < 2.0:
                dist += d
            last = p
    speeds = [p[2] for p in pts if p[2] is not None]
    return {"distance_km": round(dist, 2),
            "avg_speed": sum(speeds) / len(speeds) if speeds else None,
            "max_speed": max(speeds) if speeds else None,
            "start_pt": pts[0][:2], "end_pt": pts[-1][:2]}


def summarize(rows):
    mon = [r for r in rows if r["status"] != "CALIBRATING"]
    if not mon:
        return None
    t0 = float(mon[0]["time_s"])
    t = [float(r["time_s"]) - t0 for r in mon]
    fat = [float(r.get("fatigue") or 0) for r in mon]
    events = []
    for ti, r in zip(t, mon):
        for e in (r.get("events") or "").split("|"):
            if e:
                events.append((ti, e))
    drowsy_spans, start = [], None
    for ti, r in zip(t, mon):
        if r["status"] == "DROWSY" and start is None:
            start = ti
        elif r["status"] != "DROWSY" and start is not None:
            drowsy_spans.append((start, ti)); start = None
    if start is not None:
        drowsy_spans.append((start, t[-1]))
    duration = t[-1] if t else 0
    blinks = max([int(r.get("blinks") or 0) for r in mon] + [0])
    n_closed = sum(1 for r in mon if r["status"] in ("EYES CLOSED", "DROWSY"))
    return {
        "t": t, "fatigue": fat, "events": events, "drowsy_spans": drowsy_spans,
        "ear": [float(r["ear"]) if r["ear"] else float("nan") for r in mon],
        "threshold": [float(r["threshold"]) for r in mon],
        "duration": duration,
        "alarms": len(drowsy_spans),
        "yawns": sum(1 for _, e in events if e == "yawn"),
        "nods": sum(1 for _, e in events if e == "nod"),
        "distractions": sum(1 for _, e in events if e == "distracted"),
        "break_reminders": sum(1 for _, e in events if e == "long_drive"),
        "slow_blinks": sum(1 for _, e in events if e == "slow_blink"),
        "blink_rate": blinks / (duration / 60) if duration > 30 else 0,
        "avg_fatigue": sum(fat) / len(fat) if fat else 0,
        "max_fatigue": max(fat) if fat else 0,
        "perclos": n_closed / len(mon),
        "time_tired": sum(1 for f in fat if f >= 35) / len(fat) if fat else 0,
        **route_stats(mon),
    }


def _style(ax):
    for s in ("top", "right", "left"):
        ax.spines[s].set_visible(False)
    ax.spines["bottom"].set_color(MUTED)
    ax.tick_params(colors=INK_2, length=0, labelsize=8)
    ax.yaxis.grid(True, color=GRID)
    ax.set_axisbelow(True)


def make_trip_report(rows, out_png, events_csv=None, title_extra=""):
    s = summarize(rows)
    if s is None:
        print("Trip too short for a report.")
        return None
    fig = plt.figure(figsize=(11, 8.2), dpi=150)
    fig.patch.set_facecolor("white")
    gs = fig.add_gridspec(3, 1, height_ratios=[0.75, 1.6, 1.2], hspace=0.45,
                          left=0.07, right=0.97, top=0.9, bottom=0.07)
    fig.text(0.07, 0.955, "Blink to Safety - Trip Report", fontsize=16,
             fontweight="bold", color=INK)
    fig.text(0.07, 0.928, title_extra, fontsize=9, color=MUTED)
    if s.get("distance_km") is not None:
        route = "Route: %.1f km driven" % s["distance_km"]
        if s.get("avg_speed") is not None:
            route += ", average %d km/h, top %d km/h" % (round(s["avg_speed"]), round(s["max_speed"]))
        route += "   |   start %.4f, %.4f  ->  end %.4f, %.4f" % (s["start_pt"] + s["end_pt"])
        fig.text(0.07, 0.905, route, fontsize=9, color=INK_2)

    # --- stat tiles ---
    if s["max_fatigue"] >= 65 or s["alarms"]:
        verdict, vcol = "Driver was dangerously drowsy", CRITICAL
    elif s["max_fatigue"] >= 35:
        verdict, vcol = "Driver showed signs of fatigue", SERIOUS
    else:
        verdict, vcol = "Driver stayed alert", "#0ca30c"
    tiles = [("Trip time", _fmt_time(s["duration"])),
             ("Drowsy alarms", str(s["alarms"])),
             ("Yawns", str(s["yawns"])),
             ("Head nods", str(s["nods"])),
             ("Distractions", str(s["distractions"])),
             ("Avg fatigue", "%d / 100" % round(s["avg_fatigue"])),
             ("Peak fatigue", "%d / 100" % round(s["max_fatigue"])),
             ("PERCLOS", "%.1f%%" % (100 * s["perclos"]))]
    ax0 = fig.add_subplot(gs[0]); ax0.axis("off")
    n = len(tiles)
    for i, (lab, val) in enumerate(tiles):
        x = i / n
        ax0.add_patch(plt.Rectangle((x + 0.004, 0.08), 1 / n - 0.012, 0.84,
                                    transform=ax0.transAxes, color="#f4f3f0", lw=0))
        ax0.text(x + 0.5 / n, 0.62, val, transform=ax0.transAxes, ha="center",
                 fontsize=15, fontweight="bold", color=INK)
        ax0.text(x + 0.5 / n, 0.26, lab, transform=ax0.transAxes, ha="center",
                 fontsize=8.5, color=INK_2)
    fig.text(0.97, 0.955, verdict, fontsize=11, fontweight="bold", color=vcol, ha="right")

    # --- fatigue timeline ---
    ax1 = fig.add_subplot(gs[1])
    t = s["t"]
    ax1.axhspan(35, 65, color=WARNING, alpha=0.10, lw=0)
    ax1.axhspan(65, 100, color=CRITICAL, alpha=0.08, lw=0)
    ax1.text(t[-1], 50, "TIRED ", ha="right", va="center", fontsize=7.5, color=INK_2)
    ax1.text(t[-1], 82, "VERY TIRED ", ha="right", va="center", fontsize=7.5, color=INK_2)
    for i, (a, b) in enumerate(s["drowsy_spans"]):
        ax1.axvspan(a, max(b, a + 0.3), color=CRITICAL, alpha=0.35, lw=0,
                    label="Drowsy alarm" if i == 0 else None)
    ax1.plot(t, s["fatigue"], color=BLUE, lw=2, label="Fatigue score", zorder=3)
    for kind, (lab, col, mk) in EVENT_STYLE.items():
        xs = [e[0] for e in s["events"] if e[1] == kind]
        if xs:
            ax1.scatter(xs, [103] * len(xs), marker=mk, s=42, color=col, label=lab,
                        zorder=4, clip_on=False, edgecolors="white", linewidths=1.5)
    ax1.set_ylim(0, 100); ax1.set_xlim(0, max(t[-1], 1))
    ax1.set_ylabel("Fatigue score (0-100)", color=INK_2, fontsize=9)
    ax1.set_title("Fatigue during the trip", loc="left", fontsize=11, color=INK)
    _style(ax1)
    ax1.legend(loc="upper left", bbox_to_anchor=(0, -0.1), ncol=6, frameon=False,
               fontsize=8, labelcolor=INK_2)

    # --- EAR ---
    ax2 = fig.add_subplot(gs[2])
    for a, b in s["drowsy_spans"]:
        ax2.axvspan(a, max(b, a + 0.3), color=CRITICAL, alpha=0.15, lw=0)
    ax2.plot(t, s["ear"], color=BLUE, lw=1.1)
    ax2.plot(t, s["threshold"], color=CRITICAL, lw=1, ls="--")
    ax2.text(t[-1], s["threshold"][-1], "threshold ", ha="right", va="bottom",
             fontsize=7.5, color=CRITICAL)
    ax2.set_xlim(0, max(t[-1], 1)); ax2.set_ylim(0, 0.5)
    ax2.set_ylabel("Eye Aspect Ratio", color=INK_2, fontsize=9)
    ax2.set_xlabel("Time (seconds)", color=INK_2, fontsize=9)
    ax2.set_title("Eye opening (EAR)", loc="left", fontsize=11, color=INK)
    _style(ax2)

    os.makedirs(os.path.dirname(out_png), exist_ok=True)
    fig.savefig(out_png, facecolor="white")
    plt.close(fig)

    if events_csv:
        with open(events_csv, "w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["time_s", "time", "event"])
            for a, b in s["drowsy_spans"]:
                w.writerow([round(a, 2), _fmt_time(a), "drowsy alarm (%.1f s)" % (b - a)])
            for ti, e in s["events"]:
                if e in EVENT_STYLE:
                    w.writerow([round(ti, 2), _fmt_time(ti), EVENT_STYLE[e][0].lower()])
    return s


def print_summary(s):
    print("Trip time       : %s" % _fmt_time(s["duration"]))
    print("Drowsy alarms   : %d" % s["alarms"])
    print("Yawns / nods    : %d / %d" % (s["yawns"], s["nods"]))
    print("Distractions    : %d" % s["distractions"])
    if s["break_reminders"]:
        print("Break reminders : %d" % s["break_reminders"])
    print("Fatigue avg/peak: %d / %d" % (round(s["avg_fatigue"]), round(s["max_fatigue"])))
    print("PERCLOS         : %.1f%%" % (100 * s["perclos"]))
    if s.get("distance_km") is not None:
        print("Distance        : %.2f km%s" % (s["distance_km"], "" if s.get("avg_speed") is None
                                                 else " (avg %d km/h)" % round(s["avg_speed"])))


if __name__ == "__main__":
    if len(sys.argv) > 1:
        path = sys.argv[1]
    else:
        logs = sorted(glob.glob(os.path.join(PROJECT_DIR, "logs", "session_*.csv")))
        if not logs:
            raise SystemExit("No logs found. Run main.py first.")
        path = logs[-1]
    name = os.path.splitext(os.path.basename(path))[0].replace("session_", "")
    out = os.path.join(PROJECT_DIR, "results", "trip_report_%s.png" % name)
    s = make_trip_report(load_session(path), out,
                         os.path.join(PROJECT_DIR, "results", "trip_events_%s.csv" % name),
                         "Session log: " + os.path.basename(path))
    if s:
        print_summary(s)
        print("Report saved:", out)
