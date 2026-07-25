"""Regression tests for evidence gaps that must remain abstentions.

These fixtures encode authority and policy boundaries, not packet IDs or
fallback literals.  They protect against turning missing document evidence,
review-only flags, benign worlds, or denial-themed watermarks into invented
deny evidence.
"""
from datetime import date

import pytest

from mib import parse_ocr, rules
from mib.pipeline import decide
from mib.vocab import DISQUALIFYING_FLAGS


EPOCH = date(2026, 7, 7)
RANK = {
    "intake": 2,
    "fee_receipt": 2,
    "biometric": 3,
    "registry": 5,
}


def _candidate(value, source, score):
    return [value, source, RANK[source], score, value]


def _state(*, world="Europa Station", visa="XW-2",
           risk_flags="none", include_risk=True, doc_notes=None):
    pools = {
        "applicant_name": [
            _candidate("Solmora Tekvoss", "intake", 95.0),
        ],
        "species_code": [
            _candidate("TRIANGULAN", "intake", 100.0),
        ],
        "home_world": [
            _candidate(world, "intake", 100.0),
            _candidate(world, "registry", 100.0),
        ],
        "visa_class": [
            _candidate(visa, "intake", 100.0),
        ],
        "sponsor_id": [
            _candidate("SPN-1234", "intake", 95.0),
        ],
        "arrival_date": [
            _candidate("2026-06-01", "intake", 95.0),
            _candidate("2026-06-01", "registry", 95.0),
        ],
        "declared_purpose": [
            _candidate("research", "intake", 100.0),
        ],
        "fee_status": [
            _candidate("paid", "fee_receipt", 100.0),
        ],
    }
    if include_risk:
        # Two independent visible sources are used so "none" is established
        # evidence rather than an uncorroborated approval-direction read.
        pools["risk_flags"] = [
            _candidate(risk_flags, "biometric", 95.0),
            _candidate(risk_flags, "registry", 95.0),
        ]
    return {
        "case_id": "MIB-900001",
        "pools": pools,
        "doc_notes": doc_notes or {},
        "page_types": ["intake", "registry", "fee_receipt"],
        "mean_ocr_conf": 0.99,
        "injection": {},
        "hidden_field_mentions": {},
    }


def _flag_set(prediction):
    return set(prediction["risk_flags"].split("|")) - {"", "none"}


def test_rescinded_denial_remains_review_only():
    prediction, detail = decide(_state(risk_flags="rescinded_denial"))

    assert prediction["adjudication"] == "NEEDS_REVIEW"
    assert detail["reasons"] == ["review_flag"]
    assert not (_flag_set(prediction) & DISQUALIFYING_FLAGS)


def test_wolf_dip1_is_not_a_denial_without_an_independent_trigger():
    fields = {
        "home_world": "Wolf-1061c",
        "visa_class": "DIP-1",
        "sponsor_id": "SPN-1234",
        "arrival_date": "2026-06-01",
        "risk_flags": "none",
        "fee_status": "paid",
    }
    decision, reasons = rules.adjudicate(fields, receipt_date=EPOCH)

    assert decision == "APPROVED"
    assert "embargoed_world" not in reasons


def test_missing_b13_flag_evidence_stays_review_without_inventing_a_flag():
    prediction, detail = decide(_state(include_risk=False))

    assert prediction["adjudication"] == "NEEDS_REVIEW"
    assert detail["reasons"][0].startswith("insufficient_evidence:")
    assert not (_flag_set(prediction) & DISQUALIFYING_FLAGS)


@pytest.mark.parametrize("world", ["Sirius Outpost", "Kepler-186f"])
def test_non_embargo_world_does_not_proxy_planetary_embargo(world):
    prediction, detail = decide(_state(world=world, include_risk=False))

    assert prediction["adjudication"] == "NEEDS_REVIEW"
    assert detail["reasons"][0].startswith("insufficient_evidence:")
    assert "planetary_embargo" not in _flag_set(prediction)


def test_sample_denial_without_explicit_finding_has_no_authority():
    lines = [
        ("Manual Adjudicator Note", 0.99),
        ("SAMPLE DENIAL", 0.99),
        ("Reason: denial supported by damaged registry evidence.", 0.95),
        ("DENIED", 0.95),
    ]
    page_type, fields, notes = parse_ocr.parse_page(lines)

    assert page_type == "adjudicator_note"
    assert notes["watermark"]
    assert notes["finding"] is None
    assert "risk_flags" not in fields

    prediction, detail = decide(_state(doc_notes=notes))
    assert prediction["adjudication"] != "DENIED"
    assert detail["reasons"] != ["adjudicator_note"]
