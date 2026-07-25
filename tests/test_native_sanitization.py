"""Regression gates for the native-candidate validity sanitization.

`two_ledger.sanitize_native` routes each native field winner through the SAME
per-field validity gates the baseline already enforces before the frozen evdom
comparison runs, closing the sanity-gate bypass that let a native year-garble
date (MIB-000340) and a lexicon-legal but less-corroborated native name
(MIB-000783) overwrite a correct baseline. The selection inputs below are the
exact base/native values and evidence those two cases produced in the ab2
two-ledger run (ab2/ledger_full.jsonl two_ledger.field_selection + per-ledger
field evidence); the assertions require the baseline value to be retained after
the fix while genuinely stronger native reads (MIB-000564, MIB-000092) still
win.
"""
from datetime import date

from mib import two_ledger

MINED_EPOCH = date(2026, 7, 7)


def _fuse(field, base_value, base_ev, native_value, native_ev,
          receipt=MINED_EPOCH):
    """Run the production path for one field: sanitize the native winner, then
    apply the frozen evdom selector. Returns (fused_value, reject_reasons)."""
    base_fields = {field: base_value}
    native_fields = {field: native_value}
    base_evidence = {field: base_ev} if base_ev else {}
    native_evidence = {field: native_ev} if native_ev else {}
    sanitized, rejections = two_ledger.sanitize_native(
        base_fields, base_evidence, native_fields, native_evidence, receipt)
    fused, _ = two_ledger.select_fields(
        base_fields, base_evidence,
        {field: sanitized[field]}, native_evidence)
    return fused[field], [r["reason"] for r in rejections]


# --- Regression 1: MIB-000340 arrival-date year garble ------------------------

def test_340_native_year_garble_keeps_baseline_date():
    # ab2 selection input: base 2026-03-03 (weak, rank 6) vs native 2028-03-03,
    # a +2y future twin of the baseline -> the shipped twin arbitration drops it.
    fused, reasons = _fuse(
        "arrival_date",
        "2026-03-03", {"rank": 6, "snap_score": 70.0, "agreement": 1},
        "2028-03-03", {"rank": 6, "snap_score": 70.0, "agreement": 1})
    assert fused == "2026-03-03"
    assert reasons == ["date_year_garble"]


def test_native_date_correction_still_wins():
    # The mirror case (MIB-000092): the baseline read is the future garble and
    # the native read is the plausible twin; the native correction must survive.
    fused, reasons = _fuse(
        "arrival_date",
        "2028-05-26", {"rank": 6, "snap_score": 87.0, "agreement": 2},
        "2026-05-26", {"rank": 6, "snap_score": 70.0, "agreement": 1})
    assert fused == "2026-05-26"
    assert reasons == []


# --- Regression 2: MIB-000783 lexicon-legal, under-corroborated native name ---

def test_783_under_corroborated_native_name_keeps_baseline():
    # ab2 selection input: base "Luix Zarix" (agreement 2) vs native "Luix
    # Zanax" (agreement 1). Both are legal two-token lexicon names, so validity
    # alone cannot separate them; the native read is less corroborated and must
    # not displace the baseline.
    fused, reasons = _fuse(
        "applicant_name",
        "Luix Zarix", {"rank": 4, "snap_score": 90.0, "agreement": 2},
        "Luix Zanax", {"rank": 3, "snap_score": 90.0, "agreement": 1})
    assert fused == "Luix Zarix"
    assert reasons == ["name_less_corroborated_than_baseline"]


def test_equally_corroborated_native_name_still_wins():
    # MIB-000564: native "Ariix Zaix" (agreement 2) is as corroborated as the
    # baseline "Tektari Xanrix" (agreement 2) and reads stronger (rank 3 < 4), so
    # evdom's native_evidence_dominates rule must still select it.
    fused, reasons = _fuse(
        "applicant_name",
        "Tektari Xanrix", {"rank": 4, "snap_score": 90.0, "agreement": 2},
        "Ariix Zaix", {"rank": 3, "snap_score": 90.0, "agreement": 2})
    assert fused == "Ariix Zaix"
    assert reasons == []


def test_native_name_over_fallback_baseline_still_wins():
    # MIB-000802: the baseline name is the unread fallback (no evidence), so the
    # corroboration guard is inert and the native read fills the field.
    fused, reasons = _fuse(
        "applicant_name",
        "Tekdane Ixovara", None,
        "Solul Veenax", {"rank": 3, "snap_score": 90.0, "agreement": 1})
    assert fused == "Solul Veenax"
    assert reasons == []


def test_off_lexicon_native_name_rejected():
    # A native "name" that misses the lexicon (a captured label line) is not a
    # name misread and cannot overwrite the baseline.
    fused, reasons = _fuse(
        "applicant_name",
        "Luix Zarix", {"rank": 4, "snap_score": 90.0, "agreement": 1},
        "Species Code", {"rank": 3, "snap_score": 90.0, "agreement": 1})
    assert fused == "Luix Zarix"
    assert reasons == ["name_off_lexicon"]


# --- Closed-vocab legality + adverse-flip preservation ------------------------

def test_native_risk_token_addition_preserved():
    # MIB-000672's native active_warrant is a legal flag and must pass through
    # sanitization so the adverse flip can fire.
    fused, reasons = _fuse(
        "risk_flags",
        "none", None,
        "active_warrant", {"rank": 3, "snap_score": 85.0, "agreement": 1})
    assert fused == "active_warrant"
    assert reasons == []


def test_off_vocabulary_native_value_rejected():
    fused, reasons = _fuse(
        "visa_class",
        "MED-3", {"rank": 3, "snap_score": 95.0, "agreement": 1},
        "NOT-A-VISA", {"rank": 2, "snap_score": 99.0, "agreement": 1})
    assert fused == "MED-3"
    assert reasons == ["off_vocabulary_value"]
