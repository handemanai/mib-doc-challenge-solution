#!/usr/bin/env python3
"""Create and verify fail-closed native-scan experiment bindings.

The binding is deliberately generated outside the OCR image.  It joins a clean
producer revision, an exact image identity, a file-by-file runtime manifest, a
canonical effective configuration, the exact ordered input bytes, and the
result artifacts.  Earlier, weaker binding schemas are intentionally not
accepted.
"""
import argparse
import hashlib
import json
import math
import os
import re
import subprocess
import tempfile
from datetime import date
from pathlib import Path, PurePosixPath


SCHEMA = "mib-native-artifact-binding-v3"
RUNTIME_MANIFEST_SCHEMA = "mib-runtime-manifest-v1"
RUN_IDENTITY_SCHEMA = "mib-run-identity-v1"
RUN_RECEIPT_SCHEMA = "mib-run-receipt-v2"
SHA1_RE = re.compile(r"[0-9a-f]{40}")
SHA256_RE = re.compile(r"[0-9a-f]{64}")
IMAGE_ID_RE = re.compile(r"sha256:[0-9a-f]{64}")
SPONSOR_VALUE_RE = re.compile(r"SPN-\d{4}")
VISA_CLASSES = {"DIP-1", "MED-3", "TRANSIT-7", "XW-1", "XW-2"}
# Exact current-producer contract for baseline_batch_context provenance.
# This table deliberately excludes latent channels: current pixmatch gates
# cannot populate these fields, and sponsor text extraction has no slip/letter
# label pattern. Generic labeled OCR remains allowed wherever parse_page can
# emit it, with sponsor/visa selector remaps reflected in the stored rank.
BASELINE_CONTEXT_FIELD_RANKS = {
    "arrival_date": {
        "adjudicator_note": 1,
        "intake": 2,
        "fee_receipt": 2,
        "slip_label": 3,
        "biometric": 3,
        "letter_label": 4,
        "sponsor_letter": 4,
        "registry": 5,
        "unknown": 6,
    },
    "sponsor_id": {
        "adjudicator_note": 1,
        "manual_correction": 1,
        "fee_receipt": 2,
        "sponsor_letter": 2,
        "intake": 3,
        "biometric": 3,
        "registry": 5,
        "unknown": 6,
    },
    "visa_class": {
        "adjudicator_note": 1,
        "manual_correction": 1,
        "fee_receipt": 2,
        "sponsor_letter": 2,
        "letter_label": 2,
        "intake": 3,
        "biometric": 3,
        "slip_label": 3,
        "registry": 5,
        "unknown": 6,
    },
}
BASELINE_BARE_SOURCES = frozenset({
    "adjudicator_note_bare", "intake_bare", "fee_receipt_bare",
    "biometric_bare", "sponsor_letter_bare", "registry_bare",
    "unknown_bare",
})
BASELINE_OCR_PAGE_SOURCES = frozenset({
    "adjudicator_note", "intake", "fee_receipt", "biometric",
    "sponsor_letter", "registry", "unknown",
})


def _baseline_context_expected_rank(field, source):
    """Return the only rank this field/source pair can leave the producer."""
    if source in BASELINE_BARE_SOURCES:
        return 6
    return BASELINE_CONTEXT_FIELD_RANKS.get(field, {}).get(source)


def _baseline_context_confidence_is_possible(
        field, source, confidence, value, raw):
    """Whether one retained confidence/raw tuple can leave the producer.

    Arrival pools retain creation-time scores. Sponsor and visa retain one
    selected record but may raise only its confidence from same-value support;
    source, rank, and raw remain attached to the selected record. These bounds
    therefore follow the actual parser/extractor paths rather than accepting an
    arbitrary 0..100 value that could suppress batch sponsor or epoch logic.
    """
    score = float(confidence)
    if field == "arrival_date":
        if source in {"slip_label", "letter_label"}:
            return score == 95 and raw == value
        if source in BASELINE_OCR_PAGE_SOURCES:
            return score in {72, 75, 80, 87, 90, 95}
        if source in BASELINE_BARE_SOURCES:
            return score in {65, 70}
        return False
    if field == "sponsor_id":
        if source == "manual_correction":
            return score == 99 and raw == value
        if source in BASELINE_OCR_PAGE_SOURCES:
            return score in {87, 90, 95}
        if source in BASELINE_BARE_SOURCES:
            return score == 70
        return False
    if field == "visa_class":
        if source == "manual_correction":
            return 99 <= score <= 100 and raw == value
        if source in {"slip_label", "letter_label"}:
            return 95 <= score <= 100 and raw == value
        if source in BASELINE_OCR_PAGE_SOURCES:
            # snap() gates the initial best match at 72, but its weighted
            # reranker may choose a near alternative (>60); truncated-label
            # parsing then subtracts eight. The strict lower bound is >52.
            return 52 < score <= 100
        if source in BASELINE_BARE_SOURCES:
            return score == 66
        return False
    return False


ARTIFACT_NAME_RE = re.compile(r"[a-z][a-z0-9_]*")
ADJUDICATIONS = {"APPROVED", "DENIED", "NEEDS_REVIEW"}
PREDICTION_FIELDS = (
    "applicant_name", "species_code", "home_world", "visa_class",
    "sponsor_id", "arrival_date", "declared_purpose", "risk_flags",
    "fee_status",
)
SEMANTIC_RANK1_CONFLICTS = {"finding_vs_signed_evidence"}
IMAGE_VIEW_REGISTRY_SCHEMA = "mib-image-view-registry-v1"
VIEW_TOKEN_RE = re.compile(r"[a-z][a-z0-9_]*")
PIX_GATE_THRESHOLDS = {
    "species_code": (0.45, 0.08),
    "home_world": (0.55, 0.12),
}
PIX_FIELD_PAGE_TYPES = {
    "species_code": {"intake", "registry", "biometric", "unknown"},
    "home_world": {"intake", "registry", "unknown"},
}
# Exact closed-vocabulary producer contract. These values intentionally live
# in the stdlib-only binder as well as the runtime; tests pin them together so
# the external verifier does not acquire OCR/runtime package dependencies.
PIX_ALLOWED_VALUES = {
    "species_code": frozenset({
        "ALPHA_DRACONIAN", "ANDROMEDAN", "AQUARIAN_MANTIS", "ARCTURIAN",
        "CENTAURI_SYNTH", "JOVIAN_GASFORM", "KAIJU_MICRO", "LUNA_SECURID",
        "ORION_GRAYS", "SIRIUS_AVIAN", "TRIANGULAN",
        "VENUSIAN_MYCELIAL",
    }),
    "home_world": frozenset({
        "Barnard-c", "Eris Relay", "Europa Station", "Gliese-581g",
        "Kepler-186f", "Luyten-b", "Mars Dome-7", "Proxima-b",
        "Sirius Outpost", "TRAPPIST-1e", "Titan Freeport", "Wolf-1061c",
        "Zeta Reticuli",
    }),
}
PIX_BASELINE_GUARD_WORLDS = frozenset({
    "Eris Relay", "TRAPPIST-1e", "Wolf-1061c",
})

# Exact Dockerfile runtime closure for this integration candidate. Tooling and
# evaluation helpers are intentionally excluded because the image does not COPY
# them. A manifest with even one missing or extra file cannot identify this
# runtime.
EXPECTED_RUNTIME_REPO_PATHS = (
    "mib/__init__.py",
    "mib/caseid.py",
    "mib/correct.py",
    "mib/ctcscore.py",
    "mib/extract.py",
    "mib/feeread.py",
    "mib/flagread.py",
    "mib/forensics.py",
    "mib/native_ledger.py",
    "mib/noteread.py",
    "mib/ocr.py",
    "mib/parse_ocr.py",
    "mib/pipeline.py",
    "mib/pixmatch.py",
    "mib/rules.py",
    "mib/sponsorread.py",
    "mib/two_ledger.py",
    "mib/vocab.py",
    "mib/view_registry.py",
    "mib/worldread.py",
    "models/calibrator.json",
    "models/confusion_costs.json",
    "models/en_PP-OCRv5_rec_mobile.onnx",
    "models/name_vocab.json",
    "models/path_confidence.json",
    "models/pix_bank.npz",
    "models/reason_buckets.json",
    "models/transducer_dec.int8.onnx",
    "models/transducer_enc.int8.onnx",
    "models/transducer_vocab.json",
    "run.sh",
    "scripts/predict.py",
    "scripts/run_shard.py",
)
EXPECTED_RUNTIME_FILE_MAP = {
    repo_path: f"/app/{repo_path}" for repo_path in EXPECTED_RUNTIME_REPO_PATHS
}

