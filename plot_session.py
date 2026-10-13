"""
plot_session.py - Draws the "EAR over time" graph for your paper from a
session log saved by main.py.

    python plot_session.py                      # newest log in logs/
    python plot_session.py logs/session_X.csv   # a specific log

The graph shows: the EAR line, the drowsiness threshold (dashed), short dips
(normal blinks) and the red-shaded periods where the alarm was on.
Tip: record a 30-60 s session where you blink normally, then close your eyes
for 3 s once or twice - it makes a very clear figure.
"""

import csv
import glob
import os
import sys

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

from report import BLUE, GRID, INK, INK_2, MUTED

PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))
RED = "#d03b3b"


def load(path):
    t, ear, thr, status = [], [], [], []
    with open(path, newline="") as f:
        for r in csv.DictReader(f):
            if r["status"] == "CALIBRATING":
                continue
            t.append(float(r["time_s"]))
            ear.append(float(r["ear"]) if r["ear"] else float("nan"))
            thr.append(float(r["threshold"]))
            status.append(r["status"])
    return t, ear, thr, status


def drowsy_spans(t, status):
    spans, start = [], None
    for ti, s in zip(t, status):
        if s == "DROWSY" and start is None:
            start = ti
        elif s != "DROWSY" and start is not None:
            spans.append((start, ti))
            start = None
    if start is not None:
        spans.append((start, t[-1]))
    return spans


def main():
    if len(sys.argv) > 1:
        path = sys.argv[1]
    else:
        logs = sorted(glob.glob(os.path.join(PROJECT_DIR, "logs", "session_*.csv")))
        if not logs:
            raise SystemExit("No logs found. Run main.py first.")
        path = logs[-1]

    t, ear, thr, status = load(path)
    if not t:
        raise SystemExit("Log has no data after calibration: " + path)
    t0 = t[0]
    t = [x - t0 for x in t]

    fig, ax = plt.subplots(figsize=(8, 3.4), dpi=200)
    for i, (a, b) in enumerate(drowsy_spans(t, status)):
        ax.axvspan(a, b, color=RED, alpha=0.12, lw=0,
                   label="Drowsiness alarm on" if i == 0 else None)
    ax.plot(t, ear, color=BLUE, lw=1.4, label="Eye Aspect Ratio (EAR)")
    ax.plot(t, thr, color=RED, lw=1.2, ls="--", label="Threshold (%.3f)" % thr[-1])

    ax.set_xlabel("Time (seconds)", color=INK_2)
    ax.set_ylabel("EAR", color=INK_2)
    ax.set_title("Eye Aspect Ratio during a driving session", color=INK, fontsize=11)
    ax.set_xlim(0, t[-1])
    valid = [e for e in ear if e == e]
    ax.set_ylim(0, max(0.45, max(valid) * 1.1) if valid else 0.5)
    ax.yaxis.grid(True, color=GRID)
    for s in ("top", "right", "left"):
        ax.spines[s].set_visible(False)
    ax.spines["bottom"].set_color(MUTED)
    ax.tick_params(colors=INK_2, length=0)
    ax.legend(loc="lower right", frameon=False, fontsize=8, labelcolor=INK_2)
    fig.tight_layout()

    os.makedirs(os.path.join(PROJECT_DIR, "results"), exist_ok=True)
    out = os.path.join(PROJECT_DIR, "results",
                       os.path.splitext(os.path.basename(path))[0] + "_ear_graph.png")
    fig.savefig(out, facecolor="white")
    print("Graph saved:", out)


if __name__ == "__main__":
    main()
