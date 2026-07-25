#!/usr/bin/env python3
"""Build a deterministic no-OCR census for native-scan selector eligibility."""
import argparse
import hashlib
import json
import os
import subprocess
import sys
import tempfile
from collections import Counter
from pathlib import Path

import fitz

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from mib import forensics  # noqa: E402
from tools.native_artifact_binding import (  # noqa: E402
    _input_identity,
    _validate_run_identity,
    canonical_effective_config,
    canonical_sha256,
)


SCHEMA = "mib-native-selector-census-v1"
BOUND_SOURCE_PATHS = ("mib/forensics.py", "tools/native_selector_census.py")
MAX_CASES_PER_INSPECTOR = 48
INSPECTOR_TIMEOUT_SECS = 120


def _sha256_file(path):
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _is_holdout(case_id):
    return int(hashlib.md5(case_id.encode()).hexdigest(), 16) % 5 == 0


def _inspect_snapshot(snapshot, outcome_catalog):
    """Inspect one already-bound packet and return path-free census data."""
    pdf = Path(snapshot["path"])
    raw = pdf.read_bytes()
    if (len(raw) != snapshot["size"]
            or hashlib.sha256(raw).hexdigest() != snapshot["sha256"]):
        raise ValueError("selector census input changed before inspection")
    record = {
        "ordinal": snapshot["ordinal"],
        "case_id": snapshot["case_id"],
        "filename": pdf.name,
        "size": snapshot["size"],
        "sha256": snapshot["sha256"],
        "pages": [],
    }
    local_outcomes = Counter()
    local_pages = []
    try:
        with fitz.open(stream=raw, filetype="pdf") as doc:
            for page in doc:
                result = forensics.native_full_page_scan_audit(page)
                if result["reason"] not in outcome_catalog:
                    raise ValueError(
                        "selector returned an unknown outcome category")
                page_record = {
                    "page": int(page.number),
                    "eligible": bool(result["eligible"]),
                    "reason": result["reason"],
                }
                if result["eligible"]:
                    page_record["metadata"] = result["metadata"]
                local_pages.append(page_record)
                local_outcomes[result["reason"]] += 1
    except ValueError as exc:
        if str(exc) == "selector returned an unknown outcome category":
            raise
        error = f"document_inspection_error({type(exc).__name__})"
        record["document_error"] = error
        return {
            "record": record,
            "outcomes": {},
            "page_count": 0,
            "eligible": False,
            "document_error": {
                "case_id": snapshot["case_id"], "error": error},
        }
    except Exception as exc:
        # Preserve the affected case without leaking environment-specific
        # paths or exception strings into the reproducible artifact.
        error = f"document_inspection_error({type(exc).__name__})"
        record["document_error"] = error
        return {
            "record": record,
            "outcomes": {},
            "page_count": 0,
            "eligible": False,
            "document_error": {
                "case_id": snapshot["case_id"], "error": error},
        }
    record["pages"] = local_pages
    return {
        "record": record,
        "outcomes": dict(local_outcomes),
        "page_count": len(local_pages),
        "eligible": any(page["eligible"] for page in local_pages),
        "document_error": None,
    }


def _inspect_worker(request_path, output_path):
    request = json.loads(Path(request_path).read_text())
    if not isinstance(request, dict) or set(request) != {
            "snapshots", "outcome_catalog"}:
        raise ValueError("selector worker request is malformed")
    results = [
        _inspect_snapshot(snapshot, tuple(request["outcome_catalog"]))
        for snapshot in request["snapshots"]
    ]
    Path(output_path).write_text(json.dumps(results, sort_keys=True) + "\n")