# Every environment value below can alter extraction, retry/fault containment,
# timing, or the evidence artifact.  The JSON accepted by the CLI is an
# override map; omitted values are expanded to these effective defaults before
# hashing.  External model paths are forbidden for this focused campaign: the
# exact image and runtime manifest bind the bundled model bytes instead.
EFFECTIVE_CONFIG_DEFAULTS = {
    "MIB_NATIVE_SCAN_OCR": "1",
    "MIB_NATIVE_SCAN_FAST_DPI": "150",
    "MIB_PIXMATCH": "1",
    "MIB_TRANSDUCER": "0",
    "MIB_ANTI_ORACLE_GUARD": "0",
    "MIB_GOVERNOR": "1",
    "MIB_REC_MODEL": "",
    "MIB_PIX_BANK": "",
    "MIB_DUMP_RAW": "0",
    "MIB_DISABLE_EXTRACTION_RETRY": "0",
    "MIB_WORKER_MAX_CASES": "48",
    "MIB_MAX_RETRY_CASES": "8",
    "MIB_RETRY_CASE_TIMEOUT": "130",
    "MIB_RETRY_BUDGET_SECS": "1100",
    "MIB_RETRY_KILL_GRACE_SECS": "5",
    "MIB_BATCH_LIMIT_SECS": "30000",
    "MIB_FINALIZE_RESERVE_SECS": "60",
    "MIB_CASE_TIMEOUT": "120",
    "MIB_STUCK_SECS": "150",
    "MIB_STARTUP_GRACE": "120",
    "MIB_WATCHDOG_POLL": "2",
    "MIB_FLUSH_SECS": "300",
    "OMP_NUM_THREADS": "1",
    "OPENBLAS_NUM_THREADS": "1",
    "MKL_NUM_THREADS": "1",
}
BOOLEAN_CONFIG = {
    "MIB_NATIVE_SCAN_OCR", "MIB_PIXMATCH", "MIB_DUMP_RAW",
    "MIB_DISABLE_EXTRACTION_RETRY", "MIB_TRANSDUCER",
    "MIB_ANTI_ORACLE_GUARD", "MIB_GOVERNOR",
}
INTEGER_CONFIG = {
    "MIB_NATIVE_SCAN_FAST_DPI", "MIB_WORKER_MAX_CASES",
    "MIB_MAX_RETRY_CASES", "MIB_CASE_TIMEOUT",
    "OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS",
}
FLOAT_CONFIG = {
    "MIB_RETRY_CASE_TIMEOUT", "MIB_RETRY_BUDGET_SECS",
    "MIB_RETRY_KILL_GRACE_SECS", "MIB_BATCH_LIMIT_SECS",
    "MIB_FINALIZE_RESERVE_SECS", "MIB_STUCK_SECS", "MIB_STARTUP_GRACE",
    "MIB_WATCHDOG_POLL", "MIB_FLUSH_SECS",
}
NON_CONFIG_MIB_ENV = {"MIB_LEDGER"}
INTERNAL_OR_INJECTION_ENV = {"MIB_ACTIVE_CASE", "MIB_EXTRACTION_ATTEMPT",
                             "MIB_GOVERNOR_FORCE_LEVEL"}
IDENTITY_KEYS = {
    "producer_git_sha", "image_id", "image_revision",
    "image_inspect_sha256", "runtime_manifest_sha256", "config_sha256",
    "input_manifest_sha256", "run_receipt_sha256", "run_split", "run_nonce",
    "binding_sha256",
}
RUN_IDENTITY_KEYS = {
    "schema", "producer_git_sha", "image_id", "image_revision",
    "image_inspect_sha256", "runtime_manifest_sha256", "config_sha256",
    "input_manifest_sha256", "run_split", "run_nonce",
}
RUN_SPLITS = {"dev", "holdout", "validation"}


def sha256_file(path):
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def canonical_sha256(value):
    encoded = json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _git(repo, *args, text=True):
    return subprocess.check_output(
        ["git", *args], cwd=repo, text=text, stderr=subprocess.STDOUT)


def _git_head(repo):
    return _git(repo, "rev-parse", "HEAD").strip()


def _require_clean_repo(repo):
    status = _git(repo, "status", "--porcelain", "--untracked-files=all")
    if status.strip():
        raise ValueError("producer repository is dirty; commit or remove every change")


def _validate_runtime_manifest(manifest, producer_sha, image_id, repo=None):
    if not isinstance(manifest, dict) or set(manifest) != {
            "schema", "producer_git_sha", "image_id", "image_revision", "files"}:
        raise ValueError("runtime manifest has unexpected or missing keys")
    if manifest.get("schema") != RUNTIME_MANIFEST_SCHEMA:
        raise ValueError("unsupported runtime manifest schema")
    if manifest.get("producer_git_sha") != producer_sha:
        raise ValueError("runtime manifest producer differs from binding producer")
    if manifest.get("image_id") != image_id:
        raise ValueError("runtime manifest image ID differs from binding image")
    if manifest.get("image_revision") != producer_sha:
        raise ValueError("runtime manifest image revision must equal producer SHA")
    files = manifest.get("files")
    if not isinstance(files, list):
        raise ValueError("runtime manifest files must be a list")

    repo_paths, image_paths = set(), set()
    for record in files:
        if not isinstance(record, dict) or set(record) != {
                "repo_path", "image_path", "source_sha256", "image_sha256"}:
            raise ValueError("runtime manifest file record is malformed")
        repo_path = record.get("repo_path")
        image_path = record.get("image_path")
        if not isinstance(repo_path, str) or not repo_path or \
                Path(repo_path).is_absolute() or ".." in Path(repo_path).parts:
            raise ValueError("runtime manifest repo_path must be a safe relative path")
        if not isinstance(image_path, str) or not image_path.startswith("/app/"):
            raise ValueError("runtime manifest image_path must be under /app")
        canonical_image_path = str(PurePosixPath(image_path))
        if canonical_image_path != image_path or ".." in PurePosixPath(
                image_path).parts:
            raise ValueError("runtime manifest image_path must be canonical")
        if repo_path in repo_paths or image_path in image_paths:
            raise ValueError("runtime manifest contains duplicate source/image paths")
        repo_paths.add(repo_path)
        image_paths.add(image_path)
        source_hash = record.get("source_sha256")
        image_hash = record.get("image_sha256")
        if not SHA256_RE.fullmatch(source_hash or "") or \
                not SHA256_RE.fullmatch(image_hash or ""):
            raise ValueError("runtime manifest contains a malformed file hash")
        if source_hash != image_hash:
            raise ValueError("runtime image file differs from tracked source bytes")
        if repo is not None:
            try:
                committed = _git(repo, "show", f"{producer_sha}:{repo_path}", text=False)
            except subprocess.CalledProcessError as exc:
                raise ValueError(
                    f"runtime manifest path is not tracked at producer SHA: {repo_path}"
                ) from exc
            if hashlib.sha256(committed).hexdigest() != source_hash:
                raise ValueError(
                    f"runtime manifest source hash differs from producer: {repo_path}")
    if repo_paths != set(EXPECTED_RUNTIME_FILE_MAP) or image_paths != set(
            EXPECTED_RUNTIME_FILE_MAP.values()):
        missing = sorted(set(EXPECTED_RUNTIME_FILE_MAP) - repo_paths)
        extra = sorted(repo_paths - set(EXPECTED_RUNTIME_FILE_MAP))
        raise ValueError(
            "runtime manifest does not match exact Docker runtime closure; "
            f"missing={missing} extra={extra}")
    for record in files:
        if EXPECTED_RUNTIME_FILE_MAP[record["repo_path"]] != record["image_path"]:
            raise ValueError(
                "runtime manifest source/image path mapping differs from Dockerfile")
    return manifest


def canonical_effective_config(overrides, environment=None):
    if not isinstance(overrides, dict):
        raise ValueError("effective config must be a JSON object")
    unknown = set(overrides) - set(EFFECTIVE_CONFIG_DEFAULTS)
    if unknown:
        raise ValueError("unknown effective config keys: " + ", ".join(sorted(unknown)))
    if any(not isinstance(value, str) for value in overrides.values()):
        raise ValueError("effective config values must be strings")

    environment = os.environ if environment is None else environment
    for key in environment:
        if key.startswith("MIB_TEST_") or key in INTERNAL_OR_INJECTION_ENV:
            raise ValueError(f"test/injection environment is forbidden: {key}")
        if key.startswith("MIB_") and key not in EFFECTIVE_CONFIG_DEFAULTS \
                and key not in NON_CONFIG_MIB_ENV:
            raise ValueError(f"unknown MIB environment is forbidden: {key}")

    effective = dict(EFFECTIVE_CONFIG_DEFAULTS)
    effective.update(overrides)
    for key, value in effective.items():
        if key in environment and environment[key] != value:
            raise ValueError(f"claimed config differs from live environment: {key}")
    for key in BOOLEAN_CONFIG:
        if effective[key] not in {"0", "1"}:
            raise ValueError(f"{key} must be 0 or 1")
    for key in INTEGER_CONFIG:
        try:
            parsed = int(effective[key])
        except ValueError as exc:
            raise ValueError(f"{key} must be an integer") from exc
        if parsed <= 0 and key != "MIB_MAX_RETRY_CASES":
            raise ValueError(f"{key} must be positive")
        if parsed < 0:
            raise ValueError(f"{key} must be nonnegative")
    for key in FLOAT_CONFIG:
        try:
            parsed = float(effective[key])
        except ValueError as exc:
            raise ValueError(f"{key} must be numeric") from exc
        if not math.isfinite(parsed) or parsed <= 0:
            raise ValueError(f"{key} must be positive")
    if effective["MIB_TRANSDUCER"] != "0":
        raise ValueError("MIB_TRANSDUCER must remain disabled for this candidate")
    for key in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS"):
        if effective[key] != "1":
            raise ValueError(f"{key} must be pinned to 1")
    for key in ("MIB_REC_MODEL", "MIB_PIX_BANK"):
        if effective[key]:
            raise ValueError(
                f"{key} must use image-bundled bytes for this bound candidate")
    return effective


