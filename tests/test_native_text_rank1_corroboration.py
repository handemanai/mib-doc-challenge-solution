"""Native text may describe different glyphs than the reviewer sees.

These tests keep the security boundary at the first point a born-digital page
can acquire rank-1 authority: every finding and signed correction must be
recovered with identical semantics from the composited page pixels.
"""

from types import SimpleNamespace

import numpy as np
import pytest

from mib import parse_ocr, pipeline


CID = "MIB-700001"


def _parsed(*lines):
    return parse_ocr.parse_page([(line, 0.99) for line in lines])


def _page():
    return SimpleNamespace(number=0)


def _pixel_ocr(monkeypatch, *lines):
    calls = []

    def render(page, dpi):
        calls.append(("render", page.number, dpi))
        return np.full((32, 32), 255, dtype=np.uint8)

    def recognize(image, hq=False):
        calls.append(("ocr", image.shape, hq))
        return [(line, 99.0) for line in lines], {}

    monkeypatch.setattr(pipeline.forensics, "composited_page_gray", render)
    monkeypatch.setattr(pipeline, "_ocr_page_with_capture", recognize)
    return calls


def _note(*authority_lines):
    return _parsed(
        "Manual Adjudicator Note",
        f"Case ID: {CID}",
        "Applicant: Oridane Soltari",
        *authority_lines,
    )


def test_native_page_without_rank1_payload_runs_no_pixel_ocr(monkeypatch):
    parsed = _parsed(
        "Sponsor Attestation Letter",
        f"Case ID: {CID}",
        "Sponsor ID: SPN-1001",
    )

    def unexpected(*args, **kwargs):
        raise AssertionError("ordinary native pages must not pay for OCR")

    monkeypatch.setattr(
        pipeline.forensics, "composited_page_gray", unexpected)
    assert pipeline._corroborate_native_text_rank1(_page(), parsed) is parsed


def test_matching_pixel_finding_preserves_native_text_authority(monkeypatch):
    parsed = _note("Finding: APPROVED")
    calls = _pixel_ocr(
        monkeypatch,
        "Manual Adjudicator Note",
        f"Case ID: {CID}",
        "Finding: APPROVED",
    )

    assert pipeline._corroborate_native_text_rank1(_page(), parsed) is parsed
    assert calls == [("render", 0, 250), ("ocr", (32, 32), True)]


def test_visible_finding_mismatch_strips_authority_but_keeps_ordinary_field(
        monkeypatch):
    parsed = _note("Finding: APPROVED")
    _pixel_ocr(
        monkeypatch,
        "Manual Adjudicator Note",
        f"Case ID: {CID}",
        "Applicant: Oridane Soltari",
        "Finding: DENIED",
    )

    ptype, fields, notes = pipeline._corroborate_native_text_rank1(
        _page(), parsed)
    assert ptype == "unknown"
    assert fields["applicant_name"][0] == "Oridane Soltari"
    assert notes["finding"] is None
    assert notes["corrections"] == {}
    assert notes["rank1_observations"] == {}


@pytest.mark.parametrize("pixel_lines", [
    (),
    (
        "Manual Adjudicator Note",
        f"Case ID: {CID}",
        "Finding: APPROVED",
    ),
    (
        "Manual Adjudicator Note",
        f"Case ID: {CID}",
        "Finding: APPROVED",
        "Manual correction: sponsor is SPN-9999",
    ),
])
def test_partial_missing_or_extra_pixel_authority_fails_closed(
        monkeypatch, pixel_lines):
    parsed = _note(
        "Finding: APPROVED",
        "Manual correction: sponsor is SPN-0007",
    )
    _pixel_ocr(monkeypatch, *pixel_lines)

    _, _, notes = pipeline._corroborate_native_text_rank1(_page(), parsed)
    assert notes["finding"] is None
    assert notes["corrections"] == {}


def test_matching_complete_pixel_authority_preserves_all_values(monkeypatch):
    lines = (
        "Manual Adjudicator Note",
        f"Case ID: {CID}",
        "Finding: NEEDS_REVIEW",
        "Manual correction: visa class is DIP-1",
    )
    parsed = _parsed(*lines)
    _pixel_ocr(monkeypatch, *lines)

    assert pipeline._corroborate_native_text_rank1(_page(), parsed) is parsed


def test_render_or_ocr_failure_strips_native_text_authority(monkeypatch):
    parsed = _note("Finding: APPROVED")

    def fail(*args, **kwargs):
        raise RuntimeError("synthetic renderer failure")

    monkeypatch.setattr(pipeline.forensics, "composited_page_gray", fail)
    _, _, notes = pipeline._corroborate_native_text_rank1(_page(), parsed)
    assert notes["finding"] is None
    assert notes["corrections"] == {}
