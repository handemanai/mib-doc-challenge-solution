"""Reason-bucket confidence shrink: near-deterministic (decision, reason)
buckets pull the calibrator output toward their empirical accuracy with
n/(n+k) shrinkage, applied after the existing floors. OOF-gated at fit time
(+0.052 dev calibration across 7 fold seeds).
"""
import pytest

import mib.pipeline as pipeline
from mib.pipeline import decide

from tests.test_decide import ALL, state


def test_bucket_artifact_is_loaded():
    assert pipeline._REASON_BUCKETS, "models/reason_buckets.json missing"
    bucket = pipeline._REASON_BUCKETS.get("DENIED|transit_visa")
    assert bucket and bucket["override"] and bucket["n"] > 0


def test_shrink_applies_exactly_after_floors(monkeypatch):
    st = state(dict(ALL, visa_class=("TRANSIT-7", "intake", 100.0, 2)))
    with_buckets, detail = decide(st)
    assert with_buckets["adjudication"] == "DENIED"
    reason = detail["reasons"][0].split(":")[0]
    bucket = pipeline._REASON_BUCKETS[f"DENIED|{reason}"]

    monkeypatch.setattr(pipeline, "_REASON_BUCKETS", {})
    without, _ = decide(st)

    weight = bucket["n"] / (bucket["n"] + pipeline._REASON_BUCKET_K)
    expected = weight * bucket["acc"] + (1 - weight) * without["confidence"]
    assert with_buckets["confidence"] == pytest.approx(
        round(min(0.99, max(0.02, expected)), 3), abs=0.002)


def test_unbucketed_paths_keep_calibrator_output(monkeypatch):
    # insufficient_evidence deliberately has no override (flat-bucketing it
    # regressed OOF): confidence must be identical with and without buckets.
    st = state({})
    with_buckets, detail = decide(st)
    key = f"NEEDS_REVIEW|{detail['reasons'][0].split(':')[0]}"
    assert not pipeline._REASON_BUCKETS.get(key, {}).get("override", False)
    monkeypatch.setattr(pipeline, "_REASON_BUCKETS", {})
    without, _ = decide(st)
    assert with_buckets["confidence"] == without["confidence"]