def _input_identity(entries):
    return [{key: entry[key] for key in ("ordinal", "case_id", "size", "sha256")}
            for entry in entries]


def input_manifest(paths):
    entries, seen = [], set()
    for ordinal, raw in enumerate(paths):
        path = Path(raw).resolve(strict=True)
        if not path.is_file() or path.suffix.lower() != ".pdf":
            raise ValueError(f"input is not a PDF file: {path}")
        case_id = path.stem
        if case_id in seen:
            raise ValueError(f"duplicate input case_id: {case_id}")
        seen.add(case_id)
        entries.append({
            "ordinal": ordinal,
            "case_id": case_id,
            "path": str(path),
            "size": path.stat().st_size,
            "sha256": sha256_file(path),
        })
    if not entries:
        raise ValueError("input manifest is empty")
    return entries


def _validate_image_inspect(value, image_id, image_revision):
    inspected = value[0] if isinstance(value, list) and len(value) == 1 else value
    if not isinstance(inspected, dict) or inspected.get("Id") != image_id:
        raise ValueError("image inspection ID differs from the binding")
    labels = inspected.get("Config", {}).get("Labels") or {}
    if labels.get("org.opencontainers.image.revision") != image_revision:
        raise ValueError("image revision label differs from the binding")


def _receipt_input_identity(entries):
    return [{
        "ordinal": entry["ordinal"],
        "case_id": entry["case_id"],
        "filename": Path(entry["path"]).name,
        "size": entry["size"],
        "sha256": entry["sha256"],
    } for entry in entries]


def _validate_run_identity(identity):
    if not isinstance(identity, dict) or set(identity) != RUN_IDENTITY_KEYS:
        raise ValueError("run identity has unexpected or missing keys")
    if identity.get("schema") != RUN_IDENTITY_SCHEMA:
        raise ValueError("unsupported run identity schema")
    if not SHA1_RE.fullmatch(identity.get("producer_git_sha") or ""):
        raise ValueError("run identity producer SHA is malformed")
    if not IMAGE_ID_RE.fullmatch(identity.get("image_id") or ""):
        raise ValueError("run identity image ID is malformed")
    if identity.get("image_revision") != identity["producer_git_sha"]:
        raise ValueError("run identity image revision must equal producer SHA")
    for key in (
            "image_inspect_sha256", "runtime_manifest_sha256",
            "config_sha256", "input_manifest_sha256"):
        if not SHA256_RE.fullmatch(identity.get(key) or ""):
            raise ValueError(f"run identity {key} is malformed")
    if identity.get("run_split") not in RUN_SPLITS:
        raise ValueError("run identity split is malformed")
    if not SHA256_RE.fullmatch(identity.get("run_nonce") or ""):
        raise ValueError("run identity nonce must be 256-bit lowercase hex")
    return identity


def _expected_run_identity(producer_sha, image_id, image_inspect_sha256,
                           runtime_manifest_sha256, config_sha256,
                           input_manifest_sha256, run_split, run_nonce):
    return {
        "schema": RUN_IDENTITY_SCHEMA,
        "producer_git_sha": producer_sha,
        "image_id": image_id,
        "image_revision": producer_sha,
        "image_inspect_sha256": image_inspect_sha256,
        "runtime_manifest_sha256": runtime_manifest_sha256,
        "config_sha256": config_sha256,
        "input_manifest_sha256": input_manifest_sha256,
        "run_split": run_split,
        "run_nonce": run_nonce,
    }


def _validate_run_receipt(receipt, entries, effective_config,
                          prediction_path, evidence_path,
                          expected_run_identity):
    required = {
        "schema", "run_identity", "run_identity_sha256", "effective_config",
        "config_sha256", "run_split", "run_nonce", "worker_count",
        "input_source", "input_manifest", "input_manifest_sha256", "artifacts",
        "terminal_status",
    }
    if not isinstance(receipt, dict) or set(receipt) != required:
        raise ValueError("run receipt has unexpected or missing keys")
    if receipt.get("schema") != RUN_RECEIPT_SCHEMA:
        raise ValueError("unsupported run receipt schema")
    if receipt.get("terminal_status") != "completed":
        raise ValueError("run receipt does not prove completed artifact production")
    identity = _validate_run_identity(receipt.get("run_identity"))
    identity_sha256 = receipt.get("run_identity_sha256")
    if not SHA256_RE.fullmatch(identity_sha256 or "") or \
            canonical_sha256(identity) != identity_sha256:
        raise ValueError("run receipt identity hash mismatch")
    _validate_run_identity(expected_run_identity)
    if identity != expected_run_identity:
        raise ValueError(
            "run receipt producer identity differs from independently bound identity")
    if receipt.get("run_split") != identity["run_split"]:
        raise ValueError("run receipt split differs from its bound identity")
    if receipt.get("run_nonce") != identity["run_nonce"]:
        raise ValueError("run receipt nonce differs from its bound identity")
    if canonical_effective_config(
            receipt.get("effective_config"), environment={}) != effective_config:
        raise ValueError("run receipt effective config differs from binding")
    config_sha256 = canonical_sha256(effective_config)
    if receipt.get("config_sha256") != config_sha256 or \
            identity["config_sha256"] != config_sha256:
        raise ValueError("run receipt config hash differs from binding")
    workers = receipt.get("worker_count")
    if not isinstance(workers, int) or isinstance(workers, bool) or not 1 <= workers <= 4:
        raise ValueError("run receipt worker_count must be an integer from 1 to 4")
    source = receipt.get("input_source")
    if not isinstance(source, dict) or set(source) != {
            "kind", "directory_name"} or source.get("kind") != \
            "sorted_pdf_directory" or not source.get("directory_name"):
        raise ValueError("run receipt input source is malformed")
    if receipt.get("input_manifest") != _receipt_input_identity(entries):
        raise ValueError("run receipt input manifest differs from bound inputs")
    input_manifest_sha256 = canonical_sha256(_input_identity(entries))
    if receipt.get("input_manifest_sha256") != input_manifest_sha256 or \
            identity["input_manifest_sha256"] != input_manifest_sha256:
        raise ValueError("run receipt input hash differs from bound inputs")
    artifacts = receipt.get("artifacts")
    if not isinstance(artifacts, dict) or set(artifacts) != {
            "predictions", "evidence"}:
        raise ValueError("run receipt artifacts are malformed")
    for name, artifact_path in (
            ("predictions", Path(prediction_path)),
            ("evidence", Path(evidence_path))):
        record = artifacts[name]
        if not isinstance(record, dict) or set(record) != {
                "filename", "size", "sha256"}:
            raise ValueError(f"run receipt artifact {name} record is malformed")
        if not isinstance(record.get("filename"), str) or \
                record["filename"] != artifact_path.name:
            raise ValueError(
                f"run receipt artifact {name} filename differs from bound output")
        if not isinstance(record.get("size"), int) or \
                isinstance(record["size"], bool) or record["size"] < 0:
            raise ValueError(f"run receipt artifact {name} size is malformed")
        if not SHA256_RE.fullmatch(record.get("sha256") or ""):
            raise ValueError(f"run receipt artifact {name} hash is malformed")
        if record["size"] != artifact_path.stat().st_size or \
                record["sha256"] != sha256_file(artifact_path):
            raise ValueError(
                f"run receipt artifact {name} hash/size differs from bound output")
    input_ids = [entry["case_id"] for entry in entries]
    expected_order = [
        case_id for shard in range(workers) for case_id in input_ids[shard::workers]
    ]
    return workers, expected_order


def _jsonl_case_ids(path):
    rows, case_ids = [], []
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
            rows.append(row)
            case_ids.append(case_id)
    if len(case_ids) != len(set(case_ids)):
        raise ValueError(f"duplicate case_id in {path}")
    return rows, case_ids


def _validate_prediction_rows(rows):
    for row in rows:
        missing = [field for field in (*PREDICTION_FIELDS, "adjudication")
                   if field not in row]
        if missing:
            raise ValueError(
                f"prediction row is missing required fields: {missing}")
        if row["adjudication"] not in ADJUDICATIONS:
            raise ValueError("prediction row has invalid adjudication")


