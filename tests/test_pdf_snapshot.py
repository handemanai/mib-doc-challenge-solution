"""Immutable PDF-byte ownership and PyMuPDF lifecycle contracts."""

import builtins
import hashlib
from pathlib import Path

import fitz
import pytest

from mib import forensics, pipeline


class _FakeDocument:
    def __init__(self):
        self.close_count = 0

    def close(self):
        self.close_count += 1


def test_extract_state_reads_once_stream_opens_and_closes(monkeypatch,
                                                           tmp_path):
    pdf = tmp_path / "MIB-000001.pdf"
    raw = b"one immutable packet snapshot"
    pdf.write_bytes(raw)
    original_read_bytes = Path.read_bytes
    reads = []

    def counted_read_bytes(path):
        if path == pdf:
            reads.append(path)
        return original_read_bytes(path)

    events = []
    captured = {}
    document = _FakeDocument()

    def stream_open(*args, **kwargs):
        events.append("open")
        assert args == ()
        assert kwargs == {"stream": raw, "filetype": "pdf"}
        captured["snapshot"] = kwargs["stream"]
        return document

    def extract_from_snapshot(path, opened, snapshot):
        events.append("extract")
        assert path == pdf
        assert opened is document
        assert snapshot is captured["snapshot"]
        return {"case_id": pdf.stem}

    monkeypatch.setattr(Path, "read_bytes", counted_read_bytes)
    monkeypatch.setattr(pipeline, "_clear_mupdf_warnings",
                        lambda: events.append("clear"))
    monkeypatch.setattr(pipeline.fitz, "open", stream_open)
    monkeypatch.setattr(
        pipeline, "_extract_state_from_document", extract_from_snapshot)

    assert pipeline.extract_state(pdf) == {"case_id": "MIB-000001"}
    assert reads == [pdf]
    assert events == ["clear", "open", "extract"]
    assert document.close_count == 1


def test_extract_state_closes_once_when_extraction_raises(monkeypatch,
                                                          tmp_path):
    pdf = tmp_path / "MIB-000001.pdf"
    pdf.write_bytes(b"snapshot")
    document = _FakeDocument()
    monkeypatch.setattr(pipeline, "_clear_mupdf_warnings", lambda: None)
    monkeypatch.setattr(pipeline.fitz, "open",
                        lambda **kwargs: document)

    class ExtractionFailure(Exception):
        pass

    def fail(*args):
        raise ExtractionFailure("after open")

    monkeypatch.setattr(pipeline, "_extract_state_from_document", fail)
    with pytest.raises(ExtractionFailure, match="after open"):
        pipeline.extract_state(pdf)
    assert document.close_count == 1


def test_cleanup_failure_cannot_replace_extraction_failure(monkeypatch,
                                                           tmp_path):
    pdf = tmp_path / "MIB-000001.pdf"
    pdf.write_bytes(b"snapshot")

    class CleanupFailure(Exception):
        pass

    class ExtractionFailure(Exception):
        pass

    class BrokenDocument(_FakeDocument):
        def close(self):
            super().close()
            raise CleanupFailure("secondary cleanup failure")

    document = BrokenDocument()
    monkeypatch.setattr(pipeline, "_clear_mupdf_warnings", lambda: None)
    monkeypatch.setattr(pipeline.fitz, "open",
                        lambda **kwargs: document)

    def fail(*args):
        raise ExtractionFailure("primary extraction failure")

    monkeypatch.setattr(pipeline, "_extract_state_from_document", fail)
    with pytest.raises(ExtractionFailure, match="primary extraction failure"):
        pipeline.extract_state(pdf)
    assert document.close_count == 1


def test_cleanup_failure_after_success_is_bounded(monkeypatch, tmp_path):
    pdf = tmp_path / "MIB-000001.pdf"
    raw = b"snapshot"
    pdf.write_bytes(raw)

    class CleanupFailure(Exception):
        pass

    class BrokenDocument(_FakeDocument):
        def close(self):
            super().close()
            raise CleanupFailure("unbounded incidental close detail")

    document = BrokenDocument()
    monkeypatch.setattr(pipeline, "_clear_mupdf_warnings", lambda: None)
    monkeypatch.setattr(pipeline.fitz, "open",
                        lambda **kwargs: document)
    monkeypatch.setattr(pipeline, "_extract_state_from_document",
                        lambda *args: {"case_id": pdf.stem})

    with pytest.raises(RuntimeError) as raised:
        pipeline.extract_state(pdf)
    message = str(raised.value)
    assert isinstance(raised.value.__cause__, CleanupFailure)
    assert "pdf_close_error(type=CleanupFailure" in message
    assert f"bytes={len(raw)}" in message
    assert f"sha256={hashlib.sha256(raw).hexdigest()}" in message
    assert "incidental close detail" not in message
    assert len(message) < 200
    assert document.close_count == 1


def test_pdf_open_failure_is_bounded_and_clears_stale_warnings(
        monkeypatch, tmp_path):
    pdf = tmp_path / "MIB-000001.pdf"
    raw = b"damaged immutable bytes"
    pdf.write_bytes(raw)
    events = []

    class WarningTools:
        def __init__(self):
            self.calls = 0

        def mupdf_warnings(self, reset=1):
            assert reset == 1
            self.calls += 1
            events.append(f"warnings{self.calls}")
            return "stale prior warning" if self.calls == 1 else "W" * 1000

    failure = fitz.FileDataError(
        "unbounded library detail that must stay in the chained cause")

    def fail_open(*args, **kwargs):
        events.append("open")
        raise failure

    monkeypatch.setattr(pipeline.fitz, "TOOLS", WarningTools())
    monkeypatch.setattr(pipeline.fitz, "open", fail_open)
    with pytest.raises(RuntimeError) as raised:
        pipeline.extract_state(pdf)

    message = str(raised.value)
    assert raised.value.__cause__ is failure
    assert events == ["warnings1", "open", "warnings2"]
    assert "type=FileDataError" in message
    assert f"bytes={len(raw)}" in message
    assert f"sha256={hashlib.sha256(raw).hexdigest()}" in message
    assert "stale prior warning" not in message
    assert "unbounded library detail" not in message
    assert len(message) < 400


def test_container_signals_uses_supplied_bytes_without_reopening(monkeypatch):
    doc = fitz.open()
    doc.new_page()

    def forbidden_open(*args, **kwargs):
        raise AssertionError("container forensics must not reopen a path")

    monkeypatch.setattr(builtins, "open", forbidden_open)
    signals = forensics.container_signals(
        doc, b"%PDF snapshot\n%%EOF\nlate revision\n%%EOF")
    assert signals["incremental_updates"] == 1
    doc.close()


def test_extraction_helper_passes_identical_snapshot_to_container(
        monkeypatch):
    doc = fitz.open()
    doc.new_page()
    raw = b"identity-sensitive bytes"
    observed = {}

    def container(current_doc, snapshot):
        observed["doc"] = current_doc
        observed["snapshot"] = snapshot
        return {"incremental_updates": 0}

    monkeypatch.setattr(forensics, "container_signals", container)
    state = pipeline._extract_state_from_document(
        "MIB-000001.pdf", doc, raw)
    assert state["container"] == {"incremental_updates": 0}
    assert observed == {"doc": doc, "snapshot": raw}
    doc.close()
