#!/usr/bin/env python3
"""Perturbation harness — score-stability under shifted degradations.

EVALUATION.md grades "generalization to new layout variants." The public train
set has one degradation distribution; the private set may shift it. This harness
re-renders a deterministic dev subsample with degradations the training data
does NOT contain, then measures the score delta so we can find and fix brittle
spots before 8090's private set does.

Method (label-preserving): each PDF is rasterized to grayscale, a degradation is
applied, and the rasters are re-wrapped into an image-only PDF. Ground truth is
unchanged (same case_id -> same label). Because re-wrapping already strips the
text layer, we isolate each degradation against a `raster_control` variant
(rasterize + rewrap, no degradation) rather than the native baseline — the
control measures the cost of going OCR-only, the delta from control measures the
degradation itself.

Injection robustness is NOT tested here (rasterizing removes hidden spans); that
is the job of tools/redteam/ and tests/test_redteam.py.

    python tools/perturb.py --variant rot180 --n 120
    python tools/perturb.py --all --n 120         # full stability report

For large sweeps prefer one variant at a time (--variant NAME); PyMuPDF's native
renderer can crash under sustained back-to-back rendering of hundreds of pages.

Findings (n=100 dev subsample, 2026-07-20): rotation is the robustness cliff —
rot180 -26 / rot90 -30 vs the OCR-only control, because a rotated page yields
>=4 lines of high-confidence garbage that passes ocr_page's min_lines gate, so
the ladder's rotation branch never fires. heavy_wash -0.3 (robust). FA stayed 0
under every perturbation. Fix: gate the ladder on parse-success, not line count.
"""
import argparse
import csv
import gc
import hashlib
import json
import subprocess
import sys
from pathlib import Path

import fitz
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
from tools.challenge_paths import CHALLENGE  # noqa: E402
from mib import forensics  # noqa: E402
from mib.pipeline import FALLBACKS, batch_epoch, decide  # noqa: E402
from eval_split import extract_states  # noqa: E402  (plain-process shard extraction)

BASE_DPI = 200


def is_holdout(case_id):
    return int(hashlib.md5(case_id.encode()).hexdigest(), 16) % 5 == 0


def subsample(pdfs, n, seed=13):
    """Deterministic dev subsample, hashed by case id (no RNG state)."""
    dev = [p for p in pdfs if not is_holdout(p.stem)]
    dev.sort(key=lambda p: hashlib.md5(f"{seed}:{p.stem}".encode()).hexdigest())
    return sorted(dev[:n], key=lambda p: p.stem)


# ---- degradations: grayscale uint8 image -> grayscale uint8 image ------------

def d_identity(img):
    return img


def d_rot180(img):
    return np.rot90(img, 2)


def d_rot90(img):
    return np.rot90(img, 1)


def d_heavy_wash(img):
    """Compress ink toward paper: faint low-contrast scan (~5% contrast)."""
    paper = float(np.median(img))
    out = paper - (paper - img.astype(np.float32)) * 0.20
    return np.clip(out, 0, 255).astype(np.uint8)


def d_dpi_resample(img):
    """Downsample to ~55% then back up: detector-resolution / blur stress."""
    import cv2
    h, w = img.shape
    small = cv2.resize(img, (max(1, int(w * 0.55)), max(1, int(h * 0.55))),
                       interpolation=cv2.INTER_AREA)
    return cv2.resize(small, (w, h), interpolation=cv2.INTER_LINEAR)


def d_smudge_labels(img):
    """Paint dark blobs over the left label column — smudges relocated onto the
    field labels (training smudges sit over header/value regions, not labels)."""
    out = img.copy()
    h, w = out.shape
    rng = np.random.default_rng(0)
    for frac in (0.22, 0.34, 0.46, 0.58, 0.70):
        cy = int(h * frac)
        cx = int(w * (0.08 + 0.04 * rng.random()))
        ry, rx = rng.integers(10, 20), rng.integers(40, 90)
        yy, xx = np.ogrid[max(0, cy - ry):min(h, cy + ry),
                          max(0, cx - rx):min(w, cx + rx)]
        out[max(0, cy - ry):min(h, cy + ry), max(0, cx - rx):min(w, cx + rx)] = 30
    return out


def d_pepper(img):
    """Salt-and-pepper sensor noise at 3%."""
    out = img.copy()
    rng = np.random.default_rng(1)
    mask = rng.random(out.shape)
    out[mask < 0.015] = 0
    out[mask > 0.985] = 255
    return out


def d_skew6(img):
    """6° page skew — the validation wrench census found a fatter 4-8° skew
    tail than train (6-7° band 1.8% vs 0.6%); the OCR path does not deskew."""
    import cv2
    h, w = img.shape
    m = cv2.getRotationMatrix2D((w / 2, h / 2), 6.0, 1.0)
    return cv2.warpAffine(img, m, (w, h), flags=cv2.INTER_LINEAR,
                          borderMode=cv2.BORDER_CONSTANT,
                          borderValue=int(np.median(img)))