def _validate_extraction_provenance(extraction):
    if not isinstance(extraction, dict) or set(extraction) != {
            "attempt_count", "recovered", "attempts"}:
        raise ValueError("evidence row extraction provenance is malformed")
    attempts = extraction["attempts"]
    if not isinstance(attempts, list) or len(attempts) not in {1, 2}:
        raise ValueError("evidence row extraction attempts are malformed")
    for index, attempt in enumerate(attempts, 1):
        if not isinstance(attempt, dict) or attempt.get("attempt") != index:
            raise ValueError("evidence row extraction attempt order is malformed")
        status = attempt.get("status")
        if status not in {"success", "failed", "not_attempted"}:
            raise ValueError("evidence row extraction attempt status is malformed")
        category = attempt.get("failure_category")
        if status == "success":
            if category is not None:
                raise ValueError("successful extraction attempt has failure category")
            if "error" in attempt:
                raise ValueError("successful extraction attempt has error")
        elif not isinstance(category, str) or not category:
            raise ValueError("unsuccessful extraction attempt lacks failure category")
        if "error" in attempt and (not isinstance(attempt["error"], str)
                                   or not attempt["error"]):
            raise ValueError("extraction attempt error is malformed")
    if attempts[0]["status"] == "not_attempted":
        raise ValueError("first extraction attempt cannot be not_attempted")
    if len(attempts) == 2 and attempts[0]["status"] != "failed":
        raise ValueError(
            "second extraction attempt requires a failed first attempt")
    attempt_count = sum(
        attempt["status"] != "not_attempted" for attempt in attempts)
    if (not isinstance(extraction["attempt_count"], int)
            or isinstance(extraction["attempt_count"], bool)
            or extraction["attempt_count"] != attempt_count):
        raise ValueError("evidence row extraction attempt count is inconsistent")
    recovered = (len(attempts) == 2
                 and attempts[0]["status"] != "success"
                 and attempts[1]["status"] == "success")
    if not isinstance(extraction["recovered"], bool) or \
            extraction["recovered"] is not recovered:
        raise ValueError("evidence row extraction recovery flag is inconsistent")


def _nonnegative_page(value, label):
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{label} is malformed")
    return value


def _validate_page_number_list(value, label):
    if (not isinstance(value, list)
            or any(isinstance(page, bool) or not isinstance(page, int)
                   or page < 0 for page in value)
            or value != sorted(set(value))):
        raise ValueError(f"{label} is malformed")


def _finite(value, label, *, positive=False):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{label} is malformed")
    number = float(value)
    if not math.isfinite(number) or (positive and number <= 0):
        raise ValueError(f"{label} is malformed")
    return number


def _validate_view_event_contract(event, effective_config):
    native_enabled = effective_config["MIB_NATIVE_SCAN_OCR"] == "1"
    pixmatch_enabled = effective_config["MIB_PIXMATCH"] == "1"
    consumer = event["consumer"]
    pass_name = event["pass"]
    transform = event["transform"]
    source = event["source"]
    preprocess = event["preprocess"]
    dpi = float(event["dpi"])
    rotation = float(event["rotation_degrees"])
    if consumer in {"candidate_ocr", "baseline_ocr"}:
        expected_dpi = 250.0 if pass_name == "hq" else 150.0
        if (native_enabled and consumer == "candidate_ocr"
                and source == "native_full_page_image"
                and pass_name == "fast"):
            expected_dpi = float(
                effective_config["MIB_NATIVE_SCAN_FAST_DPI"])
        if (pass_name not in {"fast", "hq"}
                or transform != "selected_ocr_input"
                or dpi != expected_dpi
                or rotation not in {0.0, 90.0, 180.0, 270.0}
                or preprocess not in {
                    "none", "pepper_filter", "stretch",
                    "pepper_filter_stretch", "rotate",
                    "pepper_filter_rotate", "stretch_rotate",
                    "pepper_filter_stretch_rotate"}):
            raise ValueError("image view OCR event contract is malformed")
        if consumer == "baseline_ocr":
            allowed_sources = {"masked_pdf_render"}
        elif native_enabled:
            allowed_sources = {
                "composited_pdf_render", "native_full_page_image"}
        else:
            allowed_sources = {"masked_pdf_render"}
        if source not in allowed_sources:
            raise ValueError("image view OCR source is inconsistent")
        return
    if consumer not in {"candidate_pixmatch", "baseline_pixmatch"}:
        raise ValueError("image view consumer is not produced by runtime")
    if not pixmatch_enabled or (consumer == "baseline_pixmatch"
                                and not native_enabled):
        raise ValueError("image view pixmatch consumer is disabled")
    if consumer == "candidate_pixmatch" and native_enabled:
        contracts = {
            "native_decoded": (
                "decode", "native_embedded_image", {"decode_grayscale"}),
            "footer_sanitized": (
                "decode", "native_embedded_image",
                {"footer_passthrough", "footer_suppression"}),
            "native_scan_output": (
                "decode", "native_full_page_image", {"orientation"}),
            "despeckled": (
                "decode", "native_full_page_image", {"despeckle"}),
            "deskewed": (
                "decode", "native_full_page_image", {"deskew"}),
            "accepted_roi": (
                None, "deskewed_pixmatch_view", {"roi"}),
        }
    else:
        contracts = {
            "p0b_scan_output": (
                "decode", "p0b_masked_scan_image",
                {"grayscale_despeckle",
                 "grayscale_despeckle_hidden_mask"}),
            "deskewed": (
                "decode", "p0b_masked_scan_image", {"deskew"}),
            "accepted_roi": (
                None, "deskewed_pixmatch_view", {"roi"}),
        }
    contract = contracts.get(transform)
    if contract is None:
        raise ValueError("image view pixmatch transform is inconsistent")
    expected_pass, expected_source, allowed_preprocess = contract
    if (source != expected_source or preprocess not in allowed_preprocess
            or (expected_pass is not None and pass_name != expected_pass)
            or (expected_pass is None and pass_name not in PIX_GATE_THRESHOLDS)):
        raise ValueError("image view pixmatch event contract is malformed")
    if transform in {"native_decoded", "footer_sanitized", "despeckled",
                     "p0b_scan_output", "accepted_roi"} and rotation != 0.0:
        raise ValueError("image view pixmatch rotation is inconsistent")
    if transform == "native_scan_output" and rotation not in {
            0.0, 90.0, 180.0, 270.0}:
        raise ValueError("native image orientation is malformed")
    if transform == "deskewed" and not -8.0 <= rotation <= 8.0:
        raise ValueError("pixmatch deskew rotation is malformed")


def _validate_image_view_registry(registry, effective_config,
                                  execution_error, fallback_pages):
    if (not isinstance(registry, dict)
            or set(registry) != {"schema", "pages", "errors"}
            or registry.get("schema") != IMAGE_VIEW_REGISTRY_SCHEMA
            or not isinstance(registry.get("pages"), list)
            or not isinstance(registry.get("errors"), list)):
        raise ValueError("image view registry is malformed")
    native_enabled = effective_config["MIB_NATIVE_SCAN_OCR"] == "1"
    pixmatch_enabled = effective_config["MIB_PIXMATCH"] == "1"
    pages = registry["pages"]
    observed_pages = []
    semantic = set()
    event_index = {}
    roi_event_keys = set()
    composited_candidate_pages = set()
    for page_record in pages:
        if (not isinstance(page_record, dict)
                or set(page_record) != {"page", "events"}
                or not isinstance(page_record["events"], list)
                or not page_record["events"]):
            raise ValueError("image view registry page is malformed")
        page = _nonnegative_page(
            page_record["page"], "image view registry page")
        observed_pages.append(page)
        for ordinal, event in enumerate(page_record["events"]):
            required = {
                "view_id", "page", "ordinal", "consumer", "pass",
                "transform", "source", "preprocess", "dpi",
                "rotation_degrees", "shape", "dtype", "pixel_sha256",
            }
            if not isinstance(event, dict) or set(event) != required:
                raise ValueError("image view registry event is malformed")
            if (event["page"] != page or event["ordinal"] != ordinal
                    or isinstance(event["ordinal"], bool)):
                raise ValueError("image view registry event order is malformed")
            for key in ("consumer", "pass", "transform", "source",
                        "preprocess"):
                if (not isinstance(event[key], str)
                        or not VIEW_TOKEN_RE.fullmatch(event[key])):
                    raise ValueError("image view registry token is malformed")
            key = (page, event["consumer"], event["pass"],
                   event["transform"])
            if key in semantic:
                raise ValueError("image view registry semantic duplicate")
            semantic.add(key)
            expected_id = (f"p{page}:{ordinal}:{event['consumer']}:"
                           f"{event['pass']}:{event['transform']}")
            if event["view_id"] != expected_id:
                raise ValueError("image view registry view ID is malformed")
            _finite(event["dpi"], "image view registry dpi", positive=True)
            _finite(event["rotation_degrees"],
                    "image view registry rotation")
            shape = event["shape"]
            if (not isinstance(shape, list) or len(shape) != 2
                    or any(isinstance(value, bool)
                           or not isinstance(value, int) or value <= 0
                           for value in shape)
                    or event["dtype"] != "uint8"
                    or not SHA256_RE.fullmatch(
                        event.get("pixel_sha256") or "")):
                raise ValueError("image view registry pixels are malformed")
            _validate_view_event_contract(event, effective_config)
            event_index[key] = event
            if event["transform"] == "accepted_roi":
                roi_event_keys.add(key)
            if (event["consumer"] == "candidate_ocr"
                    and event["source"] == "composited_pdf_render"):
                composited_candidate_pages.add(page)
    if observed_pages != sorted(set(observed_pages)):
        raise ValueError("image view registry pages are not canonical")
    for error in registry["errors"]:
        if (not isinstance(error, dict)
                or set(error) != {"page", "semantic_id", "error_type"}
                or (error["page"] is not None
                    and (isinstance(error["page"], bool)
                         or not isinstance(error["page"], int)
                         or error["page"] < 0))
                or not isinstance(error["semantic_id"], str)
                or not error["semantic_id"]
                or len(error["semantic_id"]) > 240
                or not isinstance(error["error_type"], str)
                or not error["error_type"]
                or len(error["error_type"]) > 80):
            raise ValueError("image view registry error is malformed")
    if registry["errors"]:
        raise ValueError("evidence row has image registry errors")
    if (not native_enabled and fallback_pages) or (
            native_enabled
            and composited_candidate_pages != set(fallback_pages)):
        raise ValueError(
            "native fallback pages differ from composited OCR views")

    for page in observed_pages:
        page_events = next(
            item["events"] for item in pages if item["page"] == page)
        for consumer in ("candidate_pixmatch", "baseline_pixmatch"):
            events = [event for event in page_events
                      if event["consumer"] == consumer]
            if not events:
                continue
            core = [event for event in events
                    if event["transform"] != "accepted_roi"]
            transforms = [event["transform"] for event in core]
            all_transforms = [event["transform"] for event in events]
            if consumer == "candidate_pixmatch" and native_enabled:
                full = ["native_decoded", "footer_sanitized",
                        "native_scan_output", "despeckled", "deskewed"]
                if transforms not in (["native_decoded"], full):
                    raise ValueError("native pixmatch view chain is incomplete")
                if (transforms == ["native_decoded"]
                        and all_transforms != ["native_decoded"]) or (
                        transforms == full
                        and (all_transforms[:len(full)] != full
                             or any(transform != "accepted_roi"
                                    for transform in all_transforms[len(full):]))):
                    raise ValueError("native pixmatch view order is malformed")
                if transforms == full:
                    if len({float(event["dpi"]) for event in core}) != 1:
                        raise ValueError("native pixmatch DPI chain differs")
                    if core[0]["shape"] != core[1]["shape"]:
                        raise ValueError("native footer view shape differs")
                    if (core[1]["preprocess"] == "footer_passthrough"
                            and core[0]["pixel_sha256"] !=
                            core[1]["pixel_sha256"]):
                        raise ValueError("native footer passthrough pixels differ")
                    decoded_height, decoded_width = core[1]["shape"]
                    output_shape = ([decoded_width, decoded_height]
                                    if float(core[2]["rotation_degrees"])
                                    in {90.0, 270.0}
                                    else [decoded_height, decoded_width])
                    if (core[2]["shape"] != output_shape
                            or core[2]["shape"] != core[3]["shape"]
                            or core[3]["shape"] != core[4]["shape"]):
                        raise ValueError("native deskew view shape differs")
                    if (float(core[4]["rotation_degrees"]) == 0.0
                            and core[3]["pixel_sha256"] !=
                            core[4]["pixel_sha256"]):
                        raise ValueError(
                            "zero-angle native deskew pixels differ")
            else:
                if transforms != ["p0b_scan_output", "deskewed"]:
                    raise ValueError("P0-B pixmatch view chain is incomplete")
                if (all_transforms[:2] != transforms
                        or any(transform != "accepted_roi"
                               for transform in all_transforms[2:])):
                    raise ValueError("P0-B pixmatch view order is malformed")
                if (float(core[0]["dpi"]) != float(core[1]["dpi"])
                        or core[0]["shape"] != core[1]["shape"]):
                    raise ValueError("P0-B pixmatch view chain differs")
                if (float(core[1]["rotation_degrees"]) == 0.0
                        and core[0]["pixel_sha256"] !=
                        core[1]["pixel_sha256"]):
                    raise ValueError("zero-angle P0-B deskew pixels differ")
    return event_index, roi_event_keys


