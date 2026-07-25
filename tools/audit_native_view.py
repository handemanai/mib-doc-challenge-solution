#!/usr/bin/env python3
"""Audit two exactly bound extraction runs without rerunning OCR.

Scored mode is label-aware and promotion-gated.  Validation mode is explicitly
unlabeled and audit-only: it reports execution and output changes but never
loads labels, computes false approvals, or makes score/promotion claims.
"""
import argparse
import csv
import hashlib
import json
import os
import tempfile
from collections import Counter
from pathlib import Path

from native_artifact_binding import (EFFECTIVE_CONFIG_DEFAULTS, IDENTITY_KEYS,
                                     binding_identity, canonical_sha256,
                                     sha256_file, verify_binding)


AUDIT_SCHEMA = "mib-native-audit-spec-v2"
FIELDS = ("applicant_name", "species_code", "home_world", "visa_class",
          "sponsor_id", "arrival_date", "declared_purpose", "risk_flags",
          "fee_status")
ADJUDICATIONS = {"APPROVED", "DENIED", "NEEDS_REVIEW"}
NATIVE_SCAN_FLAG = "MIB_NATIVE_SCAN_OCR"
PAIR_SHARED_IDENTITY_KEYS = (
    "producer_git_sha",
    "image_id",
    "image_revision",
    "image_inspect_sha256",
    "runtime_manifest_sha256",
)


def _rows(path):
    ordered, by_case = [], {}
    with open(path) as handle:
        for line_number, line in enumerate(handle, 1):
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"invalid JSONL at {path}:{line_number}") from exc
            case_id = row.get("case_id") if isinstance(row, dict) else None
            if not isinstance(case_id, str) or not case_id:
                raise ValueError(f"missing case_id at {path}:{line_number}")
            if case_id in by_case:
                raise ValueError(f"duplicate case_id in {path}: {case_id}")
            ordered.append(case_id)
            by_case[case_id] = row
    if not ordered:
        raise ValueError(f"empty artifact: {path}")
    return ordered, by_case


def _failure_error(row):
    explicit = row.get("error") or row.get("execution_error")
    if explicit:
        return explicit
    extraction = row.get("extraction")
    if not isinstance(extraction, dict):
        return "invalid_extraction_provenance"
    attempts = extraction.get("attempts")
    if not isinstance(attempts, list) or not attempts:
        return "invalid_extraction_provenance"
    final = attempts[-1]
    if not isinstance(final, dict):
        return "invalid_extraction_provenance"
    if final.get("status") == "success":
        return None
    category = final.get("failure_category") or "unknown_extraction_failure"
    error = final.get("error")
    return f"{category}({error})" if error else category


def _failure_category(row):
    error = _failure_error(row)
    return error.split("(", 1)[0] if error else None


def _finding(row):
    rank1 = row.get("rank1_payload")
    return ((rank1.get("finding") if isinstance(rank1, dict) else None)
            or row.get("doc_notes", {}).get("finding")
            or row.get("finding_note")
            or row.get("adjudicator_note"))


def _rank1_payload(row):
    production_payload = row.get("rank1_payload")
    if isinstance(production_payload, dict):
        if set(production_payload) != {"finding", "fields"} or not isinstance(
                production_payload.get("fields"), dict):
            raise ValueError("production rank1 payload is malformed")
        payload = {"fields": dict(sorted(production_payload["fields"].items()))}
        if production_payload.get("finding"):
            payload["finding"] = production_payload["finding"]
        return payload
    notes = row.get("doc_notes") if isinstance(row.get("doc_notes"), dict) else {}
    payload = {"fields": {}}
    finding = _finding(row)
    if finding:
        payload["finding"] = finding
    if notes.get("name_correction"):
        payload["fields"]["applicant_name"] = notes["name_correction"]
    corrections = notes.get("corrections")
    if isinstance(corrections, dict) and corrections:
        payload["fields"].update(corrections)
    return payload


def _rank1_items(payload):
    items = {}
    if payload.get("finding"):
        items["finding"] = payload["finding"]
    for field, value in payload.get("fields", {}).items():
        items[f"field:{field}"] = value
    return items


