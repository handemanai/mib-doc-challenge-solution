"""Note-finding recovery reader (mib.noteread) guards and roundtrips.

Covers the two-view finding-value acceptance, the finding-narrative reason
matcher (and its deliberate rejection of fact-stating reasons), the per-page
channel combination, the direction asymmetry enforced by decide(), the real
damaged notes it was built for (134/589/444 recover DENIED; 931 recovers
NEEDS_REVIEW), the typed SAMPLE-DENIAL note it must quarantine (710), the
truth-APPROVED notes it must never touch (047/333/685/176/545), and the
red-team injection/watermark corpus it must abstain on.
"""
import json
import os
from pathlib import Path

import fitz
import pytest

from mib import forensics, noteread, pixmatch
from mib.pipeline import decide, extract_state

from tools.challenge_paths import CHALLENGE  # noqa: E402
TRAIN = CHALLENGE / "data" / "train"
REDTEAM = Path(__file__).resolve().parent / "redteam_corpus"


# ---- structural: APPROVED is never emitted or enabled ---------------------

def test_approved_absent_from_emission_vocabulary():
    assert noteread.EMIT == ("DENIED", "NEEDS_REVIEW")
    assert "APPROVED" not in noteread.EMIT


# ---- finding-value two-view acceptance ------------------------------------

def _v(*rows):
    return list(rows)


def test_fv_accepts_clean_two_view_denied():
    raw = _v((0.44, "DENIED", 8), (0.23, "NEEDS_REVIEW", 21), (0.20, "APPROVED", 21))
    assert noteread._finding_value_from_strips((raw, raw)) == "DENIED"


def test_fv_approved_winner_is_abstain_signal():
    # 176: an APPROVED note reads "APPROVED" at the strip head; the discriminator
    # returns the abstain signal so the whole packet stands down.
    a = _v((0.31, "APPROVED", 8), (0.24, "DENIED", 9), (0.20, "NEEDS_REVIEW", 20))
    assert noteread._finding_value_from_strips((a, a)) == "APPROVED"


def test_fv_off_strip_match_rejected():
    # 047: a "DENIED" template aliases far down the strip (x=502) on an APPROVED
    # note; the head-position bound rejects it.
    o = _v((0.35, "DENIED", 502), (0.20, "NEEDS_REVIEW", 9), (0.19, "APPROVED", 9))
    assert noteread._finding_value_from_strips((o, o)) is None


def test_fv_low_ncc_rejected():
    lo = _v((0.29, "DENIED", 8), (0.20, "NEEDS_REVIEW", 9), (0.19, "APPROVED", 9))
    assert noteread._finding_value_from_strips((lo, lo)) is None


def test_fv_view_disagreement_rejected():
    # Raw view reads DENIED, contrast-stretched view reads NEEDS_REVIEW: a faint
    # white-on-gray resurrection shows up only under one preprocessing, so the
    # two views must agree.
    raw = _v((0.44, "DENIED", 8), (0.20, "NEEDS_REVIEW", 9), (0.19, "APPROVED", 9))
    stretch = _v((0.44, "NEEDS_REVIEW", 8), (0.20, "DENIED", 9), (0.19, "APPROVED", 9))
    assert noteread._finding_value_from_strips((raw, stretch)) is None


def test_fv_low_margin_rejected():
    lm = _v((0.40, "DENIED", 8), (0.35, "NEEDS_REVIEW", 9), (0.19, "APPROVED", 9))
    assert noteread._finding_value_from_strips((lm, lm)) is None


# ---- reason narrative matcher ---------------------------------------------

@pytest.mark.parametrize("line,expect", [
    ("Reason: Denial supported by damaged registry evidence and policy tier.", "DENIED"),
    # OCR-garbled denial narrative still matches (fuzzy).
    ("Reason: Denial auppoded by daraged rogjiry evdancescidat paty res:", "DENIED"),
    ("Reason: Packet contains damaged or contradictory visible evidence.", "NEEDS_REVIEW"),
    ("Reason: Clean or exception-qualified packet.", "APPROVED"),
    ("Reason: Approval supported by surviving visible evidence and notes.", "APPROVED"),
])
def test_reason_narrative_maps(line, expect):
    assert noteread._reason_finding(line) == expect