def _validate_pixmatch_provenance(row, effective_config, event_index,
                                  roi_event_keys):
    fired = row["pixmatch_fired"]
    if not isinstance(fired, list):
        raise ValueError("pixmatch fired list is malformed")
    fired_by_field = {}
    for record in fired:
        if (not isinstance(record, list) or len(record) != 4
                or record[0] not in PIX_GATE_THRESHOLDS
                or not isinstance(record[1], str) or not record[1]):
            raise ValueError("pixmatch fired record is malformed")
        ncc = _finite(record[2], "pixmatch fired NCC")
        margin = _finite(record[3], "pixmatch fired margin")
        floor_ncc, floor_margin = PIX_GATE_THRESHOLDS[record[0]]
        if (ncc < floor_ncc or margin < floor_margin
                or ncc > 1.0 or margin > 2.0
                or record[0] in fired_by_field):
            raise ValueError("pixmatch fired record is outside active gate")
        fired_by_field[record[0]] = record

    acceptances = row["pixmatch_acceptances"]
    if not isinstance(acceptances, list):
        raise ValueError("pixmatch acceptance list is malformed")
    acceptance_keys = set()
    used_roi_keys = set()
    candidate_fields = set()
    baseline_pairs = set()
    native_enabled = effective_config["MIB_NATIVE_SCAN_OCR"] == "1"
    pixmatch_enabled = effective_config["MIB_PIXMATCH"] == "1"
    for acceptance in acceptances:
        required = {
            "consumer", "field", "value", "page", "page_type",
            "effects", "deskewed_view", "roi_view", "roi_box", "ncc",
            "margin", "crosscheck",
        }
        if not isinstance(acceptance, dict) or set(acceptance) != required:
            raise ValueError("pixmatch acceptance is malformed")
        consumer = acceptance["consumer"]
        field = acceptance["field"]
        value = acceptance["value"]
        page = _nonnegative_page(
            acceptance["page"], "pixmatch acceptance page")
        if (consumer not in {"candidate_pixmatch", "baseline_pixmatch"}
                or field not in PIX_GATE_THRESHOLDS
                or not isinstance(value, str) or not value
                or value not in PIX_ALLOWED_VALUES.get(field, ())
                or acceptance["page_type"] not in
                PIX_FIELD_PAGE_TYPES[field]
                or acceptance["crosscheck"] != "not_required"):
            raise ValueError("pixmatch acceptance contract is malformed")
        effect = ("candidate_pool" if consumer == "candidate_pixmatch"
                  else "baseline_guard")
        if acceptance["effects"] != [effect]:
            raise ValueError("pixmatch acceptance effect is malformed")
        if (not pixmatch_enabled
                or (consumer == "baseline_pixmatch" and not native_enabled)):
            raise ValueError("pixmatch acceptance is disabled by config")
        unique_key = (consumer, field)
        if unique_key in acceptance_keys:
            raise ValueError("pixmatch acceptance is duplicated")
        acceptance_keys.add(unique_key)
        ncc = _finite(acceptance["ncc"], "pixmatch acceptance NCC")
        margin = _finite(
            acceptance["margin"], "pixmatch acceptance margin")
        floor_ncc, floor_margin = PIX_GATE_THRESHOLDS[field]
        if (ncc < floor_ncc or margin < floor_margin
                or ncc > 1.0 or margin > 2.0):
            raise ValueError("pixmatch acceptance is outside active gate")
        for view_name, expected_pass, expected_transform in (
                ("deskewed_view", "decode", "deskewed"),
                ("roi_view", field, "accepted_roi")):
            view = acceptance[view_name]
            if (not isinstance(view, dict)
                    or set(view) != {"page", "consumer", "pass", "transform"}
                    or view != {"page": page, "consumer": consumer,
                                "pass": expected_pass,
                                "transform": expected_transform}):
                raise ValueError("pixmatch acceptance view reference is malformed")
        deskew_key = (page, consumer, "decode", "deskewed")
        roi_key = (page, consumer, field, "accepted_roi")
        deskew_event = event_index.get(deskew_key)
        roi_event = event_index.get(roi_key)
        if deskew_event is None or roi_event is None:
            raise ValueError("pixmatch acceptance view is missing")
        box = acceptance["roi_box"]
        if (not isinstance(box, list) or len(box) != 4
                or any(isinstance(value0, bool)
                       or not isinstance(value0, int) for value0 in box)):
            raise ValueError("pixmatch acceptance ROI box is malformed")
        y0, y1, x0, x1 = box
        height, width = deskew_event["shape"]
        if (not 0 <= y0 < y1 <= height or not 0 <= x0 < x1 <= width
                or roi_event["shape"] != [y1 - y0, x1 - x0]
                or float(roi_event["dpi"]) != float(deskew_event["dpi"])):
            raise ValueError("pixmatch acceptance ROI geometry differs")
        used_roi_keys.add(roi_key)
        if consumer == "candidate_pixmatch":
            candidate_fields.add(field)
            expected_fired = fired_by_field.get(field)
            if (expected_fired is None
                    or expected_fired[1:] != [value, acceptance["ncc"],
                                               acceptance["margin"]]):
                raise ValueError("candidate acceptance differs from fired read")
            if native_enabled and page in set(
                    row["identity_disqualified_pages"]
                    + row["native_fallback_review_pages"]):
                raise ValueError("candidate acceptance uses quarantined page")
            evidence = row["evidence"].get(field)
            expected_score = round(
                60.0 + min(30.0, 200.0 * margin), 1)
            if (row["fields"].get(field) != value
                    or not isinstance(evidence, dict)
                    or set(evidence) != {
                        "rank", "snap_score", "agreement", "source"}
                    or type(evidence.get("rank")) is not int
                    or type(evidence.get("agreement")) is not int
                    or isinstance(evidence.get("snap_score"), bool)
                    or not isinstance(
                        evidence.get("snap_score"), (int, float))
                    or evidence != {
                        "rank": 6, "snap_score": expected_score,
                        "agreement": 1, "source": "pixmatch"}):
                raise ValueError(
                    "candidate acceptance differs from emitted evidence")
        else:
            baseline_pairs.add((field, value))
            if (field != "home_world"
                    or value not in PIX_BASELINE_GUARD_WORLDS):
                raise ValueError("baseline acceptance is not an active guard")
    if set(fired_by_field) != candidate_fields:
        raise ValueError("pixmatch fired reads and acceptances differ")
    pixel_guard_pairs = {
        (guard["field"], guard["value"])
        for guard in row["baseline_approval_guards"]
        if guard.get("origin") == "p0b_pixmatch"
        and guard.get("source") == "pixmatch"
    }
    if baseline_pairs != pixel_guard_pairs:
        raise ValueError("baseline pixel guards and acceptances differ")
    if used_roi_keys != roi_event_keys:
        raise ValueError("image registry has orphan pixmatch ROI")
    for field, evidence in row["evidence"].items():
        if isinstance(evidence, dict) and evidence.get("source") == "pixmatch" \
                and field not in candidate_fields:
            raise ValueError("emitted pixmatch evidence lacks acceptance")


