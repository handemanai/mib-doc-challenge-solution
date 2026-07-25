"""Decision-layer guards (mib.pipeline.decide) — the logic that stands between a
clean read and a catastrophic false approval. Exercised with synthetic state
dicts (a pool entry is [value, source, rank, score]), so no OCR is involved.
"""
from mib.pipeline import decide

RANK = {"intake": 2, "fee_receipt": 2, "biometric": 3, "registry": 5,
        "sponsor_letter": 4}
# distinct extra sources used to fabricate cross-page agreement counts
_EXTRA_SOURCES = ["biometric", "registry", "sponsor_letter"]


def state(fields, doc_notes=None, hidden=None, mean_ocr=0.8):
    """fields: {name: (value, source, score, n_sources)}. Emits pools with
    n_sources distinct page-type sources agreeing on the value, so the
    decision layer's corroboration counts are directly controllable."""
    pools = {}
    for f, (value, source, score, n) in fields.items():
        srcs = [source] + [s for s in _EXTRA_SOURCES if s != source]
        srcs = srcs[:max(1, n)]
        pools[f] = [[value, s, RANK.get(s, 6), score] for s in srcs]
    return {"case_id": "MIB-000000", "pools": pools,
            "doc_notes": doc_notes or {}, "mean_ocr_conf": mean_ocr,
            "injection": {}, "hidden_field_mentions": hidden or {}}


ALL = {
    "risk_flags": ("none", "biometric", 90.0, 2),
    "fee_status": ("paid", "fee_receipt", 95.0, 1),
    "home_world": ("Kepler-186f", "intake", 100.0, 2),
    "visa_class": ("XW-2", "intake", 100.0, 2),
    "sponsor_id": ("SPN-1234", "intake", 95.0, 2),
    "arrival_date": ("2026-06-01", "intake", 95.0, 2),
    "species_code": ("TRIANGULAN", "intake", 100.0, 2),
    "declared_purpose": ("research", "intake", 100.0, 2),
    "applicant_name": ("Solmora Tekvoss", "intake", 90.0, 2),
}


def dec(fields, **kw):
    return decide(state(fields, **kw))[0]["adjudication"]


def test_fully_read_clean_approves():
    assert dec(dict(ALL)) == "APPROVED"


def test_deny_trigger_must_be_read_not_assumed():
    # unpaid fee read from evidence -> DENIED
    f = dict(ALL, fee_status=("unpaid", "fee_receipt", 95.0, 1))
    assert dec(f) == "DENIED"


def test_deny_trigger_unverified_hedges():
    # nothing read at all -> adjudicate sees fallbacks; a deny that rests on a
    # fallback value (not in extracted) must degrade to review, never deny/approve
    st = state({})  # empty pools
    out = decide(st)[0]
    assert out["adjudication"] == "NEEDS_REVIEW"


def test_garbled_none_flags_block_approval():
    # low-score, single-source "none" flags read cannot clear a case
    f = dict(ALL, risk_flags=("none", "biometric", 40.0, 1))
    assert dec(f) == "NEEDS_REVIEW"


def test_confident_corroborated_none_flags_ok():
    f = dict(ALL, risk_flags=("none", "biometric", 90.0, 2))
    assert dec(f) == "APPROVED"


def test_missing_arrival_date_reviews():
    f = {k: v for k, v in ALL.items() if k != "arrival_date"}
    assert dec(f) == "NEEDS_REVIEW"


def test_hidden_only_sponsor_reviews():
    # sponsor absent from visible, present in hidden text, non-DIP -> review
    f = {k: v for k, v in ALL.items() if k != "sponsor_id"}
    assert dec(f, hidden={"sponsor": True}) == "NEEDS_REVIEW"
    out = decide(state(f, hidden={"sponsor": True}))[0]
    assert out["sponsor_id"] != "SPN-1234"  # hidden value never emitted


def test_hidden_only_sponsor_ok_for_dip1():
    f = {k: v for k, v in ALL.items() if k != "sponsor_id"}
    f["visa_class"] = ("DIP-1", "intake", 100.0, 2)
    # DIP-1 does not need a sponsor -> hidden mention doesn't force review here
    assert dec(f, hidden={"sponsor": True}) == "APPROVED"


def test_adjudicator_note_overrides_fields():
    f = dict(ALL)  # would approve on fields
    assert dec(f, doc_notes={"finding": "DENIED"}) == "DENIED"


def test_waived_fee_without_waiver_reviews():
    f = dict(ALL, fee_status=("waived", "fee_receipt", 95.0, 1))
    assert dec(f, doc_notes={"waiver_code": "N/A"}) == "NEEDS_REVIEW"


def test_waived_fee_ok_for_dip1():
    f = dict(ALL, fee_status=("waived", "fee_receipt", 95.0, 1),
             visa_class=("DIP-1", "intake", 100.0, 2))
    assert dec(f) == "APPROVED"


def test_staleness_gray_zone_hedges():
    # arrival ~185 days before mined epoch but inside the gray band -> hedge
    f = dict(ALL, arrival_date=("2026-01-15", "intake", 80.0, 1))
    assert dec(f) == "NEEDS_REVIEW"


def test_weak_unknown_page_date_cannot_independently_deny():
    # Rotation recovery may expose a plausible-looking date on a damaged copy
    # artifact. Keep the proposed value for audit/extraction, but do not let a
    # single weak unknown-page reconstruction create a stale denial.
    f = dict(ALL, arrival_date=("2024-01-22", "unknown", 72.0, 1))
    out, detail = decide(state(f))
    assert out["arrival_date"] == "2024-01-22"
    assert out["adjudication"] == "NEEDS_REVIEW"
    assert detail["reasons"] == ["weak_stale_date_evidence"]


def test_strong_unknown_page_date_can_still_deny():
    # The guard is about weak reconstruction, not an unknown-page ban.
    f = dict(ALL, arrival_date=("2025-06-01", "unknown", 90.0, 1))
    out, detail = decide(state(f))
    assert out["adjudication"] == "DENIED"
    assert detail["reasons"] == ["stale_application"]
