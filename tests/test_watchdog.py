"""Watchdog verification with REAL injected hangs.

The submission's last single-point-of-failure is a PDF that hangs extraction:
exceptions are caught, but a hang would eat the 30,000s batch budget. Two
layers defend against it, and each is exercised here with an actual hang:

  layer 1  per-case SIGALRM in the worker (run_shard.py) — Python-level hangs
  layer 2  heartbeat watchdog in the parent (predict.py) — C-level hangs,
           simulated by a spin with SIGALRM blocked, plus worker crashes

Every test asserts the batch still emits one well-formed row per PDF.
"""
import json
import importlib.util
import os
import subprocess
import sys
import time
from pathlib import Path

import fitz
import pytest

from tools.native_artifact_binding import EFFECTIVE_CONFIG_DEFAULTS

ROOT = Path(__file__).resolve().parents[1]
PREDICT = ROOT / "scripts" / "predict.py"
RUN_SHARD = ROOT / "scripts" / "run_shard.py"

_SPEC = importlib.util.spec_from_file_location("mib_predict", PREDICT)
PREDICT_MODULE = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(PREDICT_MODULE)
_SHARD_SPEC = importlib.util.spec_from_file_location("mib_run_shard", RUN_SHARD)
RUN_SHARD_MODULE = importlib.util.module_from_spec(_SHARD_SPEC)
_SHARD_SPEC.loader.exec_module(RUN_SHARD_MODULE)

FALLBACK_NAME = "Tekdane Ixovara"


def _make_corpus(pdf_dir, n=8):
    """Native-text one-page PDFs; each carries a sponsor-letter sentence so a
    successfully extracted row is distinguishable from a fallback row."""
    names = ["Solmora Tekvoss", "Arikesh Xanul", "Mirazarn Orinax", "Tekdane Solix",
             "Nexkesh Arimora", "Ixovara Solnax", "Orimora Tekul", "Xanvoss Mirix"]
    for i in range(n):
        cid = f"MIB-9{i:05d}"
        doc = fitz.open()
        page = doc.new_page()
        page.insert_text((72, 100), "Sponsor Attestation Letter", fontsize=14)
        page.insert_text((72, 140), f"Case ID: {cid}", fontsize=11)
        page.insert_text(
            (72, 180),
            f"Sponsor SPN-1{i:03d} attests that {names[i]} is expected on Earth "
            f"for research.",
            fontsize=11)
        doc.save(pdf_dir / f"{cid}.pdf")
        doc.close()
    return [f"MIB-9{i:05d}" for i in range(n)]


def _run_predict(pdf_dir, out_path, extra_env, timeout=300):
    env = dict(os.environ, **extra_env)
    proc = subprocess.run(
        [sys.executable, str(PREDICT), str(pdf_dir), str(out_path)],
        env=env, capture_output=True, text=True, timeout=timeout)
    assert proc.returncode == 0, proc.stderr
    rows = [json.loads(l) for l in open(out_path)]
    return rows, proc.stdout


def _ledger(path):
    return {r["case_id"]: r for r in
            (json.loads(line) for line in open(path))}


def _check_complete(rows, case_ids):
    assert sorted(r["case_id"] for r in rows) == sorted(case_ids)
    for r in rows:
        assert r["adjudication"] in ("APPROVED", "DENIED", "NEEDS_REVIEW")
        assert 0.0 <= r["confidence"] <= 1.0


@pytest.fixture(scope="module")
def corpus(tmp_path_factory):
    pdf_dir = tmp_path_factory.mktemp("watchdog_pdfs")
    case_ids = _make_corpus(pdf_dir)
    return pdf_dir, case_ids


def test_no_hang_baseline(corpus, tmp_path):
    """Sanity: clean corpus, watchdog stays silent, extraction is real."""
    pdf_dir, case_ids = corpus
    rows, stdout = _run_predict(pdf_dir, tmp_path / "p.jsonl", {})
    _check_complete(rows, case_ids)
    assert "[watchdog]" not in stdout
    extracted = [r for r in rows if r["applicant_name"] != FALLBACK_NAME]
    assert len(extracted) == len(case_ids)


def test_successful_first_pass_output_is_byte_identical(corpus, tmp_path):
    """Enabling retry must be a no-op for every successful first-pass case."""
    pdf_dir, _ = corpus
    without = tmp_path / "without.jsonl"
    with_retry = tmp_path / "with.jsonl"
    _run_predict(pdf_dir, without, {"MIB_DISABLE_EXTRACTION_RETRY": "1"})
    _run_predict(pdf_dir, with_retry, {})
    assert with_retry.read_bytes() == without.read_bytes()


def test_planned_worker_recycling_is_byte_identical(corpus, tmp_path):
    """A lifecycle recycle resumes the durable tail without changing output."""
    pdf_dir, case_ids = corpus
    baseline = tmp_path / "baseline.jsonl"
    recycled = tmp_path / "recycled.jsonl"
    _run_predict(pdf_dir, baseline, {"MIB_WORKER_MAX_CASES": "48"})
    rows, stdout = _run_predict(
        pdf_dir, recycled, {"MIB_WORKER_MAX_CASES": "1"})
    _check_complete(rows, case_ids)
    assert recycled.read_bytes() == baseline.read_bytes()
    assert "skipping" not in stdout


def test_explicit_empty_success_is_not_retried():
    state = {"case_id": "MIB-999991", "pools": {}, "doc_notes": {},
             "extraction": {"attempts": [{"attempt": 1, "status": "success"}]}}
    assert PREDICT_MODULE._stub_category(state) is None


def test_legacy_empty_state_is_retryable():
    state = {"case_id": "MIB-999992", "pools": {}, "doc_notes": {}}
    assert PREDICT_MODULE._stub_category(state) == "recognizable_stub"


def test_error_summary_keeps_exception_type_and_root_tail():
    exc = RuntimeError("Traceback prefix\n/sensitive/incidental/path.py:12\n"
                       "pthread_create failed: Resource temporarily unavailable")
    summary = RUN_SHARD_MODULE._error_summary(exc)
    assert summary == ("RuntimeError: pthread_create failed: "
                       "Resource temporarily unavailable")
    assert "sensitive" not in summary
    assert len(summary) <= 400


def test_wrapped_case_timeout_is_not_misclassified_as_onnx_failure():
    wrapped = ("ONNXRuntimeError: Traceback from session.run "
               "scripts.run_shard.CaseTimeout")
    assert RUN_SHARD_MODULE._failure_category(wrapped) == "per_case_timeout"


def test_case_timeout_bypasses_best_effort_exception_handlers():
    assert issubclass(RUN_SHARD_MODULE.CaseTimeout, BaseException)
    assert not issubclass(RUN_SHARD_MODULE.CaseTimeout, Exception)


