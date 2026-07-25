#!/usr/bin/env python3
"""Harvest an empirical pixel-template bank for the closed-vocab decoder.

Synthetic base-14 renders leave ~0.3 NCC of fidelity on the table (the
generator's exact rasterizer + bilinear upscale + JPEG response). The scan
pages themselves are the exact channel, so the bank stores REAL line crops:
run the OCR engine (det gives boxes) over deskewed scan pages of the harvest
half of dev; wherever the recognized text equals "<label> <truth value>", that
line is verified clean twice over (OCR read + truth match) and its pixels are
banked under (label, value). Decode-time matching is then real-vs-real.

Output models/pix_bank.npz:
  v|{label}|{value}|{i}   value-part crop instance i (uint8)
  l|{label}|{i}           label-part crop instance i
  d|{ch}|{i}              digit atlas instance (from sponsor/date lines)
"""
import argparse
import csv
import hashlib
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import fitz  # noqa: E402

from mib import forensics, ocr, pixmatch  # noqa: E402

from tools.challenge_paths import CHALLENGE  # noqa: E402
CH = CHALLENGE
LABELS = ["Case ID:", "Applicant:", "Species Code:", "Species Match:",
          "Home World:", "Visa Class:", "Sponsor ID:", "Arrival Date:",
          "Declared Purpose:", "Observed flags:", "Fee Status:",
          "Registry Status:", "Registry Name:", "Waiver Code:"]
LABEL_FIELD = {
    "Case ID:": "case_id", "Applicant:": "applicant_name",
    "Registry Name:": "applicant_name",
    "Species Code:": "species_code", "Species Match:": "species_code",
    "Home World:": "home_world", "Visa Class:": "visa_class",
    "Sponsor ID:": "sponsor_id", "Arrival Date:": "arrival_date",
    "Declared Purpose:": "declared_purpose", "Observed flags:": "risk_flags",
    "Fee Status:": "fee_status", "Registry Status:": "registry_status",
}
MAX_INSTANCES = 8


def _norm(t):
    return re.sub(r"[\s.]+", "", t).lower()


def crop_box(img, box, pad=2):
    xs = [p[0] for p in box]
    ys = [p[1] for p in box]
    x0, x1 = int(min(xs)) - pad, int(max(xs)) + pad
    y0, y1 = int(min(ys)) - pad, int(max(ys)) + pad
    return img[max(0, y0):y1, max(0, x0):x1]


def split_ratio(label, value):
    """x fraction of the label part within the full printed line (font-metric
    ratio is size-invariant; 3px of pad on the cut protects a wrong weight
    guess)."""
    lw = fitz.get_text_length(label + " ", fontname="helv", fontsize=10)
    vw = fitz.get_text_length(value, fontname="helv", fontsize=10)
    return lw / (lw + vw)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--states", default="/tmp/mib-eval-w6/states_dev.jsonl")
    ap.add_argument("--out", default=str(Path(__file__).resolve().parents[1]
                                         / "models" / "pix_bank.npz"))
    ap.add_argument("--half", choices=["harvest", "eval", "all"], default="harvest")
    args = ap.parse_args()

    truth = {r["case_id"]: r for r in csv.DictReader(open(CH / "data/train_labels.csv"))}

    bank = defaultdict(list)
    digs = defaultdict(list)
    n_pages = n_lines = 0

    for line in open(args.states):
        s = json.loads(line)
        cid = s["case_id"]
        if args.half != "all":
            even = int(hashlib.md5((cid + "pix").encode()).hexdigest(), 16) % 2 == 0
            if (args.half == "harvest") != even:
                continue
        trow = truth.get(cid)
        if trow is None:
            continue
        doc = fitz.open(CH / "data/train" / f"{cid}.pdf")
        _, hidden = forensics.classify_spans(doc)
        for pno, img in pixmatch.scan_images(doc, hidden):
            img, _ = pixmatch.deskew(img)
            n_pages += 1
            result, _ = ocr._engine()(img, use_cls=False)
            for box, text, conf in (result or []):
                text = text.strip()
                for label in LABELS:
                    if not _norm(text).startswith(_norm(label)):
                        continue
                    field = LABEL_FIELD.get(label)
                    if field is None:
                        continue
                    tv = cid if field == "case_id" else trow.get(field, "")
                    if not tv:
                        continue
                    if _norm(text) != _norm(label + tv):
                        continue
                    crop = crop_box(img, box)
                    if crop.size == 0 or crop.shape[0] < 10:
                        continue
                    n_lines += 1
                    r = split_ratio(label, tv)
                    xcut = int(crop.shape[1] * r)
                    lab_part = crop[:, :xcut + 3]
                    val_part = crop[:, max(0, xcut - 3):]
                    if len(bank[f"l|{label}"]) < MAX_INSTANCES:
                        bank[f"l|{label}"].append(lab_part)
                    if len(bank[f"v|{label}|{tv}"]) < MAX_INSTANCES:
                        bank[f"v|{label}|{tv}"].append(val_part)
                    if field in ("sponsor_id", "arrival_date"):
                        # cell offsets must follow the font's per-char advances
                        # (digits 0.556em, hyphen 0.333em, caps ~0.7em) — cutting
                        # at uniform fractions smears neighbors into every cell.
                        vw = crop.shape[1] - xcut
                        total = fitz.get_text_length(tv, fontname="helv", fontsize=10)
                        for i, ch in enumerate(tv):
                            if not (ch.isdigit() or ch == "-"):
                                continue
                            f0 = fitz.get_text_length(tv[:i], fontname="helv",
                                                      fontsize=10) / total
                            f1 = fitz.get_text_length(tv[:i + 1], fontname="helv",
                                                      fontsize=10) / total
                            c0 = xcut + int(vw * f0)
                            c1 = xcut + int(vw * f1)
                            cell = crop[:, max(0, c0 - 1):c1 + 1]
                            key = f"d|{ch}"
                            if cell.size and len(digs[key]) < 24:
                                digs[key].append(cell)
                    break
        doc.close()

    out = {}
    for d in (bank, digs):
        for k, crops in d.items():
            for i, c in enumerate(crops):
                out[f"{k}|{i}"] = c
    np.savez_compressed(args.out, **out)
    kb = Path(args.out).stat().st_size / 1024
    keys = defaultdict(int)
    for k in out:
        keys[k.rsplit("|", 1)[0]] += 1
    print(f"{n_pages} scan pages OCR'd, {n_lines} verified lines, "
          f"{len(keys)} bank keys, {len(out)} crops, {kb:.0f} KB -> {args.out}")
    cov = defaultdict(list)
    for k in keys:
        p = k.split("|")
        if p[0] == "v":
            cov[p[1]].append(p[2])
    for lab in sorted(cov):
        print(f"  {lab} {len(cov[lab])} values: {sorted(cov[lab])[:6]}"
              f"{' ...' if len(cov[lab]) > 6 else ''}")


if __name__ == "__main__":
    main()
