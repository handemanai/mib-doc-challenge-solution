#!/usr/bin/env python3
"""Benchmark correction strategies on REAL mined confusion pairs.

Correctors are judged on the garbled subset (did we recover the truth?) and
on the clean subset (did we break a correct read = overcorrection?). Pairs are
split train/test by case hash so any learned corrector never sees its test
cases' garble.

Strategies:
  identity      emit the read as-is (what no-snapping would do)
  snap          the shipped rapidfuzz strategy (independent per-token for
                names, vocab snap for closed fields)
  joint         names only: decode over the full 144x144 joint-name grammar
                (both tokens scored together — one badly-garbled token can be
                carried by a clean one)
"""
import argparse
import hashlib
import json
import sys
from collections import defaultdict
from pathlib import Path

from rapidfuzz import fuzz, process

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from mib.parse_ocr import _norm, _snap_value  # noqa: E402
from mib.pipeline import _snap_name  # noqa: E402

_MODELS = Path(__file__).resolve().parents[2] / "models"
_NAMES = json.loads((_MODELS / "name_vocab.json").read_text())
JOINT = [f"{a} {b}" for a in _NAMES["first"] for b in _NAMES["last"]]


def corr_identity(field, src):
    return src.strip()


def corr_snap(field, src):
    if field == "applicant_name":
        v, _ = _snap_value(field, src)
        return _snap_name(v) if v else src.strip()
    v, _ = _snap_value(field, src)
    return v if v is not None else src.strip()


def corr_joint(field, src):
    if field != "applicant_name":
        return corr_snap(field, src)
    v, _ = _snap_value(field, src)     # label-strip + tokenization
    query = v if v else src.strip()
    best = process.extractOne(query, JOINT, scorer=fuzz.ratio, score_cutoff=55)
    return best[0] if best else corr_snap(field, src)


def is_test(case_id):
    return int(hashlib.md5(case_id.encode()).hexdigest(), 16) % 5 == 1


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pairs", default="/tmp/mib-pairs/real_pairs.jsonl")
    ap.add_argument("--fields", default="applicant_name,species_code,home_world,visa_class,declared_purpose")
    ap.add_argument("--split", choices=["test", "all"], default="test")
    args = ap.parse_args()
    fields = set(args.fields.split(","))

    pairs = [json.loads(l) for l in open(args.pairs)]
    pairs = [p for p in pairs if p["field"] in fields
             and (args.split == "all" or is_test(p["case"]))]

    strategies = {"identity": corr_identity, "snap": corr_snap, "joint": corr_joint}
    print(f"{len(pairs)} pairs ({args.split} split)")
    print(f"{'field':18} {'strategy':9} {'garbled':>8} {'fixed':>6} {'acc':>6}   "
          f"{'clean':>6} {'broken':>7}")
    for field in sorted(fields):
        fp = [p for p in pairs if p["field"] == field]
        garbled = [p for p in fp if _norm(p["src"]) != _norm(p["tgt"])]
        clean = [p for p in fp if _norm(p["src"]) == _norm(p["tgt"])]
        if not garbled:
            continue
        for name, fn in strategies.items():
            fixed = sum(_norm(fn(field, p["src"])) == _norm(p["tgt"]) for p in garbled)
            broken = sum(_norm(fn(field, p["src"])) != _norm(p["tgt"]) for p in clean)
            print(f"{field:18} {name:9} {len(garbled):8} {fixed:6} "
                  f"{fixed/len(garbled):6.2%}   {len(clean):6} {broken:7}")


if __name__ == "__main__":
    main()
