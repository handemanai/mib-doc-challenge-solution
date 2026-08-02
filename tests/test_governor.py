"""Batch-deadline governor (hang protection layer 3).

The per-case SIGALRM and the heartbeat watchdog protect the batch from one
pathological case; the governor protects it from slow evaluation hardware,
where every case is healthy but the sum breaches the batch limit and the
container is hard-killed. These tests cover the supervisor's projection and
hysteresis policy, the atomic level-file protocol, the worker's stateless
per-case application (including recovery back to level 0), the internal
force-level seam, and the receipt-schema wiring that keeps official runs
honest about governor state.
"""
import importlib.util
import json
import os
from pathlib import Path
from unittest import mock

import pytest

from tools.native_artifact_binding import (BOOLEAN_CONFIG,
                                           EFFECTIVE_CONFIG_DEFAULTS,
                                           INTERNAL_OR_INJECTION_ENV)

ROOT = Path(__file__).resolve().parents[1]

_SPEC = importlib.util.spec_from_file_location(
    "mib_predict_governor", ROOT / "scripts" / "predict.py")
PREDICT_MODULE = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(PREDICT_MODULE)
_SHARD_SPEC = importlib.util.spec_from_file_location(
    "mib_run_shard_governor", ROOT / "scripts" / "run_shard.py")
RUN_SHARD_MODULE = importlib.util.module_from_spec(_SHARD_SPEC)
_SHARD_SPEC.loader.exec_module(RUN_SHARD_MODULE)


# --- constants stay synchronized across the two processes --------------------

def test_level_file_name_is_synchronized():
    assert (PREDICT_MODULE.GOVERNOR_LEVEL_FILE
            == RUN_SHARD_MODULE.GOVERNOR_LEVEL_FILE)
    assert (PREDICT_MODULE.GOVERNOR_MAX_LEVEL
            == RUN_SHARD_MODULE.GOVERNOR_MAX_LEVEL)


def test_ladder_shape_and_thresholds_are_sane():
    levels = RUN_SHARD_MODULE.GOVERNOR_LEVELS
    assert sorted(levels) == [0, 1, 2, 3, 4]
    assert levels[0] == {}
    # deeper levels never re-enable work a shallower level shed
    assert levels[2]["MIB_NATIVE_SCAN_OCR"] == "0"
    assert levels[3]["MIB_NATIVE_SCAN_OCR"] == "0"
    assert levels[4]["MIB_NATIVE_SCAN_OCR"] == "0"
    up = PREDICT_MODULE.GOVERNOR_UP
    assert [lv for _, lv in up] == [4, 3, 2, 1]
    thresholds = [thr for thr, _ in up]
    assert thresholds == sorted(thresholds, reverse=True)
    # every de-escalation bound sits below its escalation threshold
    up_by_level = {lv: thr for thr, lv in up}
    for level, down in PREDICT_MODULE.GOVERNOR_DOWN.items():
        assert down < up_by_level[level]
    for level, ceiling in RUN_SHARD_MODULE.GOVERNOR_CASE_TIMEOUT.items():
        assert level >= 3
        assert ceiling < RUN_SHARD_MODULE.CASE_TIMEOUT


def test_receipt_schema_records_governor_and_rejects_force_level():
    assert EFFECTIVE_CONFIG_DEFAULTS["MIB_GOVERNOR"] == "1"
    assert "MIB_GOVERNOR" in BOOLEAN_CONFIG
    assert "MIB_GOVERNOR_FORCE_LEVEL" in INTERNAL_OR_INJECTION_ENV
    clean = {k: v for k, v in os.environ.items()
             if not k.startswith("MIB_")}
    clean.update({"OMP_NUM_THREADS": "1", "OPENBLAS_NUM_THREADS": "1",
                  "MKL_NUM_THREADS": "1"})
    with mock.patch.dict(os.environ, clean, clear=True):
        assert PREDICT_MODULE._effective_run_config()["MIB_GOVERNOR"] == "1"
    with mock.patch.dict(os.environ,
                         dict(clean, MIB_GOVERNOR_FORCE_LEVEL="2"),
                         clear=True):
        with pytest.raises(SystemExit):
            PREDICT_MODULE._effective_run_config()


# --- supervisor policy -------------------------------------------------------

def _governor(tmp_path, total=5000, enabled=True):
    return PREDICT_MODULE._Governor(tmp_path, total, batch_started=0.0,
                                    enabled=enabled)


def _feed(gov, pace, upto, start=1, step=1):
    """Feed completions at a fixed seconds-per-case pace; return last level."""
    level = gov.level
    for n in range(start, upto + 1, step):
        level = gov.update(n, now=n * pace)
    return level


def test_inert_during_warmup_even_at_terrible_pace(tmp_path):
    gov = _governor(tmp_path)
    assert _feed(gov, pace=60.0, upto=gov.warmup - 1) == 0
    assert not gov.path.exists()