def test_campaign_timeout_defaults_are_synchronized(monkeypatch):
    assert RUN_SHARD_MODULE.CASE_TIMEOUT == 120
    assert RUN_SHARD_MODULE.MAX_CASES_PER_WORKER == 48
    assert RUN_SHARD_MODULE.RECYCLE_EXIT_CODE == 75
    assert PREDICT_MODULE.MAX_RETRY_CASES == 128
    assert PREDICT_MODULE.RETRY_CASE_TIMEOUT == 240
    assert PREDICT_MODULE.RETRY_BUDGET_SECS == 3600
    assert PREDICT_MODULE.STUCK_SECS == 150
    assert PREDICT_MODULE.WORKER_RECYCLE_EXIT_CODE == 75
    # Candidate count handles plausible transient bursts.  It intentionally
    # does not reserve 128 worst-case timeouts: the retry wall deadline is the
    # time guarantee and always preserves the finalization reserve.
    assert PREDICT_MODULE.RETRY_BUDGET_SECS < \
        PREDICT_MODULE.MAX_RETRY_CASES * PREDICT_MODULE.RETRY_CASE_TIMEOUT
    assert PREDICT_MODULE.RETRY_BUDGET_SECS <= \
        PREDICT_MODULE.BATCH_LIMIT_SECS - \
        PREDICT_MODULE.FINALIZE_RESERVE_SECS
    # The heartbeat watchdog must never fire before the in-worker SIGALRM, or a
    # slow-but-progressing case gets killed instead of degrading cleanly.
    assert PREDICT_MODULE.STUCK_SECS > RUN_SHARD_MODULE.CASE_TIMEOUT

    for key in list(os.environ):
        if key.startswith("MIB_"):
            monkeypatch.delenv(key, raising=False)
    for key in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS"):
        monkeypatch.setenv(key, "1")
    assert PREDICT_MODULE._effective_run_config() == \
        EFFECTIVE_CONFIG_DEFAULTS
    assert EFFECTIVE_CONFIG_DEFAULTS["MIB_NATIVE_SCAN_OCR"] == "1"
    assert PREDICT_MODULE._effective_run_config()[
        "MIB_NATIVE_SCAN_OCR"] == "1"


def test_worker_environment_overrides_inherited_native_thread_counts(
        monkeypatch):
    monkeypatch.setenv("OMP_NUM_THREADS", "12")
    monkeypatch.setenv("OPENBLAS_NUM_THREADS", "11")
    monkeypatch.setenv("MKL_NUM_THREADS", "10")
    env = PREDICT_MODULE._worker_env(MIB_EXTRACTION_ATTEMPT="2")
    assert {key: env[key] for key in (
        "OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS"
    )} == {
        "OMP_NUM_THREADS": "1", "OPENBLAS_NUM_THREADS": "1",
        "MKL_NUM_THREADS": "1",
    }
    assert env["MIB_EXTRACTION_ATTEMPT"] == "2"


def test_worker_path_transport_preserves_spaces_newlines_and_heartbeat(
        monkeypatch, tmp_path):
    paths = [
        tmp_path / "directory with spaces" / "MIB-000001.pdf",
        tmp_path / "directory\nwith newline" / "MIB-000002.pdf",
    ]
    listing = tmp_path / "paths.json"
    state_path = tmp_path / "states.jsonl"
    heartbeat = tmp_path / "heartbeat"
    PREDICT_MODULE._write_path_list(listing, paths)
    seen = []

    def extract(path):
        seen.append(path)
        return {"case_id": Path(path).stem, "pools": {}, "doc_notes": {}}

    monkeypatch.setattr(RUN_SHARD_MODULE, "extract_state", extract)
    monkeypatch.setattr(RUN_SHARD_MODULE.os, "fsync", lambda descriptor: None)
    assert RUN_SHARD_MODULE.main(
        str(listing), str(state_path), str(heartbeat)) == 0
    assert seen == [str(path) for path in paths]
    assert PREDICT_MODULE._read_heartbeat(heartbeat) == str(paths[-1])
    rows = [json.loads(line) for line in state_path.read_text().splitlines()]
    assert [row["case_id"] for row in rows] == ["MIB-000001", "MIB-000002"]


def test_legacy_worker_path_list_preserves_spaces(tmp_path):
    paths = [tmp_path / "one folder" / "MIB-000001.pdf",
             tmp_path / "two folder" / "MIB-000002.pdf"]
    listing = tmp_path / "legacy.txt"
    listing.write_text("\n".join(str(path) for path in paths))
    assert RUN_SHARD_MODULE._read_pdf_list(listing) == [str(p) for p in paths]


def test_governed_timeout_records_the_actual_active_ceiling(
        monkeypatch, tmp_path):
    pdf = tmp_path / "MIB-000001.pdf"
    listing = tmp_path / "paths.json"
    state_path = tmp_path / "states.jsonl"
    PREDICT_MODULE._write_path_list(listing, [pdf])
    (tmp_path / RUN_SHARD_MODULE.GOVERNOR_LEVEL_FILE).write_text("3")
    alarms = []

    def timeout(_path):
        raise RUN_SHARD_MODULE.CaseTimeout()

    monkeypatch.setattr(RUN_SHARD_MODULE, "extract_state", timeout)
    monkeypatch.setattr(RUN_SHARD_MODULE.signal, "alarm", alarms.append)
    monkeypatch.setattr(RUN_SHARD_MODULE.os, "fsync", lambda descriptor: None)
    assert RUN_SHARD_MODULE.main(str(listing), str(state_path)) == 0
    state = json.loads(state_path.read_text())
    assert alarms == [60, 0]
    assert state["error"] == "per_case_timeout(60s)"
    assert state["extraction"]["attempts"][-1]["error"] == \
        "per_case_timeout(60s)"


def test_planned_recycle_fsyncs_completed_rows_before_tail_resume(
        monkeypatch, tmp_path):
    paths = [tmp_path / f"MIB-00000{number}.pdf"
             for number in (1, 2, 3)]
    listing = tmp_path / "slice.txt"
    listing.write_text("\n".join(str(path) for path in paths))
    state_path = tmp_path / "states.jsonl"
    calls = []
    fsync_calls = []

    def extract(path):
        case_id = Path(path).stem
        calls.append(case_id)
        return {"case_id": case_id, "pools": {"x": []}, "doc_notes": {}}

    monkeypatch.setattr(RUN_SHARD_MODULE, "MAX_CASES_PER_WORKER", 2)
    monkeypatch.setattr(RUN_SHARD_MODULE, "extract_state", extract)
    monkeypatch.setattr(RUN_SHARD_MODULE.os, "fsync",
                        lambda descriptor: fsync_calls.append(descriptor))

    assert RUN_SHARD_MODULE.main(str(listing), str(state_path)) == \
        RUN_SHARD_MODULE.RECYCLE_EXIT_CODE
    assert calls == ["MIB-000001", "MIB-000002"]
    assert len(fsync_calls) == 2
    rows = [json.loads(line) for line in state_path.read_text().splitlines()]
    assert [row["case_id"] for row in rows] == calls


