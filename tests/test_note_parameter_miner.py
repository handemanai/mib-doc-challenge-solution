"""Note-parameter miner: revoked sponsors named in adjudicator-note reasons
feed the batch approval-blocker as rotation insurance. Two-occurrence
acceptance, OCR digit normalization, dev-neutral by construction (mined ids
on the public corpus are all already in the static revoked list).
"""
from mib.parse_ocr import parse_page
from mib.pipeline import batch_frequent_sponsors, mine_note_parameters


def _note_page(reason_line):
    lines = ["Manual Adjudicator Note", "Case ID: MIB-000042",
             "Finding: DENIED", reason_line]
    return parse_page([(t, 0.97) for t in lines])


def _state(case_id, mined):
    return {"case_id": case_id, "pools": {},
            "doc_notes": {"mined_revoked": list(mined)}}


def test_parse_page_mines_named_revoked_sponsor():
    _, _, notes = _note_page("Reason: Revoked sponsor: SPN-5417.")
    assert notes.get("mined_revoked") == ["SPN-5417"]


def test_ocr_digit_garbles_normalize():
    _, _, notes = _note_page("Reason: Revoked sponsor: SPN-5OlB.")
    assert notes.get("mined_revoked") == ["SPN-5018"]


def test_watermarked_note_never_mines():
    lines = ["Manual Adjudicator Note", "SAMPLE DENIAL",
             "Reason: Revoked sponsor: SPN-5417."]
    _, _, notes = parse_page([(t, 0.97) for t in lines])
    assert not notes.get("mined_revoked")


def test_two_occurrence_acceptance():
    single = [_state("MIB-000001", ["SPN-5417"])]
    assert mine_note_parameters(single) == frozenset()
    double = [_state("MIB-000001", ["SPN-5417"]),
              _state("MIB-000002", ["SPN-5417"])]
    assert mine_note_parameters(double) == frozenset({"SPN-5417"})
    # two views of one case also clear the bar
    one_case_two_views = [_state("MIB-000001", ["SPN-5417", "SPN-5417"])]
    assert mine_note_parameters(one_case_two_views) == frozenset({"SPN-5417"})


def test_static_revoked_ids_stay_out_of_the_batch_set():
    # Public-corpus behavior: every mined id is already static -> dev-neutral.
    states = [_state("MIB-000001", ["SPN-0007"]),
              _state("MIB-000002", ["SPN-0007"])]
    assert mine_note_parameters(states) == frozenset()


def test_batch_frequent_sponsors_unions_mined_below_size_gate():
    states = [_state(f"MIB-0000{i:02d}", ["SPN-5417"]) for i in range(2)]
    assert batch_frequent_sponsors(states) == frozenset({"SPN-5417"})
