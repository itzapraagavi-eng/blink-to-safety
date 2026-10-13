"""
train_cnn.py - Trains a small Convolutional Neural Network (CNN) that looks
at a 32x32 grey eye image and says OPEN or CLOSED. Exports it as
models/eye_cnn.onnx, which main.py runs with OpenCV (no PyTorch needed).

Data (use one or both):
  * Your own recordings from collect_eyes.py  ->  data/eyes/open, data/eyes/closed
  * MRL Eye Dataset (free, ~85,000 eye images, search "MRL Eye Dataset"):
        python train_cnn.py --mrl path/to/mrlEyes_2018_01
    (its file names hold the label: the 5th number is 0 = closed, 1 = open)

Run:
    pip install torch            (only needed for training)
    python train_cnn.py                            # own data, 20 epochs
    python train_cnn.py --test-person P2           # fair test on an unseen person
    python train_cnn.py --mrl mrlEyes_2018_01 --epochs 15

No GPU? It trains on a laptop CPU in a few minutes. For the MRL dataset,
Google Colab (free GPU) is faster: upload the project zip and run the same command.

Outputs (in results/):  cnn_metrics.txt, cnn_confusion_matrix.png,
cnn_training_curve.png  -> ready for the paper.
"""

import argparse
import glob
import os
import random
import time
import warnings

import cv2
import numpy as np

PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))
IMG = 32

try:
    import torch
    import torch.nn as nn
except ImportError:
    raise SystemExit("PyTorch is needed for training:  pip install torch")


class EyeNet(nn.Module):
    """3 convolution blocks (16 -> 32 -> 64 filters) + 2 dense layers.
    About 90,000 parameters - fast enough for real time on a CPU."""

    def __init__(self):
        super().__init__()

        def block(cin, cout):
            return nn.Sequential(nn.Conv2d(cin, cout, 3, padding=1), nn.BatchNorm2d(cout),
                                 nn.ReLU(), nn.MaxPool2d(2))
        self.features = nn.Sequential(block(1, 16), block(16, 32), block(32, 64))
        self.classifier = nn.Sequential(nn.Flatten(), nn.Dropout(0.3),
                                        nn.Linear(64 * 4 * 4, 64), nn.ReLU(),
                                        nn.Linear(64, 2))

    def forward(self, x):
        return self.classifier(self.features(x))


def prep(img):
    """Same preparation as features.eye_crop(): grey, 32x32, equalised."""
    if img is None:
        return None
    if img.ndim == 3:
        img = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    if img.shape != (IMG, IMG):
        img = cv2.resize(img, (IMG, IMG), interpolation=cv2.INTER_AREA)
    return cv2.equalizeHist(img)


def load_own(folder):
    items = []
    for label, cls in (("open", 0), ("closed", 1)):
        for f in glob.glob(os.path.join(folder, label, "*.png")):
            items.append((f, cls, os.path.basename(f).split("_")[0]))
    return items


def load_mrl(folder):
    items = []
    for f in glob.glob(os.path.join(folder, "**", "*.png"), recursive=True):
        parts = os.path.basename(f).split("_")
        if len(parts) >= 5 and parts[4] in ("0", "1"):
            items.append((f, 0 if parts[4] == "1" else 1, "mrl_" + parts[0]))
    return items


def to_arrays(items):
    xs, ys, keep = [], [], []
    for f, y, person in items:
        img = prep(cv2.imread(f, cv2.IMREAD_GRAYSCALE))
        if img is not None:
            xs.append(img); ys.append(y); keep.append(person)
    return np.array(xs, np.float32)[:, None] / 255.0, np.array(ys, np.int64), keep


def augment(x):
    """Random flip, brightness/contrast change, small shift and noise."""
    if random.random() < 0.5:
        x = torch.flip(x, dims=[3])
    n = x.shape[0]
    contrast = torch.empty(n, 1, 1, 1, device=x.device).uniform_(0.7, 1.3)
    bright = torch.empty(n, 1, 1, 1, device=x.device).uniform_(-0.15, 0.15)
    x = (x - 0.5) * contrast + 0.5 + bright
    dx, dy = random.randint(-2, 2), random.randint(-2, 2)
    x = torch.roll(x, shifts=(dy, dx), dims=(2, 3))
    x = x + torch.randn_like(x) * 0.03
    return x.clamp(0, 1)


def evaluate(model, x, y, device, bs=512):
    model.eval()
    preds = []
    with torch.no_grad():
        for i in range(0, len(x), bs):
            preds.append(model(torch.from_numpy(x[i:i + bs]).to(device)).argmax(1).cpu().numpy())
    return np.concatenate(preds) if preds else np.array([], np.int64)