def test_session_failure_row_is_durable_before_worker_recycles(
        monkeypatch, tmp_path):
    first = tmp_path / "MIB-000001.pdf"
    tail = tmp_path / "MIB-000002.pdf"
    listing = tmp_path / "slice.txt"
    listing.write_text(f"{first}\n{tail}\n")
    state_path = tmp_path / "states.jsonl"
    calls = []

    def fail_session(path):
        calls.append(Path(path).stem)
        raise RuntimeError("injected_onnx_session_failure")

    fsync_calls = []
    monkeypatch.setattr(RUN_SHARD_MODULE, "extract_state", fail_session)
    monkeypatch.setattr(RUN_SHARD_MODULE.os, "fsync",
                        lambda descriptor: fsync_calls.append(descriptor))
    rc = RUN_SHARD_MODULE.main(str(listing), str(state_path))

    assert rc == RUN_SHARD_MODULE.RECYCLE_EXIT_CODE
    assert calls == ["MIB-000001"]
    assert len(fsync_calls) == 1
    rows = [json.loads(line) for line in state_path.read_text().splitlines()]
    assert len(rows) == 1 and rows[0]["case_id"] == "MIB-000001"
    assert rows[0]["extraction"]["attempts"][-1] == {
        "attempt": 1,
        "status": "failed",
        "failure_category": "recognizer_session_error",
        "error": "RuntimeError: injected_onnx_session_failure",
    }


def test_generic_extraction_failure_does_not_recycle_worker(
        monkeypatch, tmp_path):
    paths = [tmp_path / f"MIB-00000{number}.pdf" for number in (1, 2)]
    listing = tmp_path / "slice.txt"
    listing.write_text("\n".join(str(path) for path in paths))
    state_path = tmp_path / "states.jsonl"
    calls = []

    def extract(path):
        case_id = Path(path).stem
        calls.append(case_id)
        if len(calls) == 1:
            raise RuntimeError("ordinary_python_failure")
        return {"case_id": case_id, "pools": {"x": []}, "doc_notes": {}}

    monkeypatch.setattr(RUN_SHARD_MODULE, "extract_state", extract)
    monkeypatch.setattr(RUN_SHARD_MODULE.os, "fsync", lambda descriptor: None)
    assert RUN_SHARD_MODULE.main(str(listing), str(state_path)) == 0
    assert calls == ["MIB-000001", "MIB-000002"]
    rows = [json.loads(line) for line in state_path.read_text().splitlines()]
    assert [row["case_id"] for row in rows] == calls


def test_parent_recycle_exit_resumes_only_durable_unfinished_tail(
        monkeypatch, tmp_path):
    pdfs = [str(tmp_path / f"MIB-00000{number}.pdf")
            for number in (1, 2, 3)]
    state_file = tmp_path / "state0_g1.jsonl"
    state_file.write_text(json.dumps({
        "case_id": "MIB-000001", "pools": {}, "doc_notes": {},
        "error": "RuntimeError: injected_onnx_session_failure",
        "extraction": {"attempts": [{
            "attempt": 1, "status": "failed",
            "failure_category": "recognizer_session_error",
        }]},
    }) + "\n")
    heartbeat = tmp_path / "hb0.txt"
    heartbeat.write_text(pdfs[0])

    class RecycledProcess:
        def poll(self):
            return PREDICT_MODULE.WORKER_RECYCLE_EXIT_CODE

    shard = PREDICT_MODULE.Shard.__new__(PREDICT_MODULE.Shard)
    shard.tmp, shard.idx, shard.pdfs = tmp_path, 0, pdfs
    shard.hb, shard.gen, shard.no_progress = heartbeat, 1, 0
    shard.state_files = [state_file]
    shard.finished, shard.proc, shard.started = False, RecycledProcess(), 0.0
    respawned = []
    monkeypatch.setattr(shard, "_spawn",
                        lambda remaining: respawned.append(list(remaining)))

    shard.tick()
    assert respawned == [pdfs[1:]]
    assert json.loads(state_file.read_text())["case_id"] == "MIB-000001"


def test_run_receipt_requires_complete_identity_and_explicit_thread_pins(
        monkeypatch):
    argv = ["/in", "/out", "--ledger", "/ledger",
            "--run-receipt", "/receipt"]
    with pytest.raises(SystemExit, match="requires --run-identity"):
        PREDICT_MODULE._parse_args(argv)

    for key in list(os.environ):
        if key.startswith("MIB_") or key in {
                "OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS"}:
            monkeypatch.delenv(key, raising=False)
    with pytest.raises(SystemExit, match="explicit OMP_NUM_THREADS=1"):
        PREDICT_MODULE._effective_run_config()
    for key in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS"):
        monkeypatch.setenv(key, "1")
    assert PREDICT_MODULE._effective_run_config()["OPENBLAS_NUM_THREADS"] == "1"


