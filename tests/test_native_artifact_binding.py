import copy
import csv
import hashlib
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import types
from pathlib import Path

import pytest

from tools.native_artifact_binding import (EFFECTIVE_CONFIG_DEFAULTS,
                                           EXPECTED_RUNTIME_REPO_PATHS,
                                           PIX_ALLOWED_VALUES,
                                           PIX_BASELINE_GUARD_WORLDS,
                                           PIX_FIELD_PAGE_TYPES,
                                           PIX_GATE_THRESHOLDS, SCHEMA,
                                           _validate_evidence_rows,
                                           binding_identity,
                                           canonical_effective_config,
                                           canonical_sha256, input_manifest,
                                           verify_binding)


ROOT = Path(__file__).resolve().parents[1]
BIND = ROOT / "tools" / "native_artifact_binding.py"
AUDIT = ROOT / "tools" / "audit_native_view.py"
PREPARE_IDENTITY = ROOT / "tools" / "prepare_native_run_identity.py"
IMAGE_ID = "sha256:" + "a" * 64
FIELDS = ("applicant_name", "species_code", "home_world", "visa_class",
          "sponsor_id", "arrival_date", "declared_purpose", "risk_flags",
          "fee_status")
CONTEXT_BARE_SOURCES = (
    "adjudicator_note_bare", "intake_bare", "fee_receipt_bare",
    "biometric_bare", "sponsor_letter_bare", "registry_bare",
    "unknown_bare",
)
NATIVE_OFF = {"MIB_NATIVE_SCAN_OCR": "0"}


def _clean_env(**updates):
    env = {key: value for key, value in os.environ.items()
           if not key.startswith("MIB_") and key != "OMP_NUM_THREADS"}
    env.update(updates)
    return env


def _run(command, **env):
    return subprocess.run(
        command, text=True, capture_output=True, env=_clean_env(**env))


def _write_jsonl(path, rows):
    path.write_text("".join(json.dumps(row) + "\n" for row in rows))


def _prediction(case_id, decision="NEEDS_REVIEW", **updates):
    row = {
        "case_id": case_id,
        "applicant_name": "Nexdane Solvoss",
        "species_code": "TRIANGULAN",
        "home_world": "Luyten-b",
        "visa_class": "XW-1",
        "sponsor_id": "SPN-1001",
        "arrival_date": "2026-05-01",
        "declared_purpose": "research",
        "risk_flags": "none",
        "fee_status": "paid",
        "adjudication": decision,
    }
    row.update(updates)
    return row


def _evidence(case_id, finding=None, error=None, conflicts=None,
              adjudication="NEEDS_REVIEW", rank1_fields=None, attempts=None):
    prediction = _prediction(case_id, adjudication)
    attempt_rows = attempts or [{
        "attempt": 1,
        "status": "failed" if error else "success",
        **({"failure_category": "test_failure"} if error else {}),
    }]
    rank1_values = {
        **({"finding": [finding]} if finding else {}),
        **{field: [value] for field, value in (rank1_fields or {}).items()},
    }
    origin = {"page": 0, "view": "masked_pdf_render",
              "dpi": 150, "pass": "fast"}
    return {
        "case_id": case_id,
        "adjudication": adjudication,
        "extraction": {
            "attempt_count": sum(
                row.get("status") != "not_attempted" for row in attempt_rows),
            "recovered": (len(attempt_rows) > 1
                          and attempt_rows[-1].get("status") == "success"),
            "attempts": attempt_rows,
        },
        "fields": {field: prediction[field] for field in FIELDS},
        "evidence": {},
        "rank1_payload": {"finding": finding, "fields": dict(rank1_fields or {})},
        "composited_rank1_payload": {
            "values": rank1_values,
            "conflicts": [],
            "evidence": {
                field: [{"value": value, "origin": origin}]
                for field, (value,) in rank1_values.items()
            },
        },
        "rank1_conflicts": list(conflicts or []),
        "baseline_approval_guards": [],
        "baseline_batch_context": {},
        "image_view_registry": {
            "schema": "mib-image-view-registry-v1",
            "pages": [], "errors": [],
        },
        "pixmatch_fired": [],
        "pixmatch_acceptances": [],
        "identity_disqualified_pages": [],
        "native_fallback_review_pages": [],
        "execution_error": error,
    }


def _view_event(ordinal, consumer, pass_name, transform, source,
                preprocess, *, page=0, dpi=72.0, rotation=0.0,
                shape=(20, 20), digest=None):
    digest = digest or (str(ordinal % 10) * 64)
    return {
        "view_id": (f"p{page}:{ordinal}:{consumer}:{pass_name}:"
                    f"{transform}"),
        "page": page, "ordinal": ordinal, "consumer": consumer,
        "pass": pass_name, "transform": transform, "source": source,
        "preprocess": preprocess, "dpi": float(dpi),
        "rotation_degrees": float(rotation), "shape": list(shape),
        "dtype": "uint8", "pixel_sha256": digest,
    }


def _candidate_pixmatch_evidence(native=False):
    row = _evidence("MIB-000001")
    field, value = "home_world", "Eris Relay"
    row["fields"][field] = value
    row["evidence"][field] = {
        "rank": 6, "snap_score": 90.0, "agreement": 1,
        "source": "pixmatch",
    }
    row["pixmatch_fired"] = [[field, value, .91, .21]]
    if native:
        events = [
            _view_event(
                0, "candidate_pixmatch", "decode", "native_decoded",
                "native_embedded_image", "decode_grayscale", dpi=144,
                digest="a" * 64),
            _view_event(
                1, "candidate_pixmatch", "decode", "footer_sanitized",
                "native_embedded_image", "footer_passthrough", dpi=144,
                digest="a" * 64),
            _view_event(
                2, "candidate_pixmatch", "decode", "native_scan_output",
                "native_full_page_image", "orientation", dpi=144),
            _view_event(
                3, "candidate_pixmatch", "decode", "despeckled",
                "native_full_page_image", "despeckle", dpi=144),
            _view_event(
                4, "candidate_pixmatch", "decode", "deskewed",
                "native_full_page_image", "deskew", dpi=144,
                rotation=1.25),
            _view_event(
                5, "candidate_pixmatch", field, "accepted_roi",
                "deskewed_pixmatch_view", "roi", dpi=144,
                shape=(3, 5)),
        ]
    else:
        events = [
            _view_event(
                0, "candidate_pixmatch", "decode", "p0b_scan_output",
                "p0b_masked_scan_image", "grayscale_despeckle"),
            _view_event(
                1, "candidate_pixmatch", "decode", "deskewed",
                "p0b_masked_scan_image", "deskew", rotation=1.25),
            _view_event(
                2, "candidate_pixmatch", field, "accepted_roi",
                "deskewed_pixmatch_view", "roi", shape=(3, 5)),
        ]
    row["image_view_registry"]["pages"] = [{"page": 0, "events": events}]
    row["pixmatch_acceptances"] = [{
        "consumer": "candidate_pixmatch", "field": field,
        "value": value, "page": 0, "page_type": "intake",
        "effects": ["candidate_pool"],
        "deskewed_view": {
            "page": 0, "consumer": "candidate_pixmatch",
            "pass": "decode", "transform": "deskewed"},
        "roi_view": {
            "page": 0, "consumer": "candidate_pixmatch",
            "pass": field, "transform": "accepted_roi"},
        "roi_box": [2, 5, 3, 8], "ncc": .91, "margin": .21,
        "crosscheck": "not_required",
    }]
    return row


def _baseline_pixmatch_evidence():
    row = _evidence("MIB-000001")
    field, value = "home_world", "Eris Relay"
    row["baseline_approval_guards"] = [{
        "field": field, "value": value,
        "origin": "p0b_pixmatch", "source": "pixmatch",
    }]
    row["image_view_registry"]["pages"] = [{"page": 0, "events": [
        _view_event(
            0, "baseline_pixmatch", "decode", "p0b_scan_output",
            "p0b_masked_scan_image", "grayscale_despeckle"),
        _view_event(
            1, "baseline_pixmatch", "decode", "deskewed",
            "p0b_masked_scan_image", "deskew", digest="0" * 64),
        _view_event(
            2, "baseline_pixmatch", field, "accepted_roi",
            "deskewed_pixmatch_view", "roi", shape=(3, 5)),
    ]}]
    row["pixmatch_acceptances"] = [{
        "consumer": "baseline_pixmatch", "field": field,
        "value": value, "page": 0, "page_type": "intake",
        "effects": ["baseline_guard"],
        "deskewed_view": {
            "page": 0, "consumer": "baseline_pixmatch",
            "pass": "decode", "transform": "deskewed"},
        "roi_view": {
            "page": 0, "consumer": "baseline_pixmatch",
            "pass": field, "transform": "accepted_roi"},
        "roi_box": [2, 5, 3, 8], "ncc": .91, "margin": .21,
        "crosscheck": "not_required",
    }]
    return row


def test_pixmatch_view_registry_and_acceptance_contracts_validate():
    _validate_evidence_rows([_candidate_pixmatch_evidence()], NATIVE_OFF)
    _validate_evidence_rows(
        [_candidate_pixmatch_evidence(native=True)],
        {"MIB_NATIVE_SCAN_OCR": "1"})
    _validate_evidence_rows(
        [_baseline_pixmatch_evidence()],
        {"MIB_NATIVE_SCAN_OCR": "1"})


def test_native_sanitizer_abstention_may_leave_only_decoded_fingerprint():
    row = _evidence("MIB-000001")
    row["image_view_registry"]["pages"] = [{"page": 0, "events": [
        _view_event(
            0, "candidate_pixmatch", "decode", "native_decoded",
            "native_embedded_image", "decode_grayscale", dpi=144),
    ]}]
    _validate_evidence_rows([row], {"MIB_NATIVE_SCAN_OCR": "1"})