def metrics(y, p):
    tp = int(((p == 1) & (y == 1)).sum()); tn = int(((p == 0) & (y == 0)).sum())
    fp = int(((p == 1) & (y == 0)).sum()); fn = int(((p == 0) & (y == 1)).sum())
    acc = (tp + tn) / max(1, len(y))
    prec = tp / max(1, tp + fp); rec = tp / max(1, tp + fn)
    f1 = 2 * prec * rec / max(1e-9, prec + rec)
    return dict(TP=tp, TN=tn, FP=fp, FN=fn, accuracy=acc, precision=prec, recall=rec, f1=f1)


def save_charts(hist, m, out_dir):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    BLUE, ORANGE, INK, INK_2, MUTED, GRID = "#2a78d6", "#eb6834", "#0b0b0b", "#52514e", "#898781", "#e6e5e1"

    fig, ax = plt.subplots(figsize=(6, 3.6), dpi=200)
    ep = range(1, len(hist["train"]) + 1)
    ax.plot(ep, [100 * a for a in hist["train"]], color=BLUE, lw=2, label="Training accuracy")
    ax.plot(ep, [100 * a for a in hist["val"]], color=ORANGE, lw=2, label="Validation accuracy")
    ax.set_xlabel("Epoch", color=INK_2); ax.set_ylabel("Accuracy (%)", color=INK_2)
    ax.set_title("CNN eye-state model: training", color=INK, fontsize=11)
    ax.yaxis.grid(True, color=GRID)
    for s in ("top", "right", "left"):
        ax.spines[s].set_visible(False)
    ax.spines["bottom"].set_color(MUTED); ax.tick_params(colors=INK_2, length=0)
    ax.legend(frameon=False, fontsize=8, labelcolor=INK_2)
    fig.tight_layout(); fig.savefig(os.path.join(out_dir, "cnn_training_curve.png"), facecolor="white")
    plt.close(fig)

    cells = [[m["TP"], m["FN"]], [m["FP"], m["TN"]]]
    big = max(1, max(max(r) for r in cells))
    fig, ax = plt.subplots(figsize=(4.6, 4.0), dpi=200)
    ax.imshow(cells, cmap="Blues", vmin=0, vmax=big * 1.15)
    ax.set_xticks([0, 1], labels=["Closed", "Open"]); ax.set_yticks([0, 1], labels=["Closed", "Open"])
    ax.set_xlabel("Predicted by CNN", color=INK_2); ax.set_ylabel("Actual eye state", color=INK_2)
    for i in range(2):
        for j in range(2):
            v = cells[i][j]
            ax.text(j, i, str(v), ha="center", va="center", fontsize=15, fontweight="bold",
                    color="white" if v > big * 0.55 else INK)
    for s in ax.spines.values():
        s.set_visible(False)
    ax.tick_params(length=0, colors=INK_2)
    ax.set_title("CNN test set (accuracy %.1f%%)" % (100 * m["accuracy"]), color=INK, fontsize=11)
    fig.tight_layout(); fig.savefig(os.path.join(out_dir, "cnn_confusion_matrix.png"), facecolor="white")
    plt.close(fig)