def test_producer_receipt_binds_identity_config_inputs_split_and_nonce(
        monkeypatch, tmp_path):
    for key in list(os.environ):
        if key.startswith("MIB_"):
            monkeypatch.delenv(key, raising=False)
    for key in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS"):
        monkeypatch.setenv(key, "1")
    input_dir = tmp_path / "input"
    input_dir.mkdir()
    pdf = input_dir / "MIB-000001.pdf"
    pdf.write_bytes(b"exact test input")
    effective = PREDICT_MODULE._effective_run_config()
    entry = {
        "ordinal": 0,
        "case_id": "MIB-000001",
        "filename": pdf.name,
        "size": pdf.stat().st_size,
        "sha256": PREDICT_MODULE._sha256_file(pdf),
    }
    config_hash = PREDICT_MODULE._canonical_sha256(effective)
    input_hash = PREDICT_MODULE._canonical_sha256(
        PREDICT_MODULE._input_manifest_identity([entry]))
    nonce = "d" * 64
    identity = {
        "schema": "mib-run-identity-v1",
        "producer_git_sha": "a" * 40,
        "image_id": "sha256:" + "b" * 64,
        "image_revision": "a" * 40,
        "image_inspect_sha256": "c" * 64,
        "runtime_manifest_sha256": "e" * 64,
        "config_sha256": config_hash,
        "input_manifest_sha256": input_hash,
        "run_split": "dev",
        "run_nonce": nonce,
    }
    identity_path = tmp_path / "identity.json"
    identity_path.write_text(json.dumps(identity))
    run_dir = tmp_path / "run"
    receipt_path = run_dir / "receipt.json"
    predictions_path = run_dir / "predictions.jsonl"
    ledger_path = run_dir / "ledger.jsonl"
    prepared = PREDICT_MODULE._prepare_run_receipt(
        receipt_path, identity_path, input_dir, [str(pdf)],
        predictions_path, ledger_path, 1, "dev")
    assert run_dir.is_dir()
    assert list(run_dir.iterdir()) == []
    assert not receipt_path.exists()
    predictions_path.write_bytes(b'{"case_id":"MIB-000001"}\n')
    ledger_path.write_bytes(b'{"case_id":"MIB-000001"}\n')
    PREDICT_MODULE._publish_run_receipt(prepared)
    receipt = json.loads(receipt_path.read_text())
    assert receipt["schema"] == "mib-run-receipt-v2"
    assert receipt["terminal_status"] == "completed"
    assert receipt["run_identity"] == identity
    assert receipt["run_nonce"] == nonce
    assert receipt["run_split"] == "dev"
    assert receipt["config_sha256"] == config_hash
    assert receipt["input_manifest_sha256"] == input_hash
    assert receipt["artifacts"]["predictions"] == {
        "filename": predictions_path.name,
        "size": predictions_path.stat().st_size,
        "sha256": PREDICT_MODULE._sha256_file(predictions_path),
    }
    from tools import native_artifact_binding as binding
    entries = binding.input_manifest([pdf])
    workers, order = binding._validate_run_receipt(
        receipt, entries,
        binding.canonical_effective_config({}, environment={}),
        predictions_path, ledger_path, identity)
    assert workers == 1 and order == ["MIB-000001"]


def test_bound_run_requires_new_directory_and_exact_completion_contents(
        monkeypatch, tmp_path):
    for key in list(os.environ):
        if key.startswith("MIB_"):
            monkeypatch.delenv(key, raising=False)
    for key in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS"):
        monkeypatch.setenv(key, "1")
    input_dir = tmp_path / "inputs"
    input_dir.mkdir()
    pdf = input_dir / "MIB-000001.pdf"
    pdf.write_bytes(b"fixed input")
    effective = PREDICT_MODULE._effective_run_config()
    entry = {
        "ordinal": 0, "case_id": pdf.stem, "filename": pdf.name,
        "size": pdf.stat().st_size,
        "sha256": PREDICT_MODULE._sha256_file(pdf),
    }
    identity = {
        "schema": "mib-run-identity-v1",
        "producer_git_sha": "a" * 40,
        "image_id": "sha256:" + "b" * 64,
        "image_revision": "a" * 40,
        "image_inspect_sha256": "c" * 64,
        "runtime_manifest_sha256": "d" * 64,
        "config_sha256": PREDICT_MODULE._canonical_sha256(effective),
        "input_manifest_sha256": PREDICT_MODULE._canonical_sha256(
            PREDICT_MODULE._input_manifest_identity([entry])),
        "run_split": "dev", "run_nonce": "e" * 64,
    }
    identity_path = tmp_path / "identity.json"
    identity_path.write_text(json.dumps(identity))

    existing = tmp_path / "existing"
    existing.mkdir()
    with pytest.raises(SystemExit, match="run directory already exists"):
        PREDICT_MODULE._prepare_run_receipt(
            existing / "receipt.json", identity_path, input_dir, [str(pdf)],
            existing / "predictions.jsonl", existing / "evidence.jsonl", 1,
            "dev")

    collision = tmp_path / "collision"
    with pytest.raises(SystemExit, match="distinct sibling files"):
        PREDICT_MODULE._prepare_run_receipt(
            collision / "receipt.json", identity_path, input_dir, [str(pdf)],
            collision / "same.jsonl", collision / "same.jsonl", 1, "dev")
    assert not collision.exists()

    run_dir = tmp_path / "unexpected"
    prepared = PREDICT_MODULE._prepare_run_receipt(
        run_dir / "receipt.json", identity_path, input_dir, [str(pdf)],
        run_dir / "predictions.jsonl", run_dir / "evidence.jsonl", 1, "dev")
    (run_dir / "predictions.jsonl").write_text("{}\n")
    (run_dir / "evidence.jsonl").write_text("{}\n")
    (run_dir / "stale.jsonl").write_text("stale\n")
    with pytest.raises(SystemExit, match="unexpected or missing run artifacts"):
        PREDICT_MODULE._publish_run_receipt(prepared)
    assert not (run_dir / "receipt.json").exists()

    changed_dir = tmp_path / "changed-input"
    prepared = PREDICT_MODULE._prepare_run_receipt(
        changed_dir / "receipt.json", identity_path, input_dir, [str(pdf)],
        changed_dir / "predictions.jsonl", changed_dir / "evidence.jsonl", 1,
        "dev")
    (changed_dir / "predictions.jsonl").write_text("{}\n")
    (changed_dir / "evidence.jsonl").write_text("{}\n")
    pdf.write_bytes(b"mutated after preflight")
    with pytest.raises(SystemExit, match="input bytes changed"):
        PREDICT_MODULE._publish_run_receipt(prepared)
    assert not (changed_dir / "receipt.json").exists()


def test_decision_exception_is_visible_to_execution_failure_gate():
    detail = PREDICT_MODULE._failure_detail(
        {"case_id": "MIB-000001"}, ValueError("sensitive detail"))
    assert detail == {
        "reasons": ["decision_error"],
        "execution_error": "decision_error(ValueError)",
    }
    assert "sensitive" not in json.dumps(detail)


def test_retry_candidate_cap_and_already_expired_batch_deadline(
        monkeypatch, tmp_path):
    legacy = lambda cid: {"case_id": cid, "pools": {}, "doc_notes": {}}
    assert PREDICT_MODULE.MAX_RETRY_CASES == 128
    states = [legacy(f"MIB-{800000 + i:06d}") for i in range(129)]
    monkeypatch.setattr(PREDICT_MODULE, "BATCH_LIMIT_SECS", 1000)
    monkeypatch.setattr(PREDICT_MODULE, "FINALIZE_RESERVE_SECS", 0)
    capped = PREDICT_MODULE._retry_failed_states(
        states, [], tmp_path, time.monotonic())
    assert all(s["extraction"]["attempts"][-1]["failure_category"] ==
               "source_pdf_missing" for s in capped[:128])
    assert capped[128]["extraction"]["attempts"][-1]["failure_category"] == \
        "retry_budget_exhausted"

    monkeypatch.setattr(PREDICT_MODULE, "BATCH_LIMIT_SECS", 0)
    deadline = PREDICT_MODULE._retry_failed_states(
        [legacy("MIB-999995")], [], tmp_path, time.monotonic())
    assert deadline[0]["extraction"]["attempt_count"] == 1
    assert deadline[0]["extraction"]["attempts"][-1]["status"] == "not_attempted"
    assert deadline[0]["extraction"]["attempts"][-1]["failure_category"] == \
        "retry_budget_exhausted"


