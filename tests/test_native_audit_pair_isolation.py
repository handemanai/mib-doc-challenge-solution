"""No-OCR contract tests for native base/variant isolation."""

import sys
from pathlib import Path

import pytest


TOOLS = Path(__file__).resolve().parents[1] / "tools"
sys.path.insert(0, str(TOOLS))
import audit_native_view as audit  # noqa: E402
from native_artifact_binding import EFFECTIVE_CONFIG_DEFAULTS  # noqa: E402


def _pair():
    shared = {
        "producer_git_sha": "a" * 40,
        "image_id": "sha256:" + "b" * 64,
        "image_revision": "a" * 40,
        "image_inspect_sha256": "c" * 64,
        "runtime_manifest_sha256": "d" * 64,
        "input_manifest_sha256": "e" * 64,
        "run_split": "dev",
    }
    base_config = dict(
        EFFECTIVE_CONFIG_DEFAULTS, MIB_NATIVE_SCAN_OCR="0")
    variant_config = dict(base_config, MIB_NATIVE_SCAN_OCR="1")
    base = {
        **shared, "run_nonce": "1" * 64,
        "run_receipt_sha256": "3" * 64,
        "worker_count": 4,
        "effective_config": base_config,
    }
    variant = {
        **shared, "run_nonce": "2" * 64,
        "run_receipt_sha256": "4" * 64,
        "worker_count": 4,
        "effective_config": variant_config,
    }
    return base, variant


def test_pair_accepts_only_native_flag_difference():
    audit._validate_paired_bindings(*_pair(), "dev")


@pytest.mark.parametrize("key", [
    "producer_git_sha", "image_id", "image_revision",
    "image_inspect_sha256", "runtime_manifest_sha256",
])
def test_pair_rejects_runtime_identity_difference(key):
    base, variant = _pair()
    variant[key] = "f" * len(str(variant[key]))
    with pytest.raises(ValueError, match=key):
        audit._validate_paired_bindings(base, variant, "dev")


def test_pair_rejects_reused_nonce_and_non_native_config_drift():
    base, variant = _pair()
    variant["run_nonce"] = base["run_nonce"]
    with pytest.raises(ValueError, match="distinct run nonces"):
        audit._validate_paired_bindings(base, variant, "dev")

    base, variant = _pair()
    variant["effective_config"]["MIB_PIXMATCH"] = "0"
    with pytest.raises(ValueError, match="differ beyond"):
        audit._validate_paired_bindings(base, variant, "dev")


@pytest.mark.parametrize(("key", "value"), [
    ("MIB_NATIVE_SCAN_FAST_DPI", "144"),
    ("MIB_PIXMATCH", "0"),
    ("MIB_DISABLE_EXTRACTION_RETRY", "1"),
])
def test_pair_rejects_shared_non_campaign_config(key, value):
    base, variant = _pair()
    base["effective_config"][key] = value
    variant["effective_config"][key] = value
    with pytest.raises(ValueError, match="exact campaign configs"):
        audit._validate_paired_bindings(base, variant, "dev")


def test_pair_rejects_unequal_worker_counts():
    base, variant = _pair()
    variant["worker_count"] = 3
    with pytest.raises(ValueError, match="worker counts differ"):
        audit._validate_paired_bindings(base, variant, "dev")


def test_evidence_decision_must_be_present_valid_and_match_prediction():
    predictions = {"MIB-000001": {
        **{field: "value" for field in audit.FIELDS},
        "adjudication": "NEEDS_REVIEW",
    }}
    evidence = {"MIB-000001": {"adjudication": None}}
    with pytest.raises(ValueError, match="invalid adjudication"):
        audit._validate_decisions(
            "variant", predictions, evidence, ["MIB-000001"])


def test_attempt_census_exposes_recovered_faults_without_terminal_failure():
    evidence = {"MIB-000001": {"extraction": {"attempts": [
        {"attempt": 1, "status": "failed",
         "failure_category": "recognizer_session_error"},
        {"attempt": 2, "status": "success"},
    ]}}}
    assert audit._attempt_census(evidence) == {
        "attempt_count": 2,
        "status_counts": {"failed": 1, "success": 1},
        "failure_category_counts": {"recognizer_session_error": 1},
        "recovered_case_count": 1,
        "recovered_case_ids": ["MIB-000001"],
    }
