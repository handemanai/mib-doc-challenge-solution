"""Hard batch-deadline finalization through the production supervisor."""
import importlib.util
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from unittest import mock

import fitz


ROOT = Path(__file__).resolve().parents[1]
PREDICT = ROOT / "scripts" / "predict.py"
_SPEC = importlib.util.spec_from_file_location("mib_predict_batch_deadline", PREDICT)
PREDICT_MODULE = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(PREDICT_MODULE)


def _write_pdf(input_dir, case_id):
    input_dir.mkdir()
    document = fitz.open()
    page = document.new_page()
    page.insert_text((72, 100), f"Case ID: {case_id}")
    document.save(input_dir / f"{case_id}.pdf")
    document.close()


class _UnreapableProcess:
    def __init__(self):
        self.killed = False
        self.timeouts = []

    def poll(self):
        return None

    def kill(self):
        self.killed = True

    def wait(self, timeout=None):
        self.timeouts.append(timeout)
        raise subprocess.TimeoutExpired(["unreapable-worker"], timeout)


def test_c_level_hang_enters_reserve_and_emits_complete_fallback(tmp_path):
    """A C-level hang must not leave completion to the external hard kill."""
    case_id = "MIB-990001"
    input_dir = tmp_path / "input"
    _write_pdf(input_dir, case_id)

    predictions = tmp_path / "predictions.jsonl"
    ledger = tmp_path / "ledger.jsonl"
    env = dict(
        os.environ,
        MIB_TEST_HANG_CASE=case_id,
        MIB_TEST_HANG_MODE="c",
        # The watchdog is deliberately later than the supervisor boundary: the
        # test proves the hard batch reserve, not the per-worker watchdog.
        MIB_STUCK_SECS="60",
        MIB_STARTUP_GRACE="60",
        MIB_WATCHDOG_POLL="0.1",
        MIB_BATCH_LIMIT_SECS="10",
        MIB_FINALIZE_RESERVE_SECS="2",
        MIB_RETRY_BUDGET_SECS="60",
        MIB_LEDGER=str(ledger),
    )
    started = time.monotonic()
    result = subprocess.run(
        [sys.executable, str(PREDICT), str(input_dir), str(predictions)],
        env=env, text=True, capture_output=True, timeout=20)
    elapsed = time.monotonic() - started

    assert result.returncode == 0, result.stderr
    assert elapsed < 15
    assert "[watchdog]" not in result.stdout
    assert "[retry]" not in result.stdout
    assert "[batch-deadline] finalization reserve entered" in result.stdout
    assert "completed=0/1 backfilled=1 retries=skipped" in result.stdout

    rows = [json.loads(line) for line in predictions.read_text().splitlines()]
    assert len(rows) == 1
    assert rows[0]["case_id"] == case_id
    assert rows[0]["adjudication"] == "NEEDS_REVIEW"

    evidence = json.loads(ledger.read_text())
    assert evidence["case_id"] == case_id
    assert evidence["execution_error"] == \
        "batch_finalization_reserve_entered"
    assert evidence["extraction"] == {
        "attempt_count": 1,
        "recovered": False,
        "attempts": [{
            "attempt": 1,
            "status": "failed",
            "failure_category": "batch_finalization_reserve_entered",
        }],
    }