def test_more_than_eight_quick_retry_candidates_recover(monkeypatch, tmp_path):
    count = 12
    pdfs = []
    states = []
    for i in range(count):
        cid = f"MIB-{810000 + i:06d}"
        pdf = tmp_path / f"{cid}.pdf"
        pdf.write_bytes(b"retry fixture")
        pdfs.append(str(pdf))
        states.append({"case_id": cid, "pools": {}, "doc_notes": {},
                       "error": "worker exited"})

    launched = []

    def quick_worker(command, env, timeout):
        launched.append((command, env, timeout))
        return 0

    def recovered_state(path, cid):
        return {"case_id": cid, "pools": {"passport": [cid]},
                "doc_notes": {}, "extraction": {
                    "attempt_count": 1, "recovered": False,
                    "attempts": [{"attempt": 2, "status": "success"}]}}

    monkeypatch.setattr(PREDICT_MODULE, "_run_retry_worker", quick_worker)
    monkeypatch.setattr(PREDICT_MODULE, "_read_retry_state", recovered_state)
    recovered = PREDICT_MODULE._retry_failed_states(
        states, pdfs, tmp_path, time.monotonic())

    assert len(launched) == count
    assert all(state["extraction"]["recovered"] is True
               for state in recovered)
    assert all(state["extraction"]["attempt_count"] == 2
               for state in recovered)


def test_retry_wall_deadline_stops_candidates_and_preserves_fallback(
        monkeypatch, tmp_path):
    count = 12
    pdfs = []
    states = []
    for i in range(count):
        cid = f"MIB-{820000 + i:06d}"
        pdf = tmp_path / f"{cid}.pdf"
        pdf.write_bytes(b"retry fixture")
        pdfs.append(str(pdf))
        states.append({"case_id": cid, "pools": {}, "doc_notes": {},
                       "error": "worker exited"})

    now = [0.0]
    launched = []

    def bounded_worker(command, env, timeout):
        launched.append(timeout)
        now[0] += 1.0
        return 0

    def recovered_state(path, cid):
        return {"case_id": cid, "pools": {"passport": [cid]},
                "doc_notes": {}, "extraction": {
                    "attempt_count": 1, "recovered": False,
                    "attempts": [{"attempt": 2, "status": "success"}]}}

    monkeypatch.setattr(PREDICT_MODULE.time, "monotonic", lambda: now[0])
    monkeypatch.setattr(PREDICT_MODULE, "RETRY_BUDGET_SECS", 5.0)
    monkeypatch.setattr(PREDICT_MODULE, "BATCH_LIMIT_SECS", 100.0)
    monkeypatch.setattr(PREDICT_MODULE, "FINALIZE_RESERVE_SECS", 10.0)
    monkeypatch.setattr(PREDICT_MODULE, "_run_retry_worker", bounded_worker)
    monkeypatch.setattr(PREDICT_MODULE, "_read_retry_state", recovered_state)

    result = PREDICT_MODULE._retry_failed_states(
        states, pdfs, tmp_path, batch_started=0.0)

    assert len(launched) == 5
    assert all(state["extraction"]["recovered"] is True
               for state in result[:5])
    assert all(state["extraction"]["recovered"] is False
               for state in result[5:])
    assert all(state["extraction"]["attempts"][-1] == {
        "attempt": 2, "status": "not_attempted",
        "failure_category": "retry_budget_exhausted"}
        for state in result[5:])


def test_default_retry_wall_attempts_full_candidate_ceiling_at_burst_pace(
        monkeypatch, tmp_path):
    """The wall, not just the count cap, covers a realistic 128-case burst."""
    count = PREDICT_MODULE.MAX_RETRY_CASES
    pdfs = []
    states = []
    for i in range(count):
        cid = f"MIB-{830000 + i:06d}"
        pdf = tmp_path / f"{cid}.pdf"
        pdf.write_bytes(b"retry fixture")
        pdfs.append(str(pdf))
        states.append({"case_id": cid, "pools": {}, "doc_notes": {},
                       "error": "worker exited"})

    now = [0.0]
    launched = []

    def burst_worker(command, env, timeout):
        launched.append(timeout)
        # Model a 20-second fresh-process recovery, except one full per-case
        # timeout. Even this complete 128-candidate burst remains comfortably
        # inside the default one-hour wall.
        if len(launched) == count // 2:
            now[0] += PREDICT_MODULE.RETRY_CASE_TIMEOUT
            raise subprocess.TimeoutExpired(command, timeout)
        now[0] += 20.0
        return 0

    def recovered_state(path, cid):
        return {"case_id": cid, "pools": {"passport": [cid]},
                "doc_notes": {}, "extraction": {
                    "attempt_count": 1, "recovered": False,
                    "attempts": [{"attempt": 2, "status": "success"}]}}

    monkeypatch.setattr(PREDICT_MODULE.time, "monotonic", lambda: now[0])
    monkeypatch.setattr(PREDICT_MODULE, "BATCH_LIMIT_SECS", 30000.0)
    monkeypatch.setattr(PREDICT_MODULE, "FINALIZE_RESERVE_SECS", 60.0)
    monkeypatch.setattr(PREDICT_MODULE, "_run_retry_worker", burst_worker)
    monkeypatch.setattr(PREDICT_MODULE, "_read_retry_state", recovered_state)

    result = PREDICT_MODULE._retry_failed_states(
        states, pdfs, tmp_path, batch_started=0.0)

    assert len(launched) == count
    assert now[0] == (count - 1) * 20.0 + \
        PREDICT_MODULE.RETRY_CASE_TIMEOUT
    assert sum(state["extraction"]["recovered"] is True
               for state in result) == count - 1
    assert sum(state["extraction"]["attempts"][-1].get(
        "failure_category") == "retry_process_timeout"
        for state in result) == 1
    assert all(state["extraction"]["attempts"][-1].get(
        "failure_category") != "retry_budget_exhausted"
        for state in result)


def test_retry_candidates_follow_original_pdf_order():
    def failed(cid):
        return {"case_id": cid, "pools": {}, "doc_notes": {},
                "error": "RuntimeError: failed"}

    states = [failed("MIB-000003"), failed("MIB-000001"),
              {"case_id": "MIB-000002", "pools": {"x": []},
               "doc_notes": {}}]
    pdfs = ["/in/MIB-000001.pdf", "/in/MIB-000002.pdf",
            "/in/MIB-000003.pdf"]
    candidates = PREDICT_MODULE._retry_candidates(states, pdfs)
    assert [row[1]["case_id"] for row in candidates] == \
        ["MIB-000001", "MIB-000003"]


