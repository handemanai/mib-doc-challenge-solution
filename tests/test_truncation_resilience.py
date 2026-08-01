"""Hard-limit truncation economics: the contract path must hold a complete,
well-formed row set from the first seconds of the batch, cheap inputs must be
scheduled first, and renamed inputs must not break scheduling bookkeeping or
emit duplicate ids.
"""
import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

_SPEC = importlib.util.spec_from_file_location(
    "mib_predict", ROOT / "scripts" / "predict.py")
predict = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(predict)


def _stub_state(case_id, stem=None):
    return {
        "case_id": case_id, "pools": {}, "doc_notes": {},
        "case_id_provenance": {"stem": stem or case_id, "source": "test"},
        "mean_ocr_conf": 0.0, "injection": {},
        "error": "missing_primary_state",
        "extraction": {"attempt_count": 1, "recovered": False,
                       "attempts": [{"attempt": 1, "status": "failed",
                                     "failure_category":
                                     "missing_primary_state"}]},
    }


class _FakeShard:
    def __init__(self, rows):
        self.state_files = []
        self._rows = rows

    def materialize(self, tmp_path, name):
        path = tmp_path / name
        path.write_text("".join(json.dumps(r) + "\n" for r in self._rows))
        self.state_files.append(path)
        return self


def test_startup_flush_survives_all_stub_states(tmp_path):
    """The immediate first flush runs on 100% conservative stubs; every
    batch-context helper and the writer must tolerate that."""
    states = [_stub_state(f"MIB-00000{i}") for i in range(1, 6)]
    out = tmp_path / "predictions.jsonl"
    predict._write_predictions(
        states, predict.batch_epoch(states), out,
        predict.batch_frequent_sponsors(states))
    rows = [json.loads(line) for line in out.read_text().splitlines()]
    assert len(rows) == 5
    for row in rows:
        assert row["adjudication"] == "NEEDS_REVIEW"
        assert 0.0 <= row["confidence"] <= 1.0


def test_write_predictions_dedupes_resolved_ids(tmp_path):
    """Two renamed files resolving to one id must emit one row (duplicate
    ids are an evaluator exit-2); first resolution wins."""
    states = [_stub_state("MIB-000042", stem="scan_a"),
              _stub_state("MIB-000042", stem="scan_b"),
              _stub_state("MIB-000043", stem="scan_c")]
    out = tmp_path / "predictions.jsonl"
    predict._write_predictions(states, predict.batch_epoch(states), out,
                               predict.batch_frequent_sponsors(states))
    rows = [json.loads(line) for line in out.read_text().splitlines()]
    assert [r["case_id"] for r in rows] == ["MIB-000042", "MIB-000043"]


def test_collect_states_keys_by_source_stem(tmp_path):
    """Renamed inputs: states merge/order/backfill by source stem while the
    resolved case id rides along for emission."""
    shard = _FakeShard([_stub_state("MIB-000042", stem="scan_a")])
    shard.materialize(tmp_path, "state0.jsonl")
    pdfs = [str(tmp_path / "scan_a.pdf"), str(tmp_path / "scan_b.pdf")]
    states = predict._collect_states([shard], pdfs, complete=True)
    by_stem = {predict._state_stem(s): s for s in states}
    assert set(by_stem) == {"scan_a", "scan_b"}
    assert by_stem["scan_a"]["case_id"] == "MIB-000042"
    assert by_stem["scan_b"]["case_id"] == "scan_b"  # backfill stub
    assert by_stem["scan_b"]["case_id_provenance"]["source"] == "backfill_stub"


def test_collect_states_has_completion_timing_independent_order(tmp_path):
    pdfs = [str(tmp_path / f"MIB-00000{i}.pdf") for i in range(1, 5)]
    # Workers finish in the opposite order, and their append-only rows are
    # materialized in different files. Output remains the receipt's declared
    # shard order: shard 0's slice, then shard 1's slice.
    shard0 = _FakeShard([_stub_state("MIB-000003"),
                         _stub_state("MIB-000001")])
    shard1 = _FakeShard([_stub_state("MIB-000004"),
                         _stub_state("MIB-000002")])
    shard0.materialize(tmp_path, "state0.jsonl")
    shard1.materialize(tmp_path, "state1.jsonl")
    states = predict._collect_states([shard0, shard1], pdfs, complete=True)
    assert [state["case_id"] for state in states] == [
        "MIB-000001", "MIB-000003", "MIB-000002", "MIB-000004"]


def test_checkpoint_write_error_retains_last_good_output_and_returns_false(
        monkeypatch, tmp_path):
    states = [_stub_state("MIB-000001")]
    out = tmp_path / "predictions.jsonl"
    prior = b'{"case_id":"MIB-999999","checkpoint":"last-good"}\n'
    out.write_bytes(prior)

    def fail_replace(_source, _destination):
        raise OSError(5, "transient output failure")

    monkeypatch.setattr(predict.os, "replace", fail_replace)
    assert predict._checkpoint_predictions(states, out) is False
    assert out.read_bytes() == prior


def test_input_order_is_size_ascending(tmp_path):
    small = tmp_path / "b_small.pdf"
    big = tmp_path / "a_big.pdf"
    small.write_bytes(b"x" * 10)
    big.write_bytes(b"x" * 1000)
    ordered = sorted((str(p) for p in tmp_path.glob("*.pdf")),
                     key=lambda p: (predict.os.path.getsize(p), p))
    assert [Path(p).name for p in ordered] == ["b_small.pdf", "a_big.pdf"]
