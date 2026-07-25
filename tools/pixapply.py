#!/usr/bin/env python3
"""Gate-simulation rescorer: inject gated pixmatch reads into dumped states,
re-run decide(), score. Lets gate variants be measured on full dev in seconds
without re-extraction. The production wiring in pipeline.extract_state must
mirror the gates that ship.

  python tools/pixapply.py --rows /tmp/pixstudy /tmp/pixstudy-h \
      --states /tmp/mib-eval-w6/states_dev.jsonl --truth /tmp/mib-eval-w6/truth_dev.csv
"""
import argparse
import glob
import json
import subprocess
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from mib import pixmatch  # noqa: E402
from mib.pipeline import (FALLBACKS, batch_epoch, batch_frequent_sponsors,  # noqa: E402
                          decide)

from tools.challenge_paths import CHALLENGE  # noqa: E402
CH = CHALLENGE
APPROVE_ENABLING = pixmatch.APPROVE_ENABLING


def passes(row, gates):
    field = row["field"]
    g = gates.get(field) or gates.get("_default")
    if g is None:
        return False
    if row["ncc"] < g["ncc"] or row["margin"] < g["margin"]:
        return False
    if g.get("ctc") and not row.get("ctc_agree"):
        return False
    key = (field, str(row["pix"]))
    if key in APPROVE_ENABLING or field in gates.get("_ctc_always", ()):
        if not row.get("ctc_agree"):
            return False
    return True


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--rows", nargs="+", required=True)
    ap.add_argument("--states", default="/tmp/mib-eval-w6/states_dev.jsonl")
    ap.add_argument("--truth", default="/tmp/mib-eval-w6/truth_dev.csv")
    ap.add_argument("--out-dir", default="/tmp/pixapply")
    ap.add_argument("--gates", default=None, help="JSON gate spec")
    ap.add_argument("--tag", default="pix")
    ap.add_argument("--fill-only", action="store_true",
                    help="only inject reads for fields with no existing pool")
    args = ap.parse_args()

    gates = json.loads(args.gates) if args.gates else dict(pixmatch.GATES)

    reads = defaultdict(dict)
    for d in args.rows:
        for f in glob.glob(f"{d}/rows_*.jsonl"):
            for line in open(f):
                r = json.loads(line)
                reads[r["case_id"]][r["field"]] = r

    n_inject = n_regembargo = 0
    preds = []
    states = []
    for line in open(args.states):
        s = json.loads(line)
        states.append(s)
    epoch = batch_epoch(states)
    batch_revoked = batch_frequent_sponsors(states)

    for s in states:
        cid = s["case_id"]
        pools = s.get("pools", {})
        for field, row in reads.get(cid, {}).items():
            if not passes(row, gates):
                continue
            if field == "registry_status":
                if row["pix"] == "EMBARGO REVIEW":
                    s.setdefault("doc_notes", {})["registry_embargo"] = True
                    n_regembargo += 1
                continue
            if args.fill_only and field in pools:
                continue
            score = 60.0 + min(30.0, 200.0 * row["margin"])
            if field == "risk_flags":
                score = min(score, 84.0)
            pools.setdefault(field, []).append(
                [row["pix"], "pixmatch", 6, score, row["pix"]])
            n_inject += 1
        try:
            pred, _ = decide(s, epoch, batch_revoked=batch_revoked)
        except Exception:
            pred = {"case_id": cid, **FALLBACKS,
                    "adjudication": "NEEDS_REVIEW", "confidence": 0.3}
        preds.append(pred)

    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    pred_path = out / f"predictions_{args.tag}.jsonl"
    with open(pred_path, "w") as f:
        for p in preds:
            f.write(json.dumps(p) + "\n")
    ev_path = out / f"evaluation_{args.tag}.json"
    subprocess.run(
        [sys.executable, str(CH / "scripts/evaluate.py"),
         "--truth", args.truth, "--submission", str(pred_path),
         "--output-json", str(ev_path),
         "--case-scores-jsonl", str(out / f"case_scores_{args.tag}.jsonl")],
        check=False, capture_output=True)
    ev = json.loads(ev_path.read_text())
    sc = ev["scores"]
    print(f"{args.tag}: injected {n_inject} reads (+{n_regembargo} registry-embargo) | "
          f"total={sc['total_score']:.2f} clf={sc['classification_score']:.2f} "
          f"extr={sc['extraction_score']:.2f} calib={sc['calibration_score']:.2f} "
          f"FA={ev['raw']['catastrophic_false_approvals']}")


if __name__ == "__main__":
    main()