@pytest.mark.parametrize("line", [
    # FACT-stating reasons are NOT finding-committal: a revoked sponsor can be
    # hedged (MIB-000928 -> NEEDS_REVIEW) and a review-only flag can sit on a
    # DENIED note (MIB-000471/466). The finding-agnostic Wolf embargo reason
    # maps to both directions. None of these may vote a finding.
    "Reason: Revoked sponsor: SPN-0139.",
    "Reason: Review-only risk flag present: illegible_biometrics",
    "Reason: Embargo home world: Wolf-1061c.",
    "Reason: Fee status unknown.",
    "Reason: Mandatory fee unpaid.",
    "Reason: Disqualifying risk flag: biohazard_red.",
    # not a reason line at all
    "Finding: DENIED",
    "Manual Adjudicator Note",
])
def test_reason_fact_stating_and_nonreason_reject(line):
    assert noteread._reason_finding(line) is None


# ---- unknown-page note detection + stamp guard ----------------------------

def test_note_like_detects_structure():
    assert noteread._note_like(["Reason: Denial supported by damaged"]) is True
    assert noteread._note_like(["Finding: DENIED"]) is True
    assert noteread._note_like(["Manial Adjudieator Nofe"]) is True   # garbled hdr
    assert noteread._note_like(["Species Code: ALPHA", "Visa Class: XW-2"]) is False


def test_unknown_note_requires_two_structure_signals():
    assert noteread._note_structure_signals(
        ["Reason: Denial supported by damaged"]) == {"reason"}
    assert noteread._note_structure_signals(
        ["Manial Adjudieator Nofe", "Finding: DENIED"]) == {"header", "finding"}


def test_page_local_binding_does_not_borrow_identity_from_other_pages():
    assert noteread._page_local_binding(
        "MIB-000399", ["Reason: denial", "Packet MIB-000399 / page 2"])
    assert not noteread._page_local_binding(
        "MIB-000399", ["Reason: denial"])
    assert not noteread._page_local_binding(
        "MIB-000399", ["Case ID: MIB-000400", "Reason: denial"])


@pytest.mark.parametrize("variant", [
    "SAMPLE DENIAL", "SAMPLE DENAL", "SAMPLE DEHAL", "E DENIAL",
    "SAMRMFRENLANA",
])
def test_watermark_suspect_catches_damaged_variants(variant):
    assert noteread._watermark_suspect([variant])


def test_watermark_suspect_ignores_real_finding_and_reason():
    assert not noteread._watermark_suspect([
        "Finding: DENIED",
        "Reason: Denial supported by damaged registry evidence.",
    ])


def test_cancel_stamps_detects_superseded_marks():
    assert noteread._cancel_stamps("this is a COPY of the note") == ["COPY"]
    assert "ARCHIVE" in noteread._cancel_stamps("ARCHIVE FILED")
    assert noteread._cancel_stamps("INTAKE routing") == []   # benign


# ---- per-page channel combination -----------------------------------------

def test_page_vote_fv_only_fires():
    assert noteread._page_vote("DENIED", [], []) == ("DENIED", False)


def test_page_vote_reason_review_single_view_fires():
    # NEEDS_REVIEW is the safe direction: one OCR pass with no contradiction.
    assert noteread._page_vote(None, [], ["NEEDS_REVIEW"]) == ("NEEDS_REVIEW", False)


def test_page_vote_reason_denied_single_view_requires_unknown_page_corroboration():
    # A typed note may retain the historical single-view narrative behavior,
    # but an unknown page may not become rank-1 from one OCR reason read.
    assert noteread._page_vote(None, ["DENIED"], []) == ("DENIED", False)
    assert noteread._page_vote(None, [], ["DENIED"]) == ("DENIED", False)
    assert noteread._page_vote(
        None, ["DENIED"], [], require_denied_corroboration=True) == (None, False)


def test_page_vote_reason_denied_two_view_fires():
    assert noteread._page_vote(None, ["DENIED"], ["DENIED"]) == ("DENIED", False)


def test_page_vote_reason_denied_with_fv_corroboration_fires():
    assert noteread._page_vote("DENIED", ["DENIED"], []) == ("DENIED", False)


