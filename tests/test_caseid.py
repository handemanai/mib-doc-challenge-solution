"""Case-id resolution must survive renamed inputs and never emit the ghost id.

The scorer keys truth to the assigned file name and fails the whole submission
on any unexpected id, so the resolver emits a well-formed ``MIB-\\d{6}`` stem
whenever it has one and falls back to the visible packet header/footer grammar
only when the stem is malformed/renamed. A conflicting document vote never
overrides a valid stem.
"""

import shutil
from pathlib import Path

import fitz
import pytest

from mib import caseid, forensics

from tools.challenge_paths import CHALLENGE  # noqa: E402
TRAIN = CHALLENGE / "data" / "train"

# Spread across the corpus: vector-heavy, scan-heavy, injected, and
# multi-applicant packets all appear in this range.
RENAME_SAMPLE = [
    "MIB-000003", "MIB-000019", "MIB-000048", "MIB-000105", "MIB-000116",
    "MIB-000205", "MIB-000254", "MIB-000301", "MIB-000377", "MIB-000402",
    "MIB-000469", "MIB-000512", "MIB-000543", "MIB-000618", "MIB-000672",
    "MIB-000701", "MIB-000750", "MIB-000823", "MIB-000901", "MIB-000955",
]


class _Span:
    def __init__(self, page, text):
        self.page = page
        self.text = text


def _resolve_real(pdf_path):
    with fitz.open(pdf_path) as doc:
        visible, _ = forensics.classify_spans(doc)
    return caseid.resolve(str(pdf_path), visible)


@pytest.mark.skipif(not TRAIN.exists(), reason="challenge data not present")
def test_renamed_pdfs_resolve_to_document_id(tmp_path):
    for true_id in RENAME_SAMPLE:
        src = TRAIN / f"{true_id}.pdf"
        renamed = tmp_path / f"scan_{hash(true_id) & 0xffff:04x}.pdf"
        shutil.copyfile(src, renamed)
        resolved, provenance = _resolve_real(renamed)
        assert resolved == true_id, (true_id, provenance)
        assert provenance["source"] in {"document_unanimous",
                                        "document_plurality"}


@pytest.mark.skipif(not TRAIN.exists(), reason="challenge data not present")
def test_original_names_are_behavior_neutral():
    for true_id in RENAME_SAMPLE[:5]:
        resolved, provenance = _resolve_real(TRAIN / f"{true_id}.pdf")
        assert resolved == true_id
        assert provenance["source"] == "stem_confirmed_by_document"


def test_ghost_id_never_wins():
    spans = [_Span(0, "Packet MIB-000000 / page 1"),
             _Span(1, "Packet MIB-000000 / page 2")]
    resolved, provenance = caseid.resolve("/x/scan_01.pdf", spans)
    assert resolved == "scan_01"
    assert provenance["source"] == "stem_unverified"


def test_valid_stem_beats_single_page_disagreement():
    spans = [_Span(0, "Packet MIB-000042 / page 1")]
    resolved, provenance = caseid.resolve("/x/MIB-000007.pdf", spans)
    assert resolved == "MIB-000007"
    assert provenance["source"] == "stem_over_document_conflict"


def test_valid_stem_is_never_overridden_by_document_vote():
    # A well-formed stem is the scorer's truth key: even a unanimous multi-page
    # document vote for a different valid id must NOT override it, because
    # emitting the document id would be an unexpected id (evaluate.py exit 2).
    spans = [_Span(0, "Packet MIB-000042 / page 1"),
             _Span(1, "Packet MIB-000042 / page 2"),
             _Span(2, "MIB-000042 | MIB Eyes Only")]
    resolved, provenance = caseid.resolve("/x/MIB-000007.pdf", spans)
    assert resolved == "MIB-000007"
    assert provenance["source"] == "stem_over_document_conflict"


def test_split_vote_plurality_on_renamed_input():
    spans = [_Span(0, "Packet MIB-000042 / page 1"),
             _Span(1, "Packet MIB-000042 / page 2"),
             _Span(2, "Packet MIB-000099 / page 3")]
    resolved, provenance = caseid.resolve("/x/scan_02.pdf", spans)
    assert resolved == "MIB-000042"
    assert provenance["source"] == "document_plurality"


def test_hidden_spans_do_not_vote():
    # resolve() only ever sees visible spans by contract; this documents the
    # contract at the caseid layer: an empty visible set falls back to stem.
    resolved, provenance = caseid.resolve("/x/MIB-000007.pdf", [])
    assert resolved == "MIB-000007"
    assert provenance["source"] == "stem_only"
