"""The eight pre-registered two-ledger promotion gates.

Real-PDF gates extract each fixture twice (flag off / flag on) and assert the
pre-registered behaviour; unit gates exercise `two_ledger.reconcile` directly.
Fixtures come from the challenge dev set (`/tmp/mib-p0c-dev-input/`) and are
pre-registered regression fixtures, not tuning material. The two holdout gate
fixtures (362/799) are intentionally omitted: the holdout is never read here.
"""
import os
from pathlib import Path

import pytest

from mib import pipeline, two_ledger

DEV = Path("/tmp/mib-p0c-dev-input")

pytestmark = pytest.mark.skipif(
    not DEV.exists(), reason="dev fixtures unavailable")

_CACHE = {}


def _run(case_id, mode):
    """(pred, detail, state) for a fixture under mode in {off, fields, full}.

    Single-case batch (epoch falls back to the mined epoch, matching the batch),
    memoized so each (case, mode) OCR pass runs once.
    """
    key = (case_id, mode)
    if key in _CACHE:
        return _CACHE[key]
    saved = {k: os.environ.get(k)
             for k in ("MIB_NATIVE_SCAN_OCR", "MIB_TWO_LEDGER")}
    try:
        if mode == "off":
            os.environ["MIB_NATIVE_SCAN_OCR"] = "0"
            os.environ.pop("MIB_TWO_LEDGER", None)
        else:
            os.environ["MIB_NATIVE_SCAN_OCR"] = "1"
            os.environ["MIB_TWO_LEDGER"] = mode
        state = pipeline.extract_state(str(DEV / f"{case_id}.pdf"))
        epoch = pipeline.batch_epoch([state])
        revoked = pipeline.batch_frequent_sponsors([state])
        natives, has = two_ledger.native_batch_inputs([state])
        nepoch = pipeline.batch_epoch(natives) if has else epoch
        nrevoked = pipeline.batch_frequent_sponsors(natives) if has else revoked
        ablation = two_ledger.ablation_from_env()
        pred, detail = two_ledger.decide_case(
            state, epoch, nepoch, revoked, nrevoked, ablation)
    finally:
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
    _CACHE[key] = (pred, detail, state)
    return _CACHE[key]


def test_native_fusion_defaults_to_full(monkeypatch):
    monkeypatch.delenv("MIB_NATIVE_SCAN_OCR", raising=False)
    monkeypatch.delenv("MIB_TWO_LEDGER", raising=False)
    assert two_ledger.ablation_from_env() == "full"


def test_native_fusion_explicit_opt_out(monkeypatch):
    monkeypatch.setenv("MIB_NATIVE_SCAN_OCR", "0")
    monkeypatch.delenv("MIB_TWO_LEDGER", raising=False)
    assert two_ledger.ablation_from_env() is None


def _tuple(pred, detail):
    return (pred["adjudication"], tuple(detail.get("reasons") or []),
            pred["confidence"])


# --- Gate 1 -------------------------------------------------------------------

def test_016_baseline_pixel_world_and_denial_preserved():
    off_pred, _, _ = _run("MIB-000016", "off")
    on_pred, _, on_state = _run("MIB-000016", "full")
    assert on_state.get("native_ledger") is not None
    # The baseline pixel-decoder home world and its embargo denial survive.
    assert off_pred["home_world"] == "Wolf-1061c"
    assert off_pred["adjudication"] == "DENIED"
    assert on_pred["home_world"] == "Wolf-1061c"
    assert on_pred["adjudication"] == "DENIED"


# --- Gate 2 -------------------------------------------------------------------

def test_543_ordinary_note_sponsor_preserved():
    off_pred, _, _ = _run("MIB-000543", "off")
    on_pred, _, _ = _run("MIB-000543", "full")
    assert off_pred["sponsor_id"] == "SPN-0007"
    assert off_pred["adjudication"] == "DENIED"
    # The ordinary Manual-Note sponsor is not lost to the native supplement.
    assert on_pred["sponsor_id"] == "SPN-0007"
    assert on_pred["adjudication"] == "DENIED"


# --- Gate 3 -------------------------------------------------------------------

def test_047_unchanged_outcome_keeps_confidence():
    off_pred, off_detail, _ = _run("MIB-000047", "off")
    on_pred, on_detail, _ = _run("MIB-000047", "full")
    # An unchanged adjudication retains the baseline decision/reason/confidence
    # tuple byte-for-byte (no native calibration drift).
    assert _tuple(on_pred, on_detail) == _tuple(off_pred, off_detail)
    assert off_pred["adjudication"] == "NEEDS_REVIEW"
    # 0.626 pre reason-buckets; the hidden_only_field bucket (acc 0.0, n=4)
    # shrinks it to 0.21*0.0 + 0.79*0.626 = 0.495. The gate's invariant is
    # the on==off tuple above, not the scalar itself.
    assert off_pred["confidence"] == 0.495


