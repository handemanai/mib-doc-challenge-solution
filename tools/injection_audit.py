#!/usr/bin/env python3
"""Pre-submission injection self-audit over a finished run's states + predictions.

The unit/red-team suite proves the quarantine *mechanisms* work on packets we
authored. This audit proves the *actual submission* is uncontaminated: for every
submitted case it re-derives, from the recorded pipeline state, that every
answer has legitimate provenance and none was steered by the untrusted channels
the dataset documents (hidden text layers, planted answer keys, verdict plants,
washed watermark decoys — EVALUATION.md "Prompt-Injection Robustness").

Two dataset facts shape the checks (measured on train):
  * Planted answer keys carry TRUE field values, so "submitted value appears in
    hidden text" alone is meaningless — a correct read or even a mode-fallback
    guess collides with the key. The leak test is therefore *provenance*: a
    value is clean if it is traceable to trusted evidence (text layer / OCR
    lines, fuzzy-matched for garble), to a recorded candidate pool from any
    reader channel, to a recorded correction, or to the static FALLBACKS table.
    A hidden-present value with NO such provenance is a quarantine leak.
  * The answer key's adjudication token is adversarial exactly when it claims
    APPROVED (0/157 train packets whose key claims APPROVED are truly
    APPROVED). Bare verdict plants ("APPROVED" alone) can be true; key claims
    cannot.

Severities:

VIOLATIONS (exit 2 — do not submit until each is explained):
  hidden_only_leak   Submitted identity-field value present in hidden text with
                     no provenance in the recorded pipeline state.
  answer_key_match   >=3 such fields on one case: submission reproduces a
                     planted answer key.

WARNINGS (exit 1 — eyeball each listed case before submitting):
  oracle_approval    We output APPROVED and the packet's planted answer key
                     also claims APPROVED. By the 0/157 census such agreement
                     is a trap signature (FA risk), not corroboration.
  watermark_finding  The adjudication leaned on an adjudicator-note finding on
                     a packet that also carries watermark pages — the decoy
                     combination the watermark guard exists for.
  missing_state      A submitted case has no state row, so it could not be
                     audited. Re-dump states for these cases.
  slim_states        The states dump lacks raw_pages/hidden_texts (slim
                     schema) and no --pdfs was given: the leak checks CANNOT
                     run and a CLEAN verdict would be vacuous. Re-dump full
                     states or pass --pdfs.

With --pdfs <dir>, hidden/untrusted content is re-derived from the source PDFs
at audit time via the frozen forensics span classifier (mib.forensics), so the
audit does not depend on the run having recorded hidden_texts — and audits the
recorded classification itself. Required for slim-schema state dumps.

    python tools/injection_audit.py --states /tmp/out/states.jsonl \
        --predictions /tmp/out/predictions.jsonl \
        [--pdfs /data/pdfs] [--report /tmp/out/audit.json]
"""
import argparse
import difflib
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from mib.pipeline import FALLBACKS  # static mode-guesses are legitimate provenance

# Identity-bearing fields: a no-provenance match on one of these cannot be an
# inference coincidence. risk_flags/fee_status are excluded because the
# pipeline legitimately infers them (waiver codes, absence markers) without a
# literal trusted token.
IDENTITY_FIELDS = (
    "applicant_name", "species_code", "home_world", "visa_class",
    "sponsor_id", "arrival_date", "declared_purpose",
)

ANSWER_KEY_RE = re.compile(
    r"answer key only:\s*(MIB-\d+(?:,[^,\n]*){10})", re.IGNORECASE)


def _norm(s):
    return re.sub(r"\s+", " ", str(s)).strip().lower()


def trusted_corpus(state):
    """All strings read from trusted channels: text layers + OCR lines."""
    parts = []
    for pg in state.get("raw_pages") or []:
        if pg.get("text_layer"):
            parts.append(pg["text_layer"])
        for line_conf in pg.get("lines") or []:
            parts.append(line_conf[0])
    return parts


def recorded_candidates(state):
    """Every raw/normalized candidate string any reader channel recorded."""
    out = set()
    for pool in (state.get("pools") or {}).values():
        for cand in pool or []:
            for item in cand:
                if isinstance(item, str):
                    out.add(_norm(item))
    notes = state.get("doc_notes") or {}
    for value in (notes.get("corrections") or {}).values():
        out.add(_norm(value))
    if notes.get("name_correction"):
        out.add(_norm(notes["name_correction"]))
    for fired in state.get("pix_fired") or []:
        if isinstance(fired, dict):
            for item in fired.values():
                if isinstance(item, str):
                    out.add(_norm(item))
        elif isinstance(fired, str):
            out.add(_norm(fired))
    return out


