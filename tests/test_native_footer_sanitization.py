"""Fail-closed contracts for native-only PDF footer sanitization."""
import copy
import hashlib
import io

import cv2
import fitz
import numpy as np
import pytest
from PIL import Image

from mib import forensics, pipeline


def _png(array):
    buffer = io.BytesIO()
    Image.fromarray(array).save(buffer, format="PNG")
    return buffer.getvalue()


def _insert_scan(page, array, rect=None, rotate=0):
    xref = page.insert_image(
        rect or page.rect, stream=_png(array), rotate=rotate)
    page.parent.xref_set_key(xref, "ColorSpace", "/DeviceGray")
    page.parent.xref_set_key(xref, "DecodeParms", "null")
    return xref


def _reopen(doc):
    buffer = io.BytesIO()
    doc.save(buffer)
    doc.close()
    return fitz.open(stream=buffer.getvalue(), filetype="pdf")


def _scan(faint_value=245):
    image = np.full((1584, 1224), 245, np.uint8)
    image[400:520, 180:960] = 20
    image[1450:, :650] = faint_value
    return image


def _footer_doc(faint_value=245, text="Packet MIB-123456 / page 1",
                point=(50, 764), **text_kwargs):
    image = _scan(faint_value)
    doc = fitz.open()
    page = doc.new_page(width=612, height=792)
    _insert_scan(page, image)
    page.insert_text(point, text, fontsize=text_kwargs.pop("fontsize", 7),
                     **text_kwargs)
    return _reopen(doc), image


@pytest.mark.parametrize("faint_value", range(225, 256))
def test_every_eligible_faint_value_is_whitened_and_nothing_else_changes(
        faint_value):
    doc, original = _footer_doc(faint_value)
    meta = forensics.native_full_page_scan(doc[0], visible_spans=[])
    assert meta is not None
    regions = meta["native_footer_suppression_regions"]
    assert len(regions) == 1
    assert set(regions[0]) == {
        "kind", "authorization", "page_bbox", "native_bbox", "padding_pt",
        "routing_minimum", "fill_value",
    }
    assert regions[0]["authorization"] == "blank_native_pixels"

    observed, provenance = forensics.native_scan_gray(
        doc, doc[0], visible_spans=[])
    expected = original.copy()
    for record in regions:
        x0, y0, x1, y1 = record["native_bbox"]
        expected[y0:y1, x0:x1] = 255
    assert np.array_equal(observed, expected)
    assert provenance["native_footer_suppression_regions"] == regions
    assert np.array_equal(observed[:1400], original[:1400])
    doc.close()