def test_fast_hardware_never_engages(tmp_path):
    gov = _governor(tmp_path)
    # 3 s/case toward ~15,000s, far under the ~24,840s target
    assert _feed(gov, pace=3.0, upto=1000) == 0
    assert not gov.path.exists()


def test_slow_hardware_escalates_and_publishes(tmp_path):
    gov = _governor(tmp_path)
    # 7 s/case projects ~35,000s against a ~24,840s target -> deep level
    level = _feed(gov, pace=7.0, upto=600)
    assert level >= 2
    assert gov.path.read_text().strip() == str(level)


def test_recovery_de_escalates_through_hysteresis(tmp_path):
    gov = _governor(tmp_path)
    engaged = _feed(gov, pace=7.0, upto=600)
    assert engaged >= 2
    # pace improves sharply; the recent window sees ~2 s/case
    now = 600 * 7.0
    for n in range(601, 1600):
        now += 2.0
        level = gov.update(n, now=now)
    assert level == 0
    assert gov.path.read_text().strip() == "0"


def test_warmup_scales_down_for_small_batches(tmp_path):
    # A 100-case warmup floor on a 200-case batch would delay engagement
    # until half the batch (and most of the budget) was gone.
    assert _governor(tmp_path, total=5000).warmup == 250
    assert _governor(tmp_path, total=1000).warmup == 100
    assert _governor(tmp_path, total=200).warmup == 20
    assert _governor(tmp_path, total=50).warmup == 20


def test_small_batch_target_keeps_a_workable_floor(tmp_path):
    # Fixed retry/finalize reserves must not swallow a small batch's budget:
    # 200 cases x 6s = 1200s budget; 0.9x - 3660 would be negative. The floor
    # keeps the target proportional so tiny batches are not over-degraded.
    gov = _governor(tmp_path, total=200)
    assert gov.target == pytest.approx(200 * 6.0 * 0.7)
    big = _governor(tmp_path, total=5000)
    assert big.target == pytest.approx(
        min(30000.0, 5000 * 6.0) * 0.9 - 3600.0 - 60.0)


def test_disabled_governor_never_publishes(tmp_path):
    gov = _governor(tmp_path, enabled=False)
    assert _feed(gov, pace=60.0, upto=1200) == 0
    assert not gov.path.exists()


def test_publish_is_atomic_single_file(tmp_path):
    gov = _governor(tmp_path)
    _feed(gov, pace=7.0, upto=600)
    names = {p.name for p in tmp_path.iterdir()}
    assert PREDICT_MODULE.GOVERNOR_LEVEL_FILE in names
    assert not any(name.endswith(".tmp") for name in names)


# --- completion counter ------------------------------------------------------

class _FakeShard:
    def __init__(self, files):
        self.state_files = files


def test_completion_counter_is_incremental_across_files(tmp_path):
    first = tmp_path / "state0_g1.jsonl"
    second = tmp_path / "state1_g1.jsonl"
    first.write_text("{}\n{}\n")
    second.write_text("{}\n")
    counter = PREDICT_MODULE._CompletionCounter(
        [_FakeShard([first]), _FakeShard([second])])
    assert counter.poll() == 3
    with open(first, "a") as handle:
        handle.write("{}\n")
    assert counter.poll() == 4
    assert counter.poll() == 4  # no growth, no re-read


# --- per-case ledger evidence -----------------------------------------------

def _ledger_fixture(case_id, governor_level=...):
    state = {
        "case_id": case_id,
        "pools": {"intake": []},
        "doc_notes": {},
        "extraction": {
            "attempt_count": 1,
            "recovered": False,
            "attempts": [{"attempt": 1, "status": "success"}],
        },
    }
    if governor_level is not ...:
        state["governor_level"] = governor_level
    prediction = {
        "case_id": case_id,
        **PREDICT_MODULE.FALLBACKS,
        "adjudication": "NEEDS_REVIEW",
        "confidence": 0.3,
    }
    return state, prediction


def test_governor_level_survives_state_merge_and_ledger_publication(tmp_path):
    case_id = "MIB-000001"
    pdf = tmp_path / f"{case_id}.pdf"
    state_file = tmp_path / "state0_g1.jsonl"
    state, prediction = _ledger_fixture(case_id, governor_level=3)
    state_file.write_text(json.dumps(state) + "\n")

    merged = PREDICT_MODULE._collect_states(
        [_FakeShard([state_file])], [str(pdf)], complete=True)
    assert len(merged) == 1
    assert merged[0]["governor_level"] == 3

    published = json.loads(json.dumps(
        PREDICT_MODULE._ledger_row(prediction, {}, merged[0])))
    assert published["case_id"] == case_id
    assert published["governor_level"] == 3