def _bounded_inspections(snapshots, outcome_catalog):
    """Inspect long corpora in short-lived processes.

    PyMuPDF's native parser has a repeatable process-lifetime failure on this
    corpus. The scored runtime already retires workers after 48 packets; the
    no-OCR release census uses the same boundary. A failed chunk is retried once
    in a fresh process, then fails closed instead of hanging or publishing a
    partial census.
    """
    if len(snapshots) <= MAX_CASES_PER_INSPECTOR:
        return [
            _inspect_snapshot(snapshot, outcome_catalog)
            for snapshot in snapshots
        ]
    results = []
    with tempfile.TemporaryDirectory(prefix="mib-selector-") as directory:
        root = Path(directory)
        for start in range(0, len(snapshots), MAX_CASES_PER_INSPECTOR):
            chunk = snapshots[start:start + MAX_CASES_PER_INSPECTOR]
            request = root / f"request-{start}.json"
            request.write_text(json.dumps({
                "snapshots": chunk,
                "outcome_catalog": list(outcome_catalog),
            }, sort_keys=True))
            completed = None
            for attempt in (1, 2):
                output = root / f"output-{start}-{attempt}.json"
                try:
                    completed = subprocess.run(
                        [sys.executable, str(Path(__file__).resolve()),
                         "--inspect-worker", str(request), str(output)],
                        capture_output=True, text=True,
                        timeout=INSPECTOR_TIMEOUT_SECS)
                except subprocess.TimeoutExpired:
                    completed = None
                if completed is not None and completed.returncode == 0 \
                        and output.is_file():
                    results.extend(json.loads(output.read_text()))
                    break
            else:
                end = start + len(chunk) - 1
                raise ValueError(
                    "selector inspection worker failed twice for bound "
                    f"ordinals {start}-{end}")
    return results


def _verify_producer_source(repo, source_root, producer_sha):
    """Bind the executing selector/tool bytes to one clean producer commit."""
    repo = Path(repo).resolve(strict=True)
    source_root = Path(source_root).resolve(strict=True)
    try:
        head = subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=repo, text=True,
            stderr=subprocess.STDOUT).strip()
        status = subprocess.check_output(
            ["git", "status", "--porcelain", "--untracked-files=all"],
            cwd=repo, text=True, stderr=subprocess.STDOUT)
    except subprocess.CalledProcessError as exc:
        raise ValueError("selector census producer repository is invalid") from exc
    if head != producer_sha:
        raise ValueError("selector census producer SHA differs from clean HEAD")
    if status.strip():
        raise ValueError("selector census producer repository is dirty")
    expected_live = {
        "mib/forensics.py": Path(forensics.__file__).resolve(),
        "tools/native_selector_census.py": Path(__file__).resolve(),
    }
    records = []
    for relative in BOUND_SOURCE_PATHS:
        live = (source_root / relative).resolve(strict=True)
        if live != expected_live[relative]:
            raise ValueError("selector census imported source is outside source root")
        try:
            committed = subprocess.check_output(
                ["git", "show", f"{producer_sha}:{relative}"], cwd=repo,
                stderr=subprocess.STDOUT)
        except subprocess.CalledProcessError as exc:
            raise ValueError("selector census source is absent from producer") from exc
        live_bytes = live.read_bytes()
        if committed != live_bytes:
            raise ValueError("selector census executing bytes differ from producer")
        records.append({"path": relative,
                        "sha256": hashlib.sha256(live_bytes).hexdigest()})
    return {"producer_git_sha": producer_sha, "files": records}


