"""Disqualifying-flag ROI reader: deny-direction vocabulary, two-view gate,
struck/watermark guards, and the real damaged-scan roundtrips it was built for
(MIB-000012 and uniquely suffixed MIB-000855 fire biohazard_red,
MIB-000397 fires planetary_embargo; ambiguous damage, truth-none packets, and
the hidden-text red-team injection all abstain)."""
import glob
import json
import os
from pathlib import Path

import fitz
import pytest

from mib import flagread, pipeline
from mib.vocab import DISQUALIFYING_FLAGS, REVIEW_FLAGS

from tools.challenge_paths import CHALLENGE  # noqa: E402
TRAIN = CHALLENGE / "data" / "train"


# ---- vocabulary / direction invariants ------------------------------------

def test_only_disqualifying_flags_ever_fire():
    # The reader's emission vocabulary is exactly the four disqualifying flags;
    # "none" and the review flags are never emitted (deny-direction only).
    assert set(flagread.DQ_FLAGS) == set(DISQUALIFYING_FLAGS)
    assert not (set(flagread.DQ_FLAGS) & set(REVIEW_FLAGS))
    assert "none" not in flagread.DQ_FLAGS


def test_env_gate_off_disables_channel(monkeypatch):
    monkeypatch.setenv("MIB_FLAG_ROI", "0")
    assert flagread.enabled() is False


def test_unique_suffix_requires_one_short_disqualifying_completion():
    assert flagread._unique_dq_suffix(
        ["Observed flags:", "d_red"]) == ("biohazard_red", "d_red")
    assert flagread._unique_dq_suffix(
        ["Observed flags:", "red"]) is None
    assert flagread._unique_dq_suffix(
        ["Observed flags:", "biohazard_red"]) is None
    assert flagread._unique_dq_suffix(
        ["Unrelated prose:", "d_red"]) is None


def test_partial_suffix_requires_local_b13_case_binding():
    lines = [
        "FORM B-13: Biometric Scan Slip",
        "Case ID: MIB-000855",
        "Observed flags:",
        "d_red",
    ]
    assert flagread._case_bound_b13("MIB-000855", lines)
    assert not flagread._case_bound_b13(
        "MIB-000855", lines + ["Case ID: MIB-000222"])
    assert not flagread._case_bound_b13(
        "MIB-000855", lines[1:])


# ---- pipeline abstain-population gate --------------------------------------

def test_pool_gate_counts_only_disqualifying_flags():
    # A garbled flag that snapped to "none" (or a review-only read) leaves the
    # case eligible; an existing disqualifying read makes it abstain.
    assert pipeline._pool_has_disqualifying_flag(None) is False
    assert pipeline._pool_has_disqualifying_flag(
        [["none", "unknown", 6, 40.0, "blohsecard_red"]]) is False
    assert pipeline._pool_has_disqualifying_flag(
        [["illegible_biometrics", "ocr", 3, 90.0, "x"]]) is False
    assert pipeline._pool_has_disqualifying_flag(
        [["biohazard_red", "flag_roi", 5, 87.0, "x"]]) is True


# ---- real damaged-scan roundtrips -----------------------------------------

_pt_cache = None


def _pt(case):
    global _pt_cache
    if _pt_cache is None:
        states = Path(os.environ.get("MIB_DEV_STATES",
                      "/tmp/mib-eval-w6c/states_dev.jsonl"))
        _pt_cache = {}
        if states.exists():
            for line in states.open():
                s = json.loads(line)
                _pt_cache[s["case_id"]] = s
    return _pt_cache.get(case)


def _read(case, struck=()):
    state = _pt(case)
    if state is None:
        pytest.skip("cached states not present")
    page_types = {i: t for i, t in enumerate(state["page_types"])}
    texts = {}
    for raw_page in state.get("raw_pages", []):
        if raw_page.get("kind") in ("scan", "scan_hq"):
            texts.setdefault(raw_page["page"], []).extend(
                text for text, _ in raw_page.get("lines", []))
    doc = fitz.open(str(TRAIN / f"{case}.pdf"))
    try:
        return flagread.read_flags(
            doc, page_types, texts, struck, case_id=case)
    finally:
        doc.close()


@pytest.mark.skipif(not TRAIN.exists(), reason="challenge data not present")
def test_real_012_fires_biohazard():
    read = _read("MIB-000012")
    assert read is not None and read[0] == "biohazard_red"


@pytest.mark.skipif(not TRAIN.exists(), reason="challenge data not present")
def test_real_397_fires_planetary_embargo():
    read = _read("MIB-000397")
    assert read is not None and read[0] == "planetary_embargo"


@pytest.mark.skipif(not TRAIN.exists(), reason="challenge data not present")
def test_real_855_unique_suffix_fires_biohazard():
    read = _read("MIB-000855")
    assert read is not None and read[0] == "biohazard_red"
    assert read[2]["channel"] == "unique_visible_suffix"
    assert read[2]["fragment"] == "d_red"


@pytest.mark.skipif(not TRAIN.exists(), reason="challenge data not present")
@pytest.mark.parametrize("case", [
    "MIB-000222",                 # value remains too ambiguous to complete
    "MIB-000865",                 # the one FA case, truth risk_flags=none
    "MIB-000002", "MIB-000051",   # truth-none intake/biometric packets
])
def test_real_abstains(case):
    assert _read(case) is None


@pytest.mark.skipif(not TRAIN.exists(), reason="challenge data not present")
def test_struck_flag_is_not_read():
    # A colored vector strike over the value cancels it; decide re-filters too.
    assert _read("MIB-000012", struck=["biohazard_red"]) is None


# ---- injection inertness (red-team corpus) --------------------------------

_RED = Path(__file__).resolve().parent / "redteam_corpus"


@pytest.mark.skipif(not _RED.exists(), reason="red-team corpus not present")
def test_redteam_hidden_flag_injection_abstains():
    # The traps inject "biohazard_red" as hidden PDF text on a clean packet.
    # The reader reads only the raster (never rasterized), so it must abstain.
    for pdf in sorted(glob.glob(str(_RED / "*.pdf"))):
        doc = fitz.open(pdf)
        try:
            assert flagread.flag_roi_candidate(
                doc, {}, {}, [], None, "MIB-999999") is None
        finally:
            doc.close()
