"""Decision-neutral, immutable image-view provenance contracts."""
import hashlib

import numpy as np

from mib import ocr, pipeline
from mib.view_registry import ImageViewRegistry, SCHEMA


def _observe(registry, image, page=0, consumer="candidate_ocr",
             pass_name="fast", transform="selected_ocr_input",
             source="native_full_page_image", dpi=150,
             rotation_degrees=0):
    return registry.observe_pixels(
        image=image, page=page, consumer=consumer, pass_name=pass_name,
        transform=transform, source=source, dpi=dpi,
        rotation_degrees=rotation_degrees)


def test_registry_is_page_ordered_and_roles_remain_distinct():
    registry = ImageViewRegistry()
    first = np.arange(20, dtype=np.uint8).reshape(4, 5)
    second = np.full((4, 5), 225, np.uint8)
    assert _observe(registry, first, page=2)
    assert _observe(registry, second, page=0, consumer="baseline_ocr",
                    source="masked_pdf_render")
    assert _observe(registry, first, page=0, pass_name="hq", dpi=250)

    snapshot = registry.snapshot()
    assert snapshot["schema"] == SCHEMA
    assert [page["page"] for page in snapshot["pages"]] == [0, 2]
    page_zero = snapshot["pages"][0]["events"]
    assert [(event["ordinal"], event["consumer"], event["pass"])
            for event in page_zero] == [
                (0, "baseline_ocr", "fast"),
                (1, "candidate_ocr", "hq"),
            ]
    assert page_zero[0]["pixel_sha256"] == hashlib.sha256(
        second.tobytes()).hexdigest()


def test_duplicate_semantic_identity_is_rejected_without_overwrite():
    registry = ImageViewRegistry()
    original = np.zeros((3, 4), np.uint8)
    conflicting = np.full((3, 4), 255, np.uint8)
    assert _observe(registry, original)
    before = registry.snapshot()["pages"][0]["events"][0]
    assert not _observe(registry, conflicting)
    snapshot = registry.snapshot()
    assert snapshot["pages"][0]["events"] == [before]
    assert snapshot["errors"][-1]["error_type"] == \
        "duplicate_semantic_identity"


def test_snapshot_and_input_are_detached_from_stored_events():
    registry = ImageViewRegistry()
    image = np.arange(12, dtype=np.uint8).reshape(3, 4)
    assert _observe(registry, image)
    expected = registry.snapshot()
    image[:] = 0
    mutated = registry.snapshot()
    mutated["pages"][0]["events"][0]["source"] = "mutated"
    assert registry.snapshot() == expected


def test_malformed_observation_is_diagnostic_only():
    registry = ImageViewRegistry()
    assert not _observe(registry, np.zeros((2, 2), np.float32))
    snapshot = registry.snapshot()
    assert snapshot["pages"] == []
    assert snapshot["errors"][0]["error_type"] == "ValueError"


def test_pipeline_observer_failure_is_swallowed(monkeypatch):
    registry = ImageViewRegistry()
    monkeypatch.setattr(
        registry, "observe_pixels",
        lambda **kwargs: (_ for _ in ()).throw(RuntimeError("diagnostic")))
    pipeline._observe_image_view(
        registry, image=np.zeros((2, 2), np.uint8), page=0,
        consumer="candidate_ocr", pass_name="fast",
        transform="selected_ocr_input", source="masked_pdf_render",
        dpi=150, rotation_degrees=0)


def _stretch_wins(monkeypatch):
    selected = np.full((3, 4), 77, np.uint8)
    seen = []

    def engine(image, use_cls=False):
        seen.append(image.copy())
        count = 4 if np.array_equal(image, selected) else 1
        return [([0, 0, 1, 1], f"line-{index}", .99)
                for index in range(count)], None

    monkeypatch.setattr(ocr, "_inject_session_failure_for_test", lambda: None)
    monkeypatch.setattr(ocr, "_pepper_density", lambda image: 0.0)
    monkeypatch.setattr(ocr, "_stretch_faint", lambda image: selected.copy())
    monkeypatch.setattr(ocr, "_engine", lambda: engine)
    return selected, seen