def test_page_vote_approved_signal_abstains():
    assert noteread._page_vote("APPROVED", [], [])[1] is True
    assert noteread._page_vote(None, ["APPROVED"], [])[1] is True


def test_page_vote_fv_reason_conflict_abstains():
    assert noteread._page_vote("DENIED", [], ["NEEDS_REVIEW"])[0] is None


def test_page_vote_contradictory_reasons_abstain():
    finding, approved = noteread._page_vote(None, ["DENIED"], ["NEEDS_REVIEW"])
    assert finding is None and approved is True


# ---- precondition guards --------------------------------------------------

def test_guard_legible_finding_blocks():
    assert noteread._guards_ok({"finding": "DENIED"}) is False


def test_guard_rank1_conflict_blocks():
    assert noteread._guards_ok({"rank1_conflicts": ["x"]}) is False


def test_guard_correction_allows_deny_review():
    # A signed correction no longer blocks a recovered deny/review finding — the
    # direction asymmetry protects the genuine conflict (a correction-driven
    # APPROVED can never be overridden by a recovered DENIED). MIB-000399 rides
    # alongside a consistent deny-side sponsor correction.
    assert noteread._guards_ok({"corrections": {"sponsor_id": "SPN-1"}}) is True
    assert noteread._guards_ok({"name_correction": "A B"}) is True


def test_guard_clean_passes():
    assert noteread._guards_ok({"finding": None}) is True


# ---- direction asymmetry in decide() --------------------------------------

RANK = {"intake": 2, "fee_receipt": 2, "biometric": 3}
_CLEAN = {
    "risk_flags": ("none", "biometric", 90.0, 2),
    "fee_status": ("paid", "fee_receipt", 95.0, 1),
    "home_world": ("Kepler-186f", "intake", 100.0, 2),
    "visa_class": ("XW-2", "intake", 100.0, 2),
    "sponsor_id": ("SPN-1234", "intake", 95.0, 2),
    "arrival_date": ("2026-06-01", "intake", 95.0, 2),
    "species_code": ("TRIANGULAN", "intake", 100.0, 2),
    "declared_purpose": ("research", "intake", 100.0, 2),
    "applicant_name": ("Solmora Tekvoss", "intake", 90.0, 2),
}
_EXTRA = ["biometric", "registry", "sponsor_letter"]


def _state(fields, doc_notes):
    pools = {}
    for f, (value, source, score, n) in fields.items():
        srcs = ([source] + [s for s in _EXTRA if s != source])[:max(1, n)]
        pools[f] = [[value, s, RANK.get(s, 6), score] for s in srcs]
    return {"case_id": "MIB-000000", "pools": pools, "doc_notes": doc_notes,
            "mean_ocr_conf": 0.8, "injection": {}, "hidden_field_mentions": {}}


def _decide(fields, doc_notes):
    return decide(_state(fields, doc_notes))[0]["adjudication"]


def test_recovered_denied_flips_review_to_denied():
    # baseline hedges (arrival date missing) -> recovered DENIED promotes it.
    f = {k: v for k, v in _CLEAN.items() if k != "arrival_date"}
    assert _decide(f, {"finding": None}) == "NEEDS_REVIEW"
    assert _decide(f, {"finding": None, "recovered_finding": "DENIED"}) == "DENIED"


def test_recovered_denied_never_flips_approved():
    # A clean approval must NOT be denied by a recovered finding (direction rule).
    assert _decide(dict(_CLEAN), {"finding": None}) == "APPROVED"
    assert _decide(dict(_CLEAN),
                   {"finding": None, "recovered_finding": "DENIED"}) == "APPROVED"


def test_recovered_review_flips_terminal_to_review():
    denied = dict(_CLEAN, fee_status=("unpaid", "fee_receipt", 95.0, 1))
    assert _decide(denied, {"finding": None}) == "DENIED"
    assert _decide(denied, {"finding": None,
                            "recovered_finding": "NEEDS_REVIEW"}) == "NEEDS_REVIEW"
    assert _decide(dict(_CLEAN),
                   {"finding": None,
                    "recovered_finding": "NEEDS_REVIEW"}) == "NEEDS_REVIEW"


