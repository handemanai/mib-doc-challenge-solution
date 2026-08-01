"""Fee-amount paid indicator: $809.00 is printed only on paid receipts
(unpaid/waived/unknown print $0.00), so a legible amount is decisive visible
evidence of `paid` when the status word is damaged — and must stay silent on
direct reads, superseded receipts, explicit absence markers, id fragments,
and non-receipt pages.
"""
from mib.parse_ocr import _PAID_AMOUNT_RE, parse_page


def _page(texts):
    return parse_page([(t, 0.95) for t in texts])


RECEIPT_HEADER = ["MIB Fee Receipt", "Case ID", "MIB-000042"]


def test_indicator_fires_when_status_word_is_destroyed():
    ptype, fields, _ = _page(RECEIPT_HEADER + [
        "Fee Status", "#%@!", "Amount", "$809.00", "Waiver Code", "N/A"])
    assert ptype == "fee_receipt"
    assert fields["fee_status"][0] == "paid"
    assert fields["fee_status"][2] == "amount_809_paid_indicator"


def test_ocr_garbled_amounts_still_indicate():
    for amount in ["S809.00", "$ 8O9", "8o9.00", "$809,00"]:
        _, fields, _ = _page(RECEIPT_HEADER + ["Amount", amount])
        assert fields.get("fee_status", ("",))[0] == "paid", amount


def test_direct_status_read_always_wins():
    _, fields, _ = _page(RECEIPT_HEADER + [
        "Fee Status", "unpaid", "Amount", "$0.00"])
    assert fields["fee_status"][0] == "unpaid"


def test_zero_amount_never_indicates():
    _, fields, _ = _page(RECEIPT_HEADER + ["Amount", "$0.00"])
    assert "fee_status" not in fields


def test_superseded_receipt_never_votes():
    _, fields, _ = _page(RECEIPT_HEADER + [
        "ARCHIVED COPY", "Amount", "$809.00"])
    assert "fee_status" not in fields


def test_explicit_absence_marker_keeps_hedging():
    _, fields, notes = _page(RECEIPT_HEADER + [
        "Fee Status", "ILLEGIBLE", "Amount", "$809.00"])
    assert "fee_status" not in fields
    assert "fee_status" in notes["absent_fields"]


def test_non_receipt_page_never_fires():
    ptype, fields, _ = _page(["FORM I-8090", "Applicant", "Zed Zarnax",
                              "$809.00"])
    assert ptype != "fee_receipt"
    assert "fee_status" not in fields


def test_id_fragments_and_dates_never_match():
    for text in ["Packet MIB-123809 / page 2", "SPN-1809", "2026-08-09",
                 "809", "MIB-999809"]:
        assert not _PAID_AMOUNT_RE.search(text), text


def test_currency_and_decimal_forms_match():
    for text in ["$809.00", "$809", "S809.00", "809.00", "$ 809"]:
        assert _PAID_AMOUNT_RE.search(text), text