def test_composited_candidate_ocr_source_is_native_fallback_only():
    row = _evidence("MIB-000001")
    row["native_fallback_review_pages"] = [0]
    row["image_view_registry"]["pages"] = [{"page": 0, "events": [
        _view_event(
            0, "candidate_ocr", "fast", "selected_ocr_input",
            "composited_pdf_render", "none", dpi=150),
    ]}]
    _validate_evidence_rows([row], {"MIB_NATIVE_SCAN_OCR": "1"})

    missing_fallback = copy.deepcopy(row)
    missing_fallback["native_fallback_review_pages"] = []
    with pytest.raises(ValueError, match="fallback pages"):
        _validate_evidence_rows(
            [missing_fallback], {"MIB_NATIVE_SCAN_OCR": "1"})

    impossible_source = copy.deepcopy(row)
    impossible_source["native_fallback_review_pages"] = []
    impossible_source["image_view_registry"]["pages"][0]["events"][0][
        "source"] = "masked_pdf_render"
    with pytest.raises(ValueError, match="OCR source"):
        _validate_evidence_rows(
            [impossible_source], {"MIB_NATIVE_SCAN_OCR": "1"})

    control = copy.deepcopy(row)
    control["native_fallback_review_pages"] = []
    with pytest.raises(ValueError, match="OCR source"):
        _validate_evidence_rows([control], NATIVE_OFF)


def test_native_candidate_fast_ocr_uses_configured_dpi():
    row = _evidence("MIB-000001")
    row["image_view_registry"]["pages"] = [{"page": 0, "events": [
        _view_event(
            0, "candidate_ocr", "fast", "selected_ocr_input",
            "native_full_page_image", "none", dpi=144),
    ]}]
    config = {
        "MIB_NATIVE_SCAN_OCR": "1", "MIB_NATIVE_SCAN_FAST_DPI": "144"}
    _validate_evidence_rows([row], config)

    wrong_dpi = copy.deepcopy(row)
    wrong_dpi["image_view_registry"]["pages"][0]["events"][0]["dpi"] = 150.0
    with pytest.raises(ValueError, match="OCR event contract"):
        _validate_evidence_rows([wrong_dpi], config)


def test_native_pixmatch_chain_allows_only_rotation_consistent_shapes():
    row = _candidate_pixmatch_evidence(native=True)
    events = row["image_view_registry"]["pages"][0]["events"]
    events[0]["shape"] = [20, 30]
    events[1]["shape"] = [20, 30]
    events[2]["shape"] = [30, 20]
    events[2]["rotation_degrees"] = 90.0
    events[3]["shape"] = [30, 20]
    events[4]["shape"] = [30, 20]
    config = {"MIB_NATIVE_SCAN_OCR": "1"}
    _validate_evidence_rows([row], config)

    wrong_shape = copy.deepcopy(row)
    wrong_shape["image_view_registry"]["pages"][0]["events"][2][
        "shape"] = [20, 30]
    with pytest.raises(ValueError, match="view shape"):
        _validate_evidence_rows([wrong_shape], config)


def test_pixmatch_roi_must_follow_deskew_in_registry_chronology():
    row = _candidate_pixmatch_evidence()
    events = row["image_view_registry"]["pages"][0]["events"]
    events[:] = [events[0], events[2], events[1]]
    for ordinal, event in enumerate(events):
        event["ordinal"] = ordinal
        event["view_id"] = (
            f"p0:{ordinal}:{event['consumer']}:{event['pass']}:"
            f"{event['transform']}")
    with pytest.raises(ValueError, match="view order"):
        _validate_evidence_rows([row], NATIVE_OFF)


def test_zero_angle_deskew_must_preserve_exact_pixels():
    row = _baseline_pixmatch_evidence()
    _validate_evidence_rows([row], {"MIB_NATIVE_SCAN_OCR": "1"})
    row["image_view_registry"]["pages"][0]["events"][1][
        "pixel_sha256"] = "f" * 64
    with pytest.raises(ValueError, match="zero-angle"):
        _validate_evidence_rows([row], {"MIB_NATIVE_SCAN_OCR": "1"})


def test_coordinated_illegal_candidate_value_is_rejected():
    row = _candidate_pixmatch_evidence()
    row["fields"]["home_world"] = "FORGED_WORLD"
    row["pixmatch_fired"][0][1] = "FORGED_WORLD"
    row["pixmatch_acceptances"][0]["value"] = "FORGED_WORLD"
    with pytest.raises(ValueError, match="acceptance contract"):
        _validate_evidence_rows([row], NATIVE_OFF)


def test_coordinated_non_embargo_baseline_guard_is_rejected():
    row = _baseline_pixmatch_evidence()
    row["baseline_approval_guards"][0]["value"] = "Titan Freeport"
    row["pixmatch_acceptances"][0]["value"] = "Titan Freeport"
    with pytest.raises(ValueError, match="active guard"):
        _validate_evidence_rows([row], {"MIB_NATIVE_SCAN_OCR": "1"})


@pytest.mark.parametrize("mutation", [
    lambda evidence: evidence.__setitem__("snap_score", 89.9),
    lambda evidence: evidence.__setitem__("agreement", True),
    lambda evidence: evidence.__setitem__("rank", True),
    lambda evidence: evidence.__setitem__("extra", "forged"),
])
def test_candidate_pixmatch_evidence_is_exact(mutation):
    row = _candidate_pixmatch_evidence()
    mutation(row["evidence"]["home_world"])
    with pytest.raises(ValueError, match="emitted evidence"):
        _validate_evidence_rows([row], NATIVE_OFF)


@pytest.mark.parametrize("mutation", [
    lambda row: row["pixmatch_fired"][0].__setitem__(1, "Titan Freeport"),
    lambda row: row["pixmatch_acceptances"][0].__setitem__("ncc", .92),
    lambda row: row["pixmatch_acceptances"][0].__setitem__(
        "roi_box", [2, 6, 3, 8]),
    lambda row: row["pixmatch_acceptances"][0]["roi_view"].__setitem__(
        "pass", "species_code"),
    lambda row: row["image_view_registry"]["pages"][0]["events"][1].__setitem__(
        "source", "native_full_page_image"),
    lambda row: row["image_view_registry"]["pages"][0]["events"].pop(),
    lambda row: row["pixmatch_acceptances"].clear(),
    lambda row: row["fields"].__setitem__("home_world", "Titan Freeport"),
    lambda row: row["image_view_registry"]["errors"].append({
        "page": 0, "semantic_id": "0:candidate_pixmatch",
        "error_type": "ValueError"}),
])
def test_pixmatch_provenance_tampering_fails_closed(mutation):
    row = _candidate_pixmatch_evidence()
    mutation(row)
    with pytest.raises(ValueError):
        _validate_evidence_rows([row], NATIVE_OFF)


def test_native_candidate_acceptance_cannot_use_quarantined_page():
    for key in ("identity_disqualified_pages",
                "native_fallback_review_pages"):
        row = _candidate_pixmatch_evidence(native=True)
        row[key] = [0]
        if key == "native_fallback_review_pages":
            row["image_view_registry"]["pages"][0]["events"].append(
                _view_event(
                    6, "candidate_ocr", "fast", "selected_ocr_input",
                    "composited_pdf_render", "none", dpi=150))
        with pytest.raises(ValueError, match="quarantined"):
            _validate_evidence_rows(
                [row], {"MIB_NATIVE_SCAN_OCR": "1"})


def test_baseline_pixel_guard_and_acceptance_must_cross_bind():
    row = _baseline_pixmatch_evidence()
    row["baseline_approval_guards"][0]["value"] = "Titan Freeport"
    with pytest.raises(ValueError, match="guards and acceptances"):
        _validate_evidence_rows([row], {"MIB_NATIVE_SCAN_OCR": "1"})


def test_pixmatch_records_are_rejected_when_channel_is_disabled():
    with pytest.raises(ValueError, match="disabled"):
        _validate_evidence_rows(
            [_candidate_pixmatch_evidence()],
            {"MIB_NATIVE_SCAN_OCR": "0", "MIB_PIXMATCH": "0"})


def test_registry_errors_are_rejected_even_on_execution_error_rows():
    row = _evidence("MIB-000001", error="test_failure")
    row["image_view_registry"]["errors"] = [{
        "page": None, "semantic_id": "snapshot",
        "error_type": "RuntimeError",
    }]
    with pytest.raises(ValueError, match="registry errors"):
        _validate_evidence_rows([row])


def test_blank_execution_error_cannot_bypass_registry_integrity():
    row = _evidence("MIB-000001", error="")
    with pytest.raises(ValueError, match="execution_error"):
        _validate_evidence_rows([row])


def test_binder_pixmatch_constants_match_runtime_contract():
    from mib import pixmatch, rules
    from mib.vocab import SPECIES, WORLDS

    assert PIX_ALLOWED_VALUES == {
        "species_code": frozenset(SPECIES),
        "home_world": frozenset(WORLDS),
    }
    assert PIX_GATE_THRESHOLDS == {
        field: (gate["ncc"], gate["margin"])
        for field, gate in pixmatch.GATES.items()
    }
    assert PIX_FIELD_PAGE_TYPES == {
        field: set(pixmatch.FIELD_PAGES[field]) | {"unknown"}
        for field in PIX_GATE_THRESHOLDS
    }
    assert all(
        not pixmatch.needs_ctc(field, value)
        for field, values in PIX_ALLOWED_VALUES.items()
        for value in values
    )
    assert PIX_BASELINE_GUARD_WORLDS == (
        rules.HARD_EMBARGO_WORLDS | rules.SOFT_EMBARGO_WORLDS)


def test_runtime_manifest_matches_the_docker_copied_source_and_model_tree():
    copied_tree = {
        str(path.relative_to(ROOT))
        for directory in (ROOT / "mib", ROOT / "models")
        for path in directory.iterdir()
        if path.is_file() and path.suffix in {".py", ".json", ".onnx", ".npz"}
    }
    manifested_tree = set(EXPECTED_RUNTIME_REPO_PATHS) - {
        "run.sh", "scripts/predict.py", "scripts/run_shard.py"}
    assert manifested_tree == copied_tree