def _composited_rank1_payload(row):
    payload = row.get("composited_rank1_payload")
    if (not isinstance(payload, dict)
            or set(payload) != {"values", "conflicts", "evidence"}
            or not isinstance(payload.get("values"), dict)
            or not isinstance(payload.get("conflicts"), list)
            or not isinstance(payload.get("evidence"), dict)):
        raise ValueError("production composited rank1 payload is malformed")
    return {
        "values": {field: list(values)
                   for field, values in sorted(payload["values"].items())},
        "conflicts": list(payload["conflicts"]),
        "evidence": {field: list(records)
                     for field, records in sorted(payload["evidence"].items())},
    }


def _missing_composited_rank1(base, variant):
    missing = {}
    variant_values = variant["values"]
    for field, values in base["values"].items():
        absent = sorted(set(values) - set(variant_values.get(field, [])))
        if absent:
            key = "finding" if field == "finding" else f"field:{field}"
            missing[key] = absent[0] if len(absent) == 1 else absent
    for field, records in base["evidence"].items():
        retained_values = set(variant["values"].get(field, []))
        variant_records = {
            json.dumps(record, sort_keys=True, separators=(",", ":"))
            for record in variant["evidence"].get(field, [])
        }
        for record in records:
            if record["value"] not in retained_values:
                continue
            canonical = json.dumps(
                record, sort_keys=True, separators=(",", ":"))
            if canonical in variant_records:
                continue
            key_field = "finding" if field == "finding" else f"field:{field}"
            key = f"origin:{key_field}:{record['value']}"
            missing.setdefault(key, []).append(record["origin"])
    return missing


def _rank1_conflicts(evidence):
    notes = evidence.get("doc_notes") if isinstance(
        evidence.get("doc_notes"), dict) else {}
    conflicts = set(evidence.get("rank1_conflicts") or [])
    conflicts.update(notes.get("rank1_conflicts") or [])
    reasons = evidence.get("reasons") or []
    if "rank1_note_conflict" in reasons and not conflicts:
        conflicts.add("unspecified")
    return sorted(conflicts)


def _conflict_forces_review(evidence, prediction):
    return bool(_rank1_conflicts(evidence)) and \
        prediction.get("adjudication") == "NEEDS_REVIEW"


def _artifact_path(binding, binding_path, role):
    try:
        record = binding["artifacts"][role]
    except KeyError as exc:
        raise ValueError(f"binding lacks required artifact role: {role}") from exc
    return (Path(binding_path).resolve().parent / record["path"]).resolve(strict=True)


def _labels(path, expected_ids):
    with open(path) as handle:
        rows = list(csv.DictReader(handle))
    ids = [row.get("case_id") for row in rows]
    if any(not case_id for case_id in ids) or len(ids) != len(set(ids)):
        raise ValueError("labels have missing or duplicate case_id")
    by_case = {row["case_id"]: row for row in rows}
    if set(by_case) != set(expected_ids):
        raise ValueError("labels do not contain exactly the bound cases")
    for row in rows:
        if any(field not in row for field in (*FIELDS, "adjudication")) or \
                row["adjudication"] not in ADJUDICATIONS:
            raise ValueError("labels contain missing fields or invalid adjudication")
    return by_case


def _binding_report(binding, path):
    return {
        "binding_file_sha256": sha256_file(path),
        "binding_payload_sha256": binding["binding_sha256"],
        "identity": binding_identity(binding),
        "effective_config": binding["effective_config"],
        "worker_count": binding["worker_count"],
        "output_case_count": binding["output_case_count"],
        "output_order_sha256": binding["output_order_sha256"],
        "artifacts": {
            role: {"sha256": record["sha256"], "size": record["size"]}
            for role, record in sorted(binding["artifacts"].items())
        },
    }


def _verified_binding_snapshot(path, expected_identity):
    """Verify one binding while proving its file bytes stayed stable."""
    before = sha256_file(path)
    binding = verify_binding(path, expected_identity)
    after = sha256_file(path)
    if before != after:
        raise ValueError("binding file changed during verification")
    return binding, before


