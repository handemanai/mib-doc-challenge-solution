#!/usr/bin/env python3
"""Fit the per-case confidence calibrator on dev results.

Logistic regression over evidence-quality features, 5-fold out-of-fold, then
isotonic binning of the OOF scores — fit globally AND per predicted decision
class (a hedge's P(correct) has a different shape than an approval's; classes
below MIN_CLASS_N fall back to the global curve). Exported as plain JSON
(models/calibrator.json) so the runtime computes it with math only.

    python scripts/fit_calibrator.py --details /tmp/x/details_exp.jsonl \
        --preds /tmp/x/predictions_exp.jsonl
"""
import argparse
import csv
import json
import os
import sys
from pathlib import Path

import numpy as np
from sklearn.isotonic import IsotonicRegression
from sklearn.linear_model import LogisticRegression
from sklearn.model_selection import StratifiedKFold

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from mib.pipeline import PATH_CONFIDENCE, calib_features  # noqa: E402

# Per-class isotonic with empirical-Bayes shrinkage toward the global curve:
# weight n/(n+K). Replaces the old hard MIN_CLASS_N=120 gate under which
# APPROVED — the highest-stakes class — silently fell back 100% to the global
# curve for want of ~20 samples. A blend of monotone curves stays monotone.
MIN_CLASS_N = 25
SHRINK_K = 60.0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--details", required=True)
    ap.add_argument("--preds", required=True)
    # Dev-time only (never COPYd into the image). Resolve the challenge
    # checkout from the environment so this works from any clean checkout.
    challenge = Path(os.environ.get(
        "MIB_CHALLENGE_DIR",
        Path(__file__).resolve().parents[2] / "mib-doc-challenge"))
    ap.add_argument("--labels",
                    default=str(challenge / "data" / "train_labels.csv"))
    ap.add_argument("--out", default=str(Path(__file__).resolve().parents[1] / "models" / "calibrator.json"))
    args = ap.parse_args()

    labels = {r["case_id"]: r for r in csv.DictReader(open(args.labels))}
    details = {json.loads(l)["case_id"]: json.loads(l) for l in open(args.details)}
    preds = {json.loads(l)["case_id"]: json.loads(l) for l in open(args.preds)}

    ids = sorted(details)
    names = sorted(calib_features(details[ids[0]], PATH_CONFIDENCE).keys())
    X = np.array([[calib_features(details[c], PATH_CONFIDENCE)[n] for n in names] for c in ids])
    y = np.array([int(preds[c]["adjudication"] == labels[c]["adjudication"]) for c in ids])
    cls = np.array([preds[c]["adjudication"] for c in ids])
    print(f"cases {len(y)}, correct rate {y.mean():.3f}, features {len(names)}")

    mu, sd = X.mean(0), X.std(0) + 1e-9
    Xz = (X - mu) / sd
    oof = np.zeros(len(y))
    for tr, va in StratifiedKFold(5, shuffle=True, random_state=7).split(Xz, y):
        model = LogisticRegression(C=1.0, max_iter=1000).fit(Xz[tr], y[tr])
        oof[va] = model.predict_proba(Xz[va])[:, 1]

    grid = np.linspace(0, 1, 101)
    iso_global = IsotonicRegression(out_of_bounds="clip").fit(oof, y)
    iso_by_class = {}
    cal = np.array([float(iso_global.predict([o])[0]) for o in oof])
    for c in sorted(set(cls)):
        m = cls == c
        if m.sum() >= MIN_CLASS_N:
            iso_c = IsotonicRegression(out_of_bounds="clip").fit(oof[m], y[m])
            w = m.sum() / (m.sum() + SHRINK_K)
            blend = w * iso_c.predict(grid) + (1 - w) * iso_global.predict(grid)
            iso_by_class[c] = {"x": grid.tolist(), "y": blend.tolist()}
            cal[m] = np.interp(oof[m], grid, blend)
        print(f"  class {c:13} n={m.sum():4d} acc={y[m].mean():.3f} "
              f"{'shrunk per-class iso' if c in iso_by_class else 'global iso'}")

    brier_oof = float(np.mean((cal - y) ** 2))
    brier_prev = float(np.mean((np.array([preds[c]["confidence"] for c in ids]) - y) ** 2))
    print(f"Brier: shipped confidences {brier_prev:.4f} -> OOF refit {brier_oof:.4f}")

    final = LogisticRegression(C=1.0, max_iter=1000).fit(Xz, y)
    payload = {
        "feature_names": names,
        "mu": mu.tolist(), "sd": sd.tolist(),
        "coef": final.coef_[0].tolist(), "intercept": float(final.intercept_[0]),
        "iso_x": grid.tolist(), "iso_y": iso_global.predict(grid).tolist(),
        "iso_by_class": iso_by_class,
    }
    Path(args.out).write_text(json.dumps(payload))
    print(f"wrote {args.out}")


if __name__ == "__main__":
    main()
