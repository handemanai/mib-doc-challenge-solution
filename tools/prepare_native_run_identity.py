#!/usr/bin/env python3
"""Create the pre-run identity consumed by ``scripts/predict.py``.

This is a supervised chain-of-custody artifact, not remote execution
attestation. It validates a clean producer checkout, supplied Docker inspect
evidence, the exact source/runtime manifest, canonical configuration, and
ordered input bytes before assigning one unique run nonce.
"""
import argparse
import hashlib
import json
import os
import secrets
import subprocess
import tempfile
from pathlib import Path

from native_artifact_binding import (
    IMAGE_ID_RE,
    RUN_IDENTITY_SCHEMA,
    RUN_SPLITS,
    SHA1_RE,
    SHA256_RE,
    _git_head,
    _input_identity,
    _require_clean_repo,
    _validate_image_inspect,
    _validate_runtime_manifest,
    canonical_effective_config,
    canonical_pdf_paths,
    canonical_sha256,
    input_manifest,
    sha256_file,
)


def _is_holdout(case_id):
    return int(hashlib.md5(case_id.encode()).hexdigest(), 16) % 5 == 0


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", default=".")
    parser.add_argument("--producer-sha", required=True)
    parser.add_argument("--image-id", required=True)
    parser.add_argument("--image-inspect", required=True)
    parser.add_argument("--runtime-manifest", required=True)
    parser.add_argument("--effective-config-json", required=True)
    parser.add_argument("--input-dir", required=True)
    parser.add_argument("--split", choices=sorted(RUN_SPLITS), required=True)
    parser.add_argument(
        "--partition", default="all",
        choices=("all", "dev-md5", "holdout-md5"),
        help="optional historical md5(case_id) train partition")
    parser.add_argument(
        "--run-nonce",
        help="optional preassigned 256-bit lowercase-hex nonce")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    output = Path(args.output).resolve()
    if output.exists():
        raise SystemExit(f"refusing to overwrite run identity: {output}")
    repo = Path(args.repo).resolve(strict=True)
    if not SHA1_RE.fullmatch(args.producer_sha):
        raise SystemExit("producer SHA must be 40 lowercase hex characters")
    if not IMAGE_ID_RE.fullmatch(args.image_id):
        raise SystemExit("image ID must be a full sha256:<64 lowercase hex> ID")
    nonce = args.run_nonce or secrets.token_hex(32)
    if not SHA256_RE.fullmatch(nonce):
        raise SystemExit("run nonce must be 256-bit lowercase hex")

    inspect_path = Path(args.image_inspect).resolve(strict=True)
    manifest_path = Path(args.runtime_manifest).resolve(strict=True)
    input_dir = Path(args.input_dir).resolve(strict=True)
    try:
        if _git_head(repo) != args.producer_sha:
            raise ValueError("producer SHA does not equal repository HEAD")
        _require_clean_repo(repo)
        inspected = json.loads(inspect_path.read_text())
        _validate_image_inspect(inspected, args.image_id, args.producer_sha)
        manifest = json.loads(manifest_path.read_text())
        _validate_runtime_manifest(
            manifest, args.producer_sha, args.image_id, repo=repo)
        overrides = json.loads(args.effective_config_json)
        effective = canonical_effective_config(overrides, environment={})
        if not input_dir.is_dir():
            raise ValueError("input-dir is not a directory")
        expected_split = {
            "dev-md5": "dev", "holdout-md5": "holdout",
        }.get(args.partition)
        if expected_split is not None and args.split != expected_split:
            raise ValueError("run identity split and partition disagree")
        if args.split == "validation" and args.partition != "all":
            raise ValueError("validation run identity must use the full partition")
        pdfs = canonical_pdf_paths(input_dir)
        if args.partition != "all":
            want_holdout = args.partition == "holdout-md5"
            pdfs = [
                pdf for pdf in pdfs
                if _is_holdout(pdf.stem) == want_holdout
            ]
        if not pdfs:
            raise ValueError("run identity requires at least one input PDF")
        entries = input_manifest(pdfs)
    except (json.JSONDecodeError, OSError, subprocess.CalledProcessError,
            ValueError) as exc:
        raise SystemExit(f"run identity preflight failed: {exc}") from exc

    identity = {
        "schema": RUN_IDENTITY_SCHEMA,
        "producer_git_sha": args.producer_sha,
        "image_id": args.image_id,
        "image_revision": args.producer_sha,
        "image_inspect_sha256": sha256_file(inspect_path),
        "runtime_manifest_sha256": canonical_sha256(manifest),
        "config_sha256": canonical_sha256(effective),
        "input_manifest_sha256": canonical_sha256(_input_identity(entries)),
        "run_split": args.split,
        "run_nonce": nonce,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = None
    try:
        with tempfile.NamedTemporaryFile(
                mode="w", dir=output.parent, prefix=f".{output.name}.",
                suffix=".tmp", delete=False) as handle:
            temporary_path = Path(handle.name)
            json.dump(identity, handle, indent=2, sort_keys=True)
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
        raise SystemExit(f"could not write run identity: {exc}") from exc
    finally:
        if temporary_path is not None:
            try:
                temporary_path.unlink()
            except FileNotFoundError:
                pass
    print(f"wrote preflighted run identity {output}")


if __name__ == "__main__":
    main()