def test_evidence_accepts_selected_baseline_sponsor_visa_and_date_pool():
    row = _evidence("MIB-000001")
    row["baseline_batch_context"] = {
        "sponsor_id": [[
            "SPN-1234", "sponsor_letter", 2, 95.0, "SPN-1234"]],
        "visa_class": [["DIP-1", "intake", 3, 95.0, "DIP-1"]],
        "arrival_date": [
            ["2026-05-01", "intake", 2, 95.0, "2026-05-01"],
            ["2026-05-02", "registry", 5, 90.0, "2026-05-02"],
        ],
    }
    _validate_evidence_rows([row])


@pytest.mark.parametrize(("field", "value", "source", "rank"), [
    ("sponsor_id", "SPN-1234", "adjudicator_note", 1),
    ("sponsor_id", "SPN-1234", "fee_receipt", 2),
    ("sponsor_id", "SPN-1234", "sponsor_letter", 2),
    ("sponsor_id", "SPN-1234", "intake", 3),
    ("sponsor_id", "SPN-1234", "biometric", 3),
    ("sponsor_id", "SPN-1234", "registry", 5),
    ("sponsor_id", "SPN-1234", "unknown", 6),
    ("visa_class", "XW-1", "adjudicator_note", 1),
    ("visa_class", "XW-1", "fee_receipt", 2),
    ("visa_class", "XW-1", "sponsor_letter", 2),
    ("visa_class", "XW-1", "letter_label", 2),
    ("visa_class", "XW-1", "intake", 3),
    ("visa_class", "XW-1", "biometric", 3),
    ("visa_class", "XW-1", "slip_label", 3),
    ("visa_class", "XW-1", "registry", 5),
    ("visa_class", "XW-1", "unknown", 6),
    ("arrival_date", "2026-05-01", "adjudicator_note", 1),
    ("arrival_date", "2026-05-01", "intake", 2),
    ("arrival_date", "2026-05-01", "fee_receipt", 2),
    ("arrival_date", "2026-05-01", "biometric", 3),
    ("arrival_date", "2026-05-01", "slip_label", 3),
    ("arrival_date", "2026-05-01", "letter_label", 4),
    ("arrival_date", "2026-05-01", "sponsor_letter", 4),
    ("arrival_date", "2026-05-01", "registry", 5),
    ("arrival_date", "2026-05-01", "unknown", 6),
    *((field, value, source, 6)
      for field, value in (
          ("sponsor_id", "SPN-1234"),
          ("visa_class", "XW-1"),
          ("arrival_date", "2026-05-01"))
      for source in CONTEXT_BARE_SOURCES),
])
def test_evidence_accepts_producer_possible_context_provenance(
        field, value, source, rank):
    confidence = (70.0 if source in CONTEXT_BARE_SOURCES
                  and field in {"sponsor_id", "arrival_date"}
                  else 66.0 if source in CONTEXT_BARE_SOURCES
                  else 95.0)
    row = _evidence("MIB-000001")
    row["baseline_batch_context"] = {
        field: [[value, source, rank, confidence, value]],
    }
    _validate_evidence_rows([row])


@pytest.mark.parametrize(
    ("field", "value", "source", "rank", "confidence", "raw"), [
        *(("arrival_date", "2026-05-01", "intake", 2, confidence,
           "20260501" if confidence in {72.0, 75.0, 80.0}
           else "2026-05-01")
          for confidence in (72.0, 75.0, 80.0, 87.0, 90.0, 95.0)),
        ("arrival_date", "2026-05-01", "intake_bare", 6, 65.0,
         "20260501"),
        ("arrival_date", "2026-05-01", "intake_bare", 6, 70.0,
         "2026-05-01"),
        *(("sponsor_id", "SPN-1234", "intake", 3, confidence,
           "SPN-1234") for confidence in (87.0, 90.0, 95.0)),
        ("visa_class", "XW-1", "intake", 3, 67.0, "XW-Z"),
        ("visa_class", "XW-1", "intake", 3, 100.0, "XW-1"),
        ("visa_class", "XW-1", "slip_label", 3, 100.0, "XW-1"),
    ])
def test_evidence_accepts_real_parser_confidence_boundaries(
        field, value, source, rank, confidence, raw):
    row = _evidence("MIB-000001")
    row["baseline_batch_context"] = {
        field: [[value, source, rank, confidence, raw]],
    }
    _validate_evidence_rows([row])


def _set_composited_values(row, field, observed):
    values = sorted(set(observed))
    origin = {"page": 0, "view": "masked_pdf_render",
              "dpi": 150, "pass": "fast"}
    payload = row["composited_rank1_payload"]
    payload["values"][field] = values
    payload["evidence"][field] = [
        {"value": value, "origin": origin} for value in values]
    payload["conflicts"] = sorted(
        name for name, field_values in payload["values"].items()
        if len(field_values) > 1)


@pytest.mark.parametrize(("field", "value", "confidence"), [
    ("sponsor_id", "SPN-5678", 99.0),
    ("visa_class", "DIP-1", 99.0),
    ("visa_class", "DIP-1", 100.0),
])
def test_evidence_accepts_bound_single_composited_context(
        field, value, confidence):
    row = _evidence("MIB-000001")
    _set_composited_values(row, field, [value])
    row["baseline_batch_context"] = {
        field: [[value, "manual_correction", 1, confidence, value]],
    }
    _validate_evidence_rows([row])


@pytest.mark.parametrize(("field", "values"), [
    ("sponsor_id", ["SPN-1234", "SPN-5678"]),
    ("visa_class", ["DIP-1", "XW-1"]),
])
def test_evidence_accepts_absent_context_for_composited_conflict(
        field, values):
    row = _evidence("MIB-000001")
    _set_composited_values(row, field, values)
    _validate_evidence_rows([row])


@pytest.mark.parametrize(("field", "value", "stale"), [
    ("sponsor_id", "SPN-5678", "SPN-1234"),
    ("visa_class", "DIP-1", "XW-1"),
])
@pytest.mark.parametrize("scenario", [
    "missing_context",
    "stale_manual_context",
    "ordinary_context_claims_authority",
    "wrong_manual_rank",
    "manual_without_composited_value",
    "conflict_retains_context",
])
def test_evidence_rejects_unbound_or_inconsistent_composited_context(
        field, value, stale, scenario):
    row = _evidence("MIB-000001")
    composited = [value]
    context = {}
    if scenario == "stale_manual_context":
        context = {field: [[
            stale, "manual_correction", 1, 99.0, stale]]}
    elif scenario == "ordinary_context_claims_authority":
        context = {field: [[value, "intake", 3, 99.0, value]]}
    elif scenario == "wrong_manual_rank":
        context = {field: [[
            value, "manual_correction", 2, 99.0, value]]}
    elif scenario == "manual_without_composited_value":
        context = {field: [[
            value, "manual_correction", 1, 99.0, value]]}
        composited = []
    elif scenario == "conflict_retains_context":
        context = {field: [[stale, "intake", 3, 95.0, stale]]}
        composited = [value, stale]
    if composited:
        _set_composited_values(row, field, composited)
    row["baseline_batch_context"] = context
    with pytest.raises(ValueError, match=(
            "baseline batch context|composited rank1|manual correction")):
        _validate_evidence_rows([row])


@pytest.mark.parametrize(
    ("field", "value", "source", "rank", "confidence", "raw"), [
        ("sponsor_id", "SPN-1234", "sponsor_letter", 4, 95.0,
         "SPN-1234"),
        ("sponsor_id", "SPN-1234", "letter_label", 2, 95.0,
         "SPN-1234"),
        ("sponsor_id", "SPN-1234", "slip_label", 3, 95.0,
         "SPN-1234"),
        ("sponsor_id", "SPN-1234", "intake", 2, 95.0, "SPN-1234"),
        ("sponsor_id", "SPN-1234", "pixmatch", 6, 95.0, "SPN-1234"),
        ("sponsor_id", "SPN-1234", "manual_correction", 1, 98.0,
         "SPN-1234"),
        ("sponsor_id", "SPN-1234", "manual_correction", 1, 100.0,
         "SPN-1234"),
        ("sponsor_id", "SPN-1234", "manual_correction", 1, 99.0,
         "SPN-5678"),
        ("visa_class", "DIP-1", "sponsor_letter", 4, 95.0, "DIP-1"),
        ("visa_class", "DIP-1", "intake", 2, 95.0, "DIP-1"),
        ("visa_class", "DIP-1", "pixmatch", 6, 95.0, "DIP-1"),
        ("visa_class", "DIP-1", "manual_correction", 1, 98.0, "DIP-1"),
        ("visa_class", "DIP-1", "manual_correction", 1, 99.0, "XW-1"),
        ("arrival_date", "2026-05-01", "intake", 3, 95.0,
         "2026-05-01"),
        ("arrival_date", "2026-05-01", "sponsor_letter", 2, 95.0,
         "2026-05-01"),
        ("arrival_date", "2026-05-01", "letter_label", 2, 95.0,
         "2026-05-01"),
        ("arrival_date", "2026-05-01", "slip_label", 2, 95.0,
         "2026-05-01"),
        ("arrival_date", "2026-05-01", "registry", 4, 95.0,
         "2026-05-01"),
        ("arrival_date", "2026-05-01", "intake_bare", 2, 95.0,
         "2026-05-01"),
        ("arrival_date", "2026-05-01", "pixmatch", 6, 95.0,
         "2026-05-01"),
        ("arrival_date", "2026-05-01", "manual_correction", 1, 99.0,
         "2026-05-01"),
        ("sponsor_id", "SPN-1234", "intake", 3, 0.0, "SPN-1234"),
        ("sponsor_id", "SPN-1234", "adjudicator_note", 1, 0.0,
         "SPN-1234"),
        ("sponsor_id", "SPN-1234", "intake", 3, 88.0, "SPN-1234"),
        ("sponsor_id", "SPN-1234", "intake_bare", 6, 95.0,
         "SPN-1234"),
        ("visa_class", "XW-1", "intake", 3, 0.0, "XW-1"),
        ("visa_class", "XW-1", "intake", 3, 52.0, "XW-1"),
        ("visa_class", "XW-1", "intake_bare", 6, 95.0, "XW-1"),
        ("visa_class", "XW-1", "slip_label", 3, 94.0, "XW-1"),
        ("visa_class", "XW-1", "slip_label", 3, 95.0, "XW-2"),
        ("arrival_date", "2026-05-01", "intake", 2, 0.0,
         "2026-05-01"),
        ("arrival_date", "2026-05-01", "intake", 2, 73.0,
         "2026-05-01"),
        ("arrival_date", "2026-05-01", "intake_bare", 6, 95.0,
         "2026-05-01"),
        ("arrival_date", "2026-05-01", "slip_label", 3, 95.0,
         "2026-05-02"),
    ])
