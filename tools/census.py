#!/usr/bin/env python3
"""Error census: join the evaluator's per-case scores with our decision details
and the truth labels to see WHERE the residual points are — and, critically,
whether each miss is READABLE (evidence was there and we misread it) or
STRUCTURAL (evidence absent from the packet, so no read could recover it).

Only readable channels are worth chasing; structural misses are the honest
NEEDS_REVIEW / unrecoverable-field population that the private scorer excludes
from the denominator. This is the triage that keeps Wave 3 from burning effort
on unwinnable fields.

    python tools/census.py --dir /tmp/mib-eval-059c6b4 --split dev
"""
import argparse
import csv
import json
from collections import Counter, defaultdict
from pathlib import Path

FIELDS = ["applicant_name", "species_code", "home_world", "visa_class",
          "sponsor_id", "arrival_date", "declared_purpose", "risk_flags", "fee_status"]


def load(path):
    return [json.loads(l) for l in open(path)]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", default="/tmp/mib-eval-059c6b4")
    ap.add_argument("--split", default="dev")
    args = ap.parse_args()
    d = Path(args.dir)

    scores = {s["case_id"]: s for s in load(d / f"case_scores_{args.split}.jsonl")}
    details = {x["case_id"]: x for x in load(d / f"details_{args.split}.jsonl")}
    truth = {r["case_id"]: r for r in csv.DictReader(open(d / f"truth_{args.split}.csv"))}
    preds = {p["case_id"]: p for p in load(d / f"predictions_{args.split}.jsonl")}

    print(f"== census: {len(scores)} cases ({args.split}) ==\n")

    # ---- classification errors ------------------------------------------
    clf = Counter(s["classification_reason"] for s in scores.values())
    print("classification reasons:")
    for k, v in sorted(clf.items(), key=lambda kv: -kv[1]):
        print(f"  {k:28} {v}")

    trans = Counter()
    trans_examples = defaultdict(list)
    for cid, s in scores.items():
        if s["classification_reason"] == "correct":
            continue
        key = f"{truth[cid]['adjudication']}->{preds[cid]['adjudication']}"
        trans[key] += 1
        if len(trans_examples[key]) < 3:
            trans_examples[key].append((cid, details.get(cid, {}).get("reasons")))
    print("\n  error transitions (truth->pred):")
    for k, v in sorted(trans.items(), key=lambda kv: -kv[1]):
        print(f"    {k:26} {v}   e.g. {trans_examples[k]}")

    # ---- extraction misses, readable vs structural ----------------------
    print("\nextraction field misses (points < max):")
    print(f"  {'field':16} {'misses':>7} {'fallback':>9} {'misread':>8} "
          f"{'lostpts':>8}")
    for f in FIELDS:
        miss = fallback = misread = lost = 0
        for cid, s in scores.items():
            fr = s["field_results"].get(f)
            if not fr or fr["status"] == "matched":
                continue
            if fr["max_points"] == 0:  # unrecoverable — excluded from denom
                continue
            miss += 1
            lost += fr["max_points"] - fr["points"]
            extracted = set(details.get(cid, {}).get("extracted_fields", []))
            if f in extracted:
                misread += 1     # we read something and it was wrong -> readable
            else:
                fallback += 1    # never read -> likely structural absence
        print(f"  {f:16} {miss:7} {fallback:9} {misread:8} {lost:8}")

    # ---- readable misread detail (the actually-chaseable channel) -------
    print("\nreadable misreads (extracted-but-wrong) by field, with sources:")
    for f in FIELDS:
        rows = []
        for cid, s in scores.items():
            fr = s["field_results"].get(f)
            det = details.get(cid, {})
            if not fr or fr["status"] == "matched" or fr["max_points"] == 0:
                continue
            if f in set(det.get("extracted_fields", [])):
                rows.append((cid, truth[cid][f], det.get("sources", {}).get(f)))
        if rows:
            src = Counter(r[2] for r in rows)
            print(f"  {f:16} {len(rows):3}  sources={dict(src)}  e.g. "
                  f"{[(c, t) for c, t, _ in rows[:3]]}")


if __name__ == "__main__":
    main()
