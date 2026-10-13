"""
report.py - Calculates accuracy, precision, recall, F1-score, false-alarm
rate and yawn detection rate from the trials saved by evaluate.py, and draws
the charts for your paper.

Run on its own any time to rebuild the results from results/trials.csv:
    python report.py
"""

import csv
import os
from collections import OrderedDict

import matplotlib
matplotlib.use("Agg")                 # draw to files only, no window
import matplotlib.pyplot as plt

PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))
RESULTS_DIR = os.path.join(PROJECT_DIR, "results")
RESULTS_CSV = os.path.join(RESULTS_DIR, "trials.csv")
FIELDS = ["date", "person", "condition", "method", "trial", "kind", "activity",
          "actual", "predicted", "correct", "alert_delay_s", "reason", "yawn_detected",
          "distract_detected"]

SHORT_NAMES = {
    "Look ahead, blink normally": "Normal blinking",
    "TALK out loud (count 1 to 10)": "Talking",
    "SMILE and laugh": "Smiling",
    "Look at the LEFT mirror, then back": "Left mirror",
    "Look at the RIGHT mirror, then back": "Right mirror",
    "Glance DOWN at the speedometer, then back": "Speedometer",
}
BLUE = "#2a78d6"
SERIES = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100"]   # fixed order per metric
INK = "#0b0b0b"
INK_2 = "#52514e"
MUTED = "#898781"
GRID = "#e6e5e1"


def load_trials(path=RESULTS_CSV):
    if not os.path.exists(path):
        return []
    with open(path, newline="") as f:
        rows = list(csv.DictReader(f))
    for r in rows:                         # files from older versions
        r["method"] = r.get("method") or "EAR"
        r["kind"] = r.get("kind") or r["actual"]
        r["activity"] = r.get("activity") or ""
    return rows


def compute_metrics(rows):
    """'Positive' = drowsy alarm. Returns a dict of counts and scores."""
    tp = sum(1 for r in rows if r["actual"] == "DROWSY" and r["predicted"] == "DROWSY")
    fn = sum(1 for r in rows if r["actual"] == "DROWSY" and r["predicted"] == "AWAKE")
    fp = sum(1 for r in rows if r["actual"] == "AWAKE" and r["predicted"] == "DROWSY")
    tn = sum(1 for r in rows if r["actual"] == "AWAKE" and r["predicted"] == "AWAKE")
    total = tp + fn + fp + tn

    def safe(a, b):
        return a / b if b else 0.0

    precision = safe(tp, tp + fp)
    recall = safe(tp, tp + fn)
    delays = [float(r["alert_delay_s"]) for r in rows
              if r["actual"] == "DROWSY" and str(r.get("alert_delay_s", "")).strip()]
    yawn = [r for r in rows if r.get("kind") == "YAWN" and str(r.get("yawn_detected", "")).strip()]
    def has(r, key):
        v = r.get(key)
        return v is not None and str(v).strip() != ""
    dis = [r for r in rows if r.get("kind") == "DISTRACT" and has(r, "distract_detected")]
    awake = [r for r in rows if r.get("kind") == "AWAKE" and has(r, "distract_detected")]
    return {
        "trials": total, "TP": tp, "FN": fn, "FP": fp, "TN": tn,
        "accuracy": safe(tp + tn, total),
        "precision": precision,
        "recall": recall,
        "specificity": safe(tn, tn + fp),
        "false_alarm_rate": safe(fp, fp + tn),
        "f1": safe(2 * precision * recall, precision + recall),
        "avg_alert_delay": sum(delays) / len(delays) if delays else None,
        "yawn_trials": len(yawn),
        "yawn_rate": safe(sum(int(r["yawn_detected"]) for r in yawn), len(yawn)),
        "distract_trials": len(dis),
        "distract_rate": safe(sum(int(r["distract_detected"]) for r in dis), len(dis)),
        "awake_trials": len(awake),
        "distract_false": sum(int(r["distract_detected"]) for r in awake),
    }


def _pct(x):
    return "%.1f%%" % (100 * x)