def test_evidence_rejects_producer_impossible_context_provenance(
        field, value, source, rank, confidence, raw):
    row = _evidence("MIB-000001")
    row["baseline_batch_context"] = {
        field: [[value, source, rank, confidence, raw]],
    }
    if source == "manual_correction" and field in {
            "sponsor_id", "visa_class"}:
        _set_composited_values(row, field, [value])
    with pytest.raises(ValueError, match="baseline batch context"):
        _validate_evidence_rows([row])


@pytest.mark.parametrize("context", [
    {"sponsor_id": []},
    {"sponsor_id": [
        ["SPN-1234", "intake", 3, 95.0, "SPN-1234"],
        ["SPN-5678", "intake", 3, 95.0, "SPN-5678"]]},
    {"visa_class": []},
    {"visa_class": [
        ["DIP-1", "intake", 3, 95.0, "DIP-1"],
        ["XW-1", "intake", 3, 95.0, "XW-1"]]},
    {"arrival_date": []},
    {"sponsor_id": [["SPN-12", "intake", 3, 95.0, "SPN-12"]]},
    {"visa_class": [["FAKE-1", "intake", 3, 95.0, "FAKE-1"]]},
    {"sponsor_id": [["SPN-1234", "", 3, 95.0, "SPN-1234"]]},
    {"sponsor_id": [["SPN-1234", "intake", 0, 95.0, "SPN-1234"]]},
    {"sponsor_id": [["SPN-1234", "intake", 999, 95.0, "SPN-1234"]]},
    {"sponsor_id": [["SPN-1234", "bogus", 3, 95.0, "SPN-1234"]]},
    {"sponsor_id": [[
        "SPN-1234", "intake", 3, float("nan"), "SPN-1234"]]},
    {"arrival_date": [[
        "2026-05-01", "intake", 2, float("inf"), "2026-05-01"]]},
    {"arrival_date": [[
        "2026-02-30", "intake", 2, 95.0, "2026-02-30"]]},
    {"arrival_date": [[
        "2026-05-01", "intake", 2, 101.0, "2026-05-01"]]},
    {"arrival_date": [[
        "2026-05-01", "intake", 2, -1.0, "2026-05-01"]]},
    {"arrival_date": [["2026-05-01", "intake", 2, 95.0]]},
    {"arrival_date": [[
        "2026-05-01", "intake", 2, 95.0, "2026-05-01", "extra"]]},
    {"arrival_date": [["2026-05-01", "intake", 2, 95.0, ""]]},
    {"arrival_date": [["2026-05-01", "intake", 2, 95.0, 20260501]]},
])
def test_evidence_rejects_malformed_baseline_batch_context(context):
    row = _evidence("MIB-000001")
    row["baseline_batch_context"] = context
    with pytest.raises(ValueError, match="baseline batch context"):
        _validate_evidence_rows([row])


def _producer(tmp_path):
    # The tool under test binds a clean producer *commit*, so exercising it
    # needs a real repository. git is not part of the runtime (nothing under
    # mib/ shells out to it) and the scoring image does not ship it, so skip
    # rather than fail where it is absent.
    if shutil.which("git") is None:
        pytest.skip("git is required to build the producer-repo fixture")
    repo = tmp_path / "producer"
    repo.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "Binding Test"],
                   cwd=repo, check=True)
    subprocess.run(["git", "config", "user.email", "binding@example.test"],
                   cwd=repo, check=True)
    for repo_path in EXPECTED_RUNTIME_REPO_PATHS:
        runtime_file = repo / repo_path
        runtime_file.parent.mkdir(parents=True, exist_ok=True)
        runtime_file.write_bytes(f"exact runtime bytes for {repo_path}\n".encode())
    subprocess.run(["git", "add", "."], cwd=repo, check=True)
    subprocess.run(["git", "-c", "commit.gpgsign=false", "commit", "-qm",
                    "runtime snapshot"], cwd=repo, check=True)
    sha = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=repo, text=True).strip()
    manifest = tmp_path / "runtime-manifest.json"
    manifest.write_text(json.dumps({
        "schema": "mib-runtime-manifest-v1",
        "producer_git_sha": sha,
        "image_id": IMAGE_ID,
        "image_revision": sha,
        "files": [{
            "repo_path": repo_path,
            "image_path": f"/app/{repo_path}",
            "source_sha256": hashlib.sha256(
                (repo / repo_path).read_bytes()).hexdigest(),
            "image_sha256": hashlib.sha256(
                (repo / repo_path).read_bytes()).hexdigest(),
        } for repo_path in EXPECTED_RUNTIME_REPO_PATHS],
    }, indent=2) + "\n")
    (tmp_path / "image-inspect.json").write_text(json.dumps([{
        "Id": IMAGE_ID,
        "Config": {"Labels": {"org.opencontainers.image.revision": sha}},
    }]) + "\n")
    return repo, sha, manifest


def _inputs(tmp_path, case_ids=("MIB-000001",)):
    directory = tmp_path / "inputs"
    directory.mkdir()
    for case_id in case_ids:
        (directory / f"{case_id}.pdf").write_bytes(
            f"fixed input bytes for {case_id}".encode())
    return directory


def _run_dir(tmp_path, name, split, predictions, evidence):
    directory = tmp_path / name
    directory.mkdir()
    _write_jsonl(directory / f"predictions_{split}.jsonl", predictions)
    _write_jsonl(directory / f"states_{split}.jsonl", evidence)
    return directory


def _write_run_receipt(input_dir, directory, split, config, worker_count,
                       sha, manifest):
    entries = input_manifest(sorted(input_dir.glob("*.pdf")))
    receipt = directory / f"run-receipt-{split}.json"
    effective = canonical_effective_config(config or {}, environment={})
    input_identity = [{key: entry[key] for key in (
        "ordinal", "case_id", "size", "sha256")} for entry in entries]
    config_sha256 = canonical_sha256(effective)
    input_manifest_sha256 = canonical_sha256(input_identity)
    nonce = hashlib.sha256(str(receipt.resolve()).encode()).hexdigest()
    identity = {
        "schema": "mib-run-identity-v1",
        "producer_git_sha": sha,
        "image_id": IMAGE_ID,
        "image_revision": sha,
        "image_inspect_sha256": hashlib.sha256(
            (manifest.parent / "image-inspect.json").read_bytes()).hexdigest(),
        "runtime_manifest_sha256": canonical_sha256(
            json.loads(manifest.read_text())),
        "config_sha256": config_sha256,
        "input_manifest_sha256": input_manifest_sha256,
        "run_split": split,
        "run_nonce": nonce,
    }
    predictions = directory / f"predictions_{split}.jsonl"
    evidence = directory / f"states_{split}.jsonl"
    receipt.write_text(json.dumps({
        "schema": "mib-run-receipt-v2",
        "terminal_status": "completed",
        "run_identity": identity,
        "run_identity_sha256": canonical_sha256(identity),
        "run_split": split,
        "run_nonce": nonce,
        "effective_config": effective,
        "config_sha256": config_sha256,
        "worker_count": worker_count,
        "input_source": {
            "kind": "sorted_pdf_directory",
            "directory_name": input_dir.name,
        },
        "input_manifest": [{
            "ordinal": entry["ordinal"],
            "case_id": entry["case_id"],
            "filename": Path(entry["path"]).name,
            "size": entry["size"],
            "sha256": entry["sha256"],
        } for entry in entries],
        "input_manifest_sha256": input_manifest_sha256,
        "artifacts": {
            "predictions": {
                "filename": predictions.name,
                "size": predictions.stat().st_size,
                "sha256": hashlib.sha256(predictions.read_bytes()).hexdigest(),
            },
            "evidence": {
                "filename": evidence.name,
                "size": evidence.stat().st_size,
                "sha256": hashlib.sha256(evidence.read_bytes()).hexdigest(),
            },
        },
    }, indent=2) + "\n")
    return receipt


def _binding_command(repo, sha, manifest, input_dir, directory, split,
                     config=None, output=None, image_revision=None,
                     worker_count=1, receipt=None):
    output = output or directory / f"binding_{split}.json"
    receipt = receipt or _write_run_receipt(
        input_dir, directory, split, config, worker_count, sha, manifest)
    return [
        sys.executable, str(BIND), "--repo", str(repo),
        "--producer-sha", sha, "--image-id", IMAGE_ID,
        "--image-revision", image_revision or sha,
        "--image-inspect", str(manifest.parent / "image-inspect.json"),
        "--runtime-manifest", str(manifest),
        "--run-receipt", str(receipt),
        "--split", split,
        "--effective-config-json", json.dumps(config or {}, sort_keys=True),
        "--input-dir", str(input_dir),
        "--artifact", f"predictions={directory / f'predictions_{split}.jsonl'}",
        "--artifact", f"evidence={directory / f'states_{split}.jsonl'}",
        "--output", str(output),
    ]