def _validate_evidence_rows(rows, effective_config=None):
    effective_config = canonical_effective_config(
        effective_config or {}, environment={})
    required = {
        "case_id", "adjudication", "extraction", "fields", "evidence",
        "rank1_payload", "composited_rank1_payload", "rank1_conflicts",
        "baseline_approval_guards",
        "baseline_batch_context", "image_view_registry", "pixmatch_fired",
        "pixmatch_acceptances", "identity_disqualified_pages",
        "native_fallback_review_pages", "execution_error",
    }
    for row in rows:
        if not required <= set(row):
            raise ValueError("evidence row is missing production ledger fields")
        if (row["execution_error"] is not None
                and (not isinstance(row["execution_error"], str)
                     or not row["execution_error"].strip()
                     or len(row["execution_error"]) > 400)):
            raise ValueError("evidence row execution_error is malformed")
        _validate_page_number_list(
            row["identity_disqualified_pages"],
            "identity disqualified pages")
        _validate_page_number_list(
            row["native_fallback_review_pages"],
            "native fallback review pages")
        event_index, roi_event_keys = _validate_image_view_registry(
            row["image_view_registry"], effective_config,
            row["execution_error"], row["native_fallback_review_pages"])
        if row["adjudication"] not in ADJUDICATIONS:
            raise ValueError("evidence row has invalid adjudication")
        if not isinstance(row["fields"], dict) or any(
                field not in row["fields"] for field in PREDICTION_FIELDS):
            raise ValueError("evidence row fields are incomplete")
        if not isinstance(row["evidence"], dict):
            raise ValueError("evidence row evidence map is malformed")
        _validate_extraction_provenance(row["extraction"])
        rank1 = row["rank1_payload"]
        if not isinstance(rank1, dict) or set(rank1) != {"finding", "fields"} \
                or rank1["finding"] not in ADJUDICATIONS | {None} \
                or not isinstance(rank1["fields"], dict) \
                or not set(rank1["fields"]) <= set(PREDICTION_FIELDS):
            raise ValueError("evidence row rank1 payload is malformed")
        if any(row["fields"].get(field) != value
               for field, value in rank1["fields"].items()):
            raise ValueError("rank1 payload field differs from emitted evidence field")
        composited = row["composited_rank1_payload"]
        if not isinstance(composited, dict) or set(composited) != {
                "values", "conflicts", "evidence"}:
            raise ValueError("composited rank1 payload is malformed")
        values = composited["values"]
        evidence = composited["evidence"]
        allowed_rank1_fields = {*PREDICTION_FIELDS, "finding"}
        if (not isinstance(values, dict)
                or not set(values) <= allowed_rank1_fields
                or any(not isinstance(observed, list) or not observed
                       or any(not isinstance(value, str) or not value
                              for value in observed)
                       or observed != sorted(set(observed))
                       for observed in values.values())
                or ("finding" in values
                    and not set(values["finding"]) <= ADJUDICATIONS)
                or not isinstance(evidence, dict)
                or set(evidence) != set(values)):
            raise ValueError("composited rank1 values are malformed")
        expected_conflicts = sorted(
            field for field, observed in values.items() if len(observed) > 1)
        if composited["conflicts"] != expected_conflicts:
            raise ValueError("composited rank1 conflicts are inconsistent")
        for field, records in evidence.items():
            if (not isinstance(records, list) or not records
                    or any(not isinstance(record, dict)
                           or set(record) != {"value", "origin"}
                           or record["value"] not in values[field]
                           or not isinstance(record["origin"], dict)
                           or set(record["origin"]) != {
                               "page", "view", "dpi", "pass"}
                           or not isinstance(record["origin"]["page"], int)
                           or isinstance(record["origin"]["page"], bool)
                           or not isinstance(record["origin"]["view"], str)
                           or record["origin"]["view"] not in {
                               "masked_pdf_render", "visible_text_layer"}
                           or not isinstance(record["origin"]["dpi"], int)
                           or isinstance(record["origin"]["dpi"], bool)
                           or not isinstance(record["origin"]["pass"], str)
                           or record["origin"]["pass"] not in {"fast", "hq"}
                           or (record["origin"]["view"] == "visible_text_layer"
                               and (record["origin"]["dpi"] != 0
                                    or record["origin"]["pass"] != "fast"))
                           or (record["origin"]["view"] == "masked_pdf_render"
                               and ((record["origin"]["pass"] == "fast"
                                     and record["origin"]["dpi"] != 150)
                                    or (record["origin"]["pass"] == "hq"
                                        and record["origin"]["dpi"] != 250)))
                           for record in records)
                    or not set(values[field]) <= {
                        record["value"] for record in records}):
                raise ValueError("composited rank1 evidence is malformed")
        if not isinstance(row["rank1_conflicts"], list) or any(
                field not in {*PREDICTION_FIELDS, "finding",
                              *SEMANTIC_RANK1_CONFLICTS}
                for field in row["rank1_conflicts"]):
            raise ValueError("evidence row rank1 conflicts are malformed")
        guards = row["baseline_approval_guards"]
        if not isinstance(guards, list) or any(
                not isinstance(guard, dict)
                or set(guard) != {"field", "value", "origin", "source"}
                or any(not isinstance(guard[key], str) or not guard[key]
                       for key in guard)
                for guard in guards):
            raise ValueError("evidence row baseline approval guards are malformed")
        context = row["baseline_batch_context"]
        if (not isinstance(context, dict)
                or not set(context) <= {
                    "arrival_date", "sponsor_id", "visa_class"}):
            raise ValueError("evidence row baseline batch context is malformed")
        for field, candidates in context.items():
            if (not isinstance(candidates, list) or not candidates
                    or (field in {"sponsor_id", "visa_class"}
                        and len(candidates) != 1)):
                raise ValueError(
                    "evidence row baseline batch context is malformed")
            for candidate in candidates:
                if (not isinstance(candidate, list) or len(candidate) != 5
                        or not isinstance(candidate[0], str)
                        or not candidate[0]
                        or not isinstance(candidate[1], str)
                        or not candidate[1]
                        or not isinstance(candidate[2], int)
                        or isinstance(candidate[2], bool)
                        or not 1 <= candidate[2] <= 6
                        or not isinstance(candidate[3], (int, float))
                        or isinstance(candidate[3], bool)
                        or not math.isfinite(float(candidate[3]))
                        or not 0 <= float(candidate[3]) <= 100
                        or not isinstance(candidate[4], str)
                        or not candidate[4]):
                    raise ValueError(
                        "evidence row baseline batch context is malformed")
                if candidate[2] != _baseline_context_expected_rank(
                        field, candidate[1]):
                    raise ValueError(
                        "evidence row baseline batch context is malformed")
                if not _baseline_context_confidence_is_possible(
                        field, candidate[1], candidate[3], candidate[0],
                        candidate[4]):
                    raise ValueError(
                        "evidence row baseline batch context is malformed")
                if (field == "sponsor_id"
                        and not SPONSOR_VALUE_RE.fullmatch(candidate[0])):
                    raise ValueError(
                        "evidence row baseline batch context is malformed")
                if (field == "visa_class"
                        and candidate[0] not in VISA_CLASSES):
                    raise ValueError(
                        "evidence row baseline batch context is malformed")
                if field == "arrival_date":
                    try:
                        parsed_date = date.fromisoformat(candidate[0])
                    except ValueError as exc:
                        raise ValueError(
                            "evidence row baseline batch context is malformed") \
                            from exc
                    if parsed_date.isoformat() != candidate[0]:
                        raise ValueError(
                            "evidence row baseline batch context is malformed")
        # Signed sponsor/visa corrections and their counterfactual context are
        # one semantic unit. A single composited value must be the retained
        # rank-1 manual candidate; a composited conflict must retain no winner;
        # and ordinary context cannot claim manual authority by itself.
        for field in ("sponsor_id", "visa_class"):
            observed = values.get(field, [])
            retained = context.get(field)
            if len(observed) == 1:
                if (retained is None or len(retained) != 1
                        or retained[0][0] != observed[0]
                        or retained[0][1] != "manual_correction"
                        or retained[0][2] != 1):
                    raise ValueError(
                        "evidence row baseline batch context differs from "
                        "composited rank1 correction")
            elif len(observed) > 1:
                if field in context:
                    raise ValueError(
                        "evidence row baseline batch context retains a "
                        "conflicting composited rank1 correction")
            elif (retained is not None
                  and retained[0][1] == "manual_correction"):
                raise ValueError(
                    "evidence row baseline batch context has unbound "
                    "manual correction")
        _validate_pixmatch_provenance(
            row, effective_config, event_index, roi_event_keys)


