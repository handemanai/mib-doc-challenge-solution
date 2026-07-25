"""creationDate drift tripwire: an OCR-free forward vote on the receipt epoch.

The public corpus was generated 2026-06-29 in one run; a materially later
private corpus moves the stale boundary with it. The stamp only ever shifts
the epoch forward, respects the deadband, is clamped by the arrival bulk, and
is provenance-grade (a corrupt or absent stamp changes nothing).
"""
from datetime import date, timedelta
from pathlib import Path

import fitz
import pytest

from mib import pipeline

from tools.challenge_paths import CHALLENGE  # noqa: E402
TRAIN = CHALLENGE / "data" / "train"


def _stamped(iso):
    return {"pdf_creation_date": iso, "pools": {}}


def _dated_state(iso_dates):
    return {"pools": {"arrival_date": [(d, "src", 0, 99) for d in iso_dates]}}


@pytest.mark.skipif(not TRAIN.exists(), reason="challenge data not present")
def test_public_pdf_stamp_parses_to_generation_day():
    with fitz.open(TRAIN / "MIB-000003.pdf") as doc:
        assert pipeline._pdf_creation_date(doc) == "2026-06-29"


def test_public_stamp_is_behavior_neutral():
    states = [_stamped("2026-06-29") for _ in range(10)]
    assert pipeline._metadata_epoch_shift(states) == 0
    assert pipeline.batch_epoch(states) == pipeline.MINED_EPOCH


def test_deadband_swallows_small_drift():
    states = [_stamped("2026-07-08") for _ in range(10)]  # +9 days
    assert pipeline._metadata_epoch_shift(states) == 0


def test_thin_arrival_pool_falls_back_to_metadata_shift():
    states = [_stamped("2026-08-28") for _ in range(10)]  # +60 days
    assert pipeline._metadata_epoch_shift(states) == 60
    assert pipeline.batch_epoch(states) == (
        pipeline.MINED_EPOCH + timedelta(days=60))


def test_bulk_clamp_bounds_the_metadata_vote():
    # 25 well-read arrivals ending past the mined floor, plus a +1y metadata
    # stamp: the epoch may follow the votes forward but never outrun the
    # observed arrival bulk.
    arrivals = [(date(2026, 6, 1) + timedelta(days=3 * i)).isoformat()
                for i in range(25)]
    state = _dated_state(arrivals)
    state["pdf_creation_date"] = "2027-06-29"
    states = [state] + [_stamped("2027-06-29") for _ in range(9)]
    epoch = pipeline.batch_epoch(states)
    bulk_max = date.fromisoformat(arrivals[-1])
    assert epoch == bulk_max          # clamped, not MINED + 365 days
    assert epoch < pipeline.MINED_EPOCH + timedelta(days=365)


def test_metadata_floor_never_moves_epoch_backward():
    # Arrivals entirely before the mined floor + a big stamp: the bulk clamp
    # suppresses the vote and the mined floor still wins (pre-existing
    # semantics preserved).
    arrivals = [(date(2026, 5, 1) + timedelta(days=2 * i)).isoformat()
                for i in range(25)]
    state = _dated_state(arrivals)
    state["pdf_creation_date"] = "2027-06-29"
    states = [state] + [_stamped("2027-06-29") for _ in range(9)]
    assert pipeline.batch_epoch(states) == pipeline.MINED_EPOCH


def test_corrupt_or_missing_stamps_are_ignored():
    states = [_stamped("not-a-date"), {"pools": {}},
              _stamped(None), _stamped("2026-06-29")]
    assert pipeline._metadata_epoch_shift(states) == 0


def test_low_confidence_arrival_candidates_still_excluded():
    # Regression guard for the pre-existing rule: sub-90-confidence arrival
    # reads never enter the epoch statistic, with or without stamps.
    state = {"pools": {"arrival_date": [("2027-01-01", "src", 0, 50)]},
             "pdf_creation_date": "2026-06-29"}
    assert pipeline.batch_epoch([state] * 30) == pipeline.MINED_EPOCH
