#!/usr/bin/env python3
"""The corrector-vs-extractor measurement.

For every extraction miss, ask: is the TRUE value present in the packet's
VISIBLE raw text (text layer + masked-raster OCR output)? Splits each field's
fallback losses into:

  PARSER-LIMITED  value is in the raw text we already produced, the parser
                  missed it -> a better parser / task-specific extractor wins
  STRUCTURAL      value absent from every visible read -> only NEEDS_REVIEW
                  honesty wins; no model can recover it

and each misread into "better source existed" vs "read was the only read".
Hidden text is excluded by construction (raw dump comes from visible spans and
the trap-masked raster), so injected bait values cannot inflate the numbers.

    python tools/fallback_presence.py --dir /tmp/mib-eval-f1 --split dev
"""
import argparse
import csv
import json
import re
from collections import Counter, defaultdict
from pathlib import Path

from rapidfuzz import fuzz

FIELDS = ["applicant_name", "species_code", "home_world", "visa_class",
          "sponsor_id", "arrival_date", "declared_purpose", "risk_flags", "fee_status"]

# partial_ratio floor per field; short values need near-exact hits to avoid
# false presence (e.g. "XW-1" fuzzy-matching form boilerplate).
THRESH = {"applicant_name": 82, "species_code": 85, "home_world": 85,
          "visa_class": 90, "sponsor_id": 88, "arrival_date": 85,
          "declared_purpose": 85, "risk_flags": 85, "fee_status": 100}


def norm(s):
    return re.sub(r"[\s.]+", "", s).lower()


def case_corpus(state, eligible_only=True):
    parts = []
    for rp in state.get("raw_pages", []):
        if eligible_only and rp.get("skipped"):
            continue
        if rp.get("text_layer"):
            parts.append(rp["text_layer"])
        parts.extend(t for t, _ in rp.get("lines", []))
    return norm(" ".join(parts))


def present(field, truth_val, corpus):
    """(is_present, matched_needle) for the true value in normalized corpus."""
    if not truth_val or truth_val in ("none",):
        return None, None
    th = THRESH[field]
    if field == "applicant_name":
        toks = [norm(t) for t in truth_val.split()]
        if all(fuzz.partial_ratio(t, corpus) >= th for t in toks):
            return True, " ".join(toks)
        return False, None
    if field == "risk_flags":
        vals = [v for v in truth_val.split("|") if v and v != "none"]
        hits = [v for v in vals if fuzz.partial_ratio(norm(v), corpus) >= th]
        return (len(hits) == len(vals)), "|".join(hits) or None
    if field == "fee_status":
        # exact-substring only: "paid" lives inside "unpaid"/"prepaid"
        n = norm(truth_val)
        occurrences = corpus.count(n)
        if n == "paid":
            occurrences -= corpus.count("unpaid")
        return occurrences > 0, n if occurrences > 0 else None
    if field == "arrival_date":
        n1, n2 = norm(truth_val), re.sub(r"\D", "", truth_val)
        ok = fuzz.partial_ratio(n1, corpus) >= th or n2 in corpus
        return ok, n1 if ok else None
    n = norm(truth_val)
    ok = fuzz.partial_ratio(n, corpus) >= th
    return ok, n if ok else None


def context(field, truth_val, state, eligible_only=True):
    """~60 chars of raw text around the best fuzzy hit, for eyeballing."""
    from rapidfuzz.fuzz import partial_ratio_alignment
    needle = norm(truth_val.split("|")[0] if field == "risk_flags" else
                  truth_val.split()[0] if field == "applicant_name" else truth_val)
    best, ctx = 0, ""
    for rp in state.get("raw_pages", []):
        if eligible_only and rp.get("skipped"):
            continue
        for t, _ in rp.get("lines", []):
            sc = fuzz.partial_ratio(needle, norm(t))
            if sc > best:
                best, ctx = sc, f"p{rp['page']}/{rp['kind']}: {t[:70]}"
    return ctx


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", default="/tmp/mib-eval-f1")
    ap.add_argument("--split", default="dev")
    ap.add_argument("--examples", type=int, default=4)
    args = ap.parse_args()
    d = Path(args.dir)

    states = {s["case_id"]: s for s in
              (json.loads(l) for l in open(d / f"states_{args.split}.jsonl"))}
    scores = {s["case_id"]: s for s in
              (json.loads(l) for l in open(d / f"case_scores_{args.split}.jsonl"))}
    details = {x["case_id"]: x for x in
               (json.loads(l) for l in open(d / f"details_{args.split}.jsonl"))}
    truth = {r["case_id"]: r for r in csv.DictReader(open(d / f"truth_{args.split}.csv"))}

    print(f"== fallback presence census: {len(scores)} cases ({args.split}) ==")
    print("channel key: PARSER-LIMITED = true value in visible raw text we already")
    print("produced; STRUCTURAL = absent from every visible read.\n")

    hdr = (f"{'field':16} {'ch':9} {'miss':>5} {'present':>8} {'struct':>7} "
           f"{'p_all':>6} {'lostpts':>8}")
    print(hdr)
    examples = defaultdict(list)
    for f in FIELDS:
        for channel in ("fallback", "misread"):
            miss = pres = pres_all = lost = 0
            for cid, s in scores.items():
                fr = s["field_results"].get(f)
                if not fr or fr["status"] == "matched" or fr["max_points"] == 0:
                    continue
                extracted = f in set(details.get(cid, {}).get("extracted_fields", []))
                if (channel == "fallback") == extracted:
                    continue
                tv = truth[cid][f]
                ok, _ = present(f, tv, case_corpus(states[cid]))
                if ok is None:
                    continue
                miss += 1
                lost += fr["max_points"] - fr["points"]
                if ok:
                    pres += 1
                    if len(examples[(f, channel)]) < args.examples:
                        examples[(f, channel)].append(
                            (cid, tv, context(f, tv, states[cid])))
                else:
                    ok_all, _ = present(f, tv, case_corpus(states[cid], eligible_only=False))
                    if ok_all:
                        pres_all += 1
            if miss:
                print(f"{f:16} {channel:9} {miss:5} {pres:8} {miss-pres-pres_all:7} "
                      f"{pres_all:6} {lost:8}")

    print("\nexamples (parser-limited candidates), field/channel: case truth | best-hit context")
    for (f, ch), rows in examples.items():
        for cid, tv, ctx in rows:
            print(f"  {f}/{ch:9} {cid} {tv!r:28} | {ctx}")


if __name__ == "__main__":
    main()
