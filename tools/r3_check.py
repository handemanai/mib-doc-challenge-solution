#!/usr/bin/env python3
"""Verify the R3 detector family is live and EV-positive.

For every hedge rule that converts a would-be decision to NEEDS_REVIEW, show:
how often it fires on dev, the truth distribution of the cases it catches, and
the measured EV delta versus NOT having the rule (per the scoring matrix:
correct 8, hedge 2, missed-review 1, wrong A/D 0, false approval -4).

Approval-side hedges (fired instead of APPROVED): truth A -6, truth NR +7,
truth D +6 (a prevented false approval: -4 -> 2).
Deny-side hedge deny_trigger_unverified (instead of DENIED): truth D -6,
truth A +2, truth NR +1.

    python tools/r3_check.py --dir /tmp/mib-eval-w1 --split dev
"""
import argparse
import csv
import json
from collections import Counter, defaultdict
from pathlib import Path

APPROVAL_SIDE = {
    "waived_without_visible_waiver", "hidden_only_field",
    "low_biometric_confidence", "missing_arrival_date", "sponsor_blank",
    "insufficient_evidence", "stale_gray_zone",
}
DENY_SIDE = {"deny_trigger_unverified"}
EV_APPROVAL = {"APPROVED": -6, "NEEDS_REVIEW": +7, "DENIED": +6}
EV_DENY = {"DENIED": -6, "APPROVED": +2, "NEEDS_REVIEW": +1}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", default="/tmp/mib-eval-w1")
    ap.add_argument("--split", default="dev")
    args = ap.parse_args()
    d = Path(args.dir)

    details = [json.loads(l) for l in open(d / f"details_{args.split}.jsonl")]
    truth = {r["case_id"]: r["adjudication"]
             for r in csv.DictReader(open(d / f"truth_{args.split}.csv"))}

    by_rule = defaultdict(Counter)
    for det in details:
        reasons = det.get("reasons") or []
        if not reasons:
            continue
        r0 = reasons[0].split(":")[0]
        if r0 in APPROVAL_SIDE | DENY_SIDE:
            by_rule[r0][truth[det["case_id"]]] += 1

    print(f"{'rule':32} {'fires':>6} {'A':>4} {'NR':>4} {'D':>4} {'EV':>6}  verdict")
    for rule, dist in sorted(by_rule.items(), key=lambda kv: -sum(kv[1].values())):
        ev_map = EV_DENY if rule in DENY_SIDE else EV_APPROVAL
        ev = sum(ev_map[t] * n for t, n in dist.items())
        fires = sum(dist.values())
        verdict = "EV+" if ev > 0 else ("~0" if ev == 0 else "EV-")
        print(f"{rule:32} {fires:6} {dist.get('APPROVED', 0):4} "
              f"{dist.get('NEEDS_REVIEW', 0):4} {dist.get('DENIED', 0):4} "
              f"{ev:+6}  {verdict}")
    missing = (APPROVAL_SIDE | DENY_SIDE) - set(by_rule)
    if missing:
        print(f"\nnever fired on {args.split}: {sorted(missing)}")


if __name__ == "__main__":
    main()
