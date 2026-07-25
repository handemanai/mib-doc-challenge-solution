"""Fee-ROI reader guards: prefix asymmetry, cancellation-stamp and strike
defenses, receipt-page gating, and the real damaged-receipt roundtrips it was
built for (MIB-000192 fires unpaid; the trap receipts fire nothing)."""
import json
import os
from pathlib import Path

import fitz
import pytest

from mib import feeread, pipeline

from tools.challenge_paths import CHALLENGE  # noqa: E402
TRAIN = CHALLENGE / "data" / "train"


def _feat(**over):
    """A clean paid-at-head feature vector; override to build other cases.
    Values mirror real dev receipts (307-style paid, 192-style unpaid)."""
    base = dict(label_ncc=0.82, paid_ncc=0.66, paid_x=0, paid_head_ncc=0.66,
                unpaid_ncc=0.45, waived_ncc=0.55, unknown_ncc=0.44,
                ink_left_paid=0.0, stamps=[])
    base.update(over)
    return base


# ---- prefix asymmetry -----------------------------------------------------

def test_paid_accepts_clean_prefix():
    assert feeread._classify(_feat(), "fee_receipt", set()) == "paid"


def test_unpaid_accepts_positive_un_prefix():
    # 192: "paid" template matches shifted right by the "un" width, with ink
    # filling the [0, x) zone and the whole-"unpaid" template corroborating.
    f = _feat(label_ncc=0.84, paid_ncc=0.894, paid_x=11, paid_head_ncc=0.783,
              unpaid_ncc=0.546, waived_ncc=0.695, unknown_ncc=0.472,
              ink_left_paid=2.5)
    assert feeread._classify(f, "unknown", set()) == "unpaid"


def test_paid_not_read_as_unpaid_without_prefix_ink():
    # "paid" at head with a clean prefix must never be promoted to unpaid.
    f = _feat(paid_ncc=0.86, paid_x=0, ink_left_paid=0.0)
    assert feeread._classify(f, "fee_receipt", set()) == "paid"


def test_waived_alias_not_read_as_unpaid():
    # 468: a washed "waived" aliases "paid" shifted-right, but the shift (x=14)
    # is wider than one "un" width, so the paid_x bound rejects it. (In the
    # live case an ARCHIVE stamp also blocks it — defense in depth.)
    f = _feat(label_ncc=0.86, paid_ncc=0.838, paid_x=14, paid_head_ncc=0.757,
              unpaid_ncc=0.580, waived_ncc=0.755, unknown_ncc=0.516,
              ink_left_paid=3.1)
    assert feeread._classify(f, "unknown", set()) is None


def test_wide_prefix_shift_not_unpaid():
    # A leading smudge on a paid receipt shifts the paid match to x>=14; only a
    # true "un" width (~11px) is accepted as unpaid.
    f = _feat(label_ncc=0.86, paid_ncc=0.89, paid_x=16, paid_head_ncc=0.68,
              unpaid_ncc=0.60, waived_ncc=0.73, unknown_ncc=0.50,
              ink_left_paid=3.2)
    assert feeread._classify(f, "unknown", set()) is None


# ---- cancellation / strike guards -----------------------------------------

def test_archive_stamp_blocks_read():
    # 323: prints an unstruck "unpaid" under an ARCHIVE stamp; the true status
    # is paid. The stamp guard must refuse both directions.
    f = _feat(label_ncc=0.84, paid_ncc=0.873, paid_x=12, paid_head_ncc=0.709,
              unpaid_ncc=0.523, waived_ncc=0.658, unknown_ncc=0.428,
              ink_left_paid=2.5, stamps=["ARCHIVE", "FILED"])
    assert feeread._classify(f, "unknown", set()) is None


def test_intake_is_not_a_cancellation_stamp():
    # INTAKE is a routing mark, not a cancellation. _page_features only ever
    # surfaces CANCEL_STAMPS, so an INTAKE-stamped receipt reads normally.
    assert "INTAKE" not in feeread.CANCEL_STAMPS
    assert "ARCHIVE" in feeread.CANCEL_STAMPS