def _build_binding(repo, sha, manifest, input_dir, directory, split,
                   config=None, output=None, worker_count=1):
    output = output or directory / f"binding_{split}.json"
    result = _run(_binding_command(
        repo, sha, manifest, input_dir, directory, split, config, output,
        worker_count=worker_count))
    assert result.returncode == 0, result.stderr
    return output


def _labels(path, rows):
    with path.open("w", newline="") as handle:
        writer = csv.DictWriter(
            handle, fieldnames=("case_id", *FIELDS, "adjudication"))
        writer.writeheader()
        writer.writerows(rows)
    return path


def _spec(path, mode, split, base_binding, variant_binding, labels=None):
    payload = {
        "schema": "mib-native-audit-spec-v2",
        "mode": mode,
        "split": split,
        "base": binding_identity(verify_binding(base_binding)),
        "variant": binding_identity(verify_binding(variant_binding)),
    }
    if mode == "scored":
        payload["labels_sha256"] = hashlib.sha256(labels.read_bytes()).hexdigest()
    path.write_text(json.dumps(payload, indent=2) + "\n")
    return path


def _audit_command(base_dir, variant_dir, split, output, base_binding,
                   variant_binding, spec, mode="scored", labels=None):
    command = [
        sys.executable, str(AUDIT), "--base-dir", str(base_dir),
        "--variant-dir", str(variant_dir), "--mode", mode,
        "--split", split, "--output", str(output),
        "--base-binding", str(base_binding),
        "--variant-binding", str(variant_binding),
        "--binding-spec", str(spec),
    ]
    if labels:
        command.extend(("--labels", str(labels)))
    return command


def _paired_fixture(tmp_path, split="dev", base_decision="NEEDS_REVIEW",
                    variant_decision="NEEDS_REVIEW", truth_decision="NEEDS_REVIEW",
                    base_evidence=None, variant_evidence=None):
    repo, sha, manifest = _producer(tmp_path)
    inputs = _inputs(tmp_path)
    case_id = "MIB-000001"
    base_pred = _prediction(case_id, base_decision)
    variant_pred = _prediction(case_id, variant_decision)
    base_dir = _run_dir(
        tmp_path, "base", split, [base_pred],
        [base_evidence or _evidence(case_id, adjudication=base_decision)])
    variant_dir = _run_dir(
        tmp_path, "variant", split, [variant_pred],
        [variant_evidence or _evidence(case_id, adjudication=variant_decision)])
    base_binding = _build_binding(
        repo, sha, manifest, inputs, base_dir, split,
        {"MIB_NATIVE_SCAN_OCR": "0"})
    variant_binding = _build_binding(
        repo, sha, manifest, inputs, variant_dir, split,
        {"MIB_NATIVE_SCAN_OCR": "1"})
    labels = None
    if split != "validation":
        labels = _labels(tmp_path / "labels.csv", [
            {**_prediction(case_id, truth_decision)}])
    return (repo, sha, manifest, inputs, base_dir, variant_dir,
            base_binding, variant_binding, labels)


def test_binding_canonicalizes_config_and_rejects_output_or_input_drift(tmp_path):
    repo, sha, manifest = _producer(tmp_path)
    inputs = _inputs(tmp_path)
    directory = _run_dir(
        tmp_path, "run", "dev", [_prediction("MIB-000001")],
        [_evidence("MIB-000001")])
    binding_path = _build_binding(
        repo, sha, manifest, inputs, directory, "dev",
        {"MIB_NATIVE_SCAN_OCR": "1"})
    binding = verify_binding(binding_path)
    assert binding["schema"] == SCHEMA
    assert binding["image_revision"] == sha
    assert binding["effective_config"]["MIB_NATIVE_SCAN_OCR"] == "1"
    assert binding["effective_config"]["MIB_MAX_RETRY_CASES"] == "8"
    assert binding["effective_config"]["MIB_CASE_TIMEOUT"] == "120"
    assert binding["effective_config"]["MIB_RETRY_CASE_TIMEOUT"] == "130"
    assert binding["effective_config"]["MIB_RETRY_BUDGET_SECS"] == "1100"
    assert binding["effective_config"]["MIB_STUCK_SECS"] == "150"
    assert EFFECTIVE_CONFIG_DEFAULTS["MIB_RETRY_BUDGET_SECS"] == "1100"
    assert binding["run_split"] == "dev"
    assert len(binding["run_nonce"]) == 64
    assert binding["image_inspect_sha256"] == binding["image_inspect"]["sha256"]
    assert binding["config_sha256"] == canonical_sha256(
        binding["effective_config"])
    assert binding_identity(binding)["binding_sha256"] == \
        binding["binding_sha256"]

    predictions = directory / "predictions_dev.jsonl"
    original = predictions.read_text()
    predictions.write_text(original + "\n")
    with pytest.raises(ValueError, match="artifact predictions hash/size mismatch"):
        verify_binding(binding_path)
    predictions.write_text(original)
    (inputs / "MIB-000001.pdf").write_bytes(b"changed input bytes")
    with pytest.raises(ValueError, match="live input PDF manifest"):
        verify_binding(binding_path)


def test_preflight_generator_binds_exact_run_identity_and_refuses_overwrite(
        tmp_path):
    repo, sha, manifest = _producer(tmp_path)
    inputs = _inputs(tmp_path)
    output = tmp_path / "run-identity.json"
    nonce = "d" * 64
    command = [
        sys.executable, str(PREPARE_IDENTITY), "--repo", str(repo),
        "--producer-sha", sha, "--image-id", IMAGE_ID,
        "--image-inspect", str(manifest.parent / "image-inspect.json"),
        "--runtime-manifest", str(manifest),
        "--effective-config-json", json.dumps({
            "MIB_NATIVE_SCAN_OCR": "1"}),
        "--input-dir", str(inputs), "--split", "dev",
        "--run-nonce", nonce, "--output", str(output),
    ]
    result = _run(command)
    assert result.returncode == 0, result.stderr
    identity = json.loads(output.read_text())
    entries = input_manifest(sorted(inputs.glob("*.pdf")))
    assert identity == {
        "schema": "mib-run-identity-v1",
        "producer_git_sha": sha,
        "image_id": IMAGE_ID,
        "image_revision": sha,
        "image_inspect_sha256": hashlib.sha256(
            (manifest.parent / "image-inspect.json").read_bytes()).hexdigest(),
        "runtime_manifest_sha256": canonical_sha256(
            json.loads(manifest.read_text())),
        "config_sha256": canonical_sha256(canonical_effective_config(
            {"MIB_NATIVE_SCAN_OCR": "1"}, environment={})),
        "input_manifest_sha256": canonical_sha256([
            {key: entry[key] for key in (
                "ordinal", "case_id", "size", "sha256")}
            for entry in entries]),
        "run_split": "dev",
        "run_nonce": nonce,
    }
    result = _run(command)
    assert result.returncode != 0
    assert "refusing to overwrite" in result.stderr


def test_preflight_generator_binds_exact_md5_partition(tmp_path):
    repo, sha, manifest = _producer(tmp_path)
    inputs = tmp_path / "train"
    inputs.mkdir()
    for ordinal in range(1, 30):
        (inputs / f"MIB-{ordinal:06d}.pdf").write_bytes(
            f"pdf bytes {ordinal}".encode())
    selected = [
        path for path in sorted(inputs.glob("*.pdf"))
        if int(hashlib.md5(path.stem.encode()).hexdigest(), 16) % 5 != 0
    ]
    assert selected
    assert len(selected) < len(list(inputs.glob("*.pdf")))

    output = tmp_path / "dev-run-identity.json"
    command = [
        sys.executable, str(PREPARE_IDENTITY), "--repo", str(repo),
        "--producer-sha", sha, "--image-id", IMAGE_ID,
        "--image-inspect", str(manifest.parent / "image-inspect.json"),
        "--runtime-manifest", str(manifest),
        "--effective-config-json", json.dumps({
            "MIB_NATIVE_SCAN_OCR": "1"}),
        "--input-dir", str(inputs), "--split", "dev",
        "--partition", "dev-md5", "--run-nonce", "e" * 64,
        "--output", str(output),
    ]
    result = _run(command)
    assert result.returncode == 0, result.stderr
    identity = json.loads(output.read_text())
    entries = input_manifest(selected)
    assert identity["input_manifest_sha256"] == canonical_sha256([
        {key: entry[key] for key in (
            "ordinal", "case_id", "size", "sha256")}
        for entry in entries
    ])

    mismatch = list(command)
    mismatch[mismatch.index("dev-md5")] = "holdout-md5"
    mismatch[mismatch.index(str(output))] = str(
        tmp_path / "mismatch-run-identity.json")
    result = _run(mismatch)
    assert result.returncode != 0
    assert "split and partition disagree" in result.stderr


def test_binding_rejects_dirty_producer_bad_revision_and_runtime_manifest(tmp_path):
    repo, sha, manifest = _producer(tmp_path)
    inputs = _inputs(tmp_path)
    directory = _run_dir(
        tmp_path, "run", "dev", [_prediction("MIB-000001")],
        [_evidence("MIB-000001")])

    (repo / "untracked.txt").write_text("dirty\n")
    result = _run(_binding_command(
        repo, sha, manifest, inputs, directory, "dev"))
    assert result.returncode != 0
    assert "producer repository is dirty" in result.stderr
    (repo / "untracked.txt").unlink()

    result = _run(_binding_command(
        repo, sha, manifest, inputs, directory, "dev",
        image_revision="f" * 40))
    assert result.returncode != 0
    assert "image revision must equal producer SHA" in result.stderr

    bad = json.loads(manifest.read_text())
    bad["files"][0]["image_sha256"] = "b" * 64
    bad_manifest = tmp_path / "bad-runtime-manifest.json"
    bad_manifest.write_text(json.dumps(bad))
    result = _run(_binding_command(
        repo, sha, bad_manifest, inputs, directory, "dev"))
    assert result.returncode != 0
    assert "runtime image file differs" in result.stderr


