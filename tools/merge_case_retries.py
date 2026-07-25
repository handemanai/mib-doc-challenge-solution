#!/usr/bin/env python3
"""Replace explicitly failed production rows with isolated successful retries.

The original batch artifacts remain unchanged. Each retry must have exactly
one prediction and ledger row, matching its filename case id, and the retry
ledger must have no execution error. This is an audit recovery utility, not a
runtime retry policy.
"""
import argparse
import hashlib
import json
import re
from pathlib import Path


def _rows(path):
    return [json.loads(line) for line in open(path)]


def _sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _ids(rows, label):
    ids = [row.get("case_id") for row in rows]
    if any(not case_id for case_id in ids):
        raise SystemExit(f"{label}: missing case_id")
    if len(ids) != len(set(ids)):
        raise SystemExit(f"{label}: duplicate case_id")
    return ids


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--predictions", required=True)
    parser.add_argument("--ledger", required=True)
    parser.add_argument("--retry-dir", required=True)
    parser.add_argument("--output-predictions", required=True)
    parser.add_argument("--output-ledger", required=True)
    parser.add_argument("--metadata", required=True)
    parser.add_argument("--producer-sha", required=True)
    parser.add_argument("--config", required=True)
    parser.add_argument("--input-manifest-sha256", required=True)
    args = parser.parse_args()
    if not re.fullmatch(r"[0-9a-f]{40}", args.producer_sha):
        raise SystemExit("producer SHA must be a full 40-character commit SHA")
    if not re.fullmatch(r"[0-9a-f]{64}", args.input_manifest_sha256):
        raise SystemExit("input manifest SHA-256 must be 64 lowercase hex characters")

    source_preds = _rows(args.predictions)
    source_ledger = _rows(args.ledger)
    pred_ids = _ids(source_preds, "source predictions")
    ledger_ids = _ids(source_ledger, "source ledger")
    if pred_ids != ledger_ids:
        raise SystemExit("source prediction/ledger ids or order differ")
    failed_ids = {row["case_id"] for row in source_ledger
                  if row.get("execution_error")}
    if not failed_ids:
        raise SystemExit("source ledger has no explicit execution failures")

    retry_dir = Path(args.retry_dir)
    replacements = {}
    for pred_path in sorted(retry_dir.glob("MIB-*.jsonl")):
        if pred_path.name.endswith(".ledger.jsonl"):
            continue
        case_id = pred_path.stem
        ledger_path = retry_dir / f"{case_id}.ledger.jsonl"
        pred_rows, ledger_rows = _rows(pred_path), _rows(ledger_path)
        if len(pred_rows) != 1 or len(ledger_rows) != 1:
            raise SystemExit(f"{case_id}: retry artifacts must contain one row")
        if pred_rows[0].get("case_id") != case_id or ledger_rows[0].get("case_id") != case_id:
            raise SystemExit(f"{case_id}: retry row id mismatch")
        if ledger_rows[0].get("execution_error"):
            raise SystemExit(f"{case_id}: retry still failed")
        replacements[case_id] = (pred_rows[0], ledger_rows[0])
    if not replacements:
        raise SystemExit("no retry artifacts found")
    if set(replacements) != failed_ids:
        raise SystemExit(
            f"retry ids must equal source execution-error ids; "
            f"missing={sorted(failed_ids - set(replacements))} "
            f"extra={sorted(set(replacements) - failed_ids)}")

    def merge(rows, index):
        return [replacements.get(row["case_id"], (None, None))[index] or row for row in rows]

    pred_rows = merge(source_preds, 0)
    ledger_rows = merge(source_ledger, 1)
    if _ids(pred_rows, "output predictions") != pred_ids:
        raise SystemExit("output prediction ids/order changed")
    if _ids(ledger_rows, "output ledger") != ledger_ids:
        raise SystemExit("output ledger ids/order changed")
    for path, rows in ((args.output_predictions, pred_rows),
                       (args.output_ledger, ledger_rows)):
        with open(path, "w") as f:
            for row in rows:
                f.write(json.dumps(row) + "\n")
    metadata = {
        "artifact_class": "stitched_estimate_not_full_batch_evidence",
        "producer_sha": args.producer_sha,
        "config": args.config,
        "input_manifest_sha256": args.input_manifest_sha256,
        "replaced_execution_error_ids": sorted(failed_ids),
        "source_predictions_sha256": _sha256(args.predictions),
        "source_ledger_sha256": _sha256(args.ledger),
        "retry_sha256": {
            path.name: _sha256(path) for path in sorted(retry_dir.glob("*.jsonl"))},
        "output_predictions_sha256": _sha256(args.output_predictions),
        "output_ledger_sha256": _sha256(args.output_ledger),
        "limitation": ("retry decisions were produced in one-case batches; "
                       "scores are estimates until extraction states are merged "
                       "and all cases are re-decided in original batch context"),
    }
    Path(args.metadata).write_text(json.dumps(metadata, indent=2) + "\n")
    print(f"stitched estimate: replaced {len(replacements)} execution failures; "
          f"wrote {len(pred_rows)} predictions")


if __name__ == "__main__":
    main()