def test_struck_value_blocked():
    f = _feat(label_ncc=0.84, paid_ncc=0.894, paid_x=11, paid_head_ncc=0.783,
              unpaid_ncc=0.546, waived_ncc=0.695, ink_left_paid=2.5)
    assert feeread._classify(f, "unknown", {"unpaid"}) is None
    assert feeread._classify(_feat(), "fee_receipt", {"paid"}) is None


# ---- receipt-page gate ----------------------------------------------------

def test_unknown_page_needs_strong_anchor():
    # A phantom "Fee Status:" anchor on a non-receipt page (label_ncc < 0.80)
    # is not a receipt.
    assert feeread._classify(_feat(label_ncc=0.77), "unknown", set()) is None


def test_unknown_page_needs_strong_value():
    # 666: an INTAKE form aliases the label at 0.77 anchor and a weak 0.696
    # paid; the tiered value floor (0.70 on unknown pages) rejects it.
    f = _feat(label_ncc=0.82, paid_ncc=0.696, paid_x=2, paid_head_ncc=0.696,
              ink_left_paid=0.591)
    assert feeread._classify(f, "unknown", set()) is None


def test_non_receipt_page_type_ignored():
    assert feeread._classify(_feat(), "intake", set()) is None
    assert feeread._classify(_feat(), "registry", set()) is None


def test_fee_receipt_allows_lower_value_ncc():
    # Pipeline-confirmed receipts may read a little weaker than damage-robust
    # unknown recoveries.
    assert feeread._classify(_feat(paid_ncc=0.62), "fee_receipt",
                             set()) == "paid"
    assert feeread._classify(_feat(paid_ncc=0.62), "unknown", set()) is None


def test_env_gate_off_disables_channel(monkeypatch):
    monkeypatch.setenv("MIB_FEE_ROI", "0")
    assert feeread.enabled() is False


# ---- real damaged-receipt roundtrips --------------------------------------
#
# These need per-page type assignments from a dev extraction pass, which is too
# expensive to redo per test. Point MIB_DEV_STATES at a states JSONL to run
# them; without it they skip. They must not run un-gated: with no page types
# every read abstains, so the "trap receipts abstain" cases would pass
# vacuously and report false confidence. Regenerate with:
#   python scripts/eval_split.py --split dev --states-out /tmp/states_dev.jsonl
DEV_STATES = Path(os.environ.get("MIB_DEV_STATES",
                                 "/tmp/mib-eval-w6c/states_dev.jsonl"))
needs_dev_states = pytest.mark.skipif(
    not (TRAIN.exists() and DEV_STATES.is_file()),
    reason="challenge data or MIB_DEV_STATES extraction states not present")

_page_types_by_case = None


def _pt(case):
    global _page_types_by_case
    if _page_types_by_case is None:
        _page_types_by_case = {}
        if DEV_STATES.is_file():
            for line in DEV_STATES.open():
                s = json.loads(line)
                _page_types_by_case[s["case_id"]] = {
                    i: t for i, t in enumerate(s["page_types"])}
    return _page_types_by_case.get(case, {})


def _read(case, struck=()):
    doc = fitz.open(str(TRAIN / f"{case}.pdf"))
    try:
        return feeread.read_fee_status(doc, _pt(case), struck)
    finally:
        doc.close()


@needs_dev_states
def test_real_192_fires_unpaid():
    read = _read("MIB-000192")
    assert read is not None and read[0] == "unpaid"


@needs_dev_states
def test_real_paid_receipt_fires_paid():
    read = _read("MIB-000307")
    assert read is not None and read[0] == "paid"


@needs_dev_states
@pytest.mark.parametrize("case", ["MIB-000323", "MIB-000158", "MIB-000552",
                                  "MIB-000666", "MIB-000514"])
def test_real_trap_receipts_do_not_fire(case):
    # 323 archived-unpaid, 158/514/552 struck/superseded, 666 intake phantom:
    # every one must abstain (vector strikes come from struck_values).
    struck = []
    for line in DEV_STATES.open():
        s = json.loads(line)
        if s["case_id"] == case:
            struck = s["struck_values"]
            break
    assert _read(case, struck) is None