def build_census(input_dir, split, run_identity, effective_config,
                 producer_repo, partition="all", source_root=ROOT):
    expected_split = {"dev-md5": "dev", "holdout-md5": "holdout"}.get(
        partition)
    if expected_split is not None and split != expected_split:
        raise ValueError("selector census split and partition disagree")
    if split == "validation" and partition != "all":
        raise ValueError("validation selector census must use the full partition")
    input_dir = Path(input_dir).resolve(strict=True)
    pdfs = sorted(input_dir.glob("*.pdf"))
    if partition != "all":
        want_holdout = partition == "holdout-md5"
        pdfs = [pdf for pdf in pdfs if _is_holdout(pdf.stem) == want_holdout]
    if not pdfs:
        raise ValueError("selector census requires at least one input PDF")

    identity = dict(run_identity)
    _validate_run_identity(identity)
    producer_source_binding = _verify_producer_source(
        producer_repo, source_root, identity["producer_git_sha"])
    if identity["run_split"] != split:
        raise ValueError("selector census split differs from run identity")
    effective = canonical_effective_config(effective_config, environment={})
    if effective["MIB_NATIVE_SCAN_OCR"] != "1":
        raise ValueError("selector census requires native OCR enabled config")
    if canonical_sha256(effective) != identity["config_sha256"]:
        raise ValueError("selector census config differs from run identity")

    # Bind all paths before inspection, then inspect a second verified byte
    # snapshot. PyMuPDF consumes that in-memory snapshot, never a path that can
    # change between hashing and selector evaluation.
    snapshots = []
    for ordinal, pdf in enumerate(pdfs):
        raw = pdf.read_bytes()
        snapshots.append({
            "ordinal": ordinal,
            "case_id": pdf.stem,
            "path": str(pdf),
            "size": len(raw),
            "sha256": hashlib.sha256(raw).hexdigest(),
        })
    if canonical_sha256(_input_identity(snapshots)) != \
            identity["input_manifest_sha256"]:
        raise ValueError("selector census inputs differ from run identity")

    outcome_catalog = tuple(forensics.NATIVE_SCAN_SELECTOR_OUTCOMES)
    if len(outcome_catalog) != len(set(outcome_catalog)) or \
            "eligible" not in outcome_catalog:
        raise ValueError("selector outcome catalog is malformed")
    outcomes = Counter({name: 0 for name in outcome_catalog})
    inputs, document_errors = [], []
    eligible_pdfs = 0
    page_count = 0
    for result in _bounded_inspections(snapshots, outcome_catalog):
        inputs.append(result["record"])
        outcomes.update(result["outcomes"])
        page_count += result["page_count"]
        eligible_pdfs += int(result["eligible"])
        if result["document_error"] is not None:
            document_errors.append(result["document_error"])

    for snapshot, pdf in zip(snapshots, pdfs):
        raw = pdf.read_bytes()
        if (len(raw) != snapshot["size"]
                or hashlib.sha256(raw).hexdigest() != snapshot["sha256"]):
            raise ValueError("selector census input changed before publication")
    if sum(outcomes.values()) != page_count:
        raise ValueError("selector outcome counts do not match inspected pages")
    return {
        "schema": SCHEMA,
        "valid": not document_errors,
        "split": split,
        "partition": partition,
        "run_identity": identity,
        "run_identity_sha256": canonical_sha256(identity),
        "effective_config_sha256": canonical_sha256(effective),
        "producer_source_binding": producer_source_binding,
        "census_tool_sha256": _sha256_file(__file__),
        "selector_source_sha256": _sha256_file(forensics.__file__),
        "input_directory_name": input_dir.name,
        "input_manifest_sha256": identity["input_manifest_sha256"],
        "pdf_count": len(inputs),
        "page_count": page_count,
        "eligible_pdf_count": eligible_pdfs,
        "eligible_page_count": outcomes["eligible"],
        "inspection_process_max_cases": MAX_CASES_PER_INSPECTOR,
        "selector_outcome_catalog": list(outcome_catalog),
        "selector_outcome_counts": {
            key: outcomes[key]
            for key in outcome_catalog
        },
        "document_error_count": len(document_errors),
        "document_errors": document_errors,
        "inputs": inputs,
    }


def _write_new(path, payload):
    path = Path(path).resolve()
    if path.exists():
        raise ValueError(f"refusing to overwrite selector census: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w") as handle:
            json.dump(payload, handle, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.link(temporary, path)
    finally:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass


def main():
    if len(sys.argv) == 4 and sys.argv[1] == "--inspect-worker":
        _inspect_worker(sys.argv[2], sys.argv[3])
        return
    parser = argparse.ArgumentParser()
    parser.add_argument("--input-dir", required=True)
    parser.add_argument("--split", required=True,
                        choices=("dev", "holdout", "validation"))
    parser.add_argument("--partition", default="all",
                        choices=("all", "dev-md5", "holdout-md5"),
                        help="optional historical md5(case_id) train partition")
    parser.add_argument("--run-identity", required=True)
    parser.add_argument("--effective-config-json", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    try:
        identity = json.loads(Path(args.run_identity).read_text())
        effective_config = json.loads(args.effective_config_json)
        report = build_census(
            args.input_dir, args.split, identity, effective_config,
            ROOT, args.partition)
        _write_new(args.output, report)
    except (json.JSONDecodeError, OSError, ValueError) as exc:
        raise SystemExit(f"selector census failed: {exc}") from exc
    if report["document_error_count"]:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
