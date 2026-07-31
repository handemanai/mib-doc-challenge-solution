"""Final-row consistency: an APPROVED row must not contradict its own fields."""
from datetime import date

from mib.two_ledger import enforce_final_consistency

RECEIPT = date(2026, 7, 7)

CLEAN = {
    "applicant_name": "Aririx Ixozarn", "species_code": "TRIANGULAN",
    "home_world": "Titan Freeport", "visa_class": "XW-1",
    "sponsor_id": "SPN-3839", "arrival_date": "2026-06-30",
    "declared_purpose": "diplomatic", "risk_flags": "none",
    "fee_status": "paid", "adjudication": "APPROVED", "confidence": 0.97,
}


def _pred(**over):
    p = dict(CLEAN)
    p.update(over)
    return p


def test_clean_approval_unchanged():
    pred, detail = enforce_final_consistency(_pred(), {"reasons": ["clean"]}, RECEIPT)
    assert pred["adjudication"] == "APPROVED"
    assert "post_fusion_consistency" not in detail


def test_non_approval_untouched():
    pred, detail = enforce_final_consistency(
        _pred(adjudication="DENIED", fee_status="unpaid"),
        {"reasons": ["unpaid_fee"]}, RECEIPT)
    assert pred["adjudication"] == "DENIED"
    assert pred["fee_status"] == "unpaid"


def test_unpaid_approval_without_note_narrows_to_review():
    pred, detail = enforce_final_consistency(
        _pred(fee_status="unpaid"), {"reasons": ["clean"]}, RECEIPT)
    assert pred["adjudication"] == "NEEDS_REVIEW"
    assert pred["confidence"] <= 0.55
    assert detail["post_fusion_consistency"]["action"] == "review_field_conflict"


def test_revoked_sponsor_approval_without_note_narrows():
    pred, _ = enforce_final_consistency(
        _pred(sponsor_id="SPN-0007"), {"reasons": ["clean"]}, RECEIPT)
    assert pred["adjudication"] == "NEEDS_REVIEW"


def test_note_approval_reconciles_unpaid_fee_to_paid():
    # MIB-000893 shape: rank-1 note finding APPROVED, superseded-copy receipt
    # misread as unpaid; truth fee is paid.
    pred, detail = enforce_final_consistency(
        _pred(fee_status="unpaid", confidence=0.99),
        {"reasons": ["adjudicator_note"]}, RECEIPT)
    assert pred["adjudication"] == "APPROVED"
    assert pred["fee_status"] == "paid"
    assert (detail["post_fusion_consistency"]["action"]
            == "fee_reconciled_to_note_finding")


def test_note_approval_with_other_conflict_is_preserved_and_audited():
    pred, detail = enforce_final_consistency(
        _pred(sponsor_id="SPN-0007"), {"reasons": ["adjudicator_note"]}, RECEIPT)
    assert pred["adjudication"] == "APPROVED"
    assert pred["sponsor_id"] == "SPN-0007"
    assert (detail["post_fusion_consistency"]["action"]
            == "preserved_rank1_finding_approval")


def test_never_creates_or_denies():
    pred, _ = enforce_final_consistency(
        _pred(adjudication="NEEDS_REVIEW", fee_status="unpaid"),
        {"reasons": ["fee_unknown"]}, RECEIPT)
    assert pred["adjudication"] == "NEEDS_REVIEW"
