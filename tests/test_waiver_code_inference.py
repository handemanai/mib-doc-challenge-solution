"""Waiver-code fee inference: a printed non-null waiver code means the fee is
waived (106/106 train receipts), but only as emission — a pooled unpaid or
unknown read always wins, so no adjudication path can change.
"""
from mib.pipeline import decide

from tests.test_decide import ALL, state


def _no_fee():
    fields = dict(ALL)
    del fields["fee_status"]
    return fields


def test_real_waiver_code_emits_waived_over_the_paid_fallback():
    st = state(_no_fee(), doc_notes={"waiver_code": "HARDSHIP-2291"})
    pred = decide(st)[0]
    assert pred["fee_status"] == "waived"


def test_null_and_garbled_codes_keep_the_paid_fallback():
    # N/A, its OCR garbles, and structureless tokens must never pass — a
    # garbled placeholder is the only false-approval vector this inference
    # could open, so only the hyphenated waiver grammar is accepted.
    for null in ("N/A", "n/a", "NONE", "", "NA", "NIA", "M/A", "WAIVER",
                 "DIPWAIVER", "A-B"):
        st = state(_no_fee(), doc_notes={"waiver_code": null})
        assert decide(st)[0]["fee_status"] == "paid", null


def test_forged_generic_codes_are_rejected():
    # The prior grammar [A-Z]{3,}-[A-Z0-9]{2,} accepted arbitrary hyphenated
    # shapes; a forged code printed on an adversarial receipt could then flip an
    # unread fee to waived and open an approval. Only the two real forms
    # (DIP-WAIVER, HARDSHIP-####) may pass now.
    for forged in ("ABC-99", "XXX-YY", "FAKE-01", "HARDSHIP-X", "DIP-WAIVE",
                   "WAIVER-01", "HARDSHIPX-22"):
        st = state(_no_fee(), doc_notes={"waiver_code": forged})
        assert decide(st)[0]["fee_status"] == "paid", forged


def test_pooled_unpaid_read_always_wins():
    st = state(dict(ALL, fee_status=("unpaid", "fee_receipt", 95.0, 1)),
               doc_notes={"waiver_code": "DIP-WAIVER"})
    pred = decide(st)[0]
    assert pred["fee_status"] == "unpaid"
    assert pred["adjudication"] == "DENIED"


def test_pooled_unknown_read_always_wins():
    st = state(dict(ALL, fee_status=("unknown", "fee_receipt", 95.0, 1)),
               doc_notes={"waiver_code": "DIP-WAIVER"})
    pred = decide(st)[0]
    assert pred["fee_status"] == "unknown"
    assert pred["adjudication"] == "NEEDS_REVIEW"


def test_structural_code_resolves_the_fee_evidence_hedge():
    # With the fee word destroyed the case hedges on missing fee evidence; a
    # legible structural waiver code IS the fee evidence (visible waiver per
    # policy), so the hedge resolves and the otherwise-clean case approves.
    base = decide(state(_no_fee()))[0]
    with_code = decide(state(_no_fee(),
                             doc_notes={"waiver_code": "DIP-WAIVER"}))[0]
    assert base["adjudication"] == "NEEDS_REVIEW"
    assert with_code["adjudication"] == "APPROVED"
    assert with_code["fee_status"] == "waived"