def _validate_paired_bindings(base, variant, split):
    """Require two independent executions that differ only by native OCR."""
    if base.get("run_split") != split or variant.get("run_split") != split:
        raise ValueError("bound run split differs from audit split")
    if base.get("run_nonce") == variant.get("run_nonce"):
        raise ValueError("base and variant must have distinct run nonces")
    if base.get("run_receipt_sha256") == variant.get("run_receipt_sha256"):
        raise ValueError("base and variant must have distinct run receipts")
    for key in PAIR_SHARED_IDENTITY_KEYS:
        if base.get(key) != variant.get(key):
            raise ValueError(f"base and variant {key} differ")
    if base.get("input_manifest_sha256") != \
            variant.get("input_manifest_sha256"):
        raise ValueError("base and variant input manifests differ")
    if base.get("worker_count") != variant.get("worker_count"):
        raise ValueError("base and variant worker counts differ")
    base_config = base.get("effective_config")
    variant_config = variant.get("effective_config")
    if not isinstance(base_config, dict) or not isinstance(variant_config, dict):
        raise ValueError("bound effective configs are malformed")
    if base_config.get(NATIVE_SCAN_FLAG) != "0" or \
            variant_config.get(NATIVE_SCAN_FLAG) != "1":
        raise ValueError(
            "native audit requires base MIB_NATIVE_SCAN_OCR=0 and variant=1")
    base_without_flag = {
        key: value for key, value in base_config.items()
        if key != NATIVE_SCAN_FLAG
    }
    variant_without_flag = {
        key: value for key, value in variant_config.items()
        if key != NATIVE_SCAN_FLAG
    }
    if base_without_flag != variant_without_flag:
        raise ValueError(
            "base and variant effective configs differ beyond "
            "MIB_NATIVE_SCAN_OCR")
    # The shipped runtime defaults native fusion on, but this paired audit is
    # deliberately an off/on ablation. Keep its control arm explicit rather
    # than inheriting the production default.
    expected_base = dict(
        EFFECTIVE_CONFIG_DEFAULTS, MIB_NATIVE_SCAN_OCR="0")
    expected_variant = dict(
        EFFECTIVE_CONFIG_DEFAULTS, MIB_NATIVE_SCAN_OCR="1")
    if base_config != expected_base or variant_config != expected_variant:
        raise ValueError(
            "native promotion audit requires the exact campaign configs")


def _validate_decisions(label, predictions, evidence, expected_ids):
    for case_id in expected_ids:
        prediction = predictions[case_id]
        missing = [field for field in (*FIELDS, "adjudication")
                   if field not in prediction]
        if missing or prediction.get("adjudication") not in ADJUDICATIONS:
            raise ValueError(
                f"{label} prediction is missing fields or has invalid "
                f"adjudication: {case_id}")
        evidence_decision = evidence[case_id].get("adjudication")
        if evidence_decision not in ADJUDICATIONS:
            raise ValueError(
                f"{label} evidence has invalid adjudication: {case_id}")
        if evidence_decision != prediction["adjudication"]:
            raise ValueError(
                f"{label} prediction/evidence adjudication differs: {case_id}")


def _attempt_census(evidence):
    """Report every attempt while leaving the gate on terminal outcomes."""
    status_counts = Counter()
    failure_categories = Counter()
    recovered_case_ids = []
    for case_id, row in evidence.items():
        extraction = row.get("extraction")
        attempts = extraction.get("attempts") if isinstance(extraction, dict) else []
        if not isinstance(attempts, list):
            attempts = []
        for attempt in attempts:
            if not isinstance(attempt, dict):
                status_counts["invalid"] += 1
                continue
            status = attempt.get("status") or "missing"
            status_counts[status] += 1
            if status == "failed":
                failure_categories[
                    attempt.get("failure_category") or "unspecified"] += 1
        if attempts and isinstance(attempts[-1], dict) and \
                attempts[-1].get("status") == "success" and any(
                    isinstance(attempt, dict)
                    and attempt.get("status") == "failed"
                    for attempt in attempts[:-1]):
            recovered_case_ids.append(case_id)
    return {
        "attempt_count": sum(status_counts.values()),
        "status_counts": dict(sorted(status_counts.items())),
        "failure_category_counts": dict(sorted(failure_categories.items())),
        "recovered_case_count": len(recovered_case_ids),
        "recovered_case_ids": recovered_case_ids,
    }


