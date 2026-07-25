"""Wave-7 decision-layer changes: past-twin date arbitration, conditional
world backfill, and the default-off fee-prior EV head."""
import os

from mib.pipeline import decide

from test_decide import ALL, state


def _fields_without(*names):
    f = dict(ALL)
    for n in names:
        f.pop(n)
    return f


def test_past_twin_stale_read_loses_to_current_twin():
    # Same month-day, one year apart: the stale read is a year garble.
    f = dict(ALL)
    st = state(f)
    st["pools"]["arrival_date"] = [
        ["2026-06-01", "intake", 2, 95.0],
        ["2025-06-01", "biometric", 3, 95.0],
    ]
    out = decide(st)[0]
    assert out["adjudication"] == "APPROVED"
    assert out["arrival_date"] == "2026-06-01"


def test_untwinned_stale_read_still_denies():
    # A genuine stale date with no current-window twin keeps its denial.
    f = dict(ALL, arrival_date=("2025-06-01", "intake", 95.0, 2))
    out = decide(state(f))[0]
    assert out["adjudication"] == "DENIED"


def test_world_backfill_requires_read_embargo_flag():
    # home_world unread + read planetary_embargo -> TRAPPIST-1e emission,
    # decision already DENIED via the read disqualifying flag.
    f = _fields_without("home_world")
    f["risk_flags"] = ("planetary_embargo", "biometric", 90.0, 2)
    out = decide(state(f))[0]
    assert out["home_world"] == "TRAPPIST-1e"
    assert out["adjudication"] == "DENIED"
    # Without the flag, the unconditional fallback stands.
    out2 = decide(state(_fields_without("home_world")))[0]
    assert out2["home_world"] == "Luyten-b"


def test_fee_head_off_by_default():
    os.environ.pop("MIB_EV_FEE_APPROVAL", None)
    out = decide(state(_fields_without("fee_status")))[0]
    assert out["adjudication"] == "NEEDS_REVIEW"


def test_fee_head_on_approves_fee_only_gap(monkeypatch):
    monkeypatch.setenv("MIB_EV_FEE_APPROVAL", "1")
    out = decide(state(_fields_without("fee_status")))[0]
    assert out["adjudication"] == "APPROVED"
    assert out["confidence"] == 0.75


def test_fee_head_never_fires_with_second_gap(monkeypatch):
    monkeypatch.setenv("MIB_EV_FEE_APPROVAL", "1")
    out = decide(state(_fields_without("fee_status", "risk_flags")))[0]
    assert out["adjudication"] == "NEEDS_REVIEW"


def test_fee_head_respects_upstream_guards(monkeypatch):
    # Registry embargo blocker outranks the head even with only fee unread.
    monkeypatch.setenv("MIB_EV_FEE_APPROVAL", "1")
    st = state(_fields_without("fee_status"),
               doc_notes={"registry_embargo": True})
    out = decide(st)[0]
    assert out["adjudication"] == "NEEDS_REVIEW"