@pytest.mark.parametrize("level", [0, 1, 2, 3, 4])
def test_ledger_publishes_only_valid_governor_integers(level):
    state, prediction = _ledger_fixture("MIB-000001", governor_level=level)
    row = PREDICT_MODULE._ledger_row(prediction, {}, state)
    assert type(row["governor_level"]) is int
    assert row["governor_level"] == level


def test_ledger_normalizes_omitted_governor_level_to_full_quality_zero():
    state, prediction = _ledger_fixture("MIB-000001")
    assert PREDICT_MODULE._ledger_row(
        prediction, {}, state)["governor_level"] == 0


def test_governor_ledger_evidence_does_not_mutate_prediction():
    state, prediction = _ledger_fixture("MIB-000001", governor_level=4)
    prediction_bytes = json.dumps(prediction, sort_keys=True)
    row = PREDICT_MODULE._ledger_row(prediction, {}, state)
    assert row["governor_level"] == 4
    assert json.dumps(prediction, sort_keys=True) == prediction_bytes


@pytest.mark.parametrize("malformed", [True, -1, 5, 2.0, "2", None, {}])
def test_ledger_fails_closed_on_malformed_governor_level(malformed):
    state, prediction = _ledger_fixture(
        "MIB-000001", governor_level=malformed)
    row = PREDICT_MODULE._ledger_row(prediction, {}, state)
    assert row["governor_level"] is None


# --- worker application ------------------------------------------------------

def _clean_governed_env():
    return {key: None for key in RUN_SHARD_MODULE._GOVERNED_KEYS}


def test_worker_reads_level_and_restores_baseline(tmp_path, monkeypatch):
    state_out = tmp_path / "state0_g1.jsonl"
    monkeypatch.delenv("MIB_GOVERNOR_FORCE_LEVEL", raising=False)
    monkeypatch.setenv("MIB_NATIVE_SCAN_OCR", "1")
    monkeypatch.setattr(RUN_SHARD_MODULE, "_BASELINE_ENV",
                        {"MIB_NATIVE_SCAN_OCR": "1",
                         "MIB_NATIVE_MAX_PAGES": None,
                         "MIB_NATIVE_MAX_HQ": None})
    # no file -> level 0, baseline untouched
    assert RUN_SHARD_MODULE._governor_level(state_out) == 0
    (tmp_path / RUN_SHARD_MODULE.GOVERNOR_LEVEL_FILE).write_text("2")
    assert RUN_SHARD_MODULE._governor_level(state_out) == 2
    RUN_SHARD_MODULE._apply_governor_env(2)
    assert os.environ["MIB_NATIVE_SCAN_OCR"] == "0"
    (tmp_path / RUN_SHARD_MODULE.GOVERNOR_LEVEL_FILE).write_text("1")
    RUN_SHARD_MODULE._apply_governor_env(1)
    assert os.environ["MIB_NATIVE_SCAN_OCR"] == "1"
    assert os.environ["MIB_NATIVE_MAX_PAGES"] == "2"
    assert os.environ["MIB_NATIVE_MAX_HQ"] == "1"
    (tmp_path / RUN_SHARD_MODULE.GOVERNOR_LEVEL_FILE).write_text("0")
    RUN_SHARD_MODULE._apply_governor_env(0)
    assert os.environ["MIB_NATIVE_SCAN_OCR"] == "1"
    assert "MIB_NATIVE_MAX_PAGES" not in os.environ
    assert "MIB_NATIVE_MAX_HQ" not in os.environ


def test_worker_force_level_overrides_file(tmp_path, monkeypatch):
    state_out = tmp_path / "state0_g1.jsonl"
    (tmp_path / RUN_SHARD_MODULE.GOVERNOR_LEVEL_FILE).write_text("3")
    monkeypatch.setenv("MIB_GOVERNOR_FORCE_LEVEL", "0")
    assert RUN_SHARD_MODULE._governor_level(state_out) == 0
    monkeypatch.setenv("MIB_GOVERNOR_FORCE_LEVEL", "2")
    assert RUN_SHARD_MODULE._governor_level(state_out) == 2


def test_worker_tolerates_garbage_level_file(tmp_path, monkeypatch):
    state_out = tmp_path / "state0_g1.jsonl"
    monkeypatch.delenv("MIB_GOVERNOR_FORCE_LEVEL", raising=False)
    (tmp_path / RUN_SHARD_MODULE.GOVERNOR_LEVEL_FILE).write_text("noise")
    assert RUN_SHARD_MODULE._governor_level(state_out) == 0
    (tmp_path / RUN_SHARD_MODULE.GOVERNOR_LEVEL_FILE).write_text("99")
    assert (RUN_SHARD_MODULE._governor_level(state_out)
            == RUN_SHARD_MODULE.GOVERNOR_MAX_LEVEL)