def test_retry_timeout_cleanup_tolerates_already_exited_process(monkeypatch):
    class RacedProcess:
        pid = 424242

        def __init__(self):
            self.waits = 0

        def wait(self, timeout=None):
            self.waits += 1
            if self.waits == 1:
                raise subprocess.TimeoutExpired(["retry-worker"], timeout)
            return 0

    raced = RacedProcess()
    monkeypatch.setattr(PREDICT_MODULE.subprocess, "Popen",
                        lambda *args, **kwargs: raced)
    kill_calls = []

    def already_gone(pid, sig):
        kill_calls.append((pid, sig))
        raise ProcessLookupError(pid)

    monkeypatch.setattr(PREDICT_MODULE.os, "killpg", already_gone)
    with pytest.raises(subprocess.TimeoutExpired):
        PREDICT_MODULE._run_retry_worker(["retry-worker"], {}, 0.01)
    assert kill_calls == [(raced.pid, PREDICT_MODULE.signal.SIGKILL)]
    assert raced.waits == 2


def test_retry_timeout_kills_worker_process_group(tmp_path):
    """A future retry helper process cannot outlive the parent wall cap."""
    group_path = tmp_path / "process-group.json"
    helper = (
        "import json,os,pathlib,subprocess,sys,time; "
        "child=subprocess.Popen([sys.executable,'-c',"
        "'import time; time.sleep(60)']); "
        "data={'parent_pid':os.getpid(),'parent_pgid':os.getpgrp(),"
        "'child_pid':child.pid,'child_pgid':os.getpgid(child.pid)}; "
        f"pathlib.Path({str(group_path)!r}).write_text(json.dumps(data)); "
        "time.sleep(60)"
    )
    started = time.monotonic()
    with pytest.raises(subprocess.TimeoutExpired):
        PREDICT_MODULE._run_retry_worker(
            [sys.executable, "-c", helper], dict(os.environ), 0.5)
    elapsed = time.monotonic() - started
    assert group_path.exists()
    group = json.loads(group_path.read_text())
    assert group["parent_pgid"] == group["parent_pid"]
    assert group["child_pgid"] == group["parent_pid"]
    child_pid = str(group["child_pid"])

    # A killed orphan may briefly remain as a zombie until PID 1 reaps it; a
    # zombie is not running and cannot escape the retry cap.
    status = ""
    deadline = time.monotonic() + 2
    while time.monotonic() < deadline:
        stat_path = Path(f"/proc/{child_pid}/stat")
        if stat_path.exists():
            fields = stat_path.read_text().split()
            status = fields[2] if len(fields) > 2 else ""
            gone = not status or status == "Z"
        else:
            try:
                os.kill(int(child_pid), 0)
                gone = False
            except ProcessLookupError:
                gone = True
        if gone:
            break
        time.sleep(0.05)
    assert gone
    assert elapsed < 2.5


@pytest.mark.parametrize(
    ("raised", "category"),
    [(OSError(11, "fork unavailable"), "retry_worker_launch_error"),
     (ValueError("unexpected retry defect"), "retry_worker_exception")],
)
def test_retry_worker_launch_exception_keeps_primary_fallback(
        monkeypatch, tmp_path, raised, category):
    def primary(cid):
        return {
            "case_id": cid, "pools": {}, "doc_notes": {},
            "error": "RuntimeError: primary extraction failed",
            "extraction": {
                "attempt_count": 1, "recovered": False,
                "attempts": [{"attempt": 1, "status": "failed",
                              "failure_category": "extraction_exception"}],
            },
        }

    case_ids = ["MIB-999996", "MIB-999997"]
    primaries = [primary(cid) for cid in case_ids]

    def fail_launch(*args, **kwargs):
        raise raised

    monkeypatch.setattr(PREDICT_MODULE, "_run_retry_worker", fail_launch)
    result = PREDICT_MODULE._retry_failed_states(
        primaries, [str(tmp_path / f"{cid}.pdf") for cid in case_ids],
        tmp_path, time.monotonic())
    assert [state["case_id"] for state in result] == case_ids
    for state, original in zip(result, primaries):
        assert state["pools"] == original["pools"]
        assert state["doc_notes"] == original["doc_notes"]
        extraction = state["extraction"]
        assert extraction["attempt_count"] == 2
        assert extraction["recovered"] is False
        assert extraction["attempts"][-1]["status"] == "failed"
        assert extraction["attempts"][-1]["failure_category"] == category
        assert type(raised).__name__ in extraction["attempts"][-1]["error"]


def test_retry_worker_setup_error_keeps_primary_and_continues(
        monkeypatch, tmp_path):
    """ENOSPC preparing one retry cannot abort or suppress a later retry."""
    def primary(cid):
        return {
            "case_id": cid, "pools": {}, "doc_notes": {},
            "error": "RuntimeError: primary extraction failed",
            "extraction": {
                "attempt_count": 1, "recovered": False,
                "attempts": [{"attempt": 1, "status": "failed",
                              "failure_category": "extraction_exception"}],
            },
        }

    case_ids = ["MIB-999994", "MIB-999995"]
    primaries = [primary(cid) for cid in case_ids]
    real_write_text = Path.write_text

    def fail_first_list_write(path, *args, **kwargs):
        if path.name == "retry_0.txt":
            raise OSError(28, "No space left on device")
        return real_write_text(path, *args, **kwargs)

    launched = []

    def recover_second(command, env, timeout):
        launched.append(command)
        state_file = Path(command[3])
        recovered = {
            "case_id": case_ids[1],
            "pools": {"sponsor_letter": ["recovered evidence"]},
            "doc_notes": {},
            "extraction": {
                "attempt_count": 1, "recovered": False,
                "attempts": [{"attempt": 2, "status": "success"}],
            },
        }
        real_write_text(state_file, json.dumps(recovered) + "\n")
        return 0

    monkeypatch.setattr(Path, "write_text", fail_first_list_write)
    monkeypatch.setattr(PREDICT_MODULE, "_run_retry_worker", recover_second)
    result = PREDICT_MODULE._retry_failed_states(
        primaries, [str(tmp_path / f"{cid}.pdf") for cid in case_ids],
        tmp_path, time.monotonic())

    first_attempt = result[0]["extraction"]["attempts"][-1]
    assert result[0]["pools"] == primaries[0]["pools"]
    assert result[0]["extraction"]["recovered"] is False
    assert result[0]["extraction"]["attempt_count"] == 1
    assert first_attempt["status"] == "not_attempted"
    assert first_attempt["failure_category"] == "retry_worker_setup_error"
    assert "OSError" in first_attempt["error"]
    assert "No space left on device" in first_attempt["error"]

    assert len(launched) == 1
    assert Path(launched[0][2]).name == "retry_1.txt"
    assert result[1]["pools"] == {"sponsor_letter": ["recovered evidence"]}
    assert result[1]["extraction"]["attempt_count"] == 2
    assert result[1]["extraction"]["recovered"] is True
    assert [a["status"] for a in result[1]["extraction"]["attempts"]] == \
        ["failed", "success"]


