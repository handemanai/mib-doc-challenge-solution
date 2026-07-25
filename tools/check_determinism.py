#!/usr/bin/env python3
"""Determinism + resource envelope check.

Runs the production entrypoint (scripts/predict.py) twice over the same PDF
directory and asserts byte-identical predictions — the property 8090's clean-
checkout rerun depends on. Optionally reports peak RSS. Sorting of output and
fixed seeds should make this hold; if it doesn't, an ONNX/threading nondeterminism
or dict-ordering bug is surfaced here rather than on the private set.

    python tools/check_determinism.py --pdf-dir <dir> [--n 60]
"""
import argparse
import hashlib
import json
import resource
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PREDICT = ROOT / "scripts" / "predict.py"


def run(pdf_dir, out_path):
    r = resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss
    subprocess.run([sys.executable, str(PREDICT), str(pdf_dir), str(out_path)],
                   check=True)
    peak = resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss - r
    return peak


def canon(path):
    """Order-insensitive digest: sort rows by case_id, canonical JSON per row."""
    rows = sorted((json.loads(l) for l in open(path)), key=lambda r: r["case_id"])
    blob = "\n".join(json.dumps(r, sort_keys=True) for r in rows)
    return hashlib.sha256(blob.encode()).hexdigest(), len(rows)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pdf-dir", required=True)
    ap.add_argument("--n", type=int, default=0, help="subsample first N pdfs")
    args = ap.parse_args()

    src = Path(args.pdf_dir)
    pdfs = sorted(src.glob("*.pdf"))
    if args.n:
        pdfs = pdfs[:args.n]
        sub = Path(tempfile.mkdtemp(prefix="mib-det-"))
        for p in pdfs:
            (sub / p.name).symlink_to(p.resolve())
        src = sub

    out1 = Path(tempfile.mktemp(suffix="_1.jsonl"))
    out2 = Path(tempfile.mktemp(suffix="_2.jsonl"))
    print(f"run 1 over {len(pdfs)} pdfs...", flush=True)
    p1 = run(src, out1)
    print(f"run 2...", flush=True)
    p2 = run(src, out2)

    # byte-identical (raw) and canonical (order-insensitive) both reported
    raw_identical = out1.read_bytes() == out2.read_bytes()
    h1, n1 = canon(out1)
    h2, n2 = canon(out2)
    peak_gib = max(p1, p2) / (1024 ** 2)  # ru_maxrss is KB on Linux, bytes on mac
    import platform
    if platform.system() == "Darwin":
        peak_gib = max(p1, p2) / (1024 ** 3)

    print(f"\nrows: {n1} / {n2}")
    print(f"raw byte-identical:       {raw_identical}")
    print(f"canonical digest match:   {h1 == h2}  ({h1[:16]})")
    print(f"peak child RSS delta:     ~{peak_gib:.2f} GiB (budget 8)")
    if h1 != h2:
        # show first divergent case
        r1 = {json.loads(l)["case_id"]: l for l in open(out1)}
        r2 = {json.loads(l)["case_id"]: l for l in open(out2)}
        for cid in sorted(r1):
            if r1[cid] != r2.get(cid):
                print(f"  DIVERGENCE at {cid}:\n   {r1[cid]}\n   {r2.get(cid)}")
                break
        raise SystemExit(2)
    print("\nDETERMINISM OK")


if __name__ == "__main__":
    main()
