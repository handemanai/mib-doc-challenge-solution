#!/usr/bin/env python3
"""Pair-level test: constrained CTC scoring vs rapidfuzz snapping on REAL
garbled OCR lines.

For scan-page lines whose OCR text starts with a known label but whose value
segment disagrees with truth (a real misread), score the legal candidates
directly against the rec model's posteriorgram of the VALUE crop and compare
top-1 accuracy with the shipped rapidfuzz snap of the text segment. If CTC
cannot beat snapping here, the whole misread channel is posterior-limited and
neither a corrector nor a retrained recognizer of the same family will move it.

  python tools/ctcstudy.py --shard 0 --nshards 6 --out /tmp/ctcstudy
"""
import argparse
import csv
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import fitz  # noqa: E402
import numpy as np  # noqa: E402

from mib import ctcscore, forensics, ocr, pixmatch  # noqa: E402
from mib.vocab import FEES, PURPOSES, SPECIES, VISAS, WORLDS, snap  # noqa: E402

from tools.challenge_paths import CHALLENGE  # noqa: E402
CH = CHALLENGE
LABEL_FIELD = {
    "Species Code:": ("species_code", SPECIES),
    "Species Match:": ("species_code", SPECIES),
    "Home World:": ("home_world", WORLDS),
    "Visa Class:": ("visa_class", VISAS),
    "Declared Purpose:": ("declared_purpose", PURPOSES),
    "Fee Status:": ("fee_status", FEES),
}


def _norm(t):
    return re.sub(r"[\s.]+", "", t).lower()


def crop_box(img, box, pad=2):
    xs = [p[0] for p in box]
    ys = [p[1] for p in box]
    return img[max(0, int(min(ys)) - pad):int(max(ys)) + pad,
               max(0, int(min(xs)) - pad):int(max(xs)) + pad]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--states", default="/tmp/mib-eval-w6/states_dev.jsonl")
    ap.add_argument("--out", default="/tmp/ctcstudy")
    ap.add_argument("--shard", type=int, default=0)
    ap.add_argument("--nshards", type=int, default=1)
    args = ap.parse_args()

    truth = {r["case_id"]: r for r in csv.DictReader(open(CH / "data/train_labels.csv"))}
    Path(args.out).mkdir(parents=True, exist_ok=True)
    fout = open(Path(args.out) / f"rows_{args.shard}.jsonl", "w")

    n = 0
    for i, line in enumerate(open(args.states)):
        if i % args.nshards != args.shard:
            continue
        s = json.loads(line)
        cid = s["case_id"]
        trow = truth.get(cid)
        if trow is None:
            continue
        doc = fitz.open(CH / "data/train" / f"{cid}.pdf")
        _, hidden = forensics.classify_spans(doc)
        for pno, img in pixmatch.scan_images(doc, hidden):
            img, _ = pixmatch.deskew(img)
            result, _ = ocr._engine()(img, use_cls=False)
            for box, text, conf in (result or []):
                text = text.strip()
                for label, (field, vocab) in LABEL_FIELD.items():
                    if not _norm(text).startswith(_norm(label)):
                        continue
                    tv = trow.get(field, "")
                    if not tv:
                        continue
                    seg = text[len(label):].strip(" .:|") if len(text) > len(label) else ""
                    if _norm(text) == _norm(label + tv):
                        kind = "clean"
                    else:
                        kind = "garbled"
                    # value crop: proportional split of the line box
                    lw = fitz.get_text_length(label + " ", fontname="helv", fontsize=10)
                    vw = fitz.get_text_length(tv, fontname="helv", fontsize=10)
                    frac = lw / (lw + vw)
                    crop = crop_box(img, box)
                    vcrop = crop[:, max(0, int(crop.shape[1] * frac) - 3):]
                    if vcrop.size == 0 or vcrop.shape[0] < 8:
                        continue
                    scored = ctcscore.score(vcrop, vocab)
                    ctc_top = scored[0][1] if scored else None
                    ctc_margin = (scored[0][0] - scored[1][0]
                                  if len(scored) > 1 else 0.0)
                    snap_v, _, _ = snap(seg, vocab, min_score=72)
                    fout.write(json.dumps({
                        "case_id": cid, "field": field, "kind": kind,
                        "truth": tv, "ocr_seg": seg[:40],
                        "snap": snap_v, "snap_ok": snap_v == tv,
                        "ctc": ctc_top, "ctc_ok": ctc_top == tv,
                        "ctc_margin": round(ctc_margin, 3),
                    }) + "\n")
                    break
        doc.close()
        n += 1
    fout.close()
    print(f"shard {args.shard}: {n} cases")


if __name__ == "__main__":
    main()