@pytest.mark.parametrize("field,replacement,error", [
    ("producer_git_sha", "f" * 40,
     "run identity image revision must equal producer SHA"),
    ("config_sha256", "b" * 64,
     "run receipt producer identity differs"),
    ("input_manifest_sha256", "c" * 64,
     "run receipt producer identity differs"),
])
def test_binding_rejects_rewritten_producer_receipt_identity(
        tmp_path, field, replacement, error):
    repo, sha, manifest = _producer(tmp_path)
    inputs = _inputs(tmp_path)
    directory = _run_dir(
        tmp_path, "run", "dev", [_prediction("MIB-000001")],
        [_evidence("MIB-000001")])
    command = _binding_command(
        repo, sha, manifest, inputs, directory, "dev")
    receipt = directory / "run-receipt-dev.json"
    payload = json.loads(receipt.read_text())
    payload["run_identity"][field] = replacement
    payload["run_identity_sha256"] = canonical_sha256(
        payload["run_identity"])
    receipt.write_text(json.dumps(payload))
    result = _run(command)
    assert result.returncode != 0
    assert error in result.stderr


@pytest.mark.parametrize(("mutation", "error"), [
    (lambda receipt: receipt.update(terminal_status="running"),
     "does not prove completed artifact production"),
    (lambda receipt: receipt["artifacts"]["predictions"].update(
        sha256="b" * 64),
     "artifact predictions hash/size differs from bound output"),
    (lambda receipt: receipt["artifacts"]["evidence"].update(
        size=receipt["artifacts"]["evidence"]["size"] + 1),
     "artifact evidence hash/size differs from bound output"),
    (lambda receipt: receipt["artifacts"]["predictions"].update(
        path="predictions_dev.jsonl"),
     "artifact predictions record is malformed"),
])
def test_binding_rejects_nonterminal_or_drifted_completion_receipt(
        tmp_path, mutation, error):
    repo, sha, manifest = _producer(tmp_path)
    inputs = _inputs(tmp_path)
    directory = _run_dir(
        tmp_path, "run", "dev", [_prediction("MIB-000001")],
        [_evidence("MIB-000001")])
    command = _binding_command(
        repo, sha, manifest, inputs, directory, "dev")
    receipt_path = directory / "run-receipt-dev.json"
    receipt = json.loads(receipt_path.read_text())
    mutation(receipt)
    receipt_path.write_text(json.dumps(receipt))

    result = _run(command)
    assert result.returncode != 0
    assert error in result.stderr


def test_binding_identity_commits_to_whole_binding_and_validates_hash_format(
        tmp_path):
    repo, sha, manifest = _producer(tmp_path)
    inputs = _inputs(tmp_path)
    directory = _run_dir(
        tmp_path, "run", "dev", [_prediction("MIB-000001")],
        [_evidence("MIB-000001")])
    binding_path = _build_binding(
        repo, sha, manifest, inputs, directory, "dev")
    binding = verify_binding(binding_path)
    expected = binding_identity(binding)
    expected["binding_sha256"] = (
        "e" * 64 if binding["binding_sha256"] == "f" * 64 else "f" * 64)
    with pytest.raises(ValueError, match="predeclared spec"):
        verify_binding(binding_path, expected)

    expected["binding_sha256"] = "not-a-sha256"
    with pytest.raises(ValueError, match="binding_sha256 is malformed"):
        verify_binding(binding_path, expected)


def test_actual_producer_completion_receipt_binds_without_running_ocr(
        tmp_path, monkeypatch):
    """Exercise the real producer receipt helpers, but no workers or OCR."""
    pipeline_stub = types.ModuleType("mib.pipeline")
    pipeline_stub.FALLBACKS = {}
    pipeline_stub.batch_epoch = lambda states: None
    pipeline_stub.batch_frequent_sponsors = lambda states: frozenset()
    pipeline_stub.decide = lambda *args, **kwargs: ({}, {})
    monkeypatch.setitem(sys.modules, "mib.pipeline", pipeline_stub)
    spec = importlib.util.spec_from_file_location(
        "mib_predict_receipt_contract", ROOT / "scripts" / "predict.py")
    producer = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(producer)

    for key in list(os.environ):
        if key.startswith("MIB_"):
            monkeypatch.delenv(key, raising=False)
    for key in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS"):
        monkeypatch.setenv(key, "1")

    repo, sha, manifest = _producer(tmp_path)
    inputs = _inputs(tmp_path)
    entries = input_manifest(sorted(inputs.glob("*.pdf")))
    effective = canonical_effective_config({}, environment={})
    input_identity = [{key: entry[key] for key in (
        "ordinal", "case_id", "size", "sha256")} for entry in entries]
    identity = {
        "schema": "mib-run-identity-v1",
        "producer_git_sha": sha,
        "image_id": IMAGE_ID,
        "image_revision": sha,
        "image_inspect_sha256": hashlib.sha256(
            (manifest.parent / "image-inspect.json").read_bytes()).hexdigest(),
        "runtime_manifest_sha256": canonical_sha256(
            json.loads(manifest.read_text())),
        "config_sha256": canonical_sha256(effective),
        "input_manifest_sha256": canonical_sha256(input_identity),
        "run_split": "dev",
        "run_nonce": "9" * 64,
    }
    identity_path = tmp_path / "run-identity.json"
    identity_path.write_text(json.dumps(identity))

    directory = tmp_path / "actual-producer-run"
    predictions = directory / "predictions_dev.jsonl"
    evidence = directory / "states_dev.jsonl"
    receipt = directory / "run-receipt-dev.json"
    prepared = producer._prepare_run_receipt(
        receipt, identity_path, inputs,
        [str(path) for path in sorted(inputs.glob("*.pdf"))],
        predictions, evidence, 1, "dev")
    assert directory.is_dir()
    assert not receipt.exists()
    _write_jsonl(predictions, [_prediction("MIB-000001")])
    _write_jsonl(evidence, [_evidence("MIB-000001")])
    producer._publish_run_receipt(prepared)

    binding_path = directory / "binding_dev.json"
    result = _run(_binding_command(
        repo, sha, manifest, inputs, directory, "dev",
        output=binding_path, receipt=receipt))
    assert result.returncode == 0, result.stderr
    binding = verify_binding(binding_path)
    assert binding["run_nonce"] == identity["run_nonce"]
    assert binding["run_receipt_sha256"] == hashlib.sha256(
        receipt.read_bytes()).hexdigest()


@pytest.mark.parametrize("environment,error", [
    ({"MIB_TEST_HANG_CASE": "MIB-000001"}, "test/injection environment"),
    ({"MIB_UNKNOWN_SWITCH": "1"}, "unknown MIB environment"),
    ({"MIB_NATIVE_SCAN_OCR": "1"}, "claimed config differs"),
])
def test_binding_rejects_injection_unknown_or_mismatched_live_env(
        tmp_path, environment, error):
    del tmp_path
    with pytest.raises(ValueError, match=error):
        canonical_effective_config(
            {"MIB_NATIVE_SCAN_OCR": "0"}, environment=environment)


def test_binding_rejects_duplicate_or_extra_output_ids_and_overwrite(tmp_path):
    repo, sha, manifest = _producer(tmp_path)
    inputs = _inputs(tmp_path)
    duplicate = _run_dir(
        tmp_path, "duplicate", "dev",
        [_prediction("MIB-000001"), _prediction("MIB-000001")],
        [_evidence("MIB-000001"), _evidence("MIB-000001")])
    result = _run(_binding_command(
        repo, sha, manifest, inputs, duplicate, "dev"))
    assert result.returncode != 0
    assert "duplicate case_id" in result.stderr

    valid = _run_dir(
        tmp_path, "valid", "dev", [_prediction("MIB-000001")],
        [_evidence("MIB-000001")])
    binding = _build_binding(repo, sha, manifest, inputs, valid, "dev")
    result = _run(_binding_command(
        repo, sha, manifest, inputs, valid, "dev", output=binding))
    assert result.returncode != 0
    assert "refusing to overwrite" in result.stderr


@pytest.mark.parametrize(("mutation", "message"), [
    (lambda extraction: extraction.update(attempt_count=7),
     "attempt count is inconsistent"),
    (lambda extraction: extraction.update(recovered=True),
     "recovery flag is inconsistent"),
    (lambda extraction: extraction["attempts"][0].update(status="maybe"),
     "attempt status is malformed"),
    (lambda extraction: extraction["attempts"][0].update(
        status="not_attempted", failure_category="not_started"),
     "first extraction attempt cannot be not_attempted"),
    (lambda extraction: extraction.update(
        attempts=[{"attempt": 1, "status": "success"},
                  {"attempt": 2, "status": "success"}],
        attempt_count=2),
     "second extraction attempt requires a failed first attempt"),
    (lambda extraction: extraction["attempts"][0].update(error="impossible"),
     "successful extraction attempt has error"),
])
def test_binding_rejects_malformed_retry_provenance(
        tmp_path, mutation, message):
    repo, sha, manifest = _producer(tmp_path)
    inputs = _inputs(tmp_path)
    evidence = _evidence("MIB-000001")
    mutation(evidence["extraction"])
    directory = _run_dir(
        tmp_path, "malformed-attempts", "dev",
        [_prediction("MIB-000001")], [evidence])
    result = _run(_binding_command(
        repo, sha, manifest, inputs, directory, "dev"))
    assert result.returncode != 0
    assert message in result.stderr