def binding_identity(binding):
    return {key: binding[key] for key in sorted(IDENTITY_KEYS)}


def _validate_identity(identity):
    if not isinstance(identity, dict) or set(identity) != IDENTITY_KEYS:
        raise ValueError("predeclared identity has unexpected or missing keys")
    if not SHA256_RE.fullmatch(identity.get("binding_sha256") or ""):
        raise ValueError("predeclared identity binding_sha256 is malformed")


def _bound_file_path(binding_path, record, label, same_directory=False):
    if not isinstance(record, dict) or set(record) != {"path", "sha256", "size"}:
        raise ValueError(f"bound {label} record is malformed")
    if not isinstance(record.get("path"), str) or not record["path"] \
            or Path(record["path"]).is_absolute():
        raise ValueError(f"bound {label} path must be relative")
    if not SHA256_RE.fullmatch(record.get("sha256") or ""):
        raise ValueError(f"bound {label} hash is malformed")
    if not isinstance(record.get("size"), int) or record["size"] < 0:
        raise ValueError(f"bound {label} size is malformed")
    parent = Path(binding_path).resolve().parent
    resolved = (parent / record["path"]).resolve(strict=True)
    if not resolved.is_file() or (same_directory and resolved.parent != parent):
        raise ValueError(f"bound {label} must be a regular file beside the binding")
    if resolved.stat().st_size != record["size"] or \
            sha256_file(resolved) != record["sha256"]:
        raise ValueError(f"bound {label} hash/size mismatch")
    return resolved


def _validate_input_source(source, entries):
    if not isinstance(source, dict) or source.get("kind") not in {
            "sorted_pdf_directory", "ordered_list"}:
        raise ValueError("binding input source is malformed")
    if source["kind"] == "sorted_pdf_directory":
        if set(source) != {"kind", "path"}:
            raise ValueError("sorted input source is malformed")
        directory = Path(source["path"]).resolve(strict=True)
        if not directory.is_dir() or input_manifest(sorted(directory.glob("*.pdf"))) != entries:
            raise ValueError("sorted input directory differs from the binding")
    else:
        if set(source) != {"kind", "path", "sha256", "size"}:
            raise ValueError("ordered-list input source is malformed")
        path = Path(source["path"]).resolve(strict=True)
        if not path.is_file() or path.stat().st_size != source["size"] or \
                sha256_file(path) != source["sha256"]:
            raise ValueError("ordered input list differs from the binding")
        listed = [line.strip() for line in path.read_text().splitlines()
                  if line.strip()]
        if input_manifest(listed) != entries:
            raise ValueError("ordered input list contents differ from the binding")


def verify_binding(path, expected_identity=None):
    """Verify self-hash, live inputs, runtime/config semantics, and artifacts."""
    path = Path(path).resolve(strict=True)
    binding = json.loads(path.read_text())
    required = {
        "schema", "producer_git_sha", "image_id", "image_revision",
        "image_inspect", "image_inspect_sha256", "runtime_manifest",
        "runtime_manifest_sha256", "runtime_manifest_file", "effective_config",
        "config_sha256", "run_receipt", "run_receipt_sha256", "run_split",
        "run_nonce", "worker_count", "input_source", "input_manifest",
        "input_manifest_sha256", "artifacts", "output_case_count",
        "output_order_sha256", "binding_sha256",
    }
    if not isinstance(binding, dict) or set(binding) != required:
        raise ValueError("binding has unexpected or missing keys")
    if binding.get("schema") != SCHEMA:
        raise ValueError("unsupported native artifact binding schema")
    if not SHA1_RE.fullmatch(binding.get("producer_git_sha") or ""):
        raise ValueError("binding producer SHA is malformed")
    if not IMAGE_ID_RE.fullmatch(binding.get("image_id") or ""):
        raise ValueError("binding image ID is malformed")
    if binding.get("image_revision") != binding["producer_git_sha"]:
        raise ValueError("binding image revision must equal producer SHA")
    if binding.get("run_split") not in RUN_SPLITS:
        raise ValueError("binding run split is malformed")
    if not SHA256_RE.fullmatch(binding.get("run_nonce") or ""):
        raise ValueError("binding run nonce must be 256-bit lowercase hex")

    supplied_hash = binding.get("binding_sha256")
    payload = dict(binding)
    payload.pop("binding_sha256", None)
    if not SHA256_RE.fullmatch(supplied_hash or ""):
        raise ValueError("binding_sha256 is missing or malformed")
    if canonical_sha256(payload) != supplied_hash:
        raise ValueError("binding payload hash mismatch")

    inspect_path = _bound_file_path(
        path, binding["image_inspect"], "image inspection")
    if binding["image_inspect_sha256"] != binding["image_inspect"]["sha256"]:
        raise ValueError("image inspection identity hash mismatch")
    try:
        inspected = json.loads(inspect_path.read_text())
    except json.JSONDecodeError as exc:
        raise ValueError("bound image inspection JSON is malformed") from exc
    _validate_image_inspect(
        inspected, binding["image_id"], binding["image_revision"])

    manifest_path = _bound_file_path(
        path, binding["runtime_manifest_file"], "runtime manifest")
    try:
        live_manifest = json.loads(manifest_path.read_text())
    except json.JSONDecodeError as exc:
        raise ValueError("bound runtime manifest JSON is malformed") from exc
    if live_manifest != binding["runtime_manifest"]:
        raise ValueError("bound runtime manifest file differs from embedded manifest")
    manifest = _validate_runtime_manifest(
        binding["runtime_manifest"], binding["producer_git_sha"],
        binding["image_id"])
    if canonical_sha256(manifest) != binding["runtime_manifest_sha256"]:
        raise ValueError("runtime manifest canonical hash mismatch")

    effective = canonical_effective_config(
        binding["effective_config"], environment={})
    if effective != binding["effective_config"] or \
            canonical_sha256(effective) != binding["config_sha256"]:
        raise ValueError("effective config hash mismatch")

    entries = binding.get("input_manifest")
    if not isinstance(entries, list) or not entries:
        raise ValueError("binding input manifest is missing")
    for ordinal, entry in enumerate(entries):
        if not isinstance(entry, dict) or set(entry) != {
                "ordinal", "case_id", "path", "size", "sha256"}:
            raise ValueError("binding input manifest entry is malformed")
        if entry["ordinal"] != ordinal or not isinstance(entry["case_id"], str) \
                or not SHA256_RE.fullmatch(entry.get("sha256") or ""):
            raise ValueError("binding input manifest order/hash is malformed")
    if len({entry["case_id"] for entry in entries}) != len(entries):
        raise ValueError("binding input manifest has duplicate case IDs")
    if canonical_sha256(_input_identity(entries)) != \
            binding.get("input_manifest_sha256"):
        raise ValueError("recorded input manifest hash mismatch")
    live_entries = input_manifest([entry["path"] for entry in entries])
    if live_entries != entries:
        raise ValueError("live input PDF manifest differs from the binding")

    source = binding.get("input_source")
    _validate_input_source(source, entries)

    artifacts = binding.get("artifacts")
    if not isinstance(artifacts, dict) or set(artifacts) != {
            "predictions", "evidence"}:
        raise ValueError("binding requires exactly predictions and evidence artifacts")
    resolved = {}
    for name, record in artifacts.items():
        if not ARTIFACT_NAME_RE.fullmatch(name):
            raise ValueError(f"invalid bound artifact name: {name}")
        resolved[name] = _bound_file_path(
            path, record, f"artifact {name}", same_directory=True)

    receipt_path = _bound_file_path(
        path, binding["run_receipt"], "run receipt", same_directory=True)
    if binding["run_receipt_sha256"] != binding["run_receipt"]["sha256"]:
        raise ValueError("run receipt identity hash mismatch")
    all_paths = [resolved["predictions"], resolved["evidence"], receipt_path]
    if len(set(all_paths)) != len(all_paths) or len({
            (item.stat().st_dev, item.stat().st_ino) for item in all_paths}) != \
            len(all_paths):
        raise ValueError("prediction, evidence, and run receipt must be distinct files")
    try:
        receipt = json.loads(receipt_path.read_text())
    except json.JSONDecodeError as exc:
        raise ValueError("bound run receipt JSON is malformed") from exc
    expected_run_identity = _expected_run_identity(
        binding["producer_git_sha"], binding["image_id"],
        binding["image_inspect_sha256"], binding["runtime_manifest_sha256"],
        binding["config_sha256"], binding["input_manifest_sha256"],
        binding["run_split"], binding["run_nonce"])
    workers, expected_order = _validate_run_receipt(
        receipt, entries, effective, resolved["predictions"],
        resolved["evidence"], expected_run_identity)
    if binding["worker_count"] != workers:
        raise ValueError("bound worker count differs from run receipt")
    if source.get("kind") != "sorted_pdf_directory" or \
            Path(source["path"]).name != receipt["input_source"]["directory_name"]:
        raise ValueError("run receipt input source differs from binding source")

    prediction_rows, prediction_ids = _jsonl_case_ids(resolved["predictions"])
    evidence_rows, evidence_ids = _jsonl_case_ids(resolved["evidence"])
    _validate_prediction_rows(prediction_rows)
    _validate_evidence_rows(evidence_rows, effective)
    input_ids = [entry["case_id"] for entry in entries]
    if prediction_ids != evidence_ids:
        raise ValueError("prediction and evidence IDs/order differ")
    if prediction_ids != expected_order or set(prediction_ids) != set(input_ids):
        raise ValueError("output order differs from the executing worker contract")
    for prediction, evidence in zip(prediction_rows, evidence_rows):
        if prediction["adjudication"] != evidence["adjudication"] or any(
                prediction[field] != evidence["fields"][field]
                for field in PREDICTION_FIELDS):
            raise ValueError("prediction and evidence values differ")
    if binding["output_case_count"] != len(prediction_ids) or \
            binding["output_order_sha256"] != canonical_sha256(prediction_ids):
        raise ValueError("bound output count/order hash mismatch")

    if expected_identity is not None:
        _validate_identity(expected_identity)
        if binding_identity(binding) != expected_identity:
            raise ValueError("binding identity does not match the predeclared spec")
    return binding


