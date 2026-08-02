"""Static selector census tests; no OCR or recognizer session is used."""
import io
import json
import shutil
import subprocess
from pathlib import Path

import fitz
import numpy as np
import pytest
from PIL import Image

from mib.caseid import canonical_pdf_paths
from tools.native_artifact_binding import (
    EFFECTIVE_CONFIG_DEFAULTS, _input_identity, canonical_sha256,
)
from tools.native_selector_census import _write_new, build_census
import tools.native_selector_census as selector_census


def _png(array):
    buffer = io.BytesIO()
    Image.fromarray(array).save(buffer, format="PNG")
    return buffer.getvalue()


def _eligible_pdf(path):
    doc = fitz.open()
    page = doc.new_page(width=612, height=792)
    image = np.full((1584, 1224), 245, np.uint8)
    image[500:560, 120:800] = 25
    xref = page.insert_image(page.rect, stream=_png(image))
    doc.xref_set_key(xref, "ColorSpace", "/DeviceGray")
    doc.xref_set_key(xref, "DecodeParms", "null")
    doc.save(path)
    doc.close()


def _bound_census_args(inputs, split="dev"):
    # The census binds a clean producer *commit*, so exercising it needs a real
    # repository. git is not part of the runtime (nothing under mib/ shells out
    # to it) and the scoring image does not ship it, so skip rather than fail
    # where it is absent.
    if shutil.which("git") is None:
        pytest.skip("git is required to build the producer-repo fixture")
    config = dict(EFFECTIVE_CONFIG_DEFAULTS, MIB_NATIVE_SCAN_OCR="1")
    entries = []
    for ordinal, path in enumerate(canonical_pdf_paths(inputs)):
        raw = path.read_bytes()
        entries.append({
            "ordinal": ordinal, "case_id": path.stem, "path": str(path),
            "size": len(raw), "sha256": __import__("hashlib").sha256(
                raw).hexdigest(),
        })
    source_root = Path(__file__).resolve().parents[1]
    repo = inputs.parent / "producer"
    repo.mkdir()
    for relative in selector_census.BOUND_SOURCE_PATHS:
        destination = repo / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes((source_root / relative).read_bytes())
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "Census Test"],
                   cwd=repo, check=True)
    subprocess.run(["git", "config", "user.email", "census@example.test"],
                   cwd=repo, check=True)
    subprocess.run(["git", "add", "."], cwd=repo, check=True)
    subprocess.run(["git", "-c", "commit.gpgsign=false", "commit", "-qm",
                    "selector source"], cwd=repo, check=True)
    sha = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=repo, text=True).strip()
    identity = {
        "schema": "mib-run-identity-v1",
        "producer_git_sha": sha,
        "image_id": "sha256:" + "b" * 64,
        "image_revision": sha,
        "image_inspect_sha256": "c" * 64,
        "runtime_manifest_sha256": "d" * 64,
        "config_sha256": canonical_sha256(config),
        "input_manifest_sha256": canonical_sha256(_input_identity(entries)),
        "run_split": split,
        "run_nonce": "e" * 64,
    }
    return identity, config, repo


def test_static_census_preserves_every_case_and_zero_count_categories(tmp_path):
    inputs = tmp_path / "dev"
    inputs.mkdir()
    _eligible_pdf(inputs / "MIB-000001.pdf")
    empty = fitz.open()
    empty.new_page()
    empty.save(inputs / "MIB-000002.pdf")
    empty.close()

    identity, config, repo = _bound_census_args(inputs)
    report = build_census(inputs, "dev", identity, config, repo)
    assert report["valid"] is True
    assert report["pdf_count"] == 2
    assert report["page_count"] == 2
    assert report["eligible_pdf_count"] == 1
    assert report["selector_outcome_counts"]["eligible"] == 1
    assert report["selector_outcome_counts"]["image_count_not_one"] == 1
    assert report["selector_outcome_counts"]["nondefault_user_unit"] == 0
    assert [record["case_id"] for record in report["inputs"]] == [
        "MIB-000001", "MIB-000002"]
    assert report["document_errors"] == []

    output = tmp_path / "census.json"
    _write_new(output, report)
    assert json.loads(output.read_text())["input_manifest_sha256"] == \
        report["input_manifest_sha256"]
    with pytest.raises(ValueError, match="refusing to overwrite"):
        _write_new(output, report)

    # No timestamps or host paths enter the report: the exact same bound
    # inputs and identity produce the exact same census payload.
    assert build_census(inputs, "dev", identity, config, repo) == report


