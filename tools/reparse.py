#!/usr/bin/env python3
"""Re-run the PARSE layer over dumped raw OCR lines, then decide + score.

extract_state = (forensics + OCR) + parsing. A MIB_DUMP_RAW states file
contains every page's raw OCR lines and visible text layer, so parser changes
(label tolerance, template regexes, value harvesting) can be measured over the
full dev split in seconds — no OCR pass. The OCR-conditional parts (which
pages got the HQ ladder, orientation retries) are frozen as dumped; final
numbers still come from a real extraction run before any milestone.

    python tools/reparse.py --states /tmp/mib-eval-f1/states_dev.jsonl \
        --truth /tmp/mib-eval-f1/truth_dev.csv --out-dir /tmp/mib-reparse --tag p1
"""
import argparse
import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import fitz  # noqa: E402

from mib import extract, forensics, parse_ocr  # noqa: E402
from mib.pipeline import (FALLBACKS, TEXT_SOURCE_RANK, batch_epoch,  # noqa: E402
                          batch_frequent_sponsors, _foreign_page,
                          _hidden_field_mentions, decide)

from tools.challenge_paths import CHALLENGE  # noqa: E402
def rebuild_state(s):
    """Reconstruct pools/doc_notes from raw pages with CURRENT parser code,
    mirroring extract_state's flow (text-layer extraction, per-page parsing
    with the dumped skip decisions, candidate pooling)."""
    case_id = s["case_id"]
    raw = s.get("raw_pages", [])
    page_texts = [rp.get("text_layer", "") for rp in raw if rp["kind"] != "scan_hq"]
    text_fields = extract.extract_from_visible_text(case_id, page_texts)

    per_page = []
    for rp in raw:
        lines = [(t, c) for t, c in rp["lines"]]
        # re-evaluate foreign-skips with CURRENT logic (dumped decisions bake
        # in the old guard); empty-skips stay skipped.
        if rp.get("skipped") == "empty":
            continue
        if _foreign_page(case_id, [t for t, _ in lines]):
            continue
        per_page.append(parse_ocr.parse_page(lines))
    ocr_candidates, doc_notes = parse_ocr.merge_candidates(per_page)

    pools = {}
    for field, (value, source) in text_fields.items():
        pools.setdefault(field, []).append([value, source, TEXT_SOURCE_RANK.get(source, 6), 95.0])
    for field, cands in ocr_candidates.items():
        pools.setdefault(field, []).extend([list(c) for c in cands])
    # the pixel-decoder stage runs in extract_state, not the parser — carry
    # its reads over from the dumped pools or the rebuild silently loses them
    for field, cands in s.get("pools", {}).items():
        for c in cands:
            if c[1] == "pixmatch":
                pools.setdefault(field, []).append(list(c))

    out = dict(s)
    out["pools"] = pools
    out["doc_notes"] = doc_notes
    out["page_types"] = [pt for pt, _, _ in per_page]
    out["hidden_field_mentions"] = _hidden_field_mentions(s.get("hidden_texts", []))
    if "struck_values" not in out:
        pdf = CHALLENGE / "data" / "train" / f"{case_id}.pdf"
        if pdf.exists():
            with fitz.open(pdf) as doc:
                visible, _ = forensics.classify_spans(doc)
                out["struck_values"] = sorted(
                    forensics.struck_values(doc, visible))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--states", required=True)
    ap.add_argument("--truth", required=True)
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--tag", default="reparse")
    ap.add_argument("--epoch", default=None,
                    help="pin the receipt epoch (YYYY-MM-DD) instead of batch inference")
    args = ap.parse_args()

    states = [rebuild_state(json.loads(l)) for l in open(args.states)]
    from datetime import date as _date
    epoch = _date.fromisoformat(args.epoch) if args.epoch else batch_epoch(states)
    print(f"epoch: {epoch}")
    batch_revoked = batch_frequent_sponsors(states)

    preds, details = [], []
    for s in states:
        try:
            pred, detail = decide(s, epoch, batch_revoked=batch_revoked)
        except Exception as exc:
            pred = {"case_id": s["case_id"], **FALLBACKS,
                    "adjudication": "NEEDS_REVIEW", "confidence": 0.3}
            detail = {"error": repr(exc)[:200]}
        preds.append(pred)
        details.append({"case_id": pred["case_id"], **detail})

    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    pred_path = out / f"predictions_{args.tag}.jsonl"
    with open(pred_path, "w") as f:
        for p in preds:
            f.write(json.dumps(p) + "\n")
    with open(out / f"details_{args.tag}.jsonl", "w") as f:
        for d in details:
            f.write(json.dumps(d) + "\n")

    ev_path = out / f"evaluation_{args.tag}.json"
    subprocess.run(
        [sys.executable, str(CHALLENGE / "scripts/evaluate.py"),
         "--truth", args.truth, "--submission", str(pred_path),
         "--output-json", str(ev_path),
         "--case-scores-jsonl", str(out / f"case_scores_{args.tag}.jsonl")],
        check=False, capture_output=True)
    ev = json.loads(ev_path.read_text())
    sc = ev["scores"]
    print(f"{args.tag}: total={sc['total_score']:.2f} clf={sc['classification_score']:.2f} "
          f"extr={sc['extraction_score']:.2f} calib={sc['calibration_score']:.2f} "
          f"FA={ev['raw']['catastrophic_false_approvals']}")


if __name__ == "__main__":
    main()