def _input_paths(args):
    directory = Path(args.input_dir).resolve(strict=True)
    if not directory.is_dir():
        raise ValueError("input-dir is not a directory")
    paths = sorted(directory.glob("*.pdf"))
    return paths, {"kind": "sorted_pdf_directory", "path": str(directory)}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", default=".")
    parser.add_argument("--producer-sha", required=True)
    parser.add_argument("--image-id", required=True)
    parser.add_argument("--image-revision", required=True)
    parser.add_argument("--image-inspect", required=True,
                        help="saved docker image inspect JSON")
    parser.add_argument("--runtime-manifest", required=True)
    parser.add_argument("--run-receipt", required=True,
                        help="receipt emitted by this exact predict.py run")
    parser.add_argument("--split", required=True, choices=sorted(RUN_SPLITS),
                        help="declared corpus split for this run")
    parser.add_argument("--effective-config-json", "--native-config-json",
                        dest="effective_config_json", required=True)
    parser.add_argument(
        "--input-dir", required=True,
        help="directory discovered exactly as predict.py sorts *.pdf")
    parser.add_argument("--artifact", action="append", required=True,
                        metavar="ROLE=PATH")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    output = Path(args.output).resolve()
    if output.exists():
        raise SystemExit(f"refusing to overwrite existing binding: {output}")
    repo = Path(args.repo).resolve(strict=True)
    if not SHA1_RE.fullmatch(args.producer_sha):
        raise SystemExit("producer SHA must be 40 lowercase hex characters")
    try:
        if _git_head(repo) != args.producer_sha:
            raise ValueError("producer SHA does not equal repository HEAD")
        _require_clean_repo(repo)
    except (subprocess.CalledProcessError, ValueError) as exc:
        raise SystemExit(f"producer verification failed: {exc}") from exc
    if not IMAGE_ID_RE.fullmatch(args.image_id):
        raise SystemExit("image ID must be a full sha256:<64 lowercase hex> ID")
    if args.image_revision != args.producer_sha:
        raise SystemExit("image revision must equal producer SHA")

    image_inspect_path = Path(args.image_inspect).resolve(strict=True)
    runtime_manifest_path = Path(args.runtime_manifest).resolve(strict=True)
    run_receipt_path = Path(args.run_receipt).resolve(strict=True)
    try:
        image_inspect = json.loads(image_inspect_path.read_text())
        _validate_image_inspect(
            image_inspect, args.image_id, args.image_revision)
        runtime_manifest = json.loads(runtime_manifest_path.read_text())
        _validate_runtime_manifest(
            runtime_manifest, args.producer_sha, args.image_id, repo=repo)
        overrides = json.loads(args.effective_config_json)
        effective_config = canonical_effective_config(overrides, environment={})
        input_paths, input_source = _input_paths(args)
        entries = input_manifest(input_paths)
        run_receipt = json.loads(run_receipt_path.read_text())
    except (json.JSONDecodeError, OSError, ValueError) as exc:
        raise SystemExit(f"binding preflight failed: {exc}") from exc

    artifact_records = {}
    for item in args.artifact:
        if "=" not in item:
            raise SystemExit("artifact must be ROLE=PATH")
        name, raw_path = item.split("=", 1)
        if not ARTIFACT_NAME_RE.fullmatch(name) or name in artifact_records:
            raise SystemExit(f"invalid or duplicate artifact name: {name}")
        artifact = Path(raw_path).resolve(strict=True)
        if artifact.parent != output.parent:
            raise SystemExit("prediction/evidence artifacts must be beside the binding")
        artifact_records[name] = {
            "path": os.path.relpath(artifact, output.parent),
            "sha256": sha256_file(artifact),
            "size": artifact.stat().st_size,
        }
    if set(artifact_records) != {"predictions", "evidence"}:
        raise SystemExit("artifacts must contain exactly predictions= and evidence=")
    if run_receipt_path.parent != output.parent:
        raise SystemExit("run receipt must be beside the binding")
    try:
        by_name = {
            item.split("=", 1)[0]: Path(item.split("=", 1)[1]).resolve(strict=True)
            for item in args.artifact
        }
        prediction_rows, prediction_ids = _jsonl_case_ids(by_name["predictions"])
        evidence_rows, evidence_ids = _jsonl_case_ids(by_name["evidence"])
        _validate_prediction_rows(prediction_rows)
        _validate_evidence_rows(evidence_rows, effective_config)
        receipt_identity = _validate_run_identity(
            run_receipt.get("run_identity") if isinstance(
                run_receipt, dict) else None)
        expected_run_identity = _expected_run_identity(
            args.producer_sha, args.image_id, sha256_file(image_inspect_path),
            canonical_sha256(runtime_manifest),
            canonical_sha256(effective_config),
            canonical_sha256(_input_identity(entries)), args.split,
            receipt_identity["run_nonce"])
        worker_count, expected_order = _validate_run_receipt(
            run_receipt, entries, effective_config, by_name["predictions"],
            by_name["evidence"], expected_run_identity)
    except (OSError, ValueError) as exc:
        raise SystemExit(f"output artifact validation failed: {exc}") from exc
    if prediction_ids != evidence_ids:
        raise SystemExit("prediction and evidence IDs/order differ")
    if prediction_ids != expected_order:
        raise SystemExit("output order differs from the executing worker contract")

    payload = {
        "schema": SCHEMA,
        "producer_git_sha": args.producer_sha,
        "image_id": args.image_id,
        "image_revision": args.image_revision,
        "image_inspect": {
            "path": os.path.relpath(image_inspect_path, output.parent),
            "sha256": sha256_file(image_inspect_path),
            "size": image_inspect_path.stat().st_size,
        },
        "image_inspect_sha256": sha256_file(image_inspect_path),
        "runtime_manifest": runtime_manifest,
        "runtime_manifest_sha256": canonical_sha256(runtime_manifest),
        "runtime_manifest_file": {
            "path": os.path.relpath(runtime_manifest_path, output.parent),
            "sha256": sha256_file(runtime_manifest_path),
            "size": runtime_manifest_path.stat().st_size,
        },
        "effective_config": effective_config,
        "config_sha256": canonical_sha256(effective_config),
        "run_receipt": {
            "path": os.path.relpath(run_receipt_path, output.parent),
            "sha256": sha256_file(run_receipt_path),
            "size": run_receipt_path.stat().st_size,
        },
        "run_receipt_sha256": sha256_file(run_receipt_path),
        "run_split": args.split,
        "run_nonce": expected_run_identity["run_nonce"],
        "worker_count": worker_count,
        "input_source": input_source,
        "input_manifest": entries,
        "input_manifest_sha256": canonical_sha256(_input_identity(entries)),
        "artifacts": artifact_records,
        "output_case_count": len(prediction_ids),
        "output_order_sha256": canonical_sha256(prediction_ids),
    }
    payload["binding_sha256"] = canonical_sha256(payload)
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = None
    try:
        with tempfile.NamedTemporaryFile(
                mode="w", dir=output.parent, prefix=f".{output.name}.",
                suffix=".tmp", delete=False) as handle:
            temporary_path = Path(handle.name)
            json.dump(payload, handle, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        verify_binding(temporary_path)
        if _git_head(repo) != args.producer_sha:
            raise ValueError("producer HEAD changed during binding")
        _require_clean_repo(repo)
        verify_binding(temporary_path)
        os.link(temporary_path, output)
        directory_fd = os.open(output.parent, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    except (OSError, subprocess.CalledProcessError, ValueError) as exc:
        raise SystemExit(f"binding finalization failed: {exc}") from exc
    finally:
        if temporary_path is not None:
            try:
                temporary_path.unlink()
            except FileNotFoundError:
                pass
    print(f"wrote verified binding {output}")


if __name__ == "__main__":
    main()
