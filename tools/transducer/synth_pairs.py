#!/usr/bin/env python3
"""Generate (garbled, clean) pairs by degrading RENDERS of known field values
and running the ACTUAL RapidOCR engine over them.

This is the edge the standard autocorrect recipe lacks: ground truth is known
and we own the OCR engine, so the confusion channel is the true one the
runtime will face — no simulator gap. Values are laid out 20 rows per page,
rendered at the pipeline's DPI, damaged, OCR'd, and re-aligned to their rows
by y-coordinate.

    venv311 python tools/transducer/synth_pairs.py --n-names 4000 --out /tmp/mib-pairs/synth.jsonl
"""
import argparse
import json
import random
import sys
from pathlib import Path

import fitz
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from mib import ocr  # noqa: E402
from mib.vocab import PURPOSES, SPECIES, VISAS, WORLDS  # noqa: E402

_MODELS = Path(__file__).resolve().parents[2] / "models"
NAMES = json.loads((_MODELS / "name_vocab.json").read_text())

ROWS, ROW_H, FONTSIZE, DPI = 20, 36, 11, 150


def damage_bank(rng):
    """Severity-parameterized damage transforms mirroring the corpus census
    (wash, blur, pepper, resample) plus small skews. Teacher-diversified: the
    severity ranges deliberately exceed the observed census to cover a private
    set generated with a harsher damage profile."""
    def wash(img, s):
        paper = 247.0
        return np.clip(paper - (paper - img.astype(np.float32)) * (1.0 - s), 0, 255).astype(np.uint8)

    def blur(img, s):
        import cv2
        k = 3 if s < 0.5 else 5
        return cv2.GaussianBlur(img, (k, k), s * 2.0)

    def pepper(img, s):
        out = img.copy()
        mask = rng.random(out.shape)
        out[mask < 0.01 + 0.03 * s] = 0
        out[mask > 1 - (0.01 + 0.03 * s)] = 255
        return out

    def resample(img, s):
        import cv2
        f = 1.0 - 0.55 * s
        small = cv2.resize(img, None, fx=f, fy=f, interpolation=cv2.INTER_AREA)
        return cv2.resize(small, img.shape[::-1], interpolation=cv2.INTER_LINEAR)

    def skew(img, s):
        import cv2
        h, w = img.shape
        ang = (rng.random() * 2 - 1) * 3.0 * s
        M = cv2.getRotationMatrix2D((w / 2, h / 2), ang, 1.0)
        return cv2.warpAffine(img, M, (w, h), borderValue=250)

    return [wash, blur, pepper, resample, skew]


def render_page(values):
    doc = fitz.open()
    page = doc.new_page(width=612, height=ROWS * ROW_H + 60)
    for i, v in enumerate(values):
        page.insert_text((54, 40 + i * ROW_H), v, fontsize=FONTSIZE)
    pix = page.get_pixmap(dpi=DPI, colorspace=fitz.csGRAY)
    img = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width).copy()
    doc.close()
    return img


def ocr_rows(img, values):
    """OCR a damaged page and re-align detected lines to rows by y-center."""
    engine = ocr._engine()
    result, _ = engine(img, use_cls=False)
    scale = DPI / 72.0
    out = {}
    for box, text, conf in (result or []):
        yc = sum(p[1] for p in box) / len(box)
        row = int(round((yc / scale - 40 + FONTSIZE * 0.35) / ROW_H))
        if 0 <= row < len(values) and text.strip():
            prev = out.get(row)
            if prev is None or float(conf) > prev[1]:
                out[row] = (text.strip(), float(conf))
    return {row: t for row, (t, _) in out.items()}


def value_stream(n_names, rng):
    vals = []
    for _ in range(n_names):
        vals.append(f"{rng.choice(NAMES['first'])} {rng.choice(NAMES['last'])}")
    closed = list(SPECIES) + list(WORLDS) + list(VISAS) + list(PURPOSES)
    vals += closed * max(1, n_names // (6 * len(closed)))
    for _ in range(n_names // 4):
        vals.append(f"SPN-{rng.randrange(10000):04d}")
    for _ in range(n_names // 4):
        vals.append(f"20{rng.randrange(25, 28)}-{rng.randrange(1, 13):02d}-{rng.randrange(1, 29):02d}")
    rng.shuffle(vals)
    return vals


def field_of(v):
    if " " in v and v[0].isupper() and v.split()[0] in set(NAMES["first"]):
        return "applicant_name"
    if v in SPECIES:
        return "species_code"
    if v in WORLDS:
        return "home_world"
    if v in VISAS:
        return "visa_class"
    if v in PURPOSES:
        return "declared_purpose"
    if v.startswith("SPN-"):
        return "sponsor_id"
    return "arrival_date"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n-names", type=int, default=4000)
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--out", default="/tmp/mib-pairs/synth.jsonl")
    args = ap.parse_args()

    rng = np.random.default_rng(args.seed)
    pyrng = random.Random(args.seed)
    vals = value_stream(args.n_names, pyrng)
    bank = damage_bank(rng)

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    n = 0
    with open(out, "w") as f:
        for start in range(0, len(vals), ROWS):
            chunk = vals[start:start + ROWS]
            base = render_page(chunk)
            # one clean pass + two damage combos per page
            variants = [base]
            for _ in range(2):
                img = base
                for fn in pyrng.sample(bank, k=pyrng.choice((1, 2))):
                    img = fn(img, pyrng.uniform(0.35, 0.95))
                variants.append(np.ascontiguousarray(img))
            for img in variants:
                got = ocr_rows(img, chunk)
                for row, text in got.items():
                    f.write(json.dumps({"field": field_of(chunk[row]), "src": text,
                                        "tgt": chunk[row], "how": "synth"}) + "\n")
                    n += 1
            if (start // ROWS) % 20 == 0:
                print(f"{start}/{len(vals)} values, {n} pairs", flush=True)
    print(f"{n} pairs -> {out}")


if __name__ == "__main__":
    main()