def test_legible_finding_wins_over_recovered():
    denied = dict(_CLEAN, fee_status=("unpaid", "fee_receipt", 95.0, 1))
    # a legible APPROVED finding stands; the recovered value is ignored.
    assert _decide(denied, {"finding": "APPROVED",
                            "recovered_finding": "NEEDS_REVIEW"}) == "APPROVED"


def test_recovered_ignored_under_rank1_conflict():
    f = {k: v for k, v in _CLEAN.items() if k != "arrival_date"}
    assert _decide(f, {"finding": None, "recovered_finding": "DENIED",
                       "rank1_conflicts": ["x"]}) == "NEEDS_REVIEW"


def test_recovered_approved_string_is_inert():
    # Even if some path set recovered_finding to APPROVED, decide() has no branch
    # that emits it: a clean approval is unchanged and a denial stays denied.
    denied = dict(_CLEAN, fee_status=("unpaid", "fee_receipt", 95.0, 1))
    assert _decide(denied, {"finding": None,
                            "recovered_finding": "APPROVED"}) == "DENIED"


# ---- real damaged-note roundtrips -----------------------------------------

_pt_cache = None


def _pt(case):
    global _pt_cache
    if _pt_cache is None:
        _pt_cache = {}
        states = Path(os.environ.get("MIB_DEV_STATES",
                      "/tmp/mib-eval-w6c/states_dev.jsonl"))
        if states.exists():
            for line in states.open():
                s = json.loads(line)
                _pt_cache[s["case_id"]] = s
    return _pt_cache.get(case)


def _read(case):
    s = _pt(case)
    if s is None:
        pytest.skip("cached states not present")
    pt_by_no = {i: t for i, t in enumerate(s.get("page_types", []))}
    texts = {}
    for rp in s.get("raw_pages", []):
        if rp.get("kind") in ("scan", "scan_hq"):
            texts.setdefault(rp["page"], []).extend(t for t, _ in rp.get("lines", []))
    doc = fitz.open(str(TRAIN / f"{case}.pdf"))
    try:
        _v, hidden = forensics.classify_spans(doc)
        return noteread.note_finding(
            doc, case, pt_by_no, texts, s["doc_notes"],
            s.get("struck_values", []), hidden_spans=hidden)
    finally:
        doc.close()


@pytest.mark.skipif(not TRAIN.exists(), reason="challenge data not present")
@pytest.mark.parametrize("case", ["MIB-000134", "MIB-000589", "MIB-000444"])
def test_real_denied_notes_recover_denied(case):
    assert _read(case) == "DENIED"


@pytest.mark.skipif(not TRAIN.exists(), reason="challenge data not present")
def test_real_review_note_recovers_review():
    assert _read("MIB-000931") == "NEEDS_REVIEW"


@pytest.mark.skipif(not TRAIN.exists(), reason="challenge data not present")
@pytest.mark.parametrize("case", [
    "MIB-000399",  # lone reason, no independently recognized note structure
    "MIB-000497",  # reason on OCR-garbled SAMPLE DENIAL page
    "MIB-000888",  # direct finding on severely garbled SAMPLE DENIAL page
    "MIB-000943",  # direct finding on FILED/COPY/ARCHIVE unknown page
    "MIB-000221",  # direct finding but no page-local active case binding
])
def test_real_untrusted_unknown_notes_abstain(case):
    assert _read(case) is None


@pytest.mark.skipif(not TRAIN.exists(), reason="challenge data not present")
def test_sample_denial_decoy_page_abstains():
    # MIB-000261 p5 is a SAMPLE-DENIAL-stamped decoy carrying the SAME genuine
    # deny narrative ("Denial supported by damaged registry evidence"). The
    # per-page watermark guard must reject it — the reader must not recover a
    # finding from a watermark decoy page.
    assert _read("MIB-000261") is None


@pytest.mark.skipif(not TRAIN.exists(), reason="challenge data not present")
def test_typed_sample_denial_note_abstains():
    # MIB-000710 p2 is correctly typed as a Manual Adjudicator Note, but the
    # note itself carries a large SAMPLE DENIAL watermark.  Recognition of the
    # form cannot restore authority to its Finding/Reason fields.
    assert _read("MIB-000710") is None


@pytest.mark.skipif(not TRAIN.exists(), reason="challenge data not present")
@pytest.mark.parametrize("case", ["MIB-000047", "MIB-000333", "MIB-000685",
                                  "MIB-000176", "MIB-000545"])
