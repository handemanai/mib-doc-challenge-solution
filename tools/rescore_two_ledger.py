#!/usr/bin/env python3
"""Re-decide cached extraction states under a chosen two-ledger ablation.

Extraction (OCR) is identical between the fields and full ablations, so a
flag-on states file saved by eval_split.py can be re-scored under either
ablation without re-extracting. Baseline states (no native_ledger) decide to the
baseline regardless of ablation.

    tools/rescore_two_ledger.py --states states_dev.jsonl \
        --truth truth_dev.csv --out-dir /tmp/x --ablation fields
"""
import argparse
import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from mib import two_ledger  # noqa: E402
from mib.pipeline import (FALLBACKS, batch_epoch,  # noqa: E402
                          batch_frequent_sponsors)

from tools.challenge_paths import CHALLENGE  # noqa: E402
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--states", required=True)
    ap.add_argument("--truth", required=True)
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--ablation", choices=["off", "fields", "full"],
                    required=True)
    ap.add_argument("--tag", default=None)
    args = ap.parse_args()
    tag = args.tag or args.ablation

    states = [json.loads(l) for l in open(args.states) if l.strip()]
    ablation = None if args.ablation == "off" else args.ablation
    epoch = batch_epoch(states)
    revoked = batch_frequent_sponsors(states)
    natives, has = two_ledger.native_batch_inputs(states)
    nepoch = batch_epoch(natives) if has else epoch
    nrevoked = batch_frequent_sponsors(natives) if has else revoked

    preds, ledger = [], []
    for s in states:
        try:
            pred, detail = two_ledger.decide_case(
                s, epoch, nepoch, revoked, nrevoked, ablation)
        except Exception as exc:
            pred = {"case_id": s["case_id"], **FALLBACKS,
                    "adjudication": "NEEDS_REVIEW", "confidence": 0.3}
            detail = {"error": repr(exc)[:200]}
        preds.append(pred)
        ledger.append({"case_id": pred["case_id"],
                       "adjudication": pred["adjudication"],
                       "confidence": pred["confidence"],
                       "fields": {f: pred[f] for f in FALLBACKS},
                       "two_ledger": detail.get("two_ledger")})

    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    pred_path = out / f"predictions_{tag}.jsonl"
    with open(pred_path, "w") as f:
        for p in preds:
            f.write(json.dumps(p) + "\n")
    with open(out / f"ledger_{tag}.jsonl", "w") as f:
        for row in ledger:
            f.write(json.dumps(row) + "\n")

    ev_path = out / f"evaluation_{tag}.json"
    subprocess.run(
        [sys.executable, str(CHALLENGE / "scripts/evaluate.py"),
         "--truth", args.truth, "--submission", str(pred_path),
         "--output-json", str(ev_path),
         "--case-scores-jsonl", str(out / f"case_scores_{tag}.jsonl")],
        check=False, capture_output=True)
    ev = json.loads(ev_path.read_text())
    s = ev["scores"]
    print(f"{tag}: total={s['total_score']:.4f} clf={s['classification_score']:.4f} "
          f"extr={s['extraction_score']:.4f} calib={s['calibration_score']:.4f} "
          f"FA={ev['raw']['catastrophic_false_approvals']}")


if __name__ == "__main__":
    main()
