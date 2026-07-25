"""Calibrator round-trip: prove the runtime's hand-rolled logistic+isotonic
confidence (mib.pipeline._calibrated_confidence, math-only so the image needs
no sklearn) reproduces an independent recomputation of the same model, and that
its feature contract matches what calib_features emits.
"""
import json
import math
from pathlib import Path

import pytest

from mib import pipeline

CALIB_PATH = Path(pipeline.__file__).resolve().parents[1] / "models" / "calibrator.json"

pytestmark = pytest.mark.skipif(not CALIB_PATH.exists(),
                                reason="calibrator.json not present")


@pytest.fixture(scope="module")
def calib():
    return json.loads(CALIB_PATH.read_text())


def _sample_detail(**over):
    d = {
        "path": "APPROVED:clean:9",
        "extracted_fields": ["fee_status", "risk_flags", "sponsor_id",
                             "visa_class", "home_world"],
        "field_evidence": {"risk_flags": [3, 90.0, 2], "fee_status": [2, 95.0, 1]},
        "finding_note": None, "bio_confidence": None, "watermark_pages": 0,
        "mean_ocr_conf": 0.8, "hidden_span_count": 0, "has_answer_key": 0,
    }
    d.update(over)
    return d


def test_feature_contract_matches(calib):
    feats = pipeline.calib_features(_sample_detail(), pipeline.PATH_CONFIDENCE)
    for name in calib["feature_names"]:
        assert name in feats, f"calibrator needs feature {name!r} not emitted"


def test_runtime_matches_independent_recompute(calib):
    detail = _sample_detail()
    f = pipeline.calib_features(detail, pipeline.PATH_CONFIDENCE)
    # independent logistic
    z = calib["intercept"]
    for name, mu, sd, w in zip(calib["feature_names"], calib["mu"],
                               calib["sd"], calib["coef"]):
        z += w * ((f[name] - mu) / sd)
    p = 1.0 / (1.0 + math.exp(-z))
    xs, ys = calib["iso_x"], calib["iso_y"]
    i = min(int(p * (len(xs) - 1)), len(xs) - 1)
    expected = ys[i]
    got = pipeline._calibrated_confidence(detail)
    assert abs(got - expected) < 1e-9


def test_confidence_in_range(calib):
    for detail in (_sample_detail(),
                   _sample_detail(has_answer_key=1, hidden_span_count=12),
                   _sample_detail(bio_confidence=45, mean_ocr_conf=0.3)):
        c = pipeline._calibrated_confidence(detail)
        assert 0.0 <= c <= 1.0


def test_full_decision_confidence_clipped():
    # decide() clips to [0.02, 0.98] regardless of calibrator output
    state = {"case_id": "MIB-000000", "pools": {}, "doc_notes": {},
             "mean_ocr_conf": 0.0, "injection": {}, "hidden_field_mentions": {}}
    pred, _ = pipeline.decide(state)
    assert 0.02 <= pred["confidence"] <= 0.98
