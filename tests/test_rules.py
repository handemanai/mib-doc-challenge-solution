"""Golden tests for the mined adjudication policy (mib/rules.py).

One assertion per rule the memo claims, plus the DIP-1 exemption matrix and the
EV decision table. These pin the policy so a refactor can't silently move a
deny rule (the failure mode that turns a hedge into a false approval).
"""
from datetime import date

import pytest

from mib import rules

EPOCH = date(2026, 7, 7)
CLEAN = {
    "applicant_name": "Solmora Tekvoss", "species_code": "TRIANGULAN",
    "home_world": "Kepler-186f", "visa_class": "XW-2", "sponsor_id": "SPN-1234",
    "arrival_date": "2026-06-01", "declared_purpose": "research",
    "risk_flags": "none", "fee_status": "paid",
}


def adj(**over):
    f = dict(CLEAN, **over)
    return rules.adjudicate(f, receipt_date=EPOCH)[0]


def test_clean_packet_approves():
    assert adj() == "APPROVED"


@pytest.mark.parametrize("flag", ["memory_tampering", "planetary_embargo",
                                  "active_warrant", "biohazard_red"])
def test_disqualifying_flags_deny(flag):
    assert adj(risk_flags=flag) == "DENIED"


@pytest.mark.parametrize("flag", ["identity_conflict", "sponsor_mismatch",
                                  "illegible_biometrics", "rescinded_denial"])
def test_review_flags_hedge(flag):
    assert adj(risk_flags=flag) == "NEEDS_REVIEW"


def test_unpaid_fee_denies_even_dip1():
    assert adj(fee_status="unpaid") == "DENIED"
    assert adj(fee_status="unpaid", visa_class="DIP-1") == "DENIED"


def test_unknown_fee_reviews():
    assert adj(fee_status="unknown") == "NEEDS_REVIEW"


def test_transit_visa_denies():
    assert adj(visa_class="TRANSIT-7") == "DENIED"


def test_wolf_embargo_denies_unless_dip1():
    assert adj(home_world="Wolf-1061c") == "DENIED"
    assert adj(home_world="Wolf-1061c", visa_class="DIP-1") == "APPROVED"


@pytest.mark.parametrize("spn", ["SPN-0007", "SPN-0139", "SPN-4040",
                                 "SPN-7331", "SPN-2718", "SPN-9090"])
def test_revoked_sponsors_deny_unless_dip1(spn):
    assert adj(sponsor_id=spn) == "DENIED"
    assert adj(sponsor_id=spn, visa_class="DIP-1") == "APPROVED"


def test_planetary_embargo_overrides_dip1():
    # a disqualifying flag denies even a DIP-1 packet
    assert adj(risk_flags="planetary_embargo", visa_class="DIP-1") == "DENIED"


def test_staleness_denies_beyond_180d_except_dip1():
    stale = "2026-01-01"  # ~187 days before EPOCH
    assert adj(arrival_date=stale) == "DENIED"
    assert adj(arrival_date=stale, visa_class="DIP-1") == "APPROVED"


def test_fresh_application_approves():
    assert adj(arrival_date="2026-06-20") == "APPROVED"


def test_deny_precedence_over_review():
    # a case with BOTH a review flag and a deny trigger must DENY
    assert adj(risk_flags="identity_conflict", fee_status="unpaid") == "DENIED"


# ---- EV decision table (rules.optimal_decision) -----------------------------

def test_ev_confident_approve():
    d, _ = rules.optimal_decision(0.95, 0.02, 0.03)
    assert d == "APPROVED"


def test_ev_torn_between_a_and_d_never_approves():
    # 1.5x rule: approve only when pA dominates pD; a near-tie must not approve
    d, ev = rules.optimal_decision(0.5, 0.45, 0.05)
    assert d != "APPROVED"
    assert ev["DENIED"] >= ev["APPROVED"]


def test_ev_high_review_hedges():
    d, _ = rules.optimal_decision(0.3, 0.2, 0.5)
    assert d == "NEEDS_REVIEW"


def test_ev_false_approval_penalty_shapes_boundary():
    # at pA=0.6/pD=0.4, the -4 penalty must pull the EV-optimal choice off
    # APPROVED (8*0.6 - 4*0.4 = 3.2 < 8*0.4 = 3.2 tie -> not strictly approve)
    d, ev = rules.optimal_decision(0.6, 0.4, 0.0)
    assert ev["APPROVED"] <= ev["DENIED"]