def in_trusted(value, trusted_lines, trusted_blob):
    """Literal or fuzzy presence in trusted evidence (tolerates OCR garble:
    the submitted value is often a snap of a damaged read)."""
    v = _norm(value)
    if v in trusted_blob:
        return True
    n = len(v)
    for line in trusted_lines:
        ln = _norm(line)
        if not ln:
            continue
        for start in range(0, max(1, len(ln) - n + 1), max(1, n // 3)):
            window = ln[start:start + n]
            if difflib.SequenceMatcher(None, v, window).ratio() >= 0.8:
                return True
    return False


def matches_candidate(value, candidates):
    """Exact or fuzzy match against recorded reader candidates. Fuzzy is
    needed because grammar/vocab snap outputs legitimately differ from every
    raw candidate string (e.g. 'Oriix Orizarn' snapped from 'Oriix Orizamn')."""
    v = _norm(value)
    if v in candidates:
        return True
    return any(difflib.SequenceMatcher(None, v, c).ratio() >= 0.8
               for c in candidates if abs(len(c) - len(v)) <= max(3, len(v) // 3))


def pdf_channels(pdf_path):
    """Re-derive (trusted_lines, hidden_texts) from the source PDF using the
    frozen forensics span classifier — independent of the run's state record."""
    import fitz  # deferred: only needed in --pdfs mode
    from mib import forensics
    doc = fitz.open(pdf_path)
    visible, hidden = forensics.classify_spans(doc)
    doc.close()
    return ([s.text for s in visible if s.text.strip()],
            [s.text for s in hidden if s.text.strip()])


def visible_by_render(pdf_path, value):
    """Last-resort provenance check for a would-be leak flag: re-OCR the
    RENDERED pages (rotation-tolerant, like the native channel) and look for
    the value in visible ink. Rendered rasters are structurally
    injection-immune — white-on-white renders invisible, off-crop is outside
    the raster, under-image stays covered — so a hit here proves the value
    was printed on the page (e.g. a rotated scan the text-layer corpus can't
    see), not leaked from a hidden channel."""
    import fitz
    import numpy as np
    from mib.ocr import ocr_page
    v = _norm(value)
    if not v:
        return False
    doc = fitz.open(pdf_path)
    try:
        for page in doc:
            for hq, dpi in ((False, 150), (True, 250)):
                pix = page.get_pixmap(dpi=dpi, colorspace=fitz.csGRAY)
                img = np.frombuffer(pix.samples, dtype=np.uint8).reshape(
                    pix.height, pix.width)
                # try all four orientations explicitly: ocr_page's internal
                # rotation ladder only fires on weak pages, and a rotated
                # scan can pass the gate with garbage lines
                for k in range(4):
                    lines = [t for t, _ in ocr_page(np.rot90(img, k) if k else img, hq=hq)]
                    if in_trusted(value, lines, _norm(" ".join(lines))):
                        return True
    finally:
        doc.close()
    return False


def _pdf_worker(item):
    cid, path = item
    try:
        visible, hidden = pdf_channels(path)
        return cid, visible, hidden, None
    except Exception as exc:  # surfaced as missing_state-grade warning
        return cid, [], [], str(exc)


def derive_pdf_channels(items, processes=4):
    """Batch pdf_channels through short-lived worker processes. pymupdf
    accumulates C-extension refcount corruption over hundreds of sequential
    opens in one interpreter (fatal none_dealloc observed at ~440 docs);
    maxtasksperchild recycles workers well before that."""
    from multiprocessing import get_context
    ctx = get_context("spawn")
    with ctx.Pool(processes=processes, maxtasksperchild=50) as pool:
        return {cid: (vis, hid, err)
                for cid, vis, hid, err in pool.map(_pdf_worker, items, chunksize=8)}


def answer_key_claims_approved(hidden):
    for text in hidden:
        m = ANSWER_KEY_RE.search(text)
        if m:
            cells = [c.strip() for c in m.group(1).split(",")]
            if len(cells) >= 11 and cells[10].upper() == "APPROVED":
                return True
    return False


def ledger_candidates(ledger):
    """Values the per-case ledger attributes to raster-OCR channels
    (native_full_page_image / masked_pdf_render). Those channels are
    injection-immune by construction — white-on-white renders invisible,
    off-crop is outside the raster, under-image stays covered — so a ledger
    record tying a value to one of them is provenance."""
    out = set()
    for sel in ((ledger.get("two_ledger") or {}).get("field_selection") or []):
        for key in ("native", "base"):
            if isinstance(sel.get(key), str):
                out.add(_norm(sel[key]))
    for acc in ledger.get("pixmatch_acceptances") or []:
        if isinstance(acc, dict):
            for item in acc.values():
                if isinstance(item, str):
                    out.add(_norm(item))
    return out


def audit(states_path, predictions_path, pdf_dir=None, ledgers_path=None):
    states = {}
    for line in open(states_path):
        s = json.loads(line)
        states[s["case_id"]] = s
    ledgers = {}
    if ledgers_path:
        for line in open(ledgers_path):
            l = json.loads(line)
            ledgers[l["case_id"]] = l

    violations = defaultdict(list)
    warnings = defaultdict(list)
    n_cases = n_hidden = n_slim = 0

    preds = [json.loads(line) for line in open(predictions_path)]
    pdf_map = {}
    if pdf_dir:
        items = []
        for pred in preds:
            cid = pred["case_id"]
            state = states.get(cid)
            if state is not None and not state.get("raw_pages"):
                path = Path(pdf_dir) / f"{cid}.pdf"
                if path.exists():
                    items.append((cid, str(path)))
        if items:
            pdf_map = derive_pdf_channels(items)

    for pred in preds:
        cid = pred["case_id"]
        n_cases += 1
        state = states.get(cid)
        if state is None:
            warnings["missing_state"].append({"case_id": cid})
            continue

        hidden = [h for h in (state.get("hidden_texts") or []) if h]
        trusted_lines = trusted_corpus(state)
        slim = not state.get("raw_pages")
        if slim and cid in pdf_map:
            pdf_visible, pdf_hidden, pdf_err = pdf_map[cid]
            if pdf_err:
                warnings["missing_state"].append(
                    {"case_id": cid, "pdf_error": pdf_err})
            else:
                trusted_lines = trusted_lines + pdf_visible
                hidden = hidden + pdf_hidden
                slim = False
        if slim:
            n_slim += 1
        if hidden:
            n_hidden += 1
        hidden_blob = _norm(" ".join(hidden))
        trusted_blob = _norm(" ".join(trusted_lines))
        candidates = recorded_candidates(state)
        if cid in ledgers:
            candidates |= ledger_candidates(ledgers[cid])

        leaked = []
        for field in IDENTITY_FIELDS:
            value = pred.get(field)
            if value is None or not _norm(value):
                continue
            v = _norm(value)
            if v not in hidden_blob:
                continue
            if v == _norm(FALLBACKS.get(field, "")):
                continue
            if matches_candidate(value, candidates):
                continue
            if in_trusted(value, trusted_lines, trusted_blob):
                continue
            leaked.append(field)
        if leaked and pdf_dir:
            pdf_path = Path(pdf_dir) / f"{cid}.pdf"
            if pdf_path.exists():
                cleared = [f for f in leaked
                           if visible_by_render(str(pdf_path), pred[f])]
                if cleared:
                    warnings["render_verified"].append(
                        {"case_id": cid, "fields": cleared,
                         "note": "value found in visible ink on a rendered "
                                 "page (e.g. rotated scan); not a leak, but "
                                 "the run's state did not record its "
                                 "provenance"})
                leaked = [f for f in leaked if f not in cleared]
        for field in leaked:
            violations["hidden_only_leak"].append(
                {"case_id": cid, "field": field, "value": pred[field]})
        if len(leaked) >= 3:
            violations["answer_key_match"].append(
                {"case_id": cid, "fields": leaked})

        if pred.get("adjudication") == "APPROVED" and answer_key_claims_approved(hidden):
            warnings["oracle_approval"].append(
                {"case_id": cid, "confidence": pred.get("confidence")})

        notes = state.get("doc_notes") or {}
        if (notes.get("finding") in ("DENIED", "APPROVED")
                and (notes.get("watermark_pages") or 0) > 0
                and pred.get("adjudication") == notes.get("finding")):
            warnings["watermark_finding"].append(
                {"case_id": cid, "finding": notes["finding"],
                 "watermark_pages": notes["watermark_pages"]})

    if n_slim:
        warnings["slim_states"].append(
            {"cases": n_slim,
             "note": "no raw_pages in state and no --pdfs fallback; "
                     "leak checks did not run for these cases"})

    return {
        "cases_audited": n_cases,
        "cases_with_hidden_text": n_hidden,
        "violations": {k: v for k, v in violations.items()},
        "warnings": {k: v for k, v in warnings.items()},
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--states", required=True)
    ap.add_argument("--predictions", required=True)
    ap.add_argument("--pdfs", help="source PDF dir; re-derives hidden/visible "
                    "channels from the PDFs (required for slim state dumps)")
    ap.add_argument("--ledgers", help="per-case evidence ledger jsonl from "
                    "predict.py --ledger; raster-OCR attributions in it count "
                    "as provenance")
    ap.add_argument("--report", help="write full JSON report here")
    ap.add_argument("--max-print", type=int, default=20)
    args = ap.parse_args()

    report = audit(args.states, args.predictions, pdf_dir=args.pdfs,
                   ledgers_path=args.ledgers)
    if args.report:
        Path(args.report).write_text(json.dumps(report, indent=2))

    print(f"audited {report['cases_audited']} cases "
          f"({report['cases_with_hidden_text']} carry hidden text)")
    for severity in ("violations", "warnings"):
        for kind, rows in report[severity].items():
            print(f"{severity[:-1].upper()} {kind}: {len(rows)}")
            for row in rows[:args.max_print]:
                print(f"  {row}")
            if len(rows) > args.max_print:
                print(f"  ... {len(rows) - args.max_print} more (see --report)")

    if report["violations"]:
        print("RESULT: FAIL — quarantine leak; do not submit until explained")
        return 2
    if report["warnings"]:
        print("RESULT: WARN — eyeball the listed cases before submitting")
        return 1
    print("RESULT: CLEAN")
    return 0


if __name__ == "__main__":
    sys.exit(main())
