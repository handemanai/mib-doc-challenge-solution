#!/usr/bin/env python3
"""Re-run the decision layer over cached extraction states and score.

The extract/decide split means decision-layer experiments (pool-selection
gates, calibrator changes, rule tweaks) never pay the OCR cost: point this at
a states_<split>.jsonl saved by `eval_split.py --states-out` and it re-runs
decide() with the CURRENT working-tree code and scores against truth.

    python tools/rescore.py --states /tmp/mib-eval-f1/states_dev.jsonl \
        --truth /tmp/mib-eval-f1/truth_dev.csv --out-dir /tmp/mib-exp1
"""
import argparse
import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from mib.pipeline import FALLBACKS, batch_epoch, decide  # noqa: E402

from tools.challenge_paths import CHALLENGE  # noqa: E402
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--states", required=True)
    ap.add_argument("--truth", required=True)
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--tag", default="exp")
    args = ap.parse_args()

    states = [json.loads(l) for l in open(args.states)]
    epoch = batch_epoch(states)

    preds, details = [], []
    for s in states:
        try:
            pred, detail = decide(s, epoch)
        except Exception as exc:
            pred = {"case_id": s["case_id"], **FALLBACKS,
                    "adjudication": "NEEDS_REVIEW", "confidence": 0.3}
            detail = {"error": repr(exc)[:200]}
        preds.append(pred)
        details.append({"case_id": pred["case_id"], **detail})

    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    pred_path = out / f"predictions_{args.tag}.jsonl"
    with open(pred_path, "w") as f:
        for p in preds:
            f.write(json.dumps(p) + "\n")
    with open(out / f"details_{args.tag}.jsonl", "w") as f:
        for d in details:
            f.write(json.dumps(d) + "\n")

    ev_path = out / f"evaluation_{args.tag}.json"
    subprocess.run(
        [sys.executable, str(CHALLENGE / "scripts/evaluate.py"),
         "--truth", args.truth, "--submission", str(pred_path),
         "--output-json", str(ev_path),
         "--case-scores-jsonl", str(out / f"case_scores_{args.tag}.jsonl")],
        check=False, capture_output=True)
    ev = json.loads(ev_path.read_text())
    s = ev["scores"]
    print(f"{args.tag}: total={s['total_score']:.2f} clf={s['classification_score']:.2f} "
          f"extr={s['extraction_score']:.2f} calib={s['calibration_score']:.2f} "
          f"FA={ev['raw']['catastrophic_false_approvals']}")


if __name__ == "__main__":
    main()