def test_retry_result_read_error_is_contained_and_truthfully_recorded(
        monkeypatch, tmp_path):
    cid = "MIB-999989"
    primary = {
        "case_id": cid, "pools": {}, "doc_notes": {},
        "error": "RuntimeError: primary extraction failed",
        "extraction": {
            "attempt_count": 1, "recovered": False,
            "attempts": [{"attempt": 1, "status": "failed",
                          "failure_category": "extraction_exception"}],
        },
    }
    monkeypatch.setattr(PREDICT_MODULE, "_run_retry_worker",
                        lambda command, env, timeout: 0)

    def unreadable_result(path, case_id):
        raise OSError(5, "retry state unreadable")

    monkeypatch.setattr(PREDICT_MODULE, "_read_retry_state", unreadable_result)
    result = PREDICT_MODULE._retry_failed_states(
        [primary], [str(tmp_path / f"{cid}.pdf")], tmp_path,
        time.monotonic())
    assert result[0]["pools"] == {}
    assert result[0]["extraction"]["recovered"] is False
    attempt = result[0]["extraction"]["attempts"][-1]
    assert attempt["status"] == "failed"
    assert attempt["failure_category"] == "retry_worker_result_error"
    assert "OSError" in attempt["error"]


def test_retry_logging_broken_pipe_cannot_replace_recovery(
        monkeypatch, tmp_path):
    cid = "MIB-999993"
    primary = {
        "case_id": cid, "pools": {}, "doc_notes": {},
        "error": "RuntimeError: primary extraction failed",
        "extraction": {
            "attempt_count": 1, "recovered": False,
            "attempts": [{"attempt": 1, "status": "failed",
                          "failure_category": "extraction_exception"}],
        },
    }
    real_write_text = Path.write_text

    def recover(command, env, timeout):
        recovered = {
            "case_id": cid,
            "pools": {"sponsor_letter": ["recovered evidence"]},
            "doc_notes": {},
            "extraction": {
                "attempts": [{"attempt": 2, "status": "success"}],
            },
        }
        real_write_text(Path(command[3]), json.dumps(recovered) + "\n")
        return 0

    def broken_pipe(*args, **kwargs):
        raise BrokenPipeError("diagnostic consumer closed")

    monkeypatch.setattr(PREDICT_MODULE, "_run_retry_worker", recover)
    monkeypatch.setitem(PREDICT_MODULE.__dict__, "print", broken_pipe)
    result = PREDICT_MODULE._retry_failed_states(
        [primary], [str(tmp_path / f"{cid}.pdf")],
        tmp_path, time.monotonic())

    assert result[0]["pools"] == {"sponsor_letter": ["recovered evidence"]}
    assert result[0]["extraction"]["attempt_count"] == 2
    assert result[0]["extraction"]["recovered"] is True
    assert [a["status"] for a in result[0]["extraction"]["attempts"]] == \
        ["failed", "success"]


def test_recognizable_stub_recovers_in_fresh_process(corpus, tmp_path):
    pdf_dir, case_ids = corpus
    cid = case_ids[3]
    ledger_path = tmp_path / "ledger.jsonl"
    rows, stdout = _run_predict(
        pdf_dir, tmp_path / "p.jsonl",
        {"MIB_TEST_STUB_CASE": cid, "MIB_LEDGER": str(ledger_path)})
    _check_complete(rows, case_ids)
    assert f"[retry] {cid} primary=recognizable_stub result=recovered" in stdout
    recovered = next(r for r in rows if r["case_id"] == cid)
    assert recovered["applicant_name"] != FALLBACK_NAME
    extraction = _ledger(ledger_path)[cid]["extraction"]
    assert extraction["attempt_count"] == 2
    assert extraction["recovered"] is True
    assert [a["status"] for a in extraction["attempts"]] == ["failed", "success"]


def test_onnx_session_failure_recovers_in_fresh_process(corpus, tmp_path):
    """A recognizer/session exception on attempt 1 is retried with a new
    process, whose fresh OCR globals recover the real extraction."""
    pdf_dir, case_ids = corpus
    cid = case_ids[0]
    source = fitz.open(pdf_dir / f"{cid}.pdf")
    pix = source[0].get_pixmap(matrix=fitz.Matrix(2, 2), alpha=False)
    scan_dir = tmp_path / "scan"
    scan_dir.mkdir()
    scan = fitz.open()
    page = scan.new_page(width=source[0].rect.width, height=source[0].rect.height)
    page.insert_image(page.rect, stream=pix.tobytes("png"))
    scan.save(scan_dir / f"{cid}.pdf")
    scan.close()
    source.close()

    ledger_path = tmp_path / "ledger.jsonl"
    rows, stdout = _run_predict(
        scan_dir, tmp_path / "p.jsonl",
        {"MIB_TEST_OCR_SESSION_FAIL_CASE": cid,
         "MIB_LEDGER": str(ledger_path)}, timeout=180)
    _check_complete(rows, [cid])
    assert f"[retry] {cid} primary=recognizer_session_error result=recovered" in stdout
    extraction = _ledger(ledger_path)[cid]["extraction"]
    assert extraction["attempt_count"] == 2
    assert extraction["recovered"] is True
    assert extraction["attempts"][0]["failure_category"] == \
        "recognizer_session_error"


