"""Rotation robustness for whole-page and embedded-scan orientations.

A page can carry an upright PDF wrapper (footer, watermark, case id, stamps)
around a sideways embedded scan. Wrapper evidence must not suppress the retry;
form-title/field evidence still protects clean upright pages from OCR cost.
"""
import cv2
import fitz
import numpy as np
import pytest
from pathlib import Path

from mib import pipeline
from mib.parse_ocr import page_anchored, page_anchor_strength

CID = "MIB-700100"
REAL_MIB_892 = (Path(__file__).resolve().parents[2] / "mib-doc-challenge"
                / "data" / "train" / "MIB-000892.pdf")
FORM_LINES = [
    ("FORM I-8090 Work Authorization Intake", 14),
    (f"Case ID: {CID}", 11),
    ("Applicant: Solmora Tekvoss", 11),
    ("Species code: TRIANGULAN", 11),
    ("Home world: Kepler-186f", 11),
    ("Visa class: XW-2", 11),
    ("Sponsor ID: SPN-1234", 11),
    ("Arrival date: 2026-06-01", 11),
    ("Purpose: research", 11),
    ("Observed flags: none", 11),
    (f"Packet {CID} / page 1", 8),
]


def _scan_pdf(tmp_path, rot_k):
    """Render a text form to an image, rotate it, save as an image-only PDF."""
    src = fitz.open()
    p = src.new_page(width=612, height=792)
    y = 80
    for text, size in FORM_LINES:
        p.insert_text((72, y), text, fontsize=size)
        y += size + 12
    pix = p.get_pixmap(dpi=150, colorspace=fitz.csGRAY)
    img = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width)
    img = np.rot90(img, rot_k) if rot_k else img
    ok, buf = cv2.imencode(".png", img)
    assert ok
    out = fitz.open()
    w, h = (612, 792) if rot_k in (0, 2) else (792, 612)
    page = out.new_page(width=w, height=h)
    page.insert_image(page.rect, stream=buf.tobytes())
    path = tmp_path / f"{CID}.pdf"
    out.save(str(path))
    return str(path)


def _sideways_body_upright_wrapper_pdf(tmp_path, body_case_id=None):
    """Sideways scan body beneath an upright vector wrapper."""
    src = fitz.open()
    p = src.new_page(width=612, height=792)
    y = 80
    for text, size in FORM_LINES:
        if text.startswith("Packet "):
            continue
        if text.startswith("Case ID:"):
            if body_case_id is None:
                continue
            text = f"Case ID: {body_case_id}"
        p.insert_text((72, y), text, fontsize=size)
        y += size + 12
    pix = p.get_pixmap(dpi=150, colorspace=fitz.csGRAY)
    body = np.frombuffer(
        pix.samples, dtype=np.uint8).reshape(pix.height, pix.width)
    body = np.rot90(body, 1)
    ok, buf = cv2.imencode(".png", body)
    assert ok

    out = fitz.open()
    page = out.new_page(width=792, height=612)
    page.insert_image(page.rect, stream=buf.tobytes())
    # These remain upright after the scan image was inserted.
    page.insert_text((36, 34), f"Case ID: {CID}", fontsize=9)
    page.insert_text((330, 34), "SAMPLE DENIAL", fontsize=9)
    page.insert_text((650, 34), "ARCHIVE", fontsize=9)
    page.insert_text((650, 54), "COPY", fontsize=9)
    page.insert_text((650, 74), "FILED", fontsize=9)
    page.insert_text((650, 94), "INTAKE", fontsize=9)
    page.insert_text((36, 594), f"Packet {CID} / page 1", fontsize=8)
    mixed_dir = tmp_path / "mixed"
    mixed_dir.mkdir()
    path = mixed_dir / f"{CID}.pdf"
    out.save(str(path))
    return str(path)


def _extracted_values(state):
    return {f: str(cands[0][0]) for f, cands in state["pools"].items()}


@pytest.mark.parametrize("rot_k", [0, 2, 1])
def test_rotated_scan_page_recovers(tmp_path, rot_k):
    state = pipeline.extract_state(_scan_pdf(tmp_path, rot_k))
    values = _extracted_values(state)
    # The deny-relevant core must be read regardless of page orientation.
    assert values.get("visa_class") == "XW-2"
    assert values.get("sponsor_id") == "SPN-1234"
    assert values.get("risk_flags") == "none"
    assert values.get("fee_status") is None or "fee_status" not in values  # no fee page in packet


def test_anchor_gate_separates_garbage_from_real():
    garbage = ["unoop aueliuo buu oeuuss", "weqpo puuo x", "aa bbb ccc", "zzz qqq"]
    assert not page_anchored(garbage)
    assert page_anchor_strength(garbage) == "none"
    for line in ["FORM I-8090 Work Authorization", "Obserdfags: none"]:
        assert page_anchor_strength([line]) == "content", line
    for line in ["PacketMIB-000023/page2", "ARCHIVE",
                 "SAMPLE DENIAL", "Case ID: MIB-000102"]:
        assert page_anchor_strength([line]) == "wrapper", line
        assert page_anchored([line]), line


def test_sideways_body_retries_despite_upright_wrapper(tmp_path):
    state = pipeline.extract_state(_sideways_body_upright_wrapper_pdf(tmp_path))
    values = _extracted_values(state)
    assert values.get("visa_class") == "XW-2"
    assert values.get("sponsor_id") == "SPN-1234"
    assert values.get("risk_flags") == "none"
    assert state["image_views"][0]["ocr_retry_rotation"] != 0
    # The winning rotated body must retain the upright wrapper's safety signal.
    assert state["doc_notes"]["watermark_pages"] >= 1


def test_upright_active_wrapper_does_not_admit_foreign_rotated_body(tmp_path):
    state = pipeline.extract_state(_sideways_body_upright_wrapper_pdf(
        tmp_path, body_case_id="MIB-799999"))
    values = _extracted_values(state)
    assert values.get("visa_class") is None
    assert values.get("sponsor_id") is None
    assert values.get("risk_flags") is None


@pytest.mark.skipif(not REAL_MIB_892.exists(),
                    reason="MIB challenge training corpus is not present")
def test_real_mib_892_replays_effective_fast_rotation_for_hq(monkeypatch):
    monkeypatch.setenv("MIB_NATIVE_SCAN_OCR", "0")
    state = pipeline.extract_state(str(REAL_MIB_892))
    prediction, _ = pipeline.decide(state)
    assert state["pools"]["home_world"][0][0] == "Wolf-1061c"
    assert prediction["home_world"] == "Wolf-1061c"
    assert prediction["adjudication"] == "DENIED"


def test_upright_page_never_pays_retry(tmp_path, monkeypatch):
    calls = {"n": 0}
    real = pipeline.ocr.ocr_page

    def counting(img, *a, **kw):
        calls["n"] += 1
        return real(img, *a, **kw)

    monkeypatch.setattr(pipeline.ocr, "ocr_page", counting)
    pipeline.extract_state(_scan_pdf(tmp_path, 0))
    # fast pass (1) + possible HQ ladder for the absent fee field (1); a
    # rotation retry would add more ocr_page calls on the SAME fast image.
    assert calls["n"] <= 2