def format_metrics(m, title=""):
    lines = [title] if title else []
    lines += [
        "  Trials              : %d  (TP %d, FN %d, FP %d, TN %d)" % (
            m["trials"], m["TP"], m["FN"], m["FP"], m["TN"]),
        "  Accuracy            : %s" % _pct(m["accuracy"]),
        "  Precision           : %s" % _pct(m["precision"]),
        "  Recall (detection)  : %s" % _pct(m["recall"]),
        "  Specificity         : %s" % _pct(m["specificity"]),
        "  False alarm rate    : %s  (alarms when the driver was alert)" % _pct(m["false_alarm_rate"]),
        "  F1-score            : %s" % _pct(m["f1"]),
    ]
    if m["avg_alert_delay"] is not None:
        lines.append("  Avg alert time      : %.2f s after eyes closed / head dropped" % m["avg_alert_delay"])
    if m["yawn_trials"]:
        lines.append("  Yawn detection      : %s  (%d yawn trials)" % (_pct(m["yawn_rate"]), m["yawn_trials"]))
    if m["distract_trials"]:
        lines.append("  Distraction detect. : %s  (%d trials)" % (_pct(m["distract_rate"]), m["distract_trials"]))
    if m["awake_trials"]:
        lines.append("  Distraction false   : %d of %d normal-driving trials" % (m["distract_false"], m["awake_trials"]))
    return "\n".join(lines)


def group_by(rows, key):
    groups = OrderedDict()
    for r in rows:
        groups.setdefault(r.get(key) or "-", []).append(r)
    return groups


def _style(ax):
    for s in ("top", "right", "left"):
        ax.spines[s].set_visible(False)
    ax.spines["bottom"].set_color(MUTED)
    ax.tick_params(colors=INK_2, length=0)
    ax.yaxis.grid(True, color=GRID, zorder=0)
    ax.set_axisbelow(True)


def confusion_chart(m, path, subtitle=""):
    cells = [[m["TP"], m["FN"]], [m["FP"], m["TN"]]]
    biggest = max(1, max(max(row) for row in cells))
    fig, ax = plt.subplots(figsize=(4.6, 4.0), dpi=200)
    ax.imshow(cells, cmap="Blues", vmin=0, vmax=biggest * 1.15)
    ax.set_xticks([0, 1], labels=["Drowsy", "Awake"])
    ax.set_yticks([0, 1], labels=["Drowsy", "Awake"])
    ax.set_xlabel("Predicted by system", color=INK_2)
    ax.set_ylabel("Actual state", color=INK_2)
    for i in range(2):
        for j in range(2):
            v = cells[i][j]
            ax.text(j, i, str(v), ha="center", va="center", fontsize=16,
                    fontweight="bold", color="white" if v > biggest * 0.55 else INK)
    for s in ax.spines.values():
        s.set_visible(False)
    ax.tick_params(length=0, colors=INK_2)
    title = "Confusion matrix (accuracy %s)" % _pct(m["accuracy"])
    ax.set_title(title + ("\n" + subtitle if subtitle else ""), color=INK, fontsize=11)
    fig.tight_layout()
    fig.savefig(path, facecolor="white")
    plt.close(fig)


def single_bar_chart(names, values, path, title, ylabel, fmt="%.1f%%"):
    fig, ax = plt.subplots(figsize=(max(4.8, 1.25 * len(names) + 1.8), 3.8), dpi=200)
    bars = ax.bar(names, values, color=BLUE, width=0.55, zorder=2)
    for b, v in zip(bars, values):
        ax.text(b.get_x() + b.get_width() / 2, v + 1.5, fmt % v,
                ha="center", va="bottom", fontsize=9, color=INK)
    ax.set_ylim(0, 110)
    ax.set_ylabel(ylabel, color=INK_2)
    ax.set_title(title, color=INK, fontsize=11)
    _style(ax)
    plt.setp(ax.get_xticklabels(), fontsize=8)
    fig.tight_layout()
    fig.savefig(path, facecolor="white")
    plt.close(fig)