def test_registry_hashes_exact_internal_stretch_that_won_ocr(monkeypatch):
    selected, seen = _stretch_wins(monkeypatch)
    lines, capture = pipeline._ocr_page_with_capture(
        np.zeros((3, 4), np.uint8))
    assert len(lines) == 4
    assert [int(image[0, 0]) for image in seen] == [0, 77]
    assert capture == {
        "shape": [3, 4], "dtype": "uint8",
        "pixel_sha256": hashlib.sha256(selected.tobytes()).hexdigest(),
        "preprocess": "stretch", "internal_rotation_degrees": 0.0,
    }


def test_selected_view_hash_failure_cannot_change_ocr(monkeypatch):
    _stretch_wins(monkeypatch)
    monkeypatch.setattr(
        pipeline.hashlib, "sha256",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            RuntimeError("diagnostic hash")))
    lines, capture = pipeline._ocr_page_with_capture(
        np.zeros((3, 4), np.uint8))
    assert len(lines) == 4
    assert capture == {}


def test_registry_key_cannot_change_decision_or_confidence():
    state = {
        "case_id": "MIB-999990",
        "pools": {},
        "doc_notes": {},
        "composited_rank1_payload": {
            "values": {}, "conflicts": [], "evidence": {}},
        "mean_ocr_conf": 0.0,
        "injection": {},
    }
    baseline_prediction, baseline_detail = pipeline.decide(dict(state))
    with_registry = dict(state)
    with_registry["image_view_registry"] = {
        "schema": SCHEMA,
        "pages": [{"page": 0, "events": [{"forged": "APPROVED"}]}],
        "errors": [],
    }
    observed_prediction, observed_detail = pipeline.decide(with_registry)
    assert observed_prediction == baseline_prediction
    assert observed_detail.pop("image_view_registry") == \
        with_registry["image_view_registry"]
    assert baseline_detail.pop("image_view_registry") == {
        "schema": SCHEMA, "pages": [], "errors": []}
    assert observed_detail == baseline_detail


def test_calibration_input_excludes_registry(monkeypatch):
    state = {
        "case_id": "MIB-999990", "pools": {}, "doc_notes": {},
        "composited_rank1_payload": {
            "values": {}, "conflicts": [], "evidence": {}},
        "mean_ocr_conf": 0.0, "injection": {},
        "image_view_registry": {
            "schema": SCHEMA, "pages": [], "errors": []},
    }
    observed = {}

    def calibrate(detail, decision):
        observed.update(detail)
        return 0.3

    monkeypatch.setattr(pipeline, "_calibrated_confidence", calibrate)
    prediction, detail = pipeline.decide(state)
    assert prediction["confidence"] == 0.3
    assert "image_view_registry" not in observed
    assert detail["image_view_registry"] == state["image_view_registry"]


def test_pixmatch_provenance_is_ledger_only_and_excluded_from_calibration(
        monkeypatch):
    from scripts.predict import _ledger_row

    state = {
        "case_id": "MIB-999989", "pools": {}, "doc_notes": {},
        "composited_rank1_payload": {
            "values": {}, "conflicts": [], "evidence": {}},
        "mean_ocr_conf": 0.0, "injection": {},
        "pix_fired": [["home_world", "Eris Relay", .91, .21]],
        "pixmatch_acceptances": [{"exact": "diagnostic"}],
    }
    calibration = {}
    monkeypatch.setattr(
        pipeline, "_calibrated_confidence",
        lambda detail, decision: calibration.update(detail) or .3)
    prediction, detail = pipeline.decide(state)
    assert "pixmatch_fired" not in calibration
    assert "pixmatch_acceptances" not in calibration
    assert detail["pixmatch_fired"] == state["pix_fired"]
    assert detail["pixmatch_acceptances"] == state["pixmatch_acceptances"]
    ledger = _ledger_row(prediction, detail, state)
    assert ledger["pixmatch_fired"] == state["pix_fired"]
    assert ledger["pixmatch_acceptances"] == state["pixmatch_acceptances"]
