#!/usr/bin/env python3
"""Run the pipeline over training PDFs and score dev/holdout splits separately.

The 800/200 split is sealed by md5(case_id): hash mod 5 == 0 -> holdout.
All tuning uses dev; holdout is read at milestones only.

Extraction uses the SAME plain-process shard workers as production
(scripts/run_shard.py) rather than a multiprocessing pool: RapidOCR + a pool
deadlocks intermittently under macOS spawn (the pool parent hangs at 0% CPU).
Plain os processes are the reliable local path and mirror the Docker runtime.
"""
import argparse
import csv
import hashlib
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from mib import two_ledger  # noqa: E402
from mib.pipeline import (FALLBACKS, batch_epoch, batch_frequent_sponsors,  # noqa: E402
                          decide)

# Dev-time only (never COPYd into the image). Resolve the challenge checkout
# from the environment so the script works from any clean checkout; defaults to
# a sibling directory of this repo.
CHALLENGE = Path(os.environ.get(
    "MIB_CHALLENGE_DIR",
    Path(__file__).resolve().parents[2] / "mib-doc-challenge"))
RUN_SHARD = Path(__file__).resolve().parent / "run_shard.py"


def is_holdout(case_id):
    return int(hashlib.md5(case_id.encode()).hexdigest(), 16) % 5 == 0


def extract_states(pdfs, workers=6):
    """Plain-process shard extraction (no pool). Returns list of state dicts."""
    tmp = Path(tempfile.mkdtemp(prefix="mib-eval-"))
    procs = []
    for i in range(workers):
        lst = tmp / f"shard{i}.txt"
        lst.write_text(json.dumps([str(p) for p in pdfs[i::workers]]))
        env = dict(os.environ, OMP_NUM_THREADS="1",
                   OPENBLAS_NUM_THREADS="1", MKL_NUM_THREADS="1")
        procs.append(subprocess.Popen(
            [sys.executable, str(RUN_SHARD), str(lst), str(tmp / f"state{i}.jsonl")],
            env=env))
    for p in procs:
        p.wait()
    states, seen = [], set()
    for i in range(workers):
        sf = tmp / f"state{i}.jsonl"
        if sf.exists():
            for line in open(sf):
                s = json.loads(line)
                states.append(s)
                seen.add(s["case_id"])
    for p in pdfs:
        if p.stem not in seen:
            states.append({"case_id": p.stem, "pools": {}, "doc_notes": {},
                           "mean_ocr_conf": 0.0, "injection": {}})
    return states


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--train-dir", default=str(CHALLENGE / "data/train"))
    ap.add_argument("--labels", default=str(CHALLENGE / "data/train_labels.csv"))
    ap.add_argument("--out-dir", default="/tmp/mib-eval")
    ap.add_argument("--split", choices=["dev", "holdout", "all"], default="dev")
    ap.add_argument("--details", action="store_true", help="write per-case debug jsonl")
    ap.add_argument("--states-out", action="store_true",
                    help="save merged extraction states to out-dir/states_<split>.jsonl "
                         "(decision-layer experiments re-run decide() without re-OCR)")
    ap.add_argument("--workers", type=int, default=6)
    args = ap.parse_args()

    pdfs = sorted(Path(args.train_dir).glob("*.pdf"))
    if args.split != "all":
        want = args.split == "holdout"
        pdfs = [p for p in pdfs if is_holdout(p.stem) == want]

    os.makedirs(args.out_dir, exist_ok=True)
    print(f"extracting {len(pdfs)} {args.split} PDFs on {args.workers} shards...", flush=True)
    states = extract_states(pdfs, args.workers)
    epoch = batch_epoch(states)
    batch_revoked = batch_frequent_sponsors(states)
    # Two-ledger fusion: the native ledgers form an independent batch whose own
    # epoch/frequent-sponsor set decide the native side. ``ablation`` is None
    # (baseline behavior) only when MIB_NATIVE_SCAN_OCR=0; fusion is the
    # production default after its sealed holdout promotion gate.
    ablation = two_ledger.ablation_from_env()
    native_states, has_native = two_ledger.native_batch_inputs(states)
    native_epoch = batch_epoch(native_states) if has_native else epoch
    native_revoked = (batch_frequent_sponsors(native_states)
                      if has_native else batch_revoked)
    print(f"batch epoch: {epoch}; batch-frequent sponsors: {sorted(batch_revoked) or 'none'}"
          f"; two-ledger ablation: {ablation}"
          f" (native ledgers: {len(native_states)})", flush=True)

    preds, details = [], []
    for s in states:
        try:
            pred, detail = two_ledger.decide_case(
                s, epoch, native_epoch, batch_revoked, native_revoked,
                ablation)
        except Exception as exc:
            pred = {"case_id": s["case_id"], **FALLBACKS,
                    "adjudication": "NEEDS_REVIEW", "confidence": 0.3}
            detail = {"error": repr(exc)[:200]}
        preds.append(pred)
        details.append({"case_id": pred["case_id"], **detail})

    if details and "mean_ocr_conf" not in details[0] and "error" not in details[0]:
        raise SystemExit("STALE MODULE: details missing mean_ocr_conf")

    if args.states_out:
        with open(Path(args.out_dir) / f"states_{args.split}.jsonl", "w") as f:
            for s in states:
                f.write(json.dumps(s) + "\n")

    pred_path = Path(args.out_dir) / f"predictions_{args.split}.jsonl"
    with open(pred_path, "w") as f:
        for p in preds:
            f.write(json.dumps(p) + "\n")
    if args.details:
        with open(Path(args.out_dir) / f"details_{args.split}.jsonl", "w") as f:
            for d in details:
                f.write(json.dumps(d) + "\n")

    with open(args.labels) as f:
        rows = list(csv.DictReader(f))
    keep = {p.stem for p in pdfs}
    truth_path = Path(args.out_dir) / f"truth_{args.split}.csv"
    with open(truth_path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=rows[0].keys())
        w.writeheader()
        w.writerows([r for r in rows if r["case_id"] in keep])

    subprocess.run(
        [sys.executable, str(CHALLENGE / "scripts/evaluate.py"),
         "--truth", str(truth_path), "--submission", str(pred_path),
         "--output-json", str(Path(args.out_dir) / f"evaluation_{args.split}.json"),
         "--case-scores-jsonl", str(Path(args.out_dir) / f"case_scores_{args.split}.jsonl")],
        check=False)
    ev = json.loads((Path(args.out_dir) / f"evaluation_{args.split}.json").read_text())
    s = ev["scores"]
    print(f"\n{args.split}: total={s['total_score']:.2f} clf={s['classification_score']:.2f} "
          f"extr={s['extraction_score']:.2f} calib={s['calibration_score']:.2f} "
          f"FA={ev['raw']['catastrophic_false_approvals']}")


if __name__ == "__main__":
    main()