VARIANTS = {
    "raster_control": d_identity,
    "rot180": d_rot180,
    "rot90": d_rot90,
    "heavy_wash": d_heavy_wash,
    "dpi_resample": d_dpi_resample,
    "smudge_labels": d_smudge_labels,
    "pepper": d_pepper,
    "skew6": d_skew6,
}


def render_variant(pdf_path, fn, out_path):
    """Rasterize every page (hidden spans masked, as the pipeline would), apply
    fn, and re-wrap as an image-only PDF."""
    doc = fitz.open(pdf_path)
    _, hidden = forensics.classify_spans(doc)
    out = fitz.open()
    for page in doc:
        img = forensics.masked_page_gray(page, hidden, dpi=BASE_DPI)
        img = np.ascontiguousarray(fn(img), dtype=np.uint8)
        h, w = img.shape
        pix = fitz.Pixmap(fitz.csGRAY, w, h, img.tobytes(), False)
        newpage = out.new_page(width=w * 72.0 / BASE_DPI, height=h * 72.0 / BASE_DPI)
        newpage.insert_image(newpage.rect, pixmap=pix)
    out.save(out_path, deflate=True)
    out.close()
    doc.close()


def score(pdfs, labels_path, workdir, tag):
    """Extract (parallel shards) + decide over pdfs, write predictions +
    filtered truth, run the official evaluator, return the eval dict."""
    states = extract_states([Path(p) for p in pdfs], workers=6)
    epoch = batch_epoch(states)
    preds = []
    for s in states:
        try:
            pred, _ = decide(s, epoch)
        except Exception:
            pred = {"case_id": s["case_id"], **FALLBACKS,
                    "adjudication": "NEEDS_REVIEW", "confidence": 0.3}
        preds.append(pred)

    workdir = Path(workdir)
    workdir.mkdir(parents=True, exist_ok=True)
    pred_path = workdir / f"pred_{tag}.jsonl"
    pred_path.write_text("\n".join(json.dumps(p) for p in preds))
    keep = {p.stem for p in pdfs}
    with open(labels_path) as f:
        rows = [r for r in csv.DictReader(f) if r["case_id"] in keep]
    truth_path = workdir / f"truth_{tag}.csv"
    with open(truth_path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=rows[0].keys())
        w.writeheader()
        w.writerows(rows)
    ev_path = workdir / f"eval_{tag}.json"
    subprocess.run([sys.executable, str(CHALLENGE / "scripts/evaluate.py"),
                    "--truth", str(truth_path), "--submission", str(pred_path),
                    "--output-json", str(ev_path)], check=False,
                   stdout=subprocess.DEVNULL)
    ev = json.loads(ev_path.read_text())
    return ev


def total_of(ev):
    return round(ev["scores"]["total_score"], 2)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--variant", choices=list(VARIANTS))
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--n", type=int, default=120)
    ap.add_argument("--workdir", default="/tmp/mib-perturb")
    args = ap.parse_args()

    pdfs = subsample(sorted((CHALLENGE / "data/train").glob("*.pdf")), args.n)
    labels = CHALLENGE / "data/train_labels.csv"
    workdir = Path(args.workdir)
    render_dir = workdir / "pdfs"
    render_dir.mkdir(parents=True, exist_ok=True)

    variants = list(VARIANTS) if args.all else [args.variant]
    if variants == [None]:
        ap.error("pass --variant NAME or --all")

    # Native baseline (real dev score on this subsample, text layer intact).
    base = total_of(score(pdfs, labels, workdir, "native"))
    print(f"native_baseline           n={len(pdfs)}  total={base}")

    report = {"n": len(pdfs), "native_baseline": base, "variants": {}}
    control = None
    for v in variants:
        vdir = render_dir / v
        vdir.mkdir(exist_ok=True)
        vp = []
        for i, p in enumerate(pdfs):
            op = vdir / p.name
            if not op.exists():
                render_variant(str(p), VARIANTS[v], str(op))
                if i % 20 == 0:
                    gc.collect()  # PyMuPDF can crash under sustained render load
            vp.append(op)
        ev = score(vp, labels, workdir, v)
        tot = total_of(ev)
        fa = ev["raw"]["catastrophic_false_approvals"]
        if v == "raster_control":
            control = tot
        rel = "" if control is None else f"  vs_control={round(tot - control, 2):+}"
        print(f"{v:24}  total={tot:6}  FA={fa}  vs_native={round(tot - base, 2):+}{rel}")
        report["variants"][v] = {"total": tot, "fa": fa,
                                 "vs_native": round(tot - base, 2),
                                 "vs_control": None if control is None else round(tot - control, 2)}
    (workdir / "stability_report.json").write_text(json.dumps(report, indent=2))
    print(f"\nreport -> {workdir / 'stability_report.json'}")


if __name__ == "__main__":
    main()
