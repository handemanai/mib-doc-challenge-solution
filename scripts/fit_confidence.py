#!/usr/bin/env python3
"""Fit per-decision-path confidence from dev-split results.

Reads details_dev.jsonl + case_scores_dev.jsonl produced by eval_split.py and
writes models/path_confidence.json mapping path -> empirical P(correct),
shrunk toward the global rate for low-count paths and clipped to [0.02, 0.98].
"""
import json
import sys
from collections import defaultdict
from pathlib import Path

SHRINK = 10  # pseudo-count toward the global accuracy


def main(out_dir="/tmp/mib-eval"):
    details = {json.loads(l)["case_id"]: json.loads(l)
               for l in open(Path(out_dir) / "details_dev.jsonl")}
    correct = {}
    for line in open(Path(out_dir) / "case_scores_dev.jsonl"):
        row = json.loads(line)
        correct[row["case_id"]] = row["truth_adjudication"] == row["pred_adjudication"]

    by_path = defaultdict(lambda: [0, 0])
    for cid, det in details.items():
        if cid not in correct:
            continue
        by_path[det["path"]][0] += int(correct[cid])
        by_path[det["path"]][1] += 1

    total_right = sum(v[0] for v in by_path.values())
    total_n = sum(v[1] for v in by_path.values())
    global_acc = total_right / max(total_n, 1)

    conf = {}
    for path, (right, n) in sorted(by_path.items()):
        p = (right + SHRINK * global_acc) / (n + SHRINK)
        conf[path] = round(min(0.98, max(0.02, p)), 4)
        print(f"{path:45s} n={n:4d} acc={right / n:.3f} -> conf={conf[path]}")

    out = Path(__file__).resolve().parents[1] / "models" / "path_confidence.json"
    out.write_text(json.dumps(conf, indent=2))
    print(f"\nglobal acc {global_acc:.3f}; wrote {out}")


if __name__ == "__main__":
    main(*sys.argv[1:])