def test_scored_audit_accepts_truth_correct_approval_and_embeds_exact_hashes(tmp_path):
    (*_, base_dir, variant_dir, base_binding, variant_binding,
     labels) = _paired_fixture(
         tmp_path, base_decision="NEEDS_REVIEW", variant_decision="APPROVED",
         truth_decision="APPROVED")
    spec = _spec(
        tmp_path / "spec.json", "scored", "dev", base_binding,
        variant_binding, labels)
    output = tmp_path / "report.json"
    result = _run(_audit_command(
        base_dir, variant_dir, "dev", output, base_binding,
        variant_binding, spec, labels=labels))
    assert result.returncode == 0, result.stderr
    report = json.loads(output.read_text())
    assert report["promotion_eligible"] is True
    assert report["gate_order"][0] == "zero_new_false_approvals"
    assert report["gates"]["zero_new_false_approvals"]["passed"] is True
    assert [row["case_id"] for row in report["approved_decision_changes"]] == \
        ["MIB-000001"]
    assert report["artifact_binding"]["base"]["binding_file_sha256"] == \
        hashlib.sha256(base_binding.read_bytes()).hexdigest()
    assert report["artifact_binding"]["variant"]["artifacts"][
        "predictions"]["sha256"] == verify_binding(variant_binding)[
            "artifacts"]["predictions"]["sha256"]


def test_scored_audit_writes_report_and_fails_on_new_false_approval(tmp_path):
    (*_, base_dir, variant_dir, base_binding, variant_binding,
     labels) = _paired_fixture(
         tmp_path, base_decision="NEEDS_REVIEW", variant_decision="APPROVED",
         truth_decision="DENIED")
    spec = _spec(
        tmp_path / "spec.json", "scored", "dev", base_binding,
        variant_binding, labels)
    output = tmp_path / "unsafe-report.json"
    result = _run(_audit_command(
        base_dir, variant_dir, "dev", output, base_binding,
        variant_binding, spec, labels=labels))
    assert result.returncode != 0
    report = json.loads(output.read_text())
    assert report["promotion_eligible"] is False
    assert report["gates"]["zero_new_false_approvals"] == {
        "passed": False,
        "base_false_approval_case_ids": [],
        "variant_false_approval_case_ids": ["MIB-000001"],
        "new_false_approval_case_ids": ["MIB-000001"],
    }


def test_scored_audit_fails_on_execution_failure_and_preserves_negative_row(tmp_path):
    case_id = "MIB-000001"
    (*_, base_dir, variant_dir, base_binding, variant_binding,
     labels) = _paired_fixture(
         tmp_path, variant_decision="APPROVED",
         variant_evidence=_evidence(
             case_id, error="ONNXRuntimeError(session failure)",
             adjudication="APPROVED"))
    spec = _spec(
        tmp_path / "spec.json", "scored", "dev", base_binding,
        variant_binding, labels)
    output = tmp_path / "failure-report.json"
    result = _run(_audit_command(
        base_dir, variant_dir, "dev", output, base_binding,
        variant_binding, spec, labels=labels))
    assert result.returncode != 0
    report = json.loads(output.read_text())
    assert report["gates"]["zero_execution_failures"]["passed"] is False
    assert report["failures"][0]["variant_error"].startswith("ONNXRuntimeError")
    assert report["variant_failure_census"] == {"ONNXRuntimeError": 1}
    assert report["approved_decision_changes"][0]["case_id"] == case_id


def test_scored_audit_reads_final_structured_attempt_status(tmp_path):
    case_id = "MIB-000001"
    failed = _evidence(case_id, attempts=[{
        "attempt": 1, "status": "failed",
        "failure_category": "recognizer_session_error",
    }])
    (*_, base_dir, variant_dir, base_binding, variant_binding,
     labels) = _paired_fixture(tmp_path, variant_evidence=failed)
    spec = _spec(
        tmp_path / "spec.json", "scored", "dev", base_binding,
        variant_binding, labels)
    output = tmp_path / "structured-failure-report.json"
    result = _run(_audit_command(
        base_dir, variant_dir, "dev", output, base_binding,
        variant_binding, spec, labels=labels))
    assert result.returncode != 0
    report = json.loads(output.read_text())
    assert report["gates"]["zero_execution_failures"]["passed"] is False
    assert report["failures"][0]["variant_error"] == \
        "recognizer_session_error"


def test_scored_audit_accepts_primary_failure_recovered_by_final_attempt(tmp_path):
    case_id = "MIB-000001"
    recovered = _evidence(case_id, attempts=[
        {"attempt": 1, "status": "failed",
         "failure_category": "recognizer_session_error"},
        {"attempt": 2, "status": "success"},
    ])
    (*_, base_dir, variant_dir, base_binding, variant_binding,
     labels) = _paired_fixture(tmp_path, variant_evidence=recovered)
    spec = _spec(
        tmp_path / "spec.json", "scored", "dev", base_binding,
        variant_binding, labels)
    output = tmp_path / "recovered-report.json"
    result = _run(_audit_command(
        base_dir, variant_dir, "dev", output, base_binding,
        variant_binding, spec, labels=labels))
    assert result.returncode == 0, result.stderr
    report = json.loads(output.read_text())
    assert report["gates"]["zero_execution_failures"]["passed"] is True
    assert report["failures"] == []


def test_scored_audit_automatically_gates_lost_baseline_rank1_payload(tmp_path):
    case_id = "MIB-000001"
    (*_, base_dir, variant_dir, base_binding, variant_binding,
     labels) = _paired_fixture(
         tmp_path,
         base_evidence=_evidence(case_id, finding="NEEDS_REVIEW"),
         variant_evidence=_evidence(case_id))
    spec = _spec(
        tmp_path / "spec.json", "scored", "dev", base_binding,
        variant_binding, labels)
    output = tmp_path / "note-loss-report.json"
    result = _run(_audit_command(
        base_dir, variant_dir, "dev", output, base_binding,
        variant_binding, spec, labels=labels))
    assert result.returncode != 0
    report = json.loads(output.read_text())
    assert report["gates"]["baseline_rank1_noninferiority"] == {
        "passed": False, "lost_case_ids": [case_id]}


def test_native_substitute_cannot_conceal_composited_rank1_loss(tmp_path):
    case_id = "MIB-000001"
    base = _evidence(case_id, finding="NEEDS_REVIEW")
    variant = _evidence(case_id, finding="NEEDS_REVIEW")
    variant["composited_rank1_payload"] = {
        "values": {}, "conflicts": [], "evidence": {}}
    (*_, base_dir, variant_dir, base_binding, variant_binding,
     labels) = _paired_fixture(
         tmp_path, base_evidence=base, variant_evidence=variant)
    spec = _spec(
        tmp_path / "spec.json", "scored", "dev", base_binding,
        variant_binding, labels)
    output = tmp_path / "native-substitute.json"
    result = _run(_audit_command(
        base_dir, variant_dir, "dev", output, base_binding,
        variant_binding, spec, labels=labels))
    assert result.returncode != 0
    report = json.loads(output.read_text())
    assert report["rank1_payload_changes"] == []
    assert report["gates"]["baseline_rank1_noninferiority"] == {
        "passed": False, "lost_case_ids": [case_id]}
    assert report["lost_baseline_rank1_payloads"][0]["missing"] == {
        "finding": "NEEDS_REVIEW"}


def test_same_composited_value_cannot_conceal_origin_loss(tmp_path):
    case_id = "MIB-000001"
    base = _evidence(case_id, finding="NEEDS_REVIEW")
    variant = _evidence(case_id, finding="NEEDS_REVIEW")
    variant["composited_rank1_payload"]["evidence"]["finding"][0][
        "origin"]["page"] = 1
    (*_, base_dir, variant_dir, base_binding, variant_binding,
     labels) = _paired_fixture(
         tmp_path, base_evidence=base, variant_evidence=variant)
    spec = _spec(
        tmp_path / "spec.json", "scored", "dev", base_binding,
        variant_binding, labels)
    output = tmp_path / "origin-loss.json"
    result = _run(_audit_command(
        base_dir, variant_dir, "dev", output, base_binding,
        variant_binding, spec, labels=labels))
    assert result.returncode != 0
    report = json.loads(output.read_text())
    assert report["gates"]["baseline_rank1_noninferiority"] == {
        "passed": False, "lost_case_ids": [case_id]}
    assert report["lost_baseline_rank1_payloads"][0]["missing"] == {
        "origin:finding:NEEDS_REVIEW": [{
            "page": 0, "view": "masked_pdf_render",
            "dpi": 150, "pass": "fast"}]}


def test_scored_audit_gates_rank1_loss_even_when_conflict_forces_review(tmp_path):
    case_id = "MIB-000001"
    (*_, base_dir, variant_dir, base_binding, variant_binding,
     labels) = _paired_fixture(
         tmp_path,
         base_evidence=_evidence(case_id, finding="NEEDS_REVIEW"),
         variant_evidence=_evidence(
             case_id, conflicts=["finding_vs_signed_evidence"]))
    spec = _spec(
        tmp_path / "spec.json", "scored", "dev", base_binding,
        variant_binding, labels)
    output = tmp_path / "conflict-note-loss-report.json"
    result = _run(_audit_command(
        base_dir, variant_dir, "dev", output, base_binding,
        variant_binding, spec, labels=labels))
    assert result.returncode != 0
    report = json.loads(output.read_text())
    assert report["gates"]["baseline_rank1_noninferiority"] == {
        "passed": False, "lost_case_ids": [case_id]}
    assert report["lost_baseline_rank1_payloads"] == [{
        "case_id": case_id,
        "base": {"finding": "NEEDS_REVIEW", "fields": {}},
        "variant": {"fields": {}},
        "missing": {"finding": "NEEDS_REVIEW"},
        "conflict_forced_review": True,
    }]
    assert report["gates"]["zero_new_rank1_conflicts"] == {
        "passed": False, "new_conflict_case_ids": [case_id]}