def compare(base_prediction_path, base_evidence_path, variant_prediction_path,
            variant_evidence_path, expected_input_ids, mode, labels=None,
            bindings=None):
    base_order, base_preds = _rows(base_prediction_path)
    base_evidence_order, base_evidence = _rows(base_evidence_path)
    variant_order, variant_preds = _rows(variant_prediction_path)
    variant_evidence_order, variant_evidence = _rows(variant_evidence_path)
    expected_set = set(expected_input_ids)
    for label, order in (("base predictions", base_order),
                         ("base evidence", base_evidence_order),
                         ("variant predictions", variant_order),
                         ("variant evidence", variant_evidence_order)):
        if len(order) != len(expected_input_ids) or set(order) != expected_set:
            raise ValueError(f"{label} does not contain exactly the bound input cases")
    if base_order != base_evidence_order:
        raise ValueError("base prediction/evidence IDs or order differ")
    if variant_order != variant_evidence_order:
        raise ValueError("variant prediction/evidence IDs or order differ")

    _validate_decisions("base", base_preds, base_evidence, expected_input_ids)
    _validate_decisions(
        "variant", variant_preds, variant_evidence, expected_input_ids)

    truth = _labels(labels, expected_input_ids) if mode == "scored" else None
    failures, field_changes, decision_changes, finding_changes = [], [], [], []
    rank1_payload_changes, composited_rank1_changes = [], []
    lost_rank1_payloads = []
    rank1_conflict_changes, new_rank1_conflict_cases = [], []
    unsafe_rank1_conflict_cases = []
    clean = []
    for case_id in expected_input_ids:
        base_state, variant_state = base_evidence[case_id], variant_evidence[case_id]
        base_error, variant_error = (_failure_error(base_state),
                                     _failure_error(variant_state))
        if base_error or variant_error:
            failures.append({
                "case_id": case_id,
                "base_error": base_error,
                "variant_error": variant_error,
            })
        else:
            clean.append(case_id)
        case_field_changes = []
        for field in FIELDS:
            if field not in base_preds[case_id] or field not in variant_preds[case_id]:
                raise ValueError(f"prediction is missing required field {field}: {case_id}")
            before, after = base_preds[case_id][field], variant_preds[case_id][field]
            if before != after:
                change = {"case_id": case_id, "field": field, "base": before,
                          "variant": after}
                if truth is not None:
                    change["truth"] = truth[case_id][field]
                field_changes.append(change)
                case_field_changes.append(change)

        before_decision = base_preds[case_id].get("adjudication")
        after_decision = variant_preds[case_id].get("adjudication")
        if before_decision != after_decision:
            change = {
                "case_id": case_id, "base": before_decision,
                "variant": after_decision, "field_changes": case_field_changes,
            }
            if truth is not None:
                change["truth"] = truth[case_id]["adjudication"]
            decision_changes.append(change)

        before_finding, after_finding = (_finding(base_state),
                                         _finding(variant_state))
        if before_finding != after_finding:
            change = {
                "case_id": case_id, "base": before_finding,
                "variant": after_finding,
                "base_decision": before_decision,
                "variant_decision": after_decision,
            }
            if truth is not None:
                change["truth"] = truth[case_id]["adjudication"]
            finding_changes.append(change)

        base_payload, variant_payload = (_rank1_payload(base_state),
                                         _rank1_payload(variant_state))
        base_items, variant_items = (_rank1_items(base_payload),
                                     _rank1_items(variant_payload))
        missing_payload = {
            key: value for key, value in base_items.items()
            if variant_items.get(key) != value
        }
        if missing_payload:
            change = {
                "case_id": case_id, "base": base_payload,
                "variant": variant_payload,
                "missing": missing_payload,
            }
            rank1_payload_changes.append(change)

        base_composited = _composited_rank1_payload(base_state)
        variant_composited = _composited_rank1_payload(variant_state)
        missing_composited = _missing_composited_rank1(
            base_composited, variant_composited)
        if (base_composited["values"] != variant_composited["values"]
                or base_composited["conflicts"] !=
                variant_composited["conflicts"]
                or base_composited["evidence"] !=
                variant_composited["evidence"]):
            composited_rank1_changes.append({
                "case_id": case_id,
                "base": base_composited,
                "variant": variant_composited,
                "missing": missing_composited,
            })
        if missing_composited:
            # Compare baseline-origin payloads, never the fused payload: a
            # native alternate with the same value cannot conceal baseline loss.
            lost_rank1_payloads.append({
                "case_id": case_id,
                "base": base_payload,
                "variant": variant_payload,
                "missing": missing_composited,
                "conflict_forced_review": _conflict_forces_review(
                    variant_state, variant_preds[case_id]),
            })

        base_conflicts = set(_rank1_conflicts(base_state))
        variant_conflicts = set(_rank1_conflicts(variant_state))
        added_conflicts = sorted(variant_conflicts - base_conflicts)
        if added_conflicts:
            new_rank1_conflict_cases.append(case_id)
            rank1_conflict_changes.append({
                "case_id": case_id,
                "base": sorted(base_conflicts),
                "variant": sorted(variant_conflicts),
                "added": added_conflicts,
            })
        if variant_conflicts and after_decision != "NEEDS_REVIEW":
            unsafe_rank1_conflict_cases.append(case_id)

    base_failure_census = Counter(
        category for category in (_failure_category(row)
                                  for row in base_evidence.values()) if category)
    variant_failure_census = Counter(
        category for category in (_failure_category(row)
                                  for row in variant_evidence.values()) if category)
    approved_changes = [
        change for change in decision_changes
        if "APPROVED" in (change["base"], change["variant"])
    ]
    entered_approved = [
        change for change in decision_changes
        if change["base"] != "APPROVED" and change["variant"] == "APPROVED"
    ]

    report = {
        "mode": mode,
        "artifact_class": ("labeled_scored_audit" if mode == "scored"
                           else "unlabeled_validation_audit_only"),
        "labels_used": mode == "scored",
        "promotion_eligible": False,
        "input_case_count": len(expected_input_ids),
        "clean_cases": len(clean),
        "base_failure_census": dict(sorted(base_failure_census.items())),
        "variant_failure_census": dict(sorted(variant_failure_census.items())),
        "attempt_census": {
            "base": _attempt_census(base_evidence),
            "variant": _attempt_census(variant_evidence),
            "gate_semantics": (
                "zero_execution_failures evaluates terminal outcomes; "
                "recovered earlier attempts remain visible here"),
        },
        "failures": failures,
        "field_changes": field_changes,
        "decision_changes": decision_changes,
        "approved_decision_changes": approved_changes,
        "entered_approved_changes": entered_approved,
        "finding_changes": finding_changes,
        "rank1_payload_changes": rank1_payload_changes,
        "composited_rank1_payload_changes": composited_rank1_changes,
        "lost_baseline_rank1_payloads": lost_rank1_payloads,
        "rank1_conflict_changes": rank1_conflict_changes,
        "unsafe_rank1_conflict_case_ids": unsafe_rank1_conflict_cases,
    }
    if bindings:
        report["artifact_binding"] = bindings

    if mode == "scored":
        base_false = sorted(
            case_id for case_id in expected_input_ids
            if base_preds[case_id].get("adjudication") == "APPROVED"
            and truth[case_id]["adjudication"] != "APPROVED")
        variant_false = sorted(
            case_id for case_id in expected_input_ids
            if variant_preds[case_id].get("adjudication") == "APPROVED"
            and truth[case_id]["adjudication"] != "APPROVED")
        new_false = sorted(set(variant_false) - set(base_false))
        gates = {
            "zero_new_false_approvals": {
                "passed": not new_false,
                "base_false_approval_case_ids": base_false,
                "variant_false_approval_case_ids": variant_false,
                "new_false_approval_case_ids": new_false,
            },
            "zero_execution_failures": {
                "passed": not failures,
                "failure_case_ids": [row["case_id"] for row in failures],
                "semantics": "terminal outcomes after configured retries",
            },
            "baseline_rank1_noninferiority": {
                "passed": not lost_rank1_payloads,
                "lost_case_ids": [row["case_id"] for row in lost_rank1_payloads],
            },
            "zero_new_rank1_conflicts": {
                "passed": not new_rank1_conflict_cases,
                "new_conflict_case_ids": new_rank1_conflict_cases,
            },
            "rank1_conflicts_force_review": {
                "passed": not unsafe_rank1_conflict_cases,
                "unsafe_conflict_case_ids": unsafe_rank1_conflict_cases,
            },
        }
        report["gate_order"] = list(gates)
        report["gates"] = gates
        report["promotion_eligible"] = all(gate["passed"] for gate in gates.values())
    else:
        report["audit_only_notice"] = (
            "Validation is unlabeled. Changes and failures are observations only; "
            "this artifact cannot support score, correctness, false-approval, or "
            "promotion claims.")
    return report


