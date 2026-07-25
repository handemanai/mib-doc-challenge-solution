#!/usr/bin/env python3
"""Build an evidence-aware human review kit from a completed prediction run.

Unlike the original one-off review kit, hints are derived from the *current*
prediction and evidence ledgers.  A value that the pipeline already read is
shown as already captured, not as something the reviewer should hunt for.
Hidden/adversarial PDF content is reported only as quarantined metadata and is
never used to construct a hint or OCR fragment.

The tool deliberately accepts artifact paths instead of embedding experiment
directories.  A prior kit may be supplied with ``--seed-kit`` to retain its
human-review mission cohorts and to hard-link unchanged rendered images into a
new output directory; the prior kit is never overwritten.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import html
import json
import os
import re
import shutil
import sys
from datetime import date
from pathlib import Path

import cv2
import fitz
import numpy as np
from rapidfuzz import fuzz

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from mib import pixmatch, rules  # noqa: E402
from mib.vocab import DISQUALIFYING_FLAGS, FLAGS  # noqa: E402


FIELDS = (
    "applicant_name", "species_code", "home_world", "visa_class",
    "sponsor_id", "arrival_date", "declared_purpose", "risk_flags",
    "fee_status",
)
FIELD_LABELS = {
    "applicant_name": "Applicant",
    "species_code": "Species",
    "home_world": "Home world",
    "visa_class": "Visa",
    "sponsor_id": "Sponsor",
    "arrival_date": "Arrival",
    "declared_purpose": "Purpose",
    "risk_flags": "Risk flags",
    "fee_status": "Fee",
}
FALLBACK_VALUES = {
    "applicant_name": "Tekdane Ixovara",
    "species_code": "TRIANGULAN",
    "home_world": "Luyten-b",
    "visa_class": "MED-3",
    "sponsor_id": "SPN-5000",
    "arrival_date": "2026-05-01",
    "declared_purpose": "research",
    "risk_flags": "none",
    "fee_status": "paid",
}


def _load_jsonl(path: Path) -> dict[str, dict]:
    rows: dict[str, dict] = {}
    with path.open() as f:
        for lineno, line in enumerate(f, 1):
            if not line.strip():
                continue
            row = json.loads(line)
            case_id = row.get("case_id")
            if not case_id or case_id in rows:
                raise ValueError(f"{path}:{lineno}: missing or duplicate case_id")
            rows[case_id] = row
    return rows


def _load_truth(path: Path) -> dict[str, dict]:
    with path.open(newline="") as f:
        return {row["case_id"]: row for row in csv.DictReader(f)}


def _load_csv(path: Path | None, key: str) -> dict[str, dict]:
    if path is None or not path.exists():
        return {}
    with path.open(newline="") as f:
        return {row[key]: row for row in csv.DictReader(f)}


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        while chunk := f.read(1024 * 1024):
            h.update(chunk)
    return h.hexdigest()


def _norm(value) -> str:
    return str(value or "").strip()


def _tokens(value) -> set[str]:
    return {
        token.strip()
        for token in _norm(value).replace(";", "|").replace(",", "|").split("|")
        if token.strip() and token.strip() != "none"
    }


def _field_matches(field: str, truth_value, pred_value) -> bool:
    if field == "risk_flags":
        return _tokens(truth_value) == _tokens(pred_value)
    return _norm(truth_value).lower() == _norm(pred_value).lower()


class ReviewData:
    def __init__(
        self,
        truth: dict[str, dict],
        predictions: dict[str, dict],
        ledger: dict[str, dict],
        states: dict[str, dict],
        details: dict[str, dict],
        printability: dict[str, dict],
        fee_audit: dict[str, dict],
    ):
        common = set(truth) & set(predictions) & set(ledger)
        if not common:
            raise ValueError("truth, predictions, and ledger have no common cases")
        if set(predictions) != set(ledger):
            raise ValueError("prediction and ledger case-id sets differ")
        self.truth = truth
        self.pred = predictions
        self.ledger = ledger
        self.states = states
        self.details = details
        self.printability = printability
        self.fee_audit = fee_audit
        self.cases = sorted(common)

    def evidence(self, case_id: str, field: str) -> dict | None:
        baseline = self.ledger[case_id].get("evidence", {}).get(field)
        if baseline is not None:
            return baseline
        # A selected native value is trusted evidence too. The top-level
        # ``evidence`` map intentionally remains the immutable baseline ledger,
        # while the fused winner and its source live in the transition record.
        for selection in self.ledger[case_id].get(
            "two_ledger", {}
        ).get("field_selection", []):
            if selection.get("field") == field:
                return {
                    "source": "native two-ledger / "
                    + _norm(selection.get("native_source") or "unknown"),
                    "rank": "selected",
                    "agreement": "n/a",
                }
        return None

    def is_fallback(self, case_id: str, field: str) -> bool:
        # Evidence absence is authoritative. Literal comparison alone is not:
        # a real read may legitimately equal the fallback value.
        return self.evidence(case_id, field) is None

    def page_types(self, case_id: str) -> list[str]:
        if case_id in self.details:
            return list(self.details[case_id].get("page_types", []))
        return list(self.states.get(case_id, {}).get("page_types", []))

    def injection(self, case_id: str) -> dict:
        state = self.states.get(case_id, {})
        inj = state.get("injection") or self.ledger[case_id].get("injection") or {}
        count = int(inj.get("hidden_span_count", inj.get("hidden_spans", 0)) or 0)
        return {
            "hidden_spans": count,
            "answer_key": bool(inj.get("has_answer_key", inj.get("answer_key_present"))),
            "system_prompt": bool(inj.get("has_system_prompt")),
        }

    def closest_fragment(self, case_id: str, field: str, target: str) -> dict | None:
        """Return the closest *trusted pool* fragment, never hidden PDF text."""
        pool = self.states.get(case_id, {}).get("pools", {}).get(field, [])
        best = None
        for candidate in pool:
            if not isinstance(candidate, list) or len(candidate) < 5:
                continue
            raw = _norm(candidate[4])
            if not raw:
                continue
            score = max(
                fuzz.ratio(target.lower(), raw.lower()),
                fuzz.partial_ratio(target.lower(), raw.lower()),
            )
            row = {
                "raw": raw,
                "source": _norm(candidate[1]) or "unknown",
                "similarity": round(float(score)),
                "parsed": _norm(candidate[0]),
            }
            if best is None or row["similarity"] > best["similarity"]:
                best = row
        return best

    def active_truth_triggers(self, case_id: str) -> list[dict]:
        t = self.truth[case_id]
        visa = _norm(t["visa_class"])
        is_dip = visa == "DIP-1"
        out: list[dict] = []
        for flag in sorted(_tokens(t["risk_flags"]) & set(DISQUALIFYING_FLAGS)):
            out.append({"field": "risk_flags", "value": flag, "why": "disqualifying flag"})
        if _norm(t["fee_status"]) == "unpaid":
            out.append({"field": "fee_status", "value": "unpaid", "why": "unpaid fee"})
        if visa == "TRANSIT-7":
            out.append({"field": "visa_class", "value": visa, "why": "TRANSIT-7 visa"})
        world = _norm(t["home_world"])
        if world in rules.HARD_EMBARGO_WORLDS:
            out.append({"field": "home_world", "value": world, "why": "hard-embargo world"})
        elif world in rules.SOFT_EMBARGO_WORLDS and not is_dip:
            out.append({"field": "home_world", "value": world, "why": "soft-embargo world"})
        sponsor = _norm(t["sponsor_id"])
        if sponsor in rules.REVOKED_SPONSORS and not is_dip:
            out.append({"field": "sponsor_id", "value": sponsor, "why": "revoked sponsor"})
        try:
            arrival = date.fromisoformat(_norm(t["arrival_date"]))
            if not is_dip and (date(2026, 7, 7) - arrival).days > rules.STALE_DAYS:
                out.append({
                    "field": "arrival_date",
                    "value": arrival.isoformat(),
                    "why": "stale arrival date",
                })
        except ValueError:
            pass
        return out

    def trigger_resolved(self, case_id: str, trigger: dict) -> bool:
        pred_value = self.pred[case_id].get(trigger["field"])
        if trigger["field"] == "risk_flags":
            return trigger["value"] in _tokens(pred_value)
        return _field_matches(trigger["field"], trigger["value"], pred_value)

    def family_status(self, case_id: str) -> list[tuple[str, str, str]]:
        """Return (family, state, explanation), distinguishing absent/unread."""
        page_types = self.page_types(case_id)
        unknown = sum(p == "unknown" for p in page_types)
        scan_n = int(self.states.get(case_id, {}).get("n_scan_pages", 0) or 0)
        result: list[tuple[str, str, str]] = []

        # Biometric slip: use the completed printability audit where available.
        pv = self.printability.get(case_id)
        if "biometric" in page_types:
            result.append(("Biometric slip", "present", "recognized by the parser"))
        elif pv and pv.get("b13_present") == "0":
            result.append(("Biometric slip", "absent", pv.get("note") or "audited as absent"))
        elif unknown or scan_n:
            result.append((
                "Biometric slip", "unread / uncertain",
                f"not positively identified; {unknown or scan_n} damaged or unknown scan page(s)",
            ))
        else:
            result.append(("Biometric slip", "absent", "no biometric page or unknown scan page"))

        # Fee receipt: the fee audit distinguishes absent from present-unread.
        fa = self.fee_audit.get(case_id)
        if "fee_receipt" in page_types:
            result.append(("Fee receipt", "present", "recognized by the parser"))
        elif fa and fa.get("category") == "D_no_fee_page":
            result.append(("Fee receipt", "absent", "manual fee-page audit found no receipt"))
        elif fa and fa.get("category", "").startswith("B"):
            result.append((
                "Fee receipt", "unread",
                "receipt present, but the value was obscured or unreadable",
            ))
        elif unknown or scan_n:
            result.append((
                "Fee receipt", "unread / uncertain",
                "not positively identified among damaged or unknown scan pages",
            ))
        else:
            result.append(("Fee receipt", "absent", "no receipt or unknown scan page"))

        if "adjudicator_note" in page_types:
            result.append(("Adjudicator note", "present", "recognized by the parser"))
        elif self.ledger[case_id].get("reasons") == ["recovered_adjudicator_note"]:
            result.append((
                "Adjudicator note", "present but OCR-damaged",
                "verdict recovered by the guarded note-region reader",
            ))
        elif pv and pv.get("structure") == "text-native":
            result.append((
                "Adjudicator note", "absent",
                "audited text-native packet contains no adjudicator-note page",
            ))
        elif unknown or scan_n:
            result.append((
                "Adjudicator note", "unread / uncertain",
                "no typed note; damaged or unknown scan pages remain",
            ))
        else:
            result.append(("Adjudicator note", "absent", "no note or unknown scan page"))
        return result


def _page_inventory(doc: fitz.Document) -> list[dict]:
    pages = []
    for pno, page in enumerate(doc):
        images = page.get_images(full=True)
        scan_xref = None
        for image in images:
            extracted = doc.extract_image(image[0])
            if extracted["width"] >= 900 and scan_xref is None:
                scan_xref = image[0]
        pages.append({
            "pno": pno,
            "scan_xref": scan_xref,
            "scan": scan_xref is not None,
        })
    return pages


class Renderer:
    def __init__(self, output: Path, seed_kit: Path | None):
        self.output = output
        self.seed_kit = seed_kit

    def _write_or_reuse(self, folder: str, filename: str, image: np.ndarray) -> None:
        target = self.output / folder / "images" / filename
        target.parent.mkdir(parents=True, exist_ok=True)
        source = self.seed_kit / folder / "images" / filename if self.seed_kit else None
        if source and source.exists():
            try:
                os.link(source, target)
                return
            except OSError:
                shutil.copy2(source, target)
                return
        if not cv2.imwrite(str(target), image):
            raise RuntimeError(f"failed to write {target}")

    @staticmethod
    def _up(image: np.ndarray, width: int = 1600) -> np.ndarray:
        height = round(image.shape[0] * width / image.shape[1])
        interpolation = cv2.INTER_CUBIC if width > image.shape[1] else cv2.INTER_AREA
        return cv2.resize(image, (width, height), interpolation=interpolation)

    def render_case(
        self,
        case_id: str,
        pdf_path: Path,
        folder: str,
        page_types: list[str],
        mode: str,
    ) -> list[dict]:
        doc = fitz.open(pdf_path)
        inventory = _page_inventory(doc)
        rendered = []
        for page in inventory:
            pno = page["pno"]
            ptype = page_types[pno] if pno < len(page_types) else "unknown"
            base = f"{case_id}_p{pno}"
            images = []
            if page["scan"]:
                blob = doc.extract_image(page["scan_xref"])["image"]
                gray = cv2.imdecode(np.frombuffer(blob, np.uint8), cv2.IMREAD_GRAYSCALE)
                deskewed, angle = pixmatch.deskew_robust(gray)
                filename = f"{base}_scan.png"
                self._write_or_reuse(folder, filename, self._up(deskewed))
                images.append((filename, f"Native scan, deskewed {angle:+.1f} degrees"))

                enhanced = cv2.createCLAHE(
                    clipLimit=3.0, tileGridSize=(8, 8)
                ).apply(deskewed)
                filename = f"{base}_enh.png"
                self._write_or_reuse(folder, filename, self._up(enhanced))
                images.append((filename, "Same native scan with contrast enhancement"))

                top = deskewed[: round(deskewed.shape[0] * 0.58)]
                top = cv2.resize(
                    top, (top.shape[1] * 2, top.shape[0] * 2),
                    interpolation=cv2.INTER_CUBIC,
                )
                filename = f"{base}_top2x.png"
                self._write_or_reuse(folder, filename, top)
                images.append((filename, "Top 58 percent magnified 2x"))
            else:
                pix = doc[pno].get_pixmap(dpi=150, colorspace=fitz.csRGB)
                arr = np.frombuffer(pix.samples, np.uint8).reshape(pix.height, pix.width, 3)
                filename = f"{base}_text.png"
                self._write_or_reuse(folder, filename, cv2.cvtColor(arr, cv2.COLOR_RGB2BGR))
                images.append((filename, "Printed page rendered at 150 DPI"))
            rendered.append({
                "page": pno + 1,
                "type": ptype,
                "scan": page["scan"],
                "images": images,
            })
        doc.close()
        return rendered


CSS = """
:root{color-scheme:light dark}
*{box-sizing:border-box}
body{font:15px/1.48 -apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;
 margin:0;background:#f4f6f9;color:#172033}
a{color:#235fbd}
.hero{background:#14233d;color:white;padding:22px 28px}
.hero h1{margin:0 0 5px;font-size:23px}.hero p{margin:4px 0;max-width:1050px}
.wrap{max-width:1220px;margin:auto;padding:18px}
.summary,.case{background:white;border:1px solid #dbe1ea;border-radius:10px;
 margin:16px 0;padding:17px 19px;box-shadow:0 1px 4px #0000000d}
.caseid{font-size:20px;font-weight:750}.badges{margin:6px 0 10px}
.badge{display:inline-block;color:white;border-radius:15px;padding:3px 9px;
 margin:0 5px 4px 0;font-size:12px;font-weight:700}
.truth{background:#166b3a}.pred{background:#8d2630}.neutral{background:#405574}
.resolved{background:#147a48}.unresolved{background:#a54d0b}.fallback{background:#7b3fa0}
.panel{border-left:5px solid #4776bd;background:#edf4ff;padding:11px 13px;
 border-radius:6px;margin:9px 0}.panel.warn{border-color:#d17817;background:#fff5e7}
.panel.safe{border-color:#27885a;background:#eaf8f0}
.panel.inject{border-color:#a33c62;background:#fff0f5}
.panel h3{margin:0 0 5px;font-size:13px;text-transform:uppercase;letter-spacing:.4px}
table{border-collapse:collapse;width:100%;margin:9px 0;font-size:13px}
th,td{text-align:left;vertical-align:top;border-bottom:1px solid #e1e5eb;padding:7px}
th{color:#596276}.ok{color:#147a48;font-weight:700}.bad{color:#a43b24;font-weight:700}
.muted{color:#687183}.fragment{font-family:ui-monospace,SFMono-Regular,monospace}
.pages{display:grid;grid-template-columns:repeat(auto-fit,minmax(330px,1fr));gap:12px}
.page{border-top:1px dashed #cfd6e0;padding-top:9px}.page img{width:100%;background:white;
 border:1px solid #cfd6df;border-radius:6px}.cap{font-size:12px;color:#606978;margin:3px 0 8px}
code{background:#edf0f6;padding:1px 4px;border-radius:3px}
@media(prefers-color-scheme:dark){
 body{background:#0e1117;color:#e7e9ed}.summary,.case{background:#171b23;border-color:#2b3340}
 .panel{background:#16243a}.panel.warn{background:#312716}.panel.safe{background:#142a20}
 .panel.inject{background:#311c26}th{color:#aab2c0}.muted,.cap{color:#aab2c0}
 td,th{border-color:#303744}code{background:#252c38}
}
"""


def _escape(value) -> str:
    return html.escape(_norm(value))


def _field_table(data: ReviewData, case_id: str) -> str:
    t, p = data.truth[case_id], data.pred[case_id]
    rows = []
    for field in FIELDS:
        match = _field_matches(field, t[field], p.get(field))
        evidence = data.evidence(case_id, field)
        fallback = data.is_fallback(case_id, field)
        if fallback:
            source = "FALLBACK — no trusted field evidence"
        else:
            source = _norm(evidence.get("source")) or "trusted evidence"
            source += f"; rank {evidence.get('rank')}, agreement {evidence.get('agreement')}"
        rows.append(
            "<tr>"
            f"<td>{FIELD_LABELS[field]}</td>"
            f"<td>{_escape(t[field])}</td>"
            f"<td>{_escape(p.get(field))}</td>"
            f"<td class=\"{'ok' if match else 'bad'}\">{'match' if match else 'mismatch'}</td>"
            f"<td>{html.escape(source)}</td>"
            "</tr>"
        )
    return (
        "<table><thead><tr><th>Field</th><th>Truth</th><th>Current read</th>"
        "<th>Status</th><th>Evidence status</th></tr></thead><tbody>"
        + "".join(rows)
        + "</tbody></table>"
    )


def _trigger_panel(data: ReviewData, case_id: str) -> str:
    triggers = data.active_truth_triggers(case_id)
    unresolved = [x for x in triggers if not data.trigger_resolved(case_id, x)]
    resolved = [x for x in triggers if data.trigger_resolved(case_id, x)]
    parts = []
    if unresolved:
        lines = []
        for trigger in unresolved:
            fragment = data.closest_fragment(
                case_id, trigger["field"], trigger["value"]
            )
            frag_text = ""
            if fragment:
                frag_text = (
                    " Closest trusted OCR fragment: "
                    f"<code>{_escape(fragment['raw'])}</code> "
                    f"({html.escape(fragment['source'])}, "
                    f"similarity {fragment['similarity']})."
                )
            lines.append(
                f"<li><b>{html.escape(trigger['why'])}:</b> "
                f"<code>{_escape(trigger['value'])}</code> is not in the current "
                f"trusted read.{frag_text}</li>"
            )
        heading = (
            "Remaining extraction gap — decision already resolved by other authority"
            if data.pred[case_id]["adjudication"] == "DENIED"
            else "Unresolved decisive evidence"
        )
        parts.append(
            f'<div class="panel warn"><h3>{heading}</h3><ul>'
            + "".join(lines)
            + "</ul></div>"
        )
    else:
        parts.append(
            '<div class="panel safe"><h3>No unresolved field-rule trigger</h3>'
            "Every structured deny trigger in truth is already captured. If the "
            "current decision still differs, inspect an explicit adjudicator-note "
            "Finding or an evidence-authority conflict—not an already-correct field."
            "</div>"
        )
    if resolved:
        lines = "".join(
            f"<li>{html.escape(x['why'])}: <code>{_escape(x['value'])}</code> "
            "(already captured)</li>"
            for x in resolved
        )
        parts.append(
            '<div class="panel safe"><h3>Already captured — do not hunt again</h3>'
            f"<ul>{lines}</ul></div>"
        )
    truth = data.truth[case_id]
    if truth["visa_class"] == "DIP-1":
        exempt = []
        if truth["home_world"] in rules.SOFT_EMBARGO_WORLDS:
            match = _field_matches(
                "home_world", truth["home_world"],
                data.pred[case_id].get("home_world"),
            )
            exempt.append(
                f"Home world <code>{_escape(truth['home_world'])}</code> is "
                f"{'already captured' if match else 'not captured'}, but DIP-1 "
                "is exempt from this soft-world embargo."
            )
        if truth["sponsor_id"] in rules.REVOKED_SPONSORS:
            match = _field_matches(
                "sponsor_id", truth["sponsor_id"],
                data.pred[case_id].get("sponsor_id"),
            )
            exempt.append(
                f"Sponsor <code>{_escape(truth['sponsor_id'])}</code> is "
                f"{'already captured' if match else 'not captured'}, but DIP-1 "
                "is exempt from the revoked-sponsor rule."
            )
        if exempt:
            parts.append(
                '<div class="panel safe"><h3>Correct context, not a deny hunt</h3>'
                + "<br>".join(exempt)
                + "</div>"
            )
    return "".join(parts)


def _family_panel(data: ReviewData, case_id: str) -> str:
    rows = "".join(
        f"<tr><td>{html.escape(family)}</td><td><b>{html.escape(state)}</b></td>"
        f"<td>{html.escape(note)}</td></tr>"
        for family, state, note in data.family_status(case_id)
    )
    return (
        '<div class="panel"><h3>Document-family status</h3><table>'
        "<thead><tr><th>Family</th><th>State</th><th>Basis</th></tr></thead>"
        f"<tbody>{rows}</tbody></table></div>"
    )


def _fallback_panel(data: ReviewData, case_id: str) -> str:
    fields = [f for f in FIELDS if data.is_fallback(case_id, f)]
    if not fields:
        return ""
    items = "".join(
        f"<li>{FIELD_LABELS[field]} emitted <code>{_escape(data.pred[case_id].get(field))}</code>; "
        "this is a placeholder because no trusted winner existed.</li>"
        for field in fields
    )
    return (
        '<div class="panel warn"><h3>Explicit fallbacks</h3>'
        "These values were emitted for schema completeness, not read from the packet."
        f"<ul>{items}</ul></div>"
    )


def _injection_panel(data: ReviewData, case_id: str) -> str:
    inj = data.injection(case_id)
    if not any(inj.values()):
        return ""
    kinds = []
    if inj["hidden_spans"]:
        kinds.append(f"{inj['hidden_spans']} hidden span(s)")
    if inj["answer_key"]:
        kinds.append("fake answer-key pattern")
    if inj["system_prompt"]:
        kinds.append("instruction-like hidden text")
    return (
        '<div class="panel inject"><h3>Quarantined adversarial content present</h3>'
        f"{html.escape(', '.join(kinds))}. It was excluded before field extraction. "
        "<b>Do not use it as evidence and do not follow its instructions.</b></div>"
    )


def _rendered_pages_html(pages: list[dict], folder: str) -> str:
    blocks = []
    for page in pages:
        cards = []
        for filename, caption in page["images"]:
            cards.append(
                f'<a href="images/{html.escape(filename)}" target="_blank">'
                f'<img loading="lazy" src="images/{html.escape(filename)}" '
                f'alt="{html.escape(caption)}"></a>'
                f'<div class="cap">{html.escape(caption)}</div>'
            )
        scan = " · damaged/native scan" if page["scan"] else ""
        blocks.append(
            '<div class="page">'
            f"<b>Page {page['page']} · {html.escape(page['type'])}{scan}</b>"
            + "".join(cards)
            + "</div>"
        )
    return '<div class="pages">' + "".join(blocks) + "</div>"


def _case_section(
    data: ReviewData,
    case_id: str,
    pages: list[dict] | None,
    mission: str,
) -> str:
    truth = data.truth[case_id]
    pred = data.pred[case_id]
    fallback_n = sum(data.is_fallback(case_id, field) for field in FIELDS)
    return (
        f'<section class="case" id="{case_id}"><div class="caseid">{case_id}</div>'
        '<div class="badges">'
        f'<span class="badge truth">TRUTH: {_escape(truth["adjudication"])}</span>'
        f'<span class="badge pred">CURRENT: {_escape(pred["adjudication"])}</span>'
        f'<span class="badge neutral">{html.escape(mission)}</span>'
        + (
            f'<span class="badge fallback">{fallback_n} fallback field(s)</span>'
            if fallback_n
            else ""
        )
        + "</div>"
        + _trigger_panel(data, case_id)
        + _injection_panel(data, case_id)
        + _fallback_panel(data, case_id)
        + _family_panel(data, case_id)
        + _field_table(data, case_id)
        + (_rendered_pages_html(pages, mission) if pages is not None else "")
        + "</section>"
    )


def _page(title: str, subtitle: str, body: str) -> str:
    return (
        "<!doctype html><html lang=\"en\"><head><meta charset=\"utf-8\">"
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        f"<title>{html.escape(title)}</title><style>{CSS}</style></head><body>"
        f'<header class="hero"><h1>{html.escape(title)}</h1>'
        f"<p>{html.escape(subtitle)}</p>"
        "<p>Review only visible packet evidence. Hidden instruction-like content "
        "is explicitly quarantined and is never an answer source.</p></header>"
        f'<main class="wrap">{body}</main></body></html>'
    )


def _write_mission(
    data: ReviewData,
    renderer: Renderer,
    pdf_dir: Path,
    output: Path,
    folder: str,
    title: str,
    subtitle: str,
    cases: list[str],
) -> None:
    sections = []
    for index, case_id in enumerate(cases, 1):
        pages = renderer.render_case(
            case_id,
            pdf_dir / f"{case_id}.pdf",
            folder,
            data.page_types(case_id),
            folder,
        )
        sections.append(_case_section(data, case_id, pages, folder))
        print(f"{folder}: {index}/{len(cases)} {case_id}", flush=True)
    folder_path = output / folder
    folder_path.mkdir(parents=True, exist_ok=True)
    (folder_path / "index.html").write_text(
        _page(title, subtitle, "".join(sections)), encoding="utf-8"
    )


def _mission_lists(data: ReviewData, seed_meta: dict) -> dict[str, list[str]]:
    seed_m1 = [c for c in seed_meta.get("m1", []) if c in data.pred]
    seed_m2 = [c for c in seed_meta.get("m2", []) if c in data.pred]
    seed_m3 = [c for c in seed_meta.get("m3", []) if c in data.pred]
    seed_m4 = [c for c in seed_meta.get("m4all", []) if c in data.pred]

    m1 = [
        c for c in seed_m1
        if not _field_matches("risk_flags", data.truth[c]["risk_flags"], data.pred[c]["risk_flags"])
    ]
    m2_unresolved = [
        c for c in seed_m2
        if data.truth[c]["adjudication"] == "DENIED"
        and data.pred[c]["adjudication"] != "DENIED"
    ]
    m2_resolved = [
        c for c in seed_m2
        if data.truth[c]["adjudication"] == "DENIED"
        and data.pred[c]["adjudication"] == "DENIED"
    ]
    m3 = [
        c for c in seed_m3
        if data.truth[c]["adjudication"] != data.pred[c]["adjudication"]
    ]
    excluded = set(m1) | set(m2_unresolved)
    candidates = [
        c for c in seed_m4
        if c not in excluded
        and not _field_matches("risk_flags", data.truth[c]["risk_flags"], data.pred[c]["risk_flags"])
    ]
    candidates.sort(
        key=lambda c: (
            bool(_tokens(data.truth[c]["risk_flags"]) & set(DISQUALIFYING_FLAGS)),
            len(_tokens(data.truth[c]["risk_flags"])),
            data.pred[c].get("risk_flags") == "none",
            c,
        ),
        reverse=True,
    )
    return {
        "m1": m1,
        "m2_unresolved": m2_unresolved,
        "m2_resolved": m2_resolved,
        "m3": m3,
        "m4": candidates[:30],
    }


def _readme(data: ReviewData, missions: dict[str, list[str]], head: str) -> str:
    resolved_rows = []
    for case_id in missions["m2_resolved"]:
        p = data.pred[case_id]
        resolved_rows.append(
            f"<tr><td>{case_id}</td><td>{_escape(p['adjudication'])}</td>"
            f"<td>{_escape('|'.join(data.ledger[case_id].get('reasons', [])))}</td>"
            f"<td>{_escape(p['risk_flags'])}</td><td>{_escape(p['fee_status'])}</td>"
            f"<td>{_escape(p['home_world'])}</td><td>{_escape(p['sponsor_id'])}</td></tr>"
        )
    resolved = (
        '<section class="summary"><h2>Resolved since the original kit</h2>'
        "These packets are no longer reviewer hunts; the current pipeline already "
        "reaches DENIED. They remain listed so improvements are not mistaken for "
        "missing evidence."
        "<table><thead><tr><th>Case</th><th>Current decision</th><th>Reason</th>"
        "<th>Flags</th><th>Fee</th><th>World</th><th>Sponsor</th></tr></thead><tbody>"
        + "".join(resolved_rows)
        + "</tbody></table>"
        '<p><a href="mission2-deny-trigger/resolved.html">Detailed current field and '
        "fallback status for resolved cases</a></p></section>"
    )
    cards = (
        '<section class="summary"><h2>Current review missions</h2><ul>'
        f'<li><a href="mission1-invisible-slips/index.html">Risk/slip review</a>: '
        f'{len(missions["m1"])} still-mismatched original cases.</li>'
        f'<li><a href="mission2-deny-trigger/index.html">Unresolved denials</a>: '
        f'{len(missions["m2_unresolved"])} cases still not DENIED. Hints name only '
        "unresolved active triggers.</li>"
        f'<li><a href="mission3-dossiers/index.html">Decision dossiers</a>: '
        f'{len(missions["m3"])} original decision errors still unresolved.</li>'
        f'<li><a href="mission4-heavy-field/index.html">Flag sample</a>: '
        f'{len(missions["m4"])} current risk-flag mismatches.</li>'
        "</ul></section>"
    )
    provenance = (
        '<section class="summary"><h2>Evidence contract</h2><ul>'
        "<li>“Current read” comes from the supplied default-on prediction artifact.</li>"
        "<li>“Fallback” means the evidence ledger contains no trusted winning source; "
        "the displayed value is schema completion, not a packet read.</li>"
        "<li>OCR fragments come only from trusted visible-evidence pools.</li>"
        "<li>Hidden fake answer keys and instruction-like spans are reported only as "
        "quarantined adversarial metadata and never shape a requested answer.</li>"
        "<li>Document families are labeled present, absent, or unread/uncertain rather "
        "than collapsing absence into OCR failure.</li></ul>"
        f'<p class="muted">Generator source revision: <code>{html.escape(head)}</code></p>'
        "</section>"
    )
    return _page(
        "MIB Human Review Kit — Current Pipeline",
        "Evidence-aware refresh: already-correct fields are no longer presented as hunts.",
        cards + resolved + provenance,
    )


def _validate_output(
    output: Path,
    data: ReviewData,
    missions: dict[str, list[str]],
) -> dict:
    missing_links = []
    html_files = sorted(output.rglob("*.html"))
    link_count = 0
    for page in html_files:
        text = page.read_text(encoding="utf-8")
        for target in re.findall(r'(?:href|src)="([^"]+)"', text):
            if target.startswith(("http:", "https:", "#")):
                continue
            link_count += 1
            resolved = (page.parent / target).resolve()
            if not resolved.exists():
                missing_links.append(f"{page.relative_to(output)} -> {target}")
    if missing_links:
        raise ValueError("broken review-kit links:\n" + "\n".join(missing_links[:20]))

    incorrect_hunts = []
    for case_id in missions["m2_unresolved"]:
        for trigger in data.active_truth_triggers(case_id):
            if data.trigger_resolved(case_id, trigger):
                # Resolved triggers may appear only under the explicit
                # "already captured" panel; they must never be an unresolved
                # hunt. The renderer uses the same partition.
                continue
            if not trigger["value"]:
                incorrect_hunts.append(f"{case_id}: empty unresolved trigger")
    if incorrect_hunts:
        raise ValueError("\n".join(incorrect_hunts))

    required_resolved = {
        "MIB-000012", "MIB-000192", "MIB-000261", "MIB-000444"
    } & set(data.pred)
    missing_resolved = required_resolved - set(missions["m2_resolved"])
    if missing_resolved:
        raise ValueError(
            "expected current fixes absent from resolved list: "
            + ", ".join(sorted(missing_resolved))
        )
    return {
        "html_files": len(html_files),
        "local_links_checked": link_count,
        "missing_links": 0,
        "m2_unresolved_cases": len(missions["m2_unresolved"]),
        "m2_resolved_cases": len(missions["m2_resolved"]),
        "required_current_fixes_resolved": sorted(required_resolved),
        "hidden_content_used_as_evidence": False,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--truth", type=Path, required=True)
    parser.add_argument("--predictions", type=Path, required=True)
    parser.add_argument("--ledger", type=Path, required=True)
    parser.add_argument("--states", type=Path, required=True)
    parser.add_argument("--details", type=Path, required=True)
    parser.add_argument("--pdf-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--seed-kit", type=Path, required=True)
    parser.add_argument("--printability-audit", type=Path)
    parser.add_argument("--fee-audit", type=Path)
    parser.add_argument("--source-revision", default="unknown")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.output.exists():
        raise SystemExit(
            f"refusing to overwrite existing review kit: {args.output}"
        )
    seed_meta_path = args.seed_kit / "_meta.json"
    seed_meta = json.loads(seed_meta_path.read_text())
    data = ReviewData(
        _load_truth(args.truth),
        _load_jsonl(args.predictions),
        _load_jsonl(args.ledger),
        _load_jsonl(args.states),
        _load_jsonl(args.details),
        _load_csv(args.printability_audit, "case_id"),
        _load_csv(args.fee_audit, "case"),
    )
    missions = _mission_lists(data, seed_meta)
    args.output.mkdir(parents=True)
    renderer = Renderer(args.output, args.seed_kit)

    _write_mission(
        data, renderer, args.pdf_dir, args.output,
        "mission1-invisible-slips", "Mission 1 — Remaining Risk/Slip Mismatches",
        "Original slip-review cases whose current risk_flags still disagree with truth.",
        missions["m1"],
    )
    _write_mission(
        data, renderer, args.pdf_dir, args.output,
        "mission2-deny-trigger", "Mission 2 — Unresolved Denials",
        "Only active deny triggers that the current trusted read still misses are requested.",
        missions["m2_unresolved"],
    )
    _write_mission(
        data, renderer, args.pdf_dir, args.output,
        "mission3-dossiers", "Mission 3 — Remaining Decision Dossiers",
        "Original dossier cases whose current decision still disagrees with truth.",
        missions["m3"],
    )
    _write_mission(
        data, renderer, args.pdf_dir, args.output,
        "mission4-heavy-field", "Mission 4 — Current Risk-Flag Mismatches",
        "A prioritized sample of risk-flag mismatches after current reader improvements.",
        missions["m4"],
    )

    resolved_dir = args.output / "mission2-deny-trigger"
    resolved_sections = "".join(
        _case_section(data, case_id, None, "resolved-current")
        for case_id in missions["m2_resolved"]
    )
    (resolved_dir / "resolved.html").write_text(
        _page(
            "Mission 2 — Resolved by Current Pipeline",
            "No image hunt is requested; this records current evidence and fallbacks.",
            resolved_sections,
        ),
        encoding="utf-8",
    )
    (args.output / "README.html").write_text(
        _readme(data, missions, args.source_revision), encoding="utf-8"
    )
    validation = _validate_output(args.output, data, missions)

    artifact_paths = {
        "truth": args.truth,
        "predictions": args.predictions,
        "ledger": args.ledger,
        "states": args.states,
        "details": args.details,
    }
    report = {
        "schema": "mib-review-kit-v2",
        "source_revision": args.source_revision,
        "seed_kit": str(args.seed_kit),
        "artifact_sha256": {
            name: {"path": str(path), "sha256": _sha256(path)}
            for name, path in artifact_paths.items()
        },
        "counts": {name: len(cases) for name, cases in missions.items()},
        "missions": missions,
        "fallback_values_for_display_only": FALLBACK_VALUES,
        "hidden_content_used_as_evidence": False,
        "validation": validation,
    }
    (args.output / "_buildreport.json").write_text(
        json.dumps(report, indent=2, sort_keys=True), encoding="utf-8"
    )
    print(json.dumps(report["counts"], sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