def main():
    p = argparse.ArgumentParser(description="Train the CNN eye-state model")
    p.add_argument("--data", default=os.path.join(PROJECT_DIR, "data", "eyes"))
    p.add_argument("--mrl", default=None, help="path to the MRL Eye Dataset (optional)")
    p.add_argument("--epochs", type=int, default=20)
    p.add_argument("--batch", type=int, default=128)
    p.add_argument("--lr", type=float, default=1e-3)
    p.add_argument("--test-person", default=None,
                   help="keep this person only for testing (fair: model never saw them)")
    p.add_argument("--max-per-class", type=int, default=20000)
    p.add_argument("--out", default=os.path.join(PROJECT_DIR, "models", "eye_cnn.onnx"))
    p.add_argument("--seed", type=int, default=42)
    args = p.parse_args()

    random.seed(args.seed); np.random.seed(args.seed); torch.manual_seed(args.seed)
    items = load_own(args.data) if os.path.isdir(args.data) else []
    if args.mrl:
        items += load_mrl(args.mrl)
    if not items:
        raise SystemExit("No images found. Run collect_eyes.py first (or use --mrl).")
    random.shuffle(items)
    by_cls = {0: [i for i in items if i[1] == 0][:args.max_per_class],
              1: [i for i in items if i[1] == 1][:args.max_per_class]}
    items = by_cls[0] + by_cls[1]
    print("Images: %d open, %d closed from %d people" % (
        len(by_cls[0]), len(by_cls[1]), len(set(i[2] for i in items))))
    if min(len(by_cls[0]), len(by_cls[1])) < 20:
        raise SystemExit("Need at least 20 images of each class.")

    # ---- split: test (20%), validation (10%), training (70%) ----
    # done separately for open and closed, so every part has both classes
    test, val, train = [], [], []
    for cls in (0, 1):
        group = by_cls[cls]
        if args.test_person:
            t = [i for i in group if i[2] == args.test_person]
            rest = [i for i in group if i[2] != args.test_person]
        else:
            n_test = int(0.2 * len(group))
            t, rest = group[:n_test], group[n_test:]
        n_val = max(1, int(0.125 * len(rest)))
        test += t; val += rest[:n_val]; train += rest[n_val:]
    if args.test_person and not test:
        raise SystemExit("No images of person %s" % args.test_person)
    for part in (test, val, train):
        random.shuffle(part)

    xtr, ytr, _ = to_arrays(train); xva, yva, _ = to_arrays(val); xte, yte, _ = to_arrays(test)
    print("Train %d | validation %d | test %d" % (len(ytr), len(yva), len(yte)))

    device = "cuda" if torch.cuda.is_available() else "cpu"
    model = EyeNet().to(device)
    print("Model parameters: %d | device: %s" % (sum(p.numel() for p in model.parameters()), device))
    counts = np.bincount(ytr, minlength=2).astype(np.float32)
    weights = torch.tensor(counts.sum() / (2 * np.maximum(counts, 1)), device=device)
    loss_fn = nn.CrossEntropyLoss(weight=weights)
    opt = torch.optim.Adam(model.parameters(), lr=args.lr, weight_decay=1e-4)
    sched = torch.optim.lr_scheduler.CosineAnnealingLR(opt, T_max=args.epochs)

    xt, yt = torch.from_numpy(xtr), torch.from_numpy(ytr)
    hist = {"train": [], "val": []}
    best_acc, best_state = -1, None
    t0 = time.time()
    for epoch in range(1, args.epochs + 1):
        model.train()
        perm = torch.randperm(len(yt))
        correct = 0
        for i in range(0, len(perm), args.batch):
            idx = perm[i:i + args.batch]
            xb, yb = augment(xt[idx].to(device)), yt[idx].to(device)
            out = model(xb)
            loss = loss_fn(out, yb)
            opt.zero_grad(); loss.backward(); opt.step()
            correct += (out.argmax(1) == yb).sum().item()
        sched.step()
        tr_acc = correct / len(yt)
        va_acc = (evaluate(model, xva, yva, device) == yva).mean()
        hist["train"].append(tr_acc); hist["val"].append(float(va_acc))
        if va_acc >= best_acc:
            best_acc = va_acc
            best_state = {k: v.detach().clone() for k, v in model.state_dict().items()}
        print("Epoch %2d/%d  loss %.3f  train %.1f%%  val %.1f%%" % (
            epoch, args.epochs, loss.item(), 100 * tr_acc, 100 * va_acc))

    model.load_state_dict(best_state)
    pred = evaluate(model, xte, yte, device)
    m = metrics(yte, pred)
    report = ("CNN eye-state model - test results (%d eye images%s)\n"
              "  Accuracy  : %.1f%%\n  Precision : %.1f%%  (closed)\n"
              "  Recall    : %.1f%%  (closed)\n  F1-score  : %.1f%%\n"
              "  TP %d  FN %d  FP %d  TN %d\n  Training time: %.0f s on %s\n" % (
                  len(yte), ", unseen person " + args.test_person if args.test_person else "",
                  100 * m["accuracy"], 100 * m["precision"], 100 * m["recall"], 100 * m["f1"],
                  m["TP"], m["FN"], m["FP"], m["TN"], time.time() - t0, device))
    print("\n" + report)

    # ---- export to ONNX (runs in OpenCV without PyTorch) ----
    model.eval().cpu()
    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    dummy = torch.zeros(1, 1, IMG, IMG)
    warnings.filterwarnings("ignore", category=DeprecationWarning)
    try:
        torch.onnx.export(model, dummy, args.out, input_names=["eye"], output_names=["logits"],
                          opset_version=12, dynamo=False)
    except TypeError:   # older PyTorch without the dynamo argument
        torch.onnx.export(model, dummy, args.out, input_names=["eye"], output_names=["logits"],
                          opset_version=12)
    # check OpenCV gives the same answers
    net = cv2.dnn.readNetFromONNX(args.out)
    same = 0
    for k in range(min(50, len(xte))):
        net.setInput(xte[k:k + 1])
        same += int(net.forward().argmax() == pred[k])
    print("Model saved: %s  (OpenCV check: %d/%d same predictions)" % (args.out, same, min(50, len(xte))))

    out_dir = os.path.join(PROJECT_DIR, "results")
    os.makedirs(out_dir, exist_ok=True)
    with open(os.path.join(out_dir, "cnn_metrics.txt"), "w") as f:
        f.write(report)
    save_charts(hist, m, out_dir)
    print("Charts and metrics saved in results/")
    print("Use it:  python main.py --method cnn    (or --method hybrid)")


if __name__ == "__main__":
    main()
