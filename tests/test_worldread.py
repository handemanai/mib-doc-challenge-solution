"""Embargo-world ROI reader: embargo-only vocabulary, two-view (CTC+NCC) gate,
and the real damaged-scan roundtrip it was built for (MIB-000261 recovers the
clean 'Wolf-1061c' the pixmatch margin gate abstained on; the other world-unread
packets, including the second Wolf seed, abstain)."""
import json
import os
from pathlib import Path

import fitz
import pytest

from mib import rules, worldread

from tools.challenge_paths import CHALLENGE  # noqa: E402
TRAIN = CHALLENGE / "data" / "train"


def test_emits_only_embargo_worlds():
    assert worldread.EMBARGO_WORLDS == (
        rules.HARD_EMBARGO_WORLDS | rules.SOFT_EMBARGO_WORLDS)
    # a non-embargo world is never in the emission set
    assert "Proxima-b" not in worldread.EMBARGO_WORLDS
    assert "Wolf-1061c" in worldread.EMBARGO_WORLDS


def test_env_gate_off_disables_channel(monkeypatch):
    monkeypatch.setenv("MIB_WORLD_ROI", "0")
    assert worldread.enabled() is False


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
                _pt_cache[s["case_id"]] = {
                    i: t for i, t in enumerate(s["page_types"])}
    return _pt_cache.get(case, {})


def _read(case, struck=()):
    doc = fitz.open(str(TRAIN / f"{case}.pdf"))
    try:
        return worldread.read_world(doc, _pt(case), None, struck)
    finally:
        doc.close()


@pytest.mark.skipif(not TRAIN.exists(), reason="challenge data not present")
def test_real_261_recovers_wolf():
    read = _read("MIB-000261")
    assert read is not None and read[0] == "Wolf-1061c"


@pytest.mark.skipif(not TRAIN.exists(), reason="challenge data not present")
@pytest.mark.parametrize("case", [
    "MIB-000892",   # second Wolf seed: anchor lands on a blank strip, glyph
                    # view finds nothing -> abstain (never guessed)
    "MIB-000002",   # non-embargo truth worlds must never produce an embargo fire
    "MIB-000051",
])
def test_real_abstains(case):
    assert _read(case) is None


@pytest.mark.skipif(not TRAIN.exists(), reason="challenge data not present")
def test_struck_world_is_not_read():
    assert _read("MIB-000261", struck=["Wolf-1061c"]) is None