# --- Gate 4 -------------------------------------------------------------------

def test_672_native_adverse_fill_denies():
    off_pred, _, _ = _run("MIB-000672", "off")
    on_pred, on_detail, _ = _run("MIB-000672", "full")
    assert off_pred["adjudication"] == "NEEDS_REVIEW"
    # A native-evidenced deny trigger flips NEEDS_REVIEW -> DENIED with a causal
    # transition record naming the native evidence.
    assert on_pred["adjudication"] == "DENIED"
    assert "active_warrant" in on_pred["risk_flags"]
    transition = on_detail["two_ledger"]["decision_transition"]
    assert transition["rule"] == "needs_review_to_denied_adverse"
    assert transition["decision_source"] == "native_adverse_flip"
    adverse = on_detail["two_ledger"]["native_adverse"]
    assert adverse["cause"] == "native_deny_trigger_risk_token"
    assert "active_warrant" in adverse["tokens"]
    # The flipped row takes the native decide() confidence.
    assert transition["confidence_source"] == "native"


# --- Gate 5 (unit) ------------------------------------------------------------

def test_benign_fill_cannot_open_approval():
    base_out = {"adjudication": "NEEDS_REVIEW",
                "reasons": ["insufficient_evidence:2"], "confidence": 0.30}
    native_out = {"adjudication": "APPROVED", "reasons": ["clean"],
                  "confidence": 0.95}
    adj, reasons, conf, transition = two_ledger.reconcile(
        base_out, native_out, None, "full")
    # A benign native fill (risk_flags=none -> native APPROVED) can never open
    # an approval; the baseline NEEDS_REVIEW tuple is copied exactly.
    assert adj == "NEEDS_REVIEW"
    assert (reasons, conf) == (["insufficient_evidence:2"], 0.30)
    assert transition["decision_source"] == "baseline"
    # And the field selector never drops a baseline risk token to a native none.
    fused, audit = two_ledger.select_fields(
        {"risk_flags": "active_warrant"},
        {"risk_flags": {"rank": 3, "snap_score": 95.0}},
        {"risk_flags": "none"},
        {"risk_flags": {"rank": 2, "snap_score": 99.0}})
    assert fused["risk_flags"] == "active_warrant"
    assert audit == []


# --- Gate 6 (unit) ------------------------------------------------------------

def test_native_finding_cannot_relax_denial():
    base_out = {"adjudication": "DENIED", "reasons": ["unpaid_fee"],
                "confidence": 0.90}
    for native_out in (
            {"adjudication": "APPROVED", "reasons": ["clean"], "confidence": 0.9},
            {"adjudication": "NEEDS_REVIEW", "reasons": ["adjudicator_note"],
             "confidence": 0.98}):
        adj, reasons, conf, transition = two_ledger.reconcile(
            base_out, native_out, None, "full")
        # A native approving/review finding can never relax a baseline denial.
        assert (adj, reasons, conf) == ("DENIED", ["unpaid_fee"], 0.90)
        assert transition["rule"] == "baseline_denied_never_relaxed"


# --- Gate 7 -------------------------------------------------------------------

@pytest.mark.parametrize("case_id", [
    "MIB-000023", "MIB-000325", "MIB-000469", "MIB-000750", "MIB-000761"])
def test_preserved_findings(case_id):
    off_pred, off_detail, _ = _run(case_id, "off")
    on_pred, on_detail, _ = _run(case_id, "full")
    # Flag-on decision + confidence equal flag-off on each preserved-finding
    # case; signed rank-1 findings are never lost or relaxed.
    assert on_pred["adjudication"] == off_pred["adjudication"]
    assert on_pred["confidence"] == off_pred["confidence"]
    if case_id == "MIB-000023":
        assert off_pred["adjudication"] == "DENIED"


# --- Gate 8 -------------------------------------------------------------------

_PANEL = ["MIB-000016", "MIB-000023", "MIB-000047", "MIB-000134", "MIB-000325",
          "MIB-000469", "MIB-000543", "MIB-000589", "MIB-000672", "MIB-000719",
          "MIB-000750", "MIB-000761", "MIB-000865"]


def test_no_new_false_approval_beyond_865():
    off_approved, on_approved = set(), set()
    for case_id in _PANEL:
        off_pred, _, _ = _run(case_id, "off")
        on_pred, _, _ = _run(case_id, "full")
        if off_pred["adjudication"] == "APPROVED":
            off_approved.add(case_id)
        if on_pred["adjudication"] == "APPROVED":
            on_approved.add(case_id)
    # No new approvals are created by the fusion over the gate panel.
    assert on_approved <= off_approved
    # The one known baseline false approval stays flag-invariant.
    off_865, _, _ = _run("MIB-000865", "off")
    on_865, _, _ = _run("MIB-000865", "full")
    assert off_865["adjudication"] == on_865["adjudication"]