def test_real_approved_notes_never_fire(case):
    # Approve direction is forbidden: these truth-APPROVED notes must abstain.
    assert _read(case) is None


# ---- red-team injection / watermark corpus --------------------------------

@pytest.mark.skipif(not REDTEAM.exists(), reason="redteam corpus not present")
def test_redteam_notes_never_recover():
    manifest = json.loads((REDTEAM / "manifest.json").read_text())
    for case, spec in manifest["cases"].items():
        state = extract_state(str(REDTEAM / spec["pdf"]))
        assert state["doc_notes"].get("recovered_finding") is None, case
        assert decide(state)[0]["adjudication"] == spec["clean_twin_decision"], case


# ---- approve-direction ablation (MIB_NOTE_ROI_APPROVE, default OFF) --------

def test_approve_disabled_by_default():
    assert noteread.approve_enabled() is False


def test_approve_env_enables(monkeypatch):
    monkeypatch.setenv("MIB_NOTE_ROI_APPROVE", "1")
    assert noteread.approve_enabled() is True


def test_recovered_approve_inert_without_flag():
    # Default (flag OFF): a recovered APPROVED never widens toward approval.
    denied = dict(_CLEAN, fee_status=("unpaid", "fee_receipt", 95.0, 1))
    assert _decide(denied, {"finding": None,
                            "recovered_finding": "APPROVED"}) == "DENIED"


def test_recovered_approve_flips_only_with_flag(monkeypatch):
    monkeypatch.setenv("MIB_NOTE_ROI_APPROVE", "1")
    denied = dict(_CLEAN, fee_status=("unpaid", "fee_receipt", 95.0, 1))
    assert _decide(denied, {"finding": None,
                            "recovered_finding": "APPROVED"}) == "APPROVED"
    # a legible finding still wins over a recovered approve.
    assert _decide(denied, {"finding": "DENIED",
                            "recovered_finding": "APPROVED"}) == "DENIED"


@pytest.mark.skipif(not TRAIN.exists(), reason="challenge data not present")
def test_finding_value_approve_reads_strong_note():
    # MIB-000176 prints a strong, clean "APPROVED" finding word.
    doc = fitz.open(str(TRAIN / "MIB-000176.pdf"))
    try:
        got = None
        for _p, img in pixmatch._p0b_scan_images(doc, None):
            desk, _ = pixmatch.deskew_robust(img)
            if noteread._finding_value_approve(desk) == "APPROVED":
                got = "APPROVED"
        assert got == "APPROVED"
    finally:
        doc.close()


@pytest.mark.skipif(not TRAIN.exists(), reason="challenge data not present")
def test_finding_value_approve_rejects_washed_note():
    # MIB-000084's washed note is sub-SNR: the finding word must NOT read.
    doc = fitz.open(str(TRAIN / "MIB-000084.pdf"))
    try:
        for _p, img in pixmatch._p0b_scan_images(doc, None):
            desk, _ = pixmatch.deskew_robust(img)
            assert noteread._finding_value_approve(desk) is None
    finally:
        doc.close()


@pytest.mark.skipif(not TRAIN.exists(), reason="challenge data not present")
@pytest.mark.parametrize("case", ["MIB-000084", "MIB-000176", "MIB-000047",
                                  "MIB-000685", "MIB-000442", "MIB-000979"])
def test_approve_direction_abstains_on_dev(case, monkeypatch):
    # With the flag ON the strict finding-word AND reason gate fires on no dev
    # note (176 has the finding word but no readable reason; 047/685 have the
    # reason but no finding word; 084/442/979 are sub-SNR). 0 dev fires.
    monkeypatch.setenv("MIB_NOTE_ROI_APPROVE", "1")
    assert _read(case) != "APPROVED"


def test_uses_deskew_robust():
    assert hasattr(pixmatch, "deskew_robust")


# ---- env gate -------------------------------------------------------------

def test_env_gate_off_disables_channel(monkeypatch):
    monkeypatch.setenv("MIB_NOTE_ROI", "0")
    assert noteread.enabled() is False
    assert noteread.note_finding(None, "MIB-0", {}, {}, {"finding": None}) is None