def _validate_spec(spec, mode, split):
    required = {"schema", "mode", "split", "base", "variant"}
    if mode == "scored":
        required.add("labels_sha256")
    if not isinstance(spec, dict) or set(spec) != required:
        raise ValueError("audit spec has unexpected or missing keys")
    if spec.get("schema") != AUDIT_SCHEMA or spec.get("mode") != mode \
            or spec.get("split") != split:
        raise ValueError("audit spec schema/mode/split differs from invocation")
    for side in ("base", "variant"):
        identity = spec.get(side)
        if not isinstance(identity, dict) or set(identity) != IDENTITY_KEYS:
            raise ValueError(f"audit spec requires an exact {side} identity")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-dir", required=True)
    parser.add_argument("--variant-dir", required=True)
    parser.add_argument("--mode", choices=("scored", "audit-only"),
                        default="scored")
    parser.add_argument("--labels")
    parser.add_argument("--split", default="dev")
    parser.add_argument("--output", required=True)
    parser.add_argument("--base-binding", required=True)
    parser.add_argument("--variant-binding", required=True)
    parser.add_argument("--binding-spec", required=True,
                        help="predeclared exact base/variant identities")
    parser.add_argument(
        "--require-finding", action="append", default=[], metavar="CASE=FINDING",
        help="additional explicit finding gate for scored audits")
    args = parser.parse_args()

    output = Path(args.output).resolve()
    if output.exists():
        raise SystemExit(f"refusing to overwrite existing audit report: {output}")
    if args.split == "validation" and args.mode != "audit-only":
        raise SystemExit("validation is unlabeled and must use --mode audit-only")
    if args.mode == "audit-only":
        if args.split != "validation":
            raise SystemExit("audit-only mode is reserved for the validation split")
        if args.labels:
            raise SystemExit("audit-only validation forbids --labels")
        if args.require_finding:
            raise SystemExit(
                "audit-only validation forbids case-specific finding gates")
    elif not args.labels:
        raise SystemExit("scored mode requires --labels")

    try:
        spec_path = Path(args.binding_spec).resolve(strict=True)
        spec_bytes = spec_path.read_bytes()
        spec_file_sha256 = hashlib.sha256(spec_bytes).hexdigest()
        spec = json.loads(spec_bytes)
        _validate_spec(spec, args.mode, args.split)
        if args.mode == "scored" and sha256_file(args.labels) != spec["labels_sha256"]:
            raise ValueError("labels hash differs from the predeclared audit spec")
        base_binding, base_binding_file_sha256 = _verified_binding_snapshot(
            args.base_binding, spec["base"])
        variant_binding, variant_binding_file_sha256 = \
            _verified_binding_snapshot(args.variant_binding, spec["variant"])
        _validate_paired_bindings(base_binding, variant_binding, args.split)
    except (KeyError, OSError, ValueError, json.JSONDecodeError) as exc:
        raise SystemExit(f"artifact binding verification failed: {exc}") from exc
    base_dir = Path(args.base_dir).resolve()
    variant_dir = Path(args.variant_dir).resolve()
    if base_dir == variant_dir or Path(args.base_binding).resolve() == \
            Path(args.variant_binding).resolve():
        raise SystemExit("base and variant must be distinct bound runs")

    try:
        base_predictions = _artifact_path(
            base_binding, args.base_binding, "predictions")
        base_evidence = _artifact_path(base_binding, args.base_binding, "evidence")
        variant_predictions = _artifact_path(
            variant_binding, args.variant_binding, "predictions")
        variant_evidence = _artifact_path(
            variant_binding, args.variant_binding, "evidence")
        for directory, paths in (
                (Path(args.base_dir).resolve(), (base_predictions, base_evidence)),
                (Path(args.variant_dir).resolve(),
                 (variant_predictions, variant_evidence))):
            if any(path.parent != directory for path in paths):
                raise ValueError("bound prediction/evidence is outside its run directory")
        binding_summary = {
            "spec_file_sha256": spec_file_sha256,
            "audit_tool_sha256": sha256_file(__file__),
            "binding_tool_sha256": sha256_file(
                Path(__file__).with_name("native_artifact_binding.py")),
            "input_manifest_sha256": base_binding["input_manifest_sha256"],
            "base": _binding_report(base_binding, args.base_binding),
            "variant": _binding_report(variant_binding, args.variant_binding),
        }
        if binding_summary["base"]["binding_file_sha256"] != \
                base_binding_file_sha256 or \
                binding_summary["variant"]["binding_file_sha256"] != \
                variant_binding_file_sha256:
            raise ValueError("binding file changed before audit comparison")
        if args.mode == "scored":
            binding_summary["labels_sha256"] = spec["labels_sha256"]
        expected_ids = [entry["case_id"] for entry in base_binding["input_manifest"]]
        report = compare(
            base_predictions, base_evidence, variant_predictions, variant_evidence,
            expected_ids, args.mode, labels=args.labels,
            bindings=binding_summary)
    except (KeyError, OSError, ValueError) as exc:
        raise SystemExit(f"artifact audit failed: {exc}") from exc

    manual_failures = []
    if args.require_finding:
        _, variant_rows = _rows(variant_evidence)
        for requirement in args.require_finding:
            if "=" not in requirement:
                raise SystemExit("--require-finding must be CASE=FINDING")
            case_id, expected = requirement.split("=", 1)
            state = variant_rows.get(case_id, {})
            actual = _finding(state)
            error = _failure_error(state)
            if error or actual != expected:
                manual_failures.append({
                    "case_id": case_id, "expected": expected,
                    "actual": actual, "error": error,
                })
    report["manual_finding_gate_failures"] = manual_failures
    if args.mode == "scored" and manual_failures:
        report["promotion_eligible"] = False

    try:
        # Close every read-to-publication interval after the optional manual
        # finding pass. The report must describe the same spec and binding
        # bytes that were parsed, not merely equivalent replacement files.
        if sha256_file(spec_path) != binding_summary["spec_file_sha256"]:
            raise ValueError("audit spec changed during the audit comparison")
        _, final_base_hash = _verified_binding_snapshot(
            args.base_binding, spec["base"])
        _, final_variant_hash = _verified_binding_snapshot(
            args.variant_binding, spec["variant"])
        if final_base_hash != binding_summary["base"]["binding_file_sha256"] \
                or final_variant_hash != \
                binding_summary["variant"]["binding_file_sha256"]:
            raise ValueError("binding file changed during the audit comparison")
        if args.mode == "scored" and \
                sha256_file(args.labels) != spec["labels_sha256"]:
            raise ValueError(
                "labels hash differs after the audit comparison")
    except (KeyError, OSError, ValueError) as exc:
        raise SystemExit(f"artifact audit final verification failed: {exc}") \
            from exc

    output.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = None
    try:
        with tempfile.NamedTemporaryFile(
                mode="w", dir=output.parent, prefix=f".{output.name}.",
                suffix=".tmp", delete=False) as handle:
            temporary_path = Path(handle.name)
            json.dump(report, handle, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.link(temporary_path, output)
        directory_fd = os.open(output.parent, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    except OSError as exc:
        raise SystemExit(f"could not write audit report: {exc}") from exc
    finally:
        if temporary_path is not None:
            try:
                temporary_path.unlink()
            except FileNotFoundError:
                pass
    report_hash = sha256_file(output)
    print(f"clean={report['clean_cases']} failures={len(report['failures'])} "
          f"fields={len(report['field_changes'])} "
          f"decisions={len(report['decision_changes'])} "
          f"approved_changes={len(report['approved_decision_changes'])} "
          f"report_sha256={report_hash}")
    failed = args.mode == "scored" and (
        not report["promotion_eligible"] or bool(manual_failures))
    raise SystemExit(1 if failed else 0)


if __name__ == "__main__":
    main()