def test_static_census_uses_runtime_size_first_manifest_order(
        tmp_path, monkeypatch):
    inputs = tmp_path / "dev"
    inputs.mkdir()
    for case_id, padding in (
            ("MIB-000001", 300), ("MIB-000002", 100), ("MIB-000003", 0)):
        pdf = fitz.open()
        pdf.new_page()
        path = inputs / f"{case_id}.pdf"
        pdf.save(path)
        pdf.close()
        if padding:
            path.write_bytes(path.read_bytes() + b"x" * padding)

    canonical_ids = [path.stem for path in canonical_pdf_paths(inputs)]
    assert canonical_ids == ["MIB-000003", "MIB-000002", "MIB-000001"]
    assert canonical_ids != [
        path.stem for path in sorted(inputs.glob("*.pdf"))]

    entries = []
    for ordinal, path in enumerate(canonical_pdf_paths(inputs)):
        raw = path.read_bytes()
        entries.append({
            "ordinal": ordinal, "case_id": path.stem, "path": str(path),
            "size": len(raw), "sha256": __import__("hashlib").sha256(
                raw).hexdigest(),
        })
    config = dict(EFFECTIVE_CONFIG_DEFAULTS, MIB_NATIVE_SCAN_OCR="1")
    identity = {
        "schema": "mib-run-identity-v1",
        "producer_git_sha": "a" * 40,
        "image_id": "sha256:" + "b" * 64,
        "image_revision": "a" * 40,
        "image_inspect_sha256": "c" * 64,
        "runtime_manifest_sha256": "d" * 64,
        "config_sha256": canonical_sha256(config),
        "input_manifest_sha256": canonical_sha256(_input_identity(entries)),
        "run_split": "dev",
        "run_nonce": "e" * 64,
    }
    monkeypatch.setattr(
        selector_census, "_verify_producer_source",
        lambda *args: {"producer_git_sha": identity["producer_git_sha"],
                       "files": []})
    report = build_census(inputs, "dev", identity, config, tmp_path)

    assert report["valid"] is True
    assert [record["case_id"] for record in report["inputs"]] == canonical_ids
    assert report["input_manifest_sha256"] == identity["input_manifest_sha256"]


def test_long_census_uses_bounded_fresh_processes(tmp_path, monkeypatch):
    inputs = tmp_path / "dev"
    inputs.mkdir()
    for number in (1, 2):
        empty = fitz.open()
        empty.new_page()
        empty.save(inputs / f"MIB-{number:06d}.pdf")
        empty.close()
    identity, config, repo = _bound_census_args(inputs)
    monkeypatch.setattr(
        selector_census, "MAX_CASES_PER_INSPECTOR", 1)

    report = selector_census.build_census(
        inputs, "dev", identity, config, repo)

    assert report["valid"] is True
    assert report["pdf_count"] == 2
    assert report["page_count"] == 2
    assert report["inspection_process_max_cases"] == 1
    assert report["selector_outcome_counts"]["image_count_not_one"] == 2


def test_document_error_is_explicit_invalid_and_never_counts_eligibility(
        tmp_path, monkeypatch):
    inputs = tmp_path / "dev"
    inputs.mkdir()
    _eligible_pdf(inputs / "MIB-000001.pdf")
    identity, config, repo = _bound_census_args(inputs)

    def fail(_page):
        raise RuntimeError("synthetic inspection failure")

    monkeypatch.setattr(
        "tools.native_selector_census.forensics.native_full_page_scan_audit",
        fail)
    report = build_census(inputs, "dev", identity, config, repo)
    assert report["valid"] is False
    assert report["document_error_count"] == 1
    assert report["eligible_pdf_count"] == 0
    assert report["eligible_page_count"] == 0
    assert report["page_count"] == 0
    assert report["inputs"][0]["pages"] == []


def test_unknown_selector_outcome_fails_closed(tmp_path, monkeypatch):
    inputs = tmp_path / "dev"
    inputs.mkdir()
    _eligible_pdf(inputs / "MIB-000001.pdf")
    identity, config, repo = _bound_census_args(inputs)
    monkeypatch.setattr(
        "tools.native_selector_census.forensics.native_full_page_scan_audit",
        lambda _page: {"eligible": False, "reason": "future_reason"})
    with pytest.raises(ValueError, match="unknown outcome"):
        build_census(inputs, "dev", identity, config, repo)


def test_input_drift_between_binding_and_inspection_fails_closed(
        tmp_path, monkeypatch):
    inputs = tmp_path / "dev"
    inputs.mkdir()
    pdf = inputs / "MIB-000001.pdf"
    _eligible_pdf(pdf)
    identity, config, repo = _bound_census_args(inputs)
    original = type(pdf).read_bytes
    reads = {str(pdf): 0}

    def drifting(path):
        raw = original(path)
        if str(path) == str(pdf):
            reads[str(pdf)] += 1
            if reads[str(pdf)] == 2:
                return raw + b"changed"
        return raw

    monkeypatch.setattr(type(pdf), "read_bytes", drifting)
    with pytest.raises(ValueError, match="changed before inspection"):
        build_census(inputs, "dev", identity, config, repo)


def test_census_rejects_dirty_or_mismatched_producer_source(tmp_path):
    inputs = tmp_path / "dev"
    inputs.mkdir()
    _eligible_pdf(inputs / "MIB-000001.pdf")
    identity, config, repo = _bound_census_args(inputs)
    (repo / "mib/forensics.py").write_text("modified after commit\n")
    with pytest.raises(ValueError, match="producer repository is dirty"):
        build_census(inputs, "dev", identity, config, repo)

    subprocess.run(["git", "add", "mib/forensics.py"], cwd=repo, check=True)
    subprocess.run(["git", "-c", "commit.gpgsign=false", "commit", "-qm",
                    "different producer"], cwd=repo, check=True)
    with pytest.raises(ValueError, match="producer SHA differs"):
        build_census(inputs, "dev", identity, config, repo)
