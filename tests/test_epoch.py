"""Batch staleness epoch (mib.pipeline.batch_epoch) robustness.

The staleness rule needs a packet-receipt date, which the PDFs don't carry. We
infer it as a robust high-order statistic of the batch's own arrival dates,
floored at the mined public-data epoch, so a regenerated (later) private test
set shifts the epoch with it while a single misread "2099" can't. These tests
pin that behavior, including the +90d epoch-shift simulation.
"""
from datetime import date, timedelta

from mib.pipeline import MINED_EPOCH, batch_epoch, decide


def _states(dates):
    return [{"case_id": f"MIB-{i:06d}",
             "pools": {"arrival_date": [[d.isoformat(), "intake", 2, 95.0]]}}
            for i, d in enumerate(dates)]


def test_small_batch_falls_back_to_mined_epoch():
    st = _states([date(2026, 6, 1)] * 5)  # < 20 -> not enough signal
    assert batch_epoch(st) == MINED_EPOCH


def test_epoch_floored_at_mined_when_batch_older():
    # an all-June batch is older than the mined July-7 floor -> floor dominates
    dates = [date(2026, 6, 1) + timedelta(days=i % 30) for i in range(200)]
    assert batch_epoch(_states(dates)) == MINED_EPOCH


def test_epoch_tracks_batch_recency_above_floor():
    # a batch reaching into September must lift the epoch past the mined floor
    base = date(2026, 8, 1)
    dates = [base + timedelta(days=i % 40) for i in range(200)]
    ep = batch_epoch(_states(dates))
    assert ep > MINED_EPOCH
    assert ep <= max(dates)


def test_epoch_shift_plus_90_days():
    """Regenerated test set: every arrival shifted +90d. The epoch must move
    with the batch, not stay pinned to the public-data epoch."""
    base = date(2026, 6, 1)
    dates = [base + timedelta(days=i % 60) for i in range(200)]
    ep0 = batch_epoch(_states(dates))
    shifted = [d + timedelta(days=90) for d in dates]
    ep1 = batch_epoch(_states(shifted))
    assert ep1 > ep0
    assert (ep1 - ep0).days >= 60  # tracks the shift (order statistic moves ~90d)


def test_single_misread_year_does_not_blow_out_epoch():
    base = date(2026, 6, 1)
    dates = [base + timedelta(days=i % 30) for i in range(200)]
    dates[7] = date(2099, 1, 1)  # one absurd misread
    ep = batch_epoch(_states(dates))
    assert ep.year == 2026  # robust 99.5th percentile ignores the outlier


def test_low_confidence_dates_ignored_for_epoch():
    # only regex-exact reads (score >= 90) inform the epoch
    st = [{"case_id": f"MIB-{i:06d}",
           "pools": {"arrival_date": [[date(2027, 1, 1).isoformat(), "intake", 2, 80.0]]}}
          for i in range(200)]
    assert batch_epoch(st) == MINED_EPOCH


def test_native_batch_epoch_cannot_drop_composited_context():
    candidate_dates = [date(2026, 6, 1) + timedelta(days=i % 30)
                       for i in range(200)]
    baseline_dates = [value + timedelta(days=150)
                      for value in candidate_dates]
    states = _states(candidate_dates)
    for state, baseline in zip(states, baseline_dates):
        state["baseline_batch_context"] = {
            "arrival_date": [[
                baseline.isoformat(), "intake", 2, 95.0,
                baseline.isoformat()]]}
    baseline_only = _states(baseline_dates)
    assert batch_epoch(states) == batch_epoch(baseline_only)
    assert batch_epoch(states) > MINED_EPOCH


def test_native_epoch_keeps_raw_baseline_dates_even_when_dates_are_struck():
    baseline_dates = [date(2026, 9, 1) + timedelta(days=i % 30)
                      for i in range(200)]
    control = _states(baseline_dates)
    native = _states([date(2026, 6, 1)] * len(baseline_dates))
    for state, baseline in zip(native, baseline_dates):
        value = baseline.isoformat()
        state["struck_values"] = [value]
        state["baseline_batch_context"] = {
            "arrival_date": [[value, "intake", 2, 95.0, value]]}
    assert batch_epoch(native) == batch_epoch(control)
    assert batch_epoch(native) > MINED_EPOCH


def test_native_dates_cannot_shift_epoch_to_open_future_date_approval():
    states = _states([date(2026, 8, 20)] * 200)
    for state in states:
        state["baseline_batch_context"] = {
            "arrival_date": [[
                "2026-06-01", "intake", 2, 95.0, "2026-06-01"]]}
    receipt = batch_epoch(states)
    assert receipt == MINED_EPOCH
    values = {
        "applicant_name": "Nexmora Lurix", "species_code": "TRIANGULAN",
        "home_world": "Europa Station", "visa_class": "XW-1",
        "sponsor_id": "SPN-1502", "arrival_date": "2026-08-20",
        "declared_purpose": "research", "risk_flags": "none",
        "fee_status": "paid",
    }
    state = {
        "case_id": "MIB-700001",
        "pools": {field: [[value, "intake", 2, 100.0, value]]
                  for field, value in values.items()},
        "doc_notes": {}, "mean_ocr_conf": .99, "injection": {},
        "page_types": ["intake"], "hidden_field_mentions": {},
    }
    prediction, detail = decide(state, receipt)
    assert prediction["adjudication"] == "NEEDS_REVIEW"
    assert detail["reasons"] == ["implausible_future_arrival"]
