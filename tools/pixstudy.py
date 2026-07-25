#!/usr/bin/env python3
"""Channel-precision study for the pixel decoder.

Runs pixmatch over the EVAL half of dev (templates were harvested from the
other half), decodes every field on every scan page, and records each read
against truth plus the pipeline's shipped value for the same case/field.
The output rows feed threshold selection: accept-gates are chosen where the
channel's precision is ~99% and net wins (pipeline-wrong or pipeline-missing,
pix-correct) stay positive.

  python tools/pixstudy.py --shard 0 --nshards 6 --out /tmp/pixstudy
"""
import argparse
import csv
import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import fitz  # noqa: E402

from mib import ctcscore, forensics, parse_ocr, pixmatch  # noqa: E402
from mib.pipeline import _NAMES  # noqa: E402

CTC_ENUMS = {"species_code", "home_world", "visa_class", "declared_purpose",
             "fee_status", "registry_status", "risk_flags"}


def ctc_check(field, strip, pix_value):
    """Second-channel verification of a pixmatch read on the same strip."""
    try:
        if field in CTC_ENUMS:
            cands = (pixmatch._FLAG_STRINGS if field == "risk_flags"
                     else pixmatch._ENUM_VALUES[field])
            scored = ctcscore.score(strip, cands)
            if not scored:
                return {}
            top = scored[0]
            margin = top[0] - scored[1][0] if len(scored) > 1 else 0.0
            return {"ctc_top": top[1], "ctc_lp": round(top[0], 3),
                    "ctc_margin": round(margin, 3),
                    "ctc_agree": top[1] == pix_value}
        greedy = ctcscore.greedy_decode(strip)
        return {"ctc_greedy": greedy,
                "ctc_agree": greedy.replace(" ", "") == str(pix_value).replace(" ", "")}
    except Exception as exc:  # never let the probe channel kill the study
        return {"ctc_err": repr(exc)[:80]}

from tools.challenge_paths import CHALLENGE  # noqa: E402
CH = CHALLENGE
FIELDS = list(pixmatch.FIELD_LABELS)


def eval_half(cid):
    return int(hashlib.md5((cid + "pix").encode()).hexdigest(), 16) % 2 == 1


def norm(field, v):
    v = str(v or "").strip().lower()
    if field == "risk_flags":
        return "|".join(sorted(p for p in v.split("|") if p and p != "none")) or "none"
    return v


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--states", default="/tmp/mib-eval-w6/states_dev.jsonl")
    ap.add_argument("--preds", default="/tmp/mib-eval-w6/predictions_dev.jsonl")
    ap.add_argument("--out", default="/tmp/pixstudy")
    ap.add_argument("--shard", type=int, default=0)
    ap.add_argument("--nshards", type=int, default=1)
    ap.add_argument("--half", choices=["eval", "harvest", "all"], default="eval",
                    help="harvest-half rows are template-optimistic (same-half "
                         "bank); gates must come from the eval half only")
    args = ap.parse_args()

    truth = {r["case_id"]: r for r in csv.DictReader(open(CH / "data/train_labels.csv"))}
    preds = {}
    for line in open(args.preds):
        p = json.loads(line)
        preds[p["case_id"]] = p

    Path(args.out).mkdir(parents=True, exist_ok=True)
    fout = open(Path(args.out) / f"rows_{args.shard}.jsonl", "w")

    n = 0
    for i, line in enumerate(open(args.states)):
        s = json.loads(line)
        cid = s["case_id"]
        if args.half != "all" and eval_half(cid) != (args.half == "eval"):
            continue
        if i % args.nshards != args.shard:
            continue
        trow = truth.get(cid)
        if trow is None:
            continue
        page_types = {}
        for rp in s.get("raw_pages", []):
            if rp["kind"] == "scan" and not rp.get("skipped"):
                page_types[rp["page"]] = parse_ocr.detect_page_type(
                    [(t, c) for t, c in rp["lines"]])
        doc = fitz.open(CH / "data/train" / f"{cid}.pdf")
        _, hidden = forensics.classify_spans(doc)
        images = [(p, pixmatch.deskew(im)[0])
                  for p, im in pixmatch.scan_images(doc, hidden)]
        doc.close()
        if not images:
            continue
        reads = pixmatch.decode(images, FIELDS, name_lexicon=_NAMES,
                                page_types=page_types)
        # pipeline context: value shipped + whether the field had a real read
        pools = s.get("pools", {})
        pred = preds.get(cid, {})
        img_by_page = dict(images)
        for field, r in reads.items():
            tv = trow.get(field, "") if field != "registry_status" else ""
            row = {
                "case_id": cid, "field": field, "pix": r["value"],
                "truth": tv, "ncc": r["ncc"], "margin": r["margin"],
                "label_ncc": r["label_ncc"], "label": r["label"],
                "page_type": page_types.get(r["page"], "?"),
                "pix_ok": (norm(field, r["value"]) == norm(field, tv)) if tv else None,
                "pipe": pred.get(field, ""),
                "pipe_ok": (norm(field, pred.get(field)) == norm(field, tv)) if tv else None,
                "pipe_had_read": field in pools,
            }
            if "strip_box" in r:
                y0, y1, x0, x1 = r["strip_box"]
                strip = img_by_page[r["page"]][y0:y1, x0:x1]
                if strip.size:
                    row.update(ctc_check(field, strip, r["value"]))
            fout.write(json.dumps(row) + "\n")
        n += 1
        if n % 25 == 0:
            print(f"shard {args.shard}: {n} cases", flush=True)
    fout.close()
    print(f"shard {args.shard} done: {n} cases")


if __name__ == "__main__":
    main()