def test_native_view_onnx_retry_matches_clean_state_and_provenance(
        corpus, tmp_path):
    """The P0-B fresh-process retry must preserve the P0-C physical view."""
    pdf_dir, case_ids = corpus
    cid = case_ids[0]
    source = fitz.open(pdf_dir / f"{cid}.pdf")
    pix = source[0].get_pixmap(matrix=fitz.Matrix(2, 2), alpha=False)
    scan_dir = tmp_path / "native_scan"
    scan_dir.mkdir()
    scan = fitz.open()
    page = scan.new_page(width=source[0].rect.width,
                         height=source[0].rect.height)
    xref = page.insert_image(page.rect, stream=pix.tobytes("png"))
    scan.xref_set_key(xref, "ColorSpace", "/DeviceRGB")
    scan.xref_set_key(xref, "DecodeParms", "null")
    scan.save(scan_dir / f"{cid}.pdf")
    scan.close()
    source.close()

    clean_ledger = tmp_path / "native.clean.ledger.jsonl"
    retry_ledger = tmp_path / "native.retry.ledger.jsonl"
    clean_rows, _ = _run_predict(
        scan_dir, tmp_path / "native.clean.jsonl",
        {"MIB_NATIVE_SCAN_OCR": "1", "MIB_PIXMATCH": "0",
         "MIB_LEDGER": str(clean_ledger)}, timeout=180)
    retry_rows, stdout = _run_predict(
        scan_dir, tmp_path / "native.retry.jsonl",
        {"MIB_NATIVE_SCAN_OCR": "1", "MIB_PIXMATCH": "0",
         "MIB_TEST_OCR_SESSION_FAIL_CASE": cid,
         "MIB_LEDGER": str(retry_ledger)}, timeout=180)
    assert retry_rows == clean_rows
    assert f"[retry] {cid} primary=recognizer_session_error result=recovered" \
        in stdout
    clean = _ledger(clean_ledger)[cid]
    recovered = _ledger(retry_ledger)[cid]
    assert recovered["image_views"] == clean["image_views"]
    # The native physical view lives in the independent native ledger; the
    # fresh-process retry must reproduce it exactly.
    assert recovered["native_ledger"]["image_views"] == \
        clean["native_ledger"]["image_views"]
    assert recovered["native_ledger"]["image_views"][0]["ocr_source"] == \
        "native_full_page_image"
    assert recovered["extraction"]["recovered"] is True


def test_python_exception_recovers_in_fresh_process(corpus, tmp_path):
    pdf_dir, case_ids = corpus
    cid = case_ids[4]
    ledger_path = tmp_path / "ledger.jsonl"
    rows, stdout = _run_predict(
        pdf_dir, tmp_path / "p.jsonl",
        {"MIB_TEST_EXTRACT_EXCEPTION_CASE": cid,
         "MIB_LEDGER": str(ledger_path)})
    _check_complete(rows, case_ids)
    assert f"[retry] {cid} primary=extraction_exception result=recovered" in stdout
    extraction = _ledger(ledger_path)[cid]["extraction"]
    assert extraction["attempt_count"] == 2
    assert extraction["recovered"] is True


def test_python_level_hang_caught_by_sigalrm(corpus, tmp_path):
    """Layer 1: an in-worker hang trips the per-case SIGALRM, the worker
    survives, the case degrades to a hedge row — parent never intervenes."""
    pdf_dir, case_ids = corpus
    hang_case = case_ids[1]
    ledger_path = tmp_path / "ledger.jsonl"
    rows, stdout = _run_predict(
        pdf_dir, tmp_path / "p.jsonl",
         {"MIB_TEST_HANG_CASE": hang_case, "MIB_TEST_HANG_MODE": "py",
         "MIB_CASE_TIMEOUT": "2", "MIB_RETRY_CASE_TIMEOUT": "3",
         "MIB_RETRY_BUDGET_SECS": "4", "MIB_LEDGER": str(ledger_path)})
    _check_complete(rows, case_ids)
    assert "[watchdog]" not in stdout, "SIGALRM layer should handle this alone"
    hung = next(r for r in rows if r["case_id"] == hang_case)
    assert hung["adjudication"] == "NEEDS_REVIEW"
    assert hung["confidence"] <= 0.6
    extraction = _ledger(ledger_path)[hang_case]["extraction"]
    assert extraction["recovered"] is False
    assert extraction["attempts"][-1]["failure_category"] == \
        "per_case_timeout"


def test_c_level_hang_caught_by_parent_watchdog(corpus, tmp_path):
    """Layer 2: a hang with SIGALRM blocked (as in a spinning C call) is
    killed by the parent's heartbeat watchdog; the worker's remaining slice
    is still processed by the respawn, and the stuck case gets a hedge row."""
    pdf_dir, case_ids = corpus
    hang_case = case_ids[1]  # shard1 slice is [case 1, case 5]: respawn must rescue case 5
    rows, stdout = _run_predict(
        pdf_dir, tmp_path / "p.jsonl",
         {"MIB_TEST_HANG_CASE": hang_case, "MIB_TEST_HANG_MODE": "c",
         "MIB_CASE_TIMEOUT": "2", "MIB_STUCK_SECS": "6",
         "MIB_WATCHDOG_POLL": "1", "MIB_RETRY_CASE_TIMEOUT": "3",
         "MIB_RETRY_BUDGET_SECS": "4"})
    _check_complete(rows, case_ids)
    assert "[watchdog]" in stdout, "parent watchdog should have fired"
    hung = next(r for r in rows if r["case_id"] == hang_case)
    assert hung["adjudication"] == "NEEDS_REVIEW"
    rescued = next(r for r in rows if r["case_id"] == case_ids[5])
    assert rescued["applicant_name"] != FALLBACK_NAME, \
        "respawn must finish the killed worker's slice"


def test_worker_crash_respawns(corpus, tmp_path):
    """A worker that dies mid-slice (segfault stand-in: SIGKILL via seam) is
    respawned and the rest of its slice is extracted, not fallback-filled."""
    pdf_dir, case_ids = corpus
    crash_case = case_ids[2]
    rows, stdout = _run_predict(
        pdf_dir, tmp_path / "p.jsonl",
        {"MIB_TEST_CRASH_CASE": crash_case, "MIB_WATCHDOG_POLL": "1",
         "MIB_RETRY_CASE_TIMEOUT": "3", "MIB_RETRY_BUDGET_SECS": "4"})
    _check_complete(rows, case_ids)
    assert "[watchdog]" in stdout
    crashed = next(r for r in rows if r["case_id"] == crash_case)
    assert crashed["adjudication"] == "NEEDS_REVIEW"
    rescued = next(r for r in rows if r["case_id"] == case_ids[6])
    assert rescued["applicant_name"] != FALLBACK_NAME


def test_killed_worker_missing_state_recovers_on_retry(corpus, tmp_path):
    pdf_dir, case_ids = corpus
    crash_case = case_ids[2]
    ledger_path = tmp_path / "ledger.jsonl"
    rows, stdout = _run_predict(
        pdf_dir, tmp_path / "p.jsonl",
        {"MIB_TEST_CRASH_CASE": crash_case, "MIB_TEST_CRASH_ATTEMPT": "1",
         "MIB_WATCHDOG_POLL": "1", "MIB_LEDGER": str(ledger_path)})
    _check_complete(rows, case_ids)
    assert "[watchdog]" in stdout
    assert f"[retry] {crash_case} primary=missing_primary_state " \
           "result=recovered" in stdout
    recovered = next(r for r in rows if r["case_id"] == crash_case)
    assert recovered["applicant_name"] != FALLBACK_NAME
    extraction = _ledger(ledger_path)[crash_case]["extraction"]
    assert extraction["attempt_count"] == 2
    assert extraction["recovered"] is True