def method_chart(groups, path):
    names = list(groups.keys())
    metrics = [("Accuracy", "accuracy"), ("Precision", "precision"),
               ("Recall", "recall"), ("F1-score", "f1")]
    ms = [compute_metrics(g) for g in groups.values()]
    fig, ax = plt.subplots(figsize=(max(6, 2.2 * len(names) + 2), 3.9), dpi=200)
    width = 0.8 / len(metrics)
    for k, (label, key) in enumerate(metrics):
        xs = [i + (k - 1.5) * width for i in range(len(names))]
        vals = [100 * m[key] for m in ms]
        ax.bar(xs, vals, width=width - 0.02, color=SERIES[k], label=label, zorder=2)
        for x, v in zip(xs, vals):
            ax.text(x, v + 1.2, "%.0f" % v, ha="center", va="bottom", fontsize=7, color=INK_2)
    ax.set_xticks(range(len(names)), labels=names)
    ax.set_ylim(0, 112)
    ax.set_ylabel("Score (%)", color=INK_2)
    ax.set_title("Method comparison: " + " vs ".join(names), color=INK, fontsize=11)
    _style(ax)
    ax.legend(frameon=False, fontsize=8, labelcolor=INK_2, ncol=4, loc="upper center",
              bbox_to_anchor=(0.5, -0.1))
    fig.tight_layout()
    fig.savefig(path, facecolor="white")
    plt.close(fig)


def make_report(rows, save=True):
    if not rows:
        print("No trial data yet. Run: python evaluate.py")
        return None
    overall = compute_metrics(rows)
    people = sorted(set(r.get("person", "") for r in rows))
    by_method = group_by(rows, "method")
    by_cond = group_by(rows, "condition")

    text = [format_metrics(overall, "OVERALL (%d people: %s)" % (len(people), ", ".join(people)))]

    def table(title, groups):
        text.append("")
        text.append(title)
        text.append("  %-18s %7s %9s %10s %8s %8s %12s" % ("", "Trials", "Accuracy",
                                                         "Precision", "Recall", "F1", "False alarm"))
        for name, g in groups.items():
            m = compute_metrics(g)
            text.append("  %-18s %7d %9s %10s %8s %8s %12s" % (
                name[:18], m["trials"], _pct(m["accuracy"]), _pct(m["precision"]),
                _pct(m["recall"]), _pct(m["f1"]), _pct(m["false_alarm_rate"])))

    if len(by_method) > 1:
        table("By method:", by_method)
    if len(by_cond) > 1:
        table("By condition:", by_cond)

    awake = [r for r in rows if r.get("kind") == "AWAKE" and r.get("activity")]
    by_act = group_by(awake, "activity")
    if by_act:
        text.append("")
        text.append("False alarms while ALERT (should be 0):")
        for name, g in by_act.items():
            fa = sum(1 for r in g if r["predicted"] == "DROWSY")
            text.append("  %-44s %d / %d" % (name[:44], fa, len(g)))
    drop = [r for r in rows if r.get("kind") == "HEAD_DROP"]
    if drop:
        det = sum(1 for r in drop if r["predicted"] == "DROWSY")
        text.append("")
        text.append("Head-drop detection : %d / %d (%s)" % (det, len(drop), _pct(det / len(drop))))
    report = "\n".join(text)
    print(report)

    if save:
        os.makedirs(RESULTS_DIR, exist_ok=True)
        with open(os.path.join(RESULTS_DIR, "summary.txt"), "w") as f:
            f.write(report + "\n")
        for name, g in by_method.items():
            m = compute_metrics(g)
            confusion_chart(m, os.path.join(RESULTS_DIR, "confusion_matrix_%s.png" % name),
                            "%s method, %d trials" % (name, m["trials"]))
        if len(by_method) > 1:
            method_chart(by_method, os.path.join(RESULTS_DIR, "method_comparison.png"))
        if len(by_cond) > 1:
            single_bar_chart(list(by_cond.keys()),
                             [100 * compute_metrics(g)["accuracy"] for g in by_cond.values()],
                             os.path.join(RESULTS_DIR, "accuracy_by_condition.png"),
                             "Detection accuracy by test condition", "Accuracy (%)")
        if by_act:
            short = [SHORT_NAMES.get(a, a[:18]) for a in by_act.keys()]
            single_bar_chart(short,
                             [100 * (1 - compute_metrics(g)["false_alarm_rate"]) for g in by_act.values()],
                             os.path.join(RESULTS_DIR, "no_false_alarm_by_activity.png"),
                             "Alert driver correctly NOT alarmed, by activity", "Correct (%)")
        print("\nSaved summary and charts in:", RESULTS_DIR)
    return overall


if __name__ == "__main__":
    make_report(load_trials())
