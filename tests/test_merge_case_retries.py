import json
import subprocess
import sys
from pathlib import Path


TOOL = Path(__file__).resolve().parents[1] / "tools" / "merge_case_retries.py"
SHA = "a" * 40
MANIFEST = "b" * 64


def _write(path, rows):
    path.write_text("".join(json.dumps(row) + "\n" for row in rows))


def _run(tmp_path, retry_ids):
    preds = tmp_path / "predictions.jsonl"
    ledger = tmp_path / "ledger.jsonl"
    retries = tmp_path / "retries"
    retries.mkdir()
    source = [{"case_id": "MIB-1", "adjudication": "NEEDS_REVIEW"},
              {"case_id": "MIB-2", "adjudication": "APPROVED"}]
    _write(preds, source)
    _write(ledger, [
        {"case_id": "MIB-1", "execution_error": "FileDataError()"},
        {"case_id": "MIB-2", "execution_error": None},
    ])
    for case_id in retry_ids:
        _write(retries / f"{case_id}.jsonl",
               [{"case_id": case_id, "adjudication": "DENIED"}])
        _write(retries / f"{case_id}.ledger.jsonl",
               [{"case_id": case_id, "execution_error": None}])
    cmd = [sys.executable, str(TOOL), "--predictions", str(preds),
           "--ledger", str(ledger), "--retry-dir", str(retries),
           "--output-predictions", str(tmp_path / "out.predictions.jsonl"),
           "--output-ledger", str(tmp_path / "out.ledger.jsonl"),
           "--metadata", str(tmp_path / "metadata.json"),
           "--producer-sha", SHA, "--config", "native=1,dpi=150",
           "--input-manifest-sha256", MANIFEST]
    return subprocess.run(cmd, text=True, capture_output=True)


def test_retry_merge_is_explicitly_stitched_and_preserves_order(tmp_path):
    result = _run(tmp_path, ["MIB-1"])
    assert result.returncode == 0, result.stderr
    metadata = json.loads((tmp_path / "metadata.json").read_text())
    assert metadata["artifact_class"] == "stitched_estimate_not_full_batch_evidence"
    assert metadata["replaced_execution_error_ids"] == ["MIB-1"]
    rows = [json.loads(line) for line in
            (tmp_path / "out.predictions.jsonl").read_text().splitlines()]
    assert [row["case_id"] for row in rows] == ["MIB-1", "MIB-2"]


def test_retry_ids_must_exactly_equal_source_failures(tmp_path):
    result = _run(tmp_path, ["MIB-1", "MIB-2"])
    assert result.returncode != 0
    assert "retry ids must equal source execution-error ids" in result.stderr