def test_value_below_boundary_and_one_mixed_dark_pixel_abstain():
    doc, _ = _footer_doc(224)
    assert forensics.native_full_page_scan(doc[0], []) is None
    doc.close()

    reference, _ = _footer_doc(245)
    region = forensics.native_full_page_scan(reference[0], [])[
        "native_footer_suppression_regions"][0]["native_bbox"]
    reference.close()
    image = _scan(245)
    x0, y0, x1, y1 = region
    image[(y0 + y1) // 2, (x0 + x1) // 2] = 224
    doc = fitz.open()
    page = doc.new_page(width=612, height=792)
    _insert_scan(page, image)
    page.insert_text((50, 764), "Packet MIB-123456 / page 1", fontsize=7)
    doc = _reopen(doc)
    assert forensics.native_full_page_scan(doc[0], []) is None
    doc.close()


@pytest.mark.parametrize("text_kwargs", [
    {"color": (1, 1, 1)},
    {"fontsize": 2.0},
    {"fontsize": 13.0},
    {"fill_opacity": 0.5},
    {"render_mode": 1},
    {"color": (0.3, 0.3, 0.3)},
])
def test_nonordinary_footer_paint_never_authorizes_suppression(text_kwargs):
    doc, _ = _footer_doc(**text_kwargs)
    assert forensics.native_full_page_scan(doc[0], visible_spans=[]) is None
    doc.close()


def test_physical_inventory_ignores_misleading_caller_span_filter():
    doc, _ = _footer_doc()
    meta = forensics.native_full_page_scan(doc[0], visible_spans=[])
    assert len(meta["native_footer_suppression_regions"]) == 1
    doc.close()

    doc = fitz.open()
    page = doc.new_page(width=612, height=792)
    _insert_scan(page, _scan())
    page.insert_text((72, 120), "Fee Status: unpaid", fontsize=12)
    doc = _reopen(doc)
    assert forensics.native_full_page_scan(doc[0], visible_spans=[]) is None
    doc.close()


@pytest.mark.parametrize("page_rotation", [90, 180, 270])
def test_page_rotation_with_footer_abstains(page_rotation):
    doc = fitz.open()
    page = doc.new_page(width=612, height=792)
    _insert_scan(page, _scan())
    page.insert_text((50, 764), "Packet MIB-123456 / page 1", fontsize=7)
    page.set_rotation(page_rotation)
    doc = _reopen(doc)
    assert forensics.native_full_page_scan(doc[0], []) is None
    doc.close()


@pytest.mark.parametrize("placement_rotation", [90, 180, 270])
def test_image_placement_rotation_with_footer_abstains(placement_rotation):
    raw = (_scan().T.copy() if placement_rotation in (90, 270) else _scan())
    doc = fitz.open()
    page = doc.new_page(width=612, height=792)
    _insert_scan(page, raw, rotate=placement_rotation)
    page.insert_text((50, 764), "Packet MIB-123456 / page 1", fontsize=7)
    doc = _reopen(doc)
    assert forensics.native_full_page_scan(doc[0], []) is None
    doc.close()


def test_shifted_cropbox_with_footer_abstains_but_plain_scan_remains_eligible():
    def build(with_footer):
        doc = fitz.open()
        page = doc.new_page(width=812, height=992)
        page.set_cropbox(fitz.Rect(100, 100, 712, 892))
        _insert_scan(page, _scan(), rect=page.rect)
        if with_footer:
            page.insert_text(
                (50, 764), "Packet MIB-123456 / page 1", fontsize=7)
        return _reopen(doc)

    plain = build(False)
    assert forensics.native_full_page_scan(plain[0]) is not None
    plain.close()
    footer = build(True)
    assert forensics.native_full_page_scan(footer[0], []) is None
    footer.close()


def test_mapping_uses_exact_placement_rect_and_two_point_padding():
    doc = fitz.open()
    page = doc.new_page(width=612, height=792)
    placement = [0.00009, 0.0, 612.0, 792.0]
    meta = {
        "placement_rotation": 0, "page_rotation": 0,
        "placement_rect": placement,
        "native_width": 10_000_000, "native_height": 12_000_000,
    }
    bbox = [50.0, 750.0, 100.0, 760.0]
    observed = forensics._native_pixel_rect(page, meta, bbox)
    sx = meta["native_width"] / (placement[2] - placement[0])
    sy = meta["native_height"] / (placement[3] - placement[1])
    expected = [
        int(np.floor((bbox[0] - 2.0 - placement[0]) * sx)),
        int(np.floor((bbox[1] - 2.0 - placement[1]) * sy)),
        int(np.ceil((bbox[2] + 2.0 - placement[0]) * sx)),
        int(np.ceil((bbox[3] + 2.0 - placement[1]) * sy)),
    ]
    page_assumption = [
        int(np.floor((bbox[0] - 2.0) * meta["native_width"] / 612)),
        int(np.floor((bbox[1] - 2.0) * meta["native_height"] / 792)),
        int(np.ceil((bbox[2] + 2.0) * meta["native_width"] / 612)),
        int(np.ceil((bbox[3] + 2.0) * meta["native_height"] / 792)),
    ]
    assert observed == expected
    assert observed != page_assumption
    doc.close()


def test_stale_one_and_a_half_point_placement_tolerance_never_returns():
    doc = fitz.open()
    page = doc.new_page(width=612, height=792)
    _insert_scan(page, _scan(), rect=fitz.Rect(1.5, 0, 612, 792))
    doc = _reopen(doc)
    audit = forensics.native_full_page_scan_audit(doc[0])
    assert audit == {"eligible": False, "reason": "not_full_bleed"}
    doc.close()


def _valid_sanitizer_fixture():
    doc, _ = _footer_doc()
    meta = forensics.native_full_page_scan(doc[0], [])
    image, _ = forensics._decode_native_gray(doc, meta)
    return doc, image, meta


def test_explicit_empty_inventory_is_identity_but_omission_fails_closed(
        monkeypatch):
    doc = fitz.open()
    page = doc.new_page(width=612, height=792)
    original = _scan()
    _insert_scan(page, original)
    doc = _reopen(doc)
    meta = forensics.native_full_page_scan(doc[0])
    assert meta["native_footer_suppression_regions"] == []
    observed, _ = forensics.native_scan_gray(doc, doc[0])
    assert np.array_equal(observed, original)

    stripped = copy.deepcopy(meta)
    stripped.pop("native_footer_suppression_regions")
    monkeypatch.setattr(
        forensics, "native_full_page_scan", lambda *args, **kwargs: stripped)
    assert forensics.native_scan_gray(doc, doc[0]) == (None, None)
    doc.close()


@pytest.mark.parametrize("mutation", [
    lambda region: region.pop("fill_value"),
    lambda region: region.update(extra=True),
    lambda region: region.update(native_bbox=[1.0, 2, 3, 4]),
    lambda region: region.update(native_bbox=[True, 2, 3, 4]),
    lambda region: region.update(native_bbox=[1, 2, 3]),
    lambda region: region.update(native_bbox=[1, 2, 1, 4]),
    lambda region: region.update(native_bbox=[-1, 2, 3, 4]),
    lambda region: region.update(fill_value=254),
    lambda region: region.update(routing_minimum=224),
    lambda region: region.update(padding_pt=1.0),
    lambda region: region.update(page_bbox=[1.0, 2.0, float("inf"), 4.0]),
    lambda region: region.update(page_bbox=[51.0, *region["page_bbox"][1:]]),
])
def test_malformed_region_metadata_abstains(mutation):
    doc, image, meta = _valid_sanitizer_fixture()
    mutated = copy.deepcopy(meta)
    mutation(mutated["native_footer_suppression_regions"][0])
    assert forensics._sanitize_native_footer_pixels(
        image, doc[0], mutated) is None
    doc.close()


def test_region_validation_is_atomic_and_rechecks_current_pixels():
    doc, image, meta = _valid_sanitizer_fixture()
    original = image.copy()
    invalid_second = copy.deepcopy(
        meta["native_footer_suppression_regions"][0])
    invalid_second["fill_value"] = 0
    two_regions = copy.deepcopy(meta)
    two_regions["native_footer_suppression_regions"].append(invalid_second)
    assert forensics._sanitize_native_footer_pixels(
        image, doc[0], two_regions) is None
    assert np.array_equal(image, original)

    changed = image.copy()
    x0, y0, x1, y1 = meta[
        "native_footer_suppression_regions"][0]["native_bbox"]
    changed[(y0 + y1) // 2, (x0 + x1) // 2] = 224
    assert forensics._sanitize_native_footer_pixels(
        changed, doc[0], meta) is None
    doc.close()


def test_truncated_multi_footer_inventory_fails_closed():
    doc = fitz.open()
    page = doc.new_page(width=612, height=792)
    _insert_scan(page, _scan(230))
    page.insert_text((50, 764), "Packet MIB-123456 / page 1", fontsize=7)
    page.insert_text(
        (350, 764), "Synthetic hiring challenge document", fontsize=7)
    doc = _reopen(doc)
    meta = forensics.native_full_page_scan(doc[0], [])
    assert len(meta["native_footer_suppression_regions"]) == 2
    image, _ = forensics._decode_native_gray(doc, meta)
    truncated = copy.deepcopy(meta)
    truncated["native_footer_suppression_regions"].pop()
    assert forensics._sanitize_native_footer_pixels(
        image, doc[0], truncated) is None
    doc.close()


def test_suppression_precedes_resizing_and_baseline_renders_never_change():
    doc, _ = _footer_doc(230)
    _, hidden = forensics.classify_spans(doc)
    baseline_before = {
        dpi: forensics.masked_page_gray(doc[0], hidden, dpi=dpi)
        for dpi in (150, 250)
    }
    native, _ = forensics.native_scan_gray(doc, doc[0])
    for dpi in (150, 250):
        observed, _ = forensics.native_scan_gray(doc, doc[0], dpi=dpi)
        target = (round(doc[0].rect.width * dpi / 72.0),
                  round(doc[0].rect.height * dpi / 72.0))
        expected = cv2.resize(native, target, interpolation=cv2.INTER_LINEAR)
        assert np.array_equal(observed, expected)
        assert np.array_equal(
            baseline_before[dpi],
            forensics.masked_page_gray(doc[0], hidden, dpi=dpi))
    repeated, repeated_meta = forensics.native_scan_gray(doc, doc[0])
    assert np.array_equal(repeated, native)
    assert repeated_meta == forensics.native_scan_gray(doc, doc[0])[1]
    doc.close()


def test_native_observer_hashes_exact_post_resize_output_without_live_pixels():
    doc, original = _footer_doc(230)
    events = []
    observed, provenance = forensics.native_scan_gray(
        doc, doc[0], dpi=150, visible_spans=[],
        view_observer=lambda **event: events.append(event))
    assert [event["transform"] for event in events] == [
        "native_decoded", "footer_sanitized", "native_scan_output"]
    assert all("image" not in event for event in events)
    assert events[0]["preprocess"] == "decode_grayscale"
    assert events[0]["pixel_sha256"] == hashlib.sha256(
        original.tobytes()).hexdigest()
    assert events[1]["preprocess"] == "footer_suppression"
    assert events[-1]["preprocess"] == "orientation_resize"
    assert events[-1]["dpi"] == 150.0
    assert events[-1]["shape"] == list(observed.shape)
    assert events[-1]["pixel_sha256"] == hashlib.sha256(
        np.ascontiguousarray(observed).tobytes()).hexdigest()
    assert provenance["output_dpi"] == 150
    doc.close()


def test_nonfinite_placement_reports_explicit_selector_reason(monkeypatch):
    doc = fitz.open()
    page = doc.new_page(width=612, height=792)
    _insert_scan(page, _scan())
    doc = _reopen(doc)
    original = fitz.Page.get_image_rects
    _, matrix = original(
        doc[0], doc[0].get_images(full=True)[0][0], transform=True)[0]

    def nonfinite(selected_page, *args, **kwargs):
        return [(fitz.Rect(float("nan"), 0, 612, 792), matrix)]

    monkeypatch.setattr(fitz.Page, "get_image_rects", nonfinite)
    assert forensics.native_full_page_scan_audit(doc[0])["reason"] == \
        "invalid_placement_rect"
    doc.close()


def test_wrong_footer_id_is_transactionally_replaced_by_untouched_baseline(
        tmp_path, monkeypatch):
    doc = fitz.open()
    page = doc.new_page(width=612, height=792)
    _insert_scan(page, _scan(230))
    page.insert_text(
        (50, 764), "Packet MIB-654321 / page 1", fontsize=7)
    path = tmp_path / "MIB-123456.pdf"
    doc.save(path)
    doc.close()

    candidate = [
        ("FORM I-8090 Work Authorization Intake", .99),
        ("Case ID: MIB-123456", .99),
        ("Applicant: Tekdane Ixovara", .99),
        ("Species Code: ARCTURIAN", .99),
        ("Home World: Europa Station", .99),
        ("Visa Class: MED-3", .99),
        ("Sponsor ID: SPN-9999", .99),
        ("Arrival Date: 2026-05-02", .99),
        ("Purpose: cultural exchange", .99),
        ("Observed Flags: none", .99),
        ("Fee Status: paid", .99),
    ]
    baseline = [
        ("FORM I-8090 Work Authorization Intake", .99),
        ("Case ID: MIB-123456", .99),
        ("Applicant: Nexmora Lurix", .99),
        ("Species Code: TRIANGULAN", .99),
        ("Home World: Eris Relay", .99),
        ("Visa Class: XW-1", .99),
        ("Sponsor ID: SPN-1502", .99),
        ("Arrival Date: 2026-06-01", .99),
        ("Purpose: research", .99),
        ("Observed Flags: planetary_embargo", .99),
        ("Fee Status: unpaid", .99),
    ]

    def fake_ocr(image, hq=False):
        return baseline if int(image[-120:].min()) < 100 else candidate

    monkeypatch.setenv("MIB_NATIVE_SCAN_OCR", "1")
    monkeypatch.setenv("MIB_PIXMATCH", "0")
    monkeypatch.setattr(pipeline.ocr, "ocr_page", fake_ocr)
    state = pipeline.extract_state(str(path))
    # The baseline top-level ledger holds the untouched composited P0-B fields.
    assert {entry[0] for entry in state["pools"]["home_world"]} == {
        "Eris Relay"}
    # The fused decision preserves the baseline denial and fields; a native
    # read on a wrong-footer packet can never relax the baseline denial.
    from mib import two_ledger
    epoch = pipeline.batch_epoch([state])
    revoked = pipeline.batch_frequent_sponsors([state])
    natives, has = two_ledger.native_batch_inputs([state])
    nepoch = pipeline.batch_epoch(natives) if has else epoch
    nrevoked = pipeline.batch_frequent_sponsors(natives) if has else revoked
    prediction, _ = two_ledger.decide_case(
        state, epoch, nepoch, revoked, nrevoked,
        two_ledger.ablation_from_env())
    assert prediction["home_world"] == "Eris Relay"
    assert prediction["fee_status"] == "unpaid"
    assert prediction["adjudication"] == "DENIED"