def test_scored_audit_gates_signed_field_loss_but_allows_additive_rank1(tmp_path):
    case_id = "MIB-000001"
    base = _evidence(case_id, rank1_fields={"fee_status": "paid"})
    variant = _evidence(case_id)
    (*_, base_dir, variant_dir, base_binding, variant_binding,
     labels) = _paired_fixture(
         tmp_path, base_evidence=base, variant_evidence=variant)
    spec = _spec(
        tmp_path / "spec.json", "scored", "dev", base_binding,
        variant_binding, labels)
    loss_output = tmp_path / "signed-field-loss.json"
    result = _run(_audit_command(
        base_dir, variant_dir, "dev", loss_output, base_binding,
        variant_binding, spec, labels=labels))
    assert result.returncode != 0
    report = json.loads(loss_output.read_text())
    assert report["lost_baseline_rank1_payloads"][0]["missing"] == {
        "field:fee_status": "paid"}

    additive_tmp = tmp_path / "additive"
    additive_tmp.mkdir()
    base2 = _evidence(case_id, rank1_fields={"fee_status": "paid"})
    variant2 = _evidence(
        case_id, rank1_fields={"fee_status": "paid", "risk_flags": "none"})
    (*_, base_dir2, variant_dir2, base_binding2, variant_binding2,
     labels2) = _paired_fixture(
         additive_tmp, base_evidence=base2, variant_evidence=variant2)
    spec2 = _spec(
        additive_tmp / "spec.json", "scored", "dev", base_binding2,
        variant_binding2, labels2)
    additive_output = additive_tmp / "additive-report.json"
    result = _run(_audit_command(
        base_dir2, variant_dir2, "dev", additive_output, base_binding2,
        variant_binding2, spec2, labels=labels2))
    assert result.returncode == 0, result.stderr
    assert json.loads(additive_output.read_text())[
        "gates"]["baseline_rank1_noninferiority"]["passed"] is True


@pytest.mark.parametrize(("variant_decision", "forces_review"), [
    ("NEEDS_REVIEW", True),
    ("APPROVED", False),
])
def test_scored_audit_blocks_every_new_rank1_conflict(
        tmp_path, variant_decision, forces_review):
    case_id = "MIB-000001"
    (*_, base_dir, variant_dir, base_binding, variant_binding,
     labels) = _paired_fixture(
         tmp_path, variant_decision=variant_decision,
         truth_decision=variant_decision,
         variant_evidence=_evidence(
             case_id, adjudication=variant_decision,
             conflicts=["finding_vs_signed_evidence"]))
    spec = _spec(
        tmp_path / "spec.json", "scored", "dev", base_binding,
        variant_binding, labels)
    output = tmp_path / "new-conflict-report.json"
    result = _run(_audit_command(
        base_dir, variant_dir, "dev", output, base_binding,
        variant_binding, spec, labels=labels))
    assert result.returncode != 0
    report = json.loads(output.read_text())
    assert report["gates"]["zero_new_rank1_conflicts"] == {
        "passed": False, "new_conflict_case_ids": [case_id]}
    assert report["gates"]["rank1_conflicts_force_review"]["passed"] is \
        forces_review


def test_binding_accepts_explicit_semantic_rank1_conflict(tmp_path):
    repo, sha, manifest = _producer(tmp_path)
    inputs = _inputs(tmp_path)
    case_id = "MIB-000001"
    directory = _run_dir(
        tmp_path, "semantic-conflict", "dev", [_prediction(case_id)],
        [_evidence(case_id, conflicts=["finding_vs_signed_evidence"])])
    binding_path = _build_binding(
        repo, sha, manifest, inputs, directory, "dev")
    assert verify_binding(binding_path)["output_case_count"] == 1


def test_validation_audit_only_forbids_labels_and_emits_no_truth_or_gate_claims(
        tmp_path):
    (*_, base_dir, variant_dir, base_binding, variant_binding,
     _) = _paired_fixture(
         tmp_path, split="validation", base_decision="NEEDS_REVIEW",
         variant_decision="APPROVED")
    spec = _spec(
        tmp_path / "validation-spec.json", "audit-only", "validation",
        base_binding, variant_binding)
    output = tmp_path / "validation-audit.json"
    result = _run(_audit_command(
        base_dir, variant_dir, "validation", output, base_binding,
        variant_binding, spec, mode="audit-only"))
    assert result.returncode == 0, result.stderr
    report = json.loads(output.read_text())
    assert report["artifact_class"] == "unlabeled_validation_audit_only"
    assert report["labels_used"] is False
    assert report["promotion_eligible"] is False
    assert "gates" not in report
    assert "truth" not in output.read_text()

    labels = _labels(tmp_path / "forbidden-labels.csv", [
        _prediction("MIB-000001", "APPROVED")])
    forbidden_output = tmp_path / "forbidden.json"
    result = _run(_audit_command(
        base_dir, variant_dir, "validation", forbidden_output, base_binding,
        variant_binding, spec, mode="audit-only", labels=labels))
    assert result.returncode != 0
    assert "forbids --labels" in result.stderr
    assert not forbidden_output.exists()

    finding_output = tmp_path / "forbidden-finding.json"
    command = _audit_command(
        base_dir, variant_dir, "validation", finding_output, base_binding,
        variant_binding, spec, mode="audit-only")
    command.extend(("--require-finding", "MIB-000001=APPROVED"))
    result = _run(command)
    assert result.returncode != 0
    assert "forbids case-specific finding gates" in result.stderr
    assert not finding_output.exists()


def test_validation_audit_exposes_conflict_without_review_without_labels(
        tmp_path):
    case_id = "MIB-000001"
    (*_, base_dir, variant_dir, base_binding, variant_binding,
     _) = _paired_fixture(
         tmp_path, split="validation", variant_decision="APPROVED",
         variant_evidence=_evidence(
             case_id, conflicts=["finding_vs_signed_evidence"],
             adjudication="APPROVED"))
    spec = _spec(
        tmp_path / "validation-spec.json", "audit-only", "validation",
        base_binding, variant_binding)
    output = tmp_path / "validation-conflict.json"
    result = _run(_audit_command(
        base_dir, variant_dir, "validation", output, base_binding,
        variant_binding, spec, mode="audit-only"))
    assert result.returncode == 0, result.stderr
    report = json.loads(output.read_text())
    assert report["unsafe_rank1_conflict_case_ids"] == [case_id]
    assert "gates" not in report


def test_audit_rejects_binding_split_relabel(tmp_path):
    (*_, base_dir, variant_dir, base_binding, variant_binding,
     labels) = _paired_fixture(tmp_path, split="dev")
    spec = _spec(
        tmp_path / "relabel-spec.json", "scored", "holdout",
        base_binding, variant_binding, labels)
    output = tmp_path / "relabel-report.json"
    result = _run(_audit_command(
        base_dir, variant_dir, "holdout", output, base_binding,
        variant_binding, spec, labels=labels))
    assert result.returncode != 0
    assert "bound run split differs from audit split" in result.stderr
    assert not output.exists()


def test_audit_rejects_unequal_workers_and_requires_complete_identity(
        tmp_path):
    repo, sha, manifest = _producer(tmp_path)
    case_ids = tuple(f"MIB-{number:06d}" for number in range(1, 6))
    inputs = _inputs(tmp_path, case_ids)
    base_dir = _run_dir(
        tmp_path, "base", "dev", [_prediction(case_id) for case_id in case_ids],
        [_evidence(case_id) for case_id in case_ids])
    two_worker_order = case_ids[::2] + case_ids[1::2]
    variant_dir = _run_dir(
        tmp_path, "variant", "dev",
        [_prediction(case_id) for case_id in two_worker_order],
        [_evidence(case_id) for case_id in two_worker_order])
    base_binding = _build_binding(
        repo, sha, manifest, inputs, base_dir, "dev")
    variant_binding = _build_binding(
        repo, sha, manifest, inputs, variant_dir, "dev",
        {"MIB_NATIVE_SCAN_OCR": "1"}, worker_count=2)
    labels = _labels(
        tmp_path / "labels.csv", [_prediction(case_id) for case_id in case_ids])
    spec = _spec(
        tmp_path / "spec.json", "scored", "dev", base_binding,
        variant_binding, labels)
    order_output = tmp_path / "order.json"
    result = _run(_audit_command(
        base_dir, variant_dir, "dev", order_output, base_binding,
        variant_binding, spec, labels=labels))
    assert result.returncode != 0
    assert "worker counts differ" in result.stderr
    assert not order_output.exists()

    equal_root = tmp_path / "equal"
    equal_root.mkdir()
    (*_, equal_base_dir, equal_variant_dir, equal_base_binding,
     equal_variant_binding, equal_labels) = _paired_fixture(
         equal_root, split="dev")
    equal_spec = _spec(
        tmp_path / "equal-spec.json", "scored", "dev", equal_base_binding,
        equal_variant_binding, equal_labels)
    incomplete = json.loads(equal_spec.read_text())
    incomplete.pop("base")
    bad_spec = tmp_path / "incomplete-spec.json"
    bad_spec.write_text(json.dumps(incomplete))
    result = _run(_audit_command(
        equal_base_dir, equal_variant_dir, "dev", tmp_path / "identity.json",
        equal_base_binding, equal_variant_binding, bad_spec,
        labels=equal_labels))
    assert result.returncode != 0
    assert "unexpected or missing keys" in result.stderr


def test_audit_fails_closed_on_bound_artifact_mismatch_and_report_overwrite(tmp_path):
    (*_, base_dir, variant_dir, base_binding, variant_binding,
     labels) = _paired_fixture(tmp_path)
    spec = _spec(
        tmp_path / "spec.json", "scored", "dev", base_binding,
        variant_binding, labels)
    first = tmp_path / "first-report.json"
    result = _run(_audit_command(
        base_dir, variant_dir, "dev", first, base_binding,
        variant_binding, spec, labels=labels))
    assert result.returncode == 0, result.stderr
    result = _run(_audit_command(
        base_dir, variant_dir, "dev", first, base_binding,
        variant_binding, spec, labels=labels))
    assert result.returncode != 0
    assert "refusing to overwrite" in result.stderr

    with (variant_dir / "predictions_dev.jsonl").open("a") as handle:
        handle.write("\n")
    result = _run(_audit_command(
        base_dir, variant_dir, "dev", tmp_path / "tampered.json", base_binding,
        variant_binding, spec, labels=labels))
    assert result.returncode != 0
    assert "artifact binding verification failed" in result.stderr
