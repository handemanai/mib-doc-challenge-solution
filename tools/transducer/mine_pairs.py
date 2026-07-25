#!/usr/bin/env python3
"""Mine REAL (garbled, clean) confusion pairs from a raw OCR dump.

This is the data channel the X-post recipe lacks: ground truth is known for
every dev packet and we own the OCR engine, so the pairs below are the TRUE
confusion distribution the shipped engine produces — no sim-to-real gap.
Holdout packets are never mined (sealed).

For each dev case and field, locate the true value's garbled occurrences in
the dumped OCR lines two ways:
  - label-anchored: the post-separator segment of a line whose head matches
    the field's label (any tier: exact, fuzzy, truncated)
  - bare: a line fuzzily similar to the value itself (partial alignment)
Clean occurrences are kept too — copy examples teach the model NOT to
overcorrect (the edit-weighted loss needs both).

    python tools/transducer/mine_pairs.py --states /tmp/mib-eval-f2/states_dev.jsonl \
        --labels .../train_labels.csv --out /tmp/mib-pairs/real_pairs.jsonl
"""
import argparse
import csv
import json
import re
import sys
from collections import Counter
from pathlib import Path

from rapidfuzz import fuzz

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from mib.parse_ocr import LABELS, _norm  # noqa: E402
from tools.challenge_paths import CHALLENGE  # noqa: E402

FIELDS = ["applicant_name", "species_code", "home_world", "visa_class",
          "sponsor_id", "arrival_date", "declared_purpose", "risk_flags", "fee_status"]


def label_field(text):
    """Field named by this line's label head, or None."""
    m = re.match(r"([^:]{3,26})[:.](.+)$", text)
    if not m:
        return None, None
    pre = _norm(m.group(1))
    if len(pre) < 4:
        return None, None
    best, best_sc = None, 0.0
    for prefix, field in LABELS.items():
        sc = max(fuzz.partial_ratio(prefix, pre), fuzz.ratio(prefix, pre))
        if sc > best_sc:
            best, best_sc = field, sc
    return (best, m.group(2).strip()) if best_sc >= 78 else (None, None)


def mine_case(state, truth):
    pairs = []
    for rp in state.get("raw_pages", []):
        if rp.get("skipped"):
            continue
        for text, conf in rp.get("lines", []):
            field, val = label_field(text)
            if field and field in truth and truth[field]:
                pairs.append({"field": field, "src": val, "tgt": truth[field],
                              "how": "label", "conf": conf,
                              "kind": rp["kind"], "case": state["case_id"]})
                continue
            # bare: line similar to a truth value
            for f in FIELDS:
                t = truth.get(f) or ""
                if len(t) < 4 or t == "none":
                    continue
                if fuzz.ratio(_norm(t), _norm(text)) >= 55:
                    pairs.append({"field": f, "src": text.strip(), "tgt": t,
                                  "how": "bare", "conf": conf,
                                  "kind": rp["kind"], "case": state["case_id"]})
                    break
    return pairs


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--states", default="/tmp/mib-eval-f2/states_dev.jsonl")
    ap.add_argument("--labels",
                    default=str(CHALLENGE / "data" / "train_labels.csv"))
    ap.add_argument("--out", default="/tmp/mib-pairs/real_pairs.jsonl")
    args = ap.parse_args()

    labels = {r["case_id"]: r for r in csv.DictReader(open(args.labels))}
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)

    n_pairs, per_field, exact = 0, Counter(), Counter()
    with open(out, "w") as f:
        for line in open(args.states):
            s = json.loads(line)
            truth = labels.get(s["case_id"])
            if truth is None:
                continue
            for p in mine_case(s, truth):
                f.write(json.dumps(p) + "\n")
                n_pairs += 1
                per_field[p["field"]] += 1
                if _norm(p["src"]) == _norm(p["tgt"]):
                    exact[p["field"]] += 1
    print(f"{n_pairs} pairs -> {out}")
    for fld, n in per_field.most_common():
        print(f"  {fld:18} {n:5}  clean {exact[fld]:5}  garbled {n - exact[fld]:5}")


if __name__ == "__main__":
    main()