def test_reserve_larger_than_limit_publishes_truthful_receipt(tmp_path):
    """Immediate finalization still publishes complete, truthful artifacts."""
    case_id = "MIB-990002"
    input_dir = tmp_path / "input"
    _write_pdf(input_dir, case_id)
    pdf = input_dir / f"{case_id}.pdf"
    run_dir = tmp_path / "run"
    predictions = run_dir / "predictions.jsonl"
    ledger = run_dir / "ledger.jsonl"
    receipt_path = run_dir / "receipt.json"

    env = {key: value for key, value in os.environ.items()
           if not key.startswith("MIB_")}
    env.update({
        "OMP_NUM_THREADS": "1",
        "OPENBLAS_NUM_THREADS": "1",
        "MKL_NUM_THREADS": "1",
        "MIB_STUCK_SECS": "60",
        "MIB_STARTUP_GRACE": "60",
        "MIB_WATCHDOG_POLL": "0.1",
        "MIB_BATCH_LIMIT_SECS": "1",
        "MIB_FINALIZE_RESERVE_SECS": "2",
    })
    with mock.patch.dict(os.environ, env, clear=True):
        effective_config = PREDICT_MODULE._effective_run_config()
    entry = {
        "ordinal": 0,
        "case_id": case_id,
        "filename": pdf.name,
        "size": pdf.stat().st_size,
        "sha256": PREDICT_MODULE._sha256_file(pdf),
    }
    input_manifest_sha256 = PREDICT_MODULE._canonical_sha256(
        PREDICT_MODULE._input_manifest_identity([entry]))
    producer_sha = "a" * 40
    identity = {
        "schema": PREDICT_MODULE.RUN_IDENTITY_SCHEMA,
        "producer_git_sha": producer_sha,
        "image_id": "sha256:" + "b" * 64,
        "image_revision": producer_sha,
        "image_inspect_sha256": "c" * 64,
        "runtime_manifest_sha256": "d" * 64,
        "config_sha256": PREDICT_MODULE._canonical_sha256(effective_config),
        "input_manifest_sha256": input_manifest_sha256,
        "run_split": "dev",
        "run_nonce": "e" * 64,
    }
    identity_path = tmp_path / "identity.json"
    identity_path.write_text(json.dumps(identity))

    started = time.monotonic()
    result = subprocess.run(
        [sys.executable, str(PREDICT), str(input_dir), str(predictions),
         "--ledger", str(ledger),
         "--run-receipt", str(receipt_path),
         "--run-identity", str(identity_path), "--run-split", "dev"],
        env=env, text=True, capture_output=True, timeout=10)
    elapsed = time.monotonic() - started

    assert result.returncode == 0, result.stderr
    assert elapsed < 5
    assert "[batch-deadline] finalization reserve entered" in result.stdout
    assert "completed=0/1 backfilled=1 retries=skipped" in result.stdout
    assert json.loads(predictions.read_text())["case_id"] == case_id
    assert json.loads(ledger.read_text())["execution_error"] == \
        "batch_finalization_reserve_entered"
    receipt = json.loads(receipt_path.read_text())
    assert receipt["terminal_status"] == "completed"
    assert receipt["run_identity"] == identity
    assert receipt["artifacts"]["predictions"]["sha256"] == \
        PREDICT_MODULE._sha256_file(predictions)
    assert receipt["artifacts"]["evidence"]["sha256"] == \
        PREDICT_MODULE._sha256_file(ledger)


def test_unreapable_worker_wait_is_bounded():
    """Even a SIGKILL-resistant child cannot consume the finalization reserve."""
    process = _UnreapableProcess()
    shard = PREDICT_MODULE.Shard.__new__(PREDICT_MODULE.Shard)
    shard.finished = False
    shard.proc = process

    assert shard.stop() is True
    started = time.monotonic()
    assert shard.reap(started + 0.01) is False
    assert time.monotonic() - started < 0.5
    assert process.killed is True
    assert len(process.timeouts) == 1
    assert 0.0 <= process.timeouts[0] <= 0.01
    assert shard.finished is True


def test_watchdog_respawn_wait_cannot_cross_finalization_boundary():
    """The ordinary watchdog path must not block before main sees the limit."""
    process = _UnreapableProcess()
    shard = PREDICT_MODULE.Shard.__new__(PREDICT_MODULE.Shard)
    shard.idx = 0
    shard.proc = process
    shard.finished = False

    deadline = time.monotonic()
    started = time.monotonic()
    assert shard._respawn("heartbeat stale", stop_deadline=deadline) is True
    assert time.monotonic() - started < 0.5
    assert process.killed is True
    assert process.timeouts == [0.0]
    assert shard.finished is True
