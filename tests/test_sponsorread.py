"""Deny-direction revoked-sponsor recovery and its abstention boundaries."""
from pathlib import Path

import fitz
import pytest

from mib import forensics, rules, sponsorread

from tools.challenge_paths import CHALLENGE  # noqa: E402
TRAIN = CHALLENGE / "data" / "train"

FAST_710 = [
    "World:",
    "2021-7331",
    "ASSPO",
    "Packet MIB-000710-page1",
]
HQ_710 = [
    "S",
    "pons(",
    "2020-7331",
    "Packet MIB-000710-page1",
]


def test_emission_vocabulary_is_revoked_only():
    for sponsor in rules.REVOKED_SPONSORS:
        suffix = sponsor.removeprefix("SPN-")
        assert sponsorread._revoked_suffix([f"2021-{suffix}"]) == sponsor
    assert sponsorread._revoked_suffix(["2021-2244"]) is None
    assert sponsorread._revoked_suffix(
        ["2021-7331", "2021-9090"]) is None


def test_page_binding_rejects_foreign_or_missing_case():
    assert sponsorread._page_bound(
        "MIB-000710", FAST_710, HQ_710)
    assert not sponsorread._page_bound(
        "MIB-000710", FAST_710, HQ_710 + ["MIB-000222"])
    assert not sponsorread._page_bound(
        "MIB-000710", ["2021-7331"], ["2020-7331"])


@pytest.mark.skipif(not TRAIN.exists(), reason="challenge data not present")
def test_real_710_pixels_and_two_ocr_views_recover_revoked_sponsor():
    with fitz.open(TRAIN / "MIB-000710.pdf") as doc:
        _visible, hidden = forensics.classify_spans(doc)
        read = sponsorread.read_revoked_sponsor(
            doc, "MIB-000710", {0: "registry"},
            {0: FAST_710}, {0: HQ_710}, hidden_spans=hidden)
    assert read is not None
    assert read[0] == "SPN-7331"
    assert read[2]["channel"] == "two_ocr_suffix_plus_prefix"


@pytest.mark.skipif(not TRAIN.exists(), reason="challenge data not present")
@pytest.mark.parametrize(
    "fast,hq,struck",
    [
        (FAST_710, [], ()),                         # missing independent view
        (FAST_710, ["2020-9090", "MIB-000710"], ()),  # views disagree
        (FAST_710, HQ_710, ("SPN-7331",)),          # field-local strike
    ],
)
def test_real_710_abstains_when_a_required_guard_is_missing(fast, hq, struck):
    with fitz.open(TRAIN / "MIB-000710.pdf") as doc:
        _visible, hidden = forensics.classify_spans(doc)
        read = sponsorread.read_revoked_sponsor(
            doc, "MIB-000710", {0: "registry"},
            {0: fast}, {0: hq}, struck, hidden)
    assert read is None
