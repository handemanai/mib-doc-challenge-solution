"""Golden tests for the wave-5 rules: hard-embargo worlds, strikethrough
cancellation, registry-status approval blocker, batch-frequency sponsor
signature, unicode sanitization, damaged-label note verdicts."""
import fitz
import pytest

from mib import extract, parse_ocr, rules
from mib.forensics import (classify_spans, sanitize_text, struck_value_sets,
                           struck_values)
from mib.pipeline import (FALLBACKS, TEXT_SOURCE_RANK,
                          _composited_rank1_attestation,
                          _rank1_strike_alias_attestation,
                          _retained_baseline_context_candidate,
                          _select_baseline_supported_candidate,
                          _tag_rank1_view, batch_frequent_sponsors, decide)


def _fields(**over):
    f = dict(FALLBACKS)
    f.update(over)
    return f


# --------------------------------------- baseline-context producer confidence
@pytest.mark.parametrize(("field", "line", "confidence", "raw"), [
    ("sponsor_id", "Sponsor ID: SPN-1234", 95.0, "SPN-1234"),
    ("sponsor_id", "Sponzor ID: SPN-1234", 90.0, "SPN-1234"),
    ("sponsor_id", "nsor ID:SPN-1234", 87.0, "SPN-1234"),
    ("arrival_date", "Arrival Date: 2026-05-01", 95.0, "2026-05-01"),
    ("arrival_date", "Arrivol Date: 2026-05-01", 90.0, "2026-05-01"),
    ("arrival_date", "val Date:2026-05-01", 87.0, "2026-05-01"),
    ("arrival_date", "Arrival Date: 20260501", 80.0, "20260501"),
    ("arrival_date", "Arrivol Date: 20260501", 75.0, "20260501"),
    ("arrival_date", "val Date:20260501", 72.0, "20260501"),
    ("visa_class", "Visa Class: XW-1", 100.0, "XW-1"),
    ("visa_class", "Vlsa Class: XW-1", 95.0, "XW-1"),
    ("visa_class", "a Class:XW-1", 92.0, "XW-1"),
    ("visa_class", "a Class:XW-Z", 67.0, "XW-Z"),
])
def test_context_confidence_fixture_is_produced_by_real_labeled_parser(
        field, line, confidence, raw):
    parsed = parse_ocr.parse_page([
        ("FORM I-8090 Extraterrestrial Work Authorization", 0.99),
        (line, 0.99),
    ])
    candidates, _ = parse_ocr.merge_candidates([parsed])
    value, source, rank, score, observed_raw = candidates[field][0]
    assert source == "intake" and rank == 2
    assert score == confidence and observed_raw == raw
    assert value in {"SPN-1234", "2026-05-01", "XW-1"}


@pytest.mark.parametrize(("line", "field", "confidence", "raw"), [
    ("2026-05-01", "arrival_date", 70.0, "2026-05-01"),
    ("20260501", "arrival_date", 65.0, "20260501"),
    ("SPN-1234", "sponsor_id", 70.0, "SPN-1234"),
    ("XW-1", "visa_class", 66.0, "XW-1"),
])
def test_context_confidence_fixture_is_produced_by_real_bare_parser(
        line, field, confidence, raw):
    parsed = parse_ocr.parse_page([("unrecognized page", 0.99),
                                   (line, 0.99)])
    candidates, _ = parse_ocr.merge_candidates([parsed])
    value, source, rank, score, observed_raw = candidates[field][0]
    assert source == "unknown_bare" and rank == 6
    assert score == confidence and observed_raw == raw


def test_visible_context_sources_are_fixed_95_with_canonical_raw():
    ordinary = extract.extract_from_visible_text("MIB-000001", [
        "Arrival date: 2026-05-01\nVisa class: XW-1",
    ])
    letter = extract.extract_from_visible_text("MIB-000001", [
        "attests\nArrival date: 2026-05-01\nVisa class: XW-1",
    ])
    assert ordinary == {
        "visa_class": ("XW-1", "slip_label"),
        "arrival_date": ("2026-05-01", "slip_label"),
    }
    assert letter == {
        "visa_class": ("XW-1", "letter_label"),
        "arrival_date": ("2026-05-01", "letter_label"),
    }
    for fields in (ordinary, letter):
        for field, (value, source) in fields.items():
            record = [value, source, TEXT_SOURCE_RANK[source], 95.0, value]
            if field == "visa_class":
                expected = list(record)
                if source == "letter_label":
                    expected[2] = 2
                assert _retained_baseline_context_candidate(
                    field, [record], []) == expected
            else:
                assert record == [
                    "2026-05-01", source, TEXT_SOURCE_RANK[source],
                    95.0, "2026-05-01"]


def _merged_candidates(field, *pages):
    parsed = [parse_ocr.parse_page(page) for page in pages]
    return [list(candidate) for candidate in
            parse_ocr.merge_candidates(parsed)[0][field]]


def test_context_support_raises_confidence_without_rewriting_provenance():
    sponsor = _merged_candidates(
        "sponsor_id",
        [("MIB Fee Receipt", 0.99), ("nsor ID:SPN-1234", 0.99)],
        [("Planetary Registry Extract", 0.99),
         ("Sponsor ID: SPN-1234", 0.99)],
    )
    retained = _retained_baseline_context_candidate(
        "sponsor_id", sponsor, [])
    assert retained == [
        "SPN-1234", "fee_receipt", 2, 95.0, "SPN-1234"]

    visible = extract.extract_from_visible_text("MIB-000001", [
        "Visa class: XW-1",
    ])["visa_class"]
    visa = [[visible[0], visible[1], 3, 95.0, visible[0]]]
    visa.extend(_merged_candidates(
        "visa_class",
        [("Planetary Registry Extract", 0.99),
         ("Visa Class: XW-1", 0.99)],
    ))
    retained = _retained_baseline_context_candidate(
        "visa_class", visa, [])
    assert retained == ["XW-1", "slip_label", 3, 100.0, "XW-1"]


def test_selected_bare_confidence_stays_fixed_or_source_changes():
    bare_pages = (
        [("FORM I-8090 Extraterrestrial Work Authorization", 0.99),
         ("SPN-1234", 0.99)],
        [("Planetary Registry Extract", 0.99), ("SPN-1234", 0.99)],
    )
    bare = _merged_candidates("sponsor_id", *bare_pages)
    retained = _retained_baseline_context_candidate(
        "sponsor_id", bare, [])
    assert retained[1].endswith("_bare") and retained[3] == 70.0

    labeled = _merged_candidates(
        "sponsor_id",
        [("Planetary Registry Extract", 0.99),
         ("Sponsor ID: SPN-1234", 0.99)],
    )
    retained = _retained_baseline_context_candidate(
        "sponsor_id", bare + labeled, [])
    assert retained == [
        "SPN-1234", "registry", 5, 95.0, "SPN-1234"]


def test_real_signed_correction_has_explicit_context_authority():
    conflicting = parse_ocr.parse_page([
        ("Manual Adjudicator Note", 0.99),
        ("Visa Class: XW-1", 0.99),
        ("Manual correction: visa class is DIP-1", 0.99),
    ])
    candidates, notes = parse_ocr.merge_candidates([conflicting])
    signed = [notes["corrections"]["visa_class"]]
    retained = _retained_baseline_context_candidate(
        "visa_class", [list(c) for c in candidates["visa_class"]], signed)
    assert retained == ["DIP-1", "manual_correction", 1, 99.0, "DIP-1"]

    agreeing = parse_ocr.parse_page([
        ("Manual Adjudicator Note", 0.99),
        ("Visa Class: DIP-1", 0.99),
        ("Manual correction: visa class is DIP-1", 0.99),
    ])
    candidates, notes = parse_ocr.merge_candidates([agreeing])
    retained = _retained_baseline_context_candidate(
        "visa_class", [list(c) for c in candidates["visa_class"]],
        [notes["corrections"]["visa_class"]])
    assert retained == ["DIP-1", "manual_correction", 1, 100.0, "DIP-1"]
    assert _retained_baseline_context_candidate(
        "visa_class", [], ["DIP-1", "XW-1"]) is None


# ---------------------------------------------------------------- rules layer
def test_hard_embargo_world_denies_even_dip1():
    for world in ("Eris Relay", "TRAPPIST-1e"):
        for visa in ("DIP-1", "XW-1"):
            decision, reasons = rules.adjudicate(
                _fields(home_world=world, visa_class=visa))
            assert decision == "DENIED" and "embargoed_world" in reasons


def test_soft_embargo_still_dip1_exempt():
    decision, _ = rules.adjudicate(
        _fields(home_world="Wolf-1061c", visa_class="DIP-1"))
    assert decision == "APPROVED"


# --------------------------------------------------------- strikethrough layer
def _strike_doc(text, strike_color=(1, 0, 0), *, text_kwargs=None,
                strike_kwargs=None, x=100, occlude=False):
    doc = fitz.open()
    page = doc.new_page(width=612, height=792)
    page.insert_text((x, 100), text, fontsize=11, **(text_kwargs or {}))
    words = page.get_text("words")
    assert words
    x0, y0, x1, y1 = words[-1][:4]
    if occlude:
        page.draw_rect(
            fitz.Rect(x0 - 2, y0 - 2, x1 + 2, y1 + 2),
            color=None, fill=(1, 1, 1), fill_opacity=1.0, overlay=True)
    yc = (y0 + y1) / 2
    page.draw_line(fitz.Point(x0 - 2, yc), fitz.Point(x1 + 2, yc),
                   color=strike_color, width=1, **(strike_kwargs or {}))
    return doc


def _struck(doc):
    visible, _ = classify_spans(doc)
    return struck_values(doc, visible)


def _strike_sets(doc):
    visible, _ = classify_spans(doc)
    return struck_value_sets(doc, visible)


def test_struck_word_detected():
    assert "unpaid" in _struck(_strike_doc("Fee Status: unpaid"))


def test_gray_line_not_a_strike():
    assert _struck(_strike_doc("Fee Status: unpaid",
                               strike_color=(0.5, 0.5, 0.5))) == set()


@pytest.mark.parametrize("stroke_opacity", [0.0, 0.05])
def test_nonvisible_line_cannot_supply_strike_evidence(stroke_opacity):
    assert _struck(_strike_doc(
        "Fee Status: unpaid",
        strike_kwargs={"stroke_opacity": stroke_opacity})) == set()


@pytest.mark.parametrize("text_kwargs", [
    {"color": (1, 1, 1)},
    {"fill_opacity": 0.0},
    {"fill_opacity": 0.05},
    {"render_mode": 3},
])
def test_nonvisible_word_cannot_supply_strike_evidence(text_kwargs):
    assert _struck(_strike_doc(
        "Fee Status: unpaid", text_kwargs=text_kwargs)) == set()


def test_partially_offcrop_word_cannot_supply_strike_evidence():
    assert _struck(_strike_doc("unpaid", x=-10)) == set()


def test_occluded_word_cannot_supply_strike_evidence():
    assert _struck(_strike_doc(
        "Fee Status: unpaid", occlude=True)) == set()


@pytest.mark.parametrize("cross_page", [False, True])
def test_unstruck_visible_duplicate_prevents_global_cancellation(cross_page):
    doc = _strike_doc("unpaid")
    page = doc.new_page(width=612, height=792) if cross_page else doc[0]
    page.insert_text((100, 140), "unpaid", fontsize=11)
    assert _struck(doc) == set()


def test_struck_deny_trigger_never_denies():
    state = {
        "case_id": "MIB-000001",
        "pools": {"fee_status": [["unpaid", "fee_receipt", 2, 100.0, "unpaid"]],
                  "visa_class": [["XW-1", "intake", 2, 95.0, "XW-1"]]},
        "doc_notes": {}, "injection": {}, "mean_ocr_conf": 0.9,
        "struck_values": ["unpaid"],
    }
    pred, detail = decide(state)
    assert pred["adjudication"] != "DENIED"
    assert "unpaid_fee" not in detail["reasons"]


def test_strike_cancellation_cannot_promote_ordinary_denial_to_approval():
    state = _approval_state()
    state["pools"]["risk_flags"] = [
        ["biohazard_red", "biometric", 3, 95.0, "biohazard_red"],
        ["none", "registry", 5, 95.0, "none"],
    ]
    state["struck_values"] = ["biohazard_red"]

    prediction, detail = decide(state)
    assert prediction["adjudication"] == "NEEDS_REVIEW"
    assert detail["reasons"] == ["strike_cancellation_guard"]


@pytest.mark.parametrize(("field", "blocked", "clean", "batch_revoked"), [
    ("fee_status", "unpaid", "paid", frozenset()),
    ("fee_status", "unknown", "paid", frozenset()),
    ("fee_status", "waived", "paid", frozenset()),
    ("visa_class", "TRANSIT-7", "XW-1", frozenset()),
    ("home_world", "Eris Relay", "Luyten-b", frozenset()),
    ("home_world", "Wolf-1061c", "Luyten-b", frozenset()),
    ("sponsor_id", "SPN-0007", "SPN-5678", frozenset()),
    ("sponsor_id", "SPN-8888", "SPN-5678", frozenset({"SPN-8888"})),
    ("arrival_date", "2025-01-01", "2026-06-01", frozenset()),
    ("risk_flags", "identity_conflict|none", "none", frozenset()),
])
def test_action_bearing_strike_cannot_open_approval(
        field, blocked, clean, batch_revoked):
    state = _approval_state()
    state["pools"][field] = [
        [blocked, "intake", 2, 95.0, blocked],
        [clean, "registry", 5, 95.0, clean],
    ]
    state["struck_values"] = [blocked.lower()]

    prediction, detail = decide(state, batch_revoked=batch_revoked)
    assert prediction["adjudication"] == "NEEDS_REVIEW"
    assert prediction["confidence"] == 0.15
    assert detail["reasons"] == ["strike_cancellation_guard"]


def test_benign_name_strike_does_not_demote_clean_approval():
    state = _approval_state()
    state["pools"]["applicant_name"] = [
        ["Ari Vale", "intake", 2, 95.0, "Ari Vale"],
        ["Tekdane Ixovara", "registry", 5, 95.0, "Tekdane Ixovara"],
    ]
    state["struck_values"] = ["ari"]
    prediction, detail = decide(state)
    assert prediction["adjudication"] == "APPROVED"
    assert detail["reasons"] == ["clean"]


@pytest.mark.parametrize("reconciled_field", ["fee_status", "applicant_name"])
def test_only_matching_composited_correction_reconciles_action_strike(
        reconciled_field):
    state = _approval_state()
    state["pools"]["fee_status"] = [
        ["unpaid", "fee_receipt", 2, 95.0, "unpaid"],
        ["paid", "registry", 5, 95.0, "paid"],
    ]
    state["struck_values"] = ["unpaid"]
    value = "paid" if reconciled_field == "fee_status" else "Tekdane Ixovara"
    state["doc_notes"]["corrections"] = {reconciled_field: value}
    state["composited_rank1_payload"] = _composited_values(
        **{reconciled_field: value})

    prediction, detail = decide(state)
    expected = "APPROVED" if reconciled_field == "fee_status" else "NEEDS_REVIEW"
    assert prediction["adjudication"] == expected
    assert detail["reasons"] == [
        "clean" if expected == "APPROVED" else "strike_cancellation_guard"]


def test_explicit_composited_rank1_approval_retains_precedence_over_strike():
    state = _approval_state()
    state["pools"]["fee_status"] = [
        ["unpaid", "fee_receipt", 2, 95.0, "unpaid"],
        ["paid", "registry", 5, 95.0, "paid"],
    ]
    state["struck_values"] = ["unpaid"]
    state["doc_notes"] = {
        "finding": "APPROVED",
        "finding_authority_origin": {"view": "masked_pdf_render"},
    }
    prediction, detail = decide(state)
    assert prediction["adjudication"] == "APPROVED"
    assert detail["reasons"] == ["adjudicator_note"]


def test_recovered_approval_cannot_bypass_action_strike_guard(monkeypatch):
    monkeypatch.setenv("MIB_NOTE_ROI_APPROVE", "1")
    state = _approval_state()
    state["pools"]["fee_status"] = [
        ["unpaid", "fee_receipt", 2, 95.0, "unpaid"],
        ["paid", "registry", 5, 95.0, "paid"],
    ]
    state["struck_values"] = ["unpaid"]
    state["doc_notes"].update({
        "registry_embargo": True,
        "recovered_finding": "APPROVED",
    })
    prediction, detail = decide(state)
    assert prediction["adjudication"] == "NEEDS_REVIEW"
    assert detail["reasons"] == ["strike_cancellation_guard"]


def test_local_struck_finding_cannot_hide_behind_unstruck_duplicate():
    doc = _strike_doc("Finding: APPROVED")
    duplicate_page = doc.new_page(width=612, height=792)
    duplicate_page.insert_text((100, 100), "APPROVED", fontsize=11)
    global_values, authority_values = _strike_sets(doc)
    assert "approved" not in global_values
    assert "approved" in authority_values

    state = _approval_state()
    state["pools"]["risk_flags"] = [[
        "active_warrant", "biometric", 3, 95.0, "active_warrant"]]
    state["struck_values"] = sorted(global_values)
    state["struck_authority_values"] = sorted(authority_values)
    state["doc_notes"] = {
        "finding": "APPROVED",
        "finding_authority_origin": {"view": "masked_pdf_render"},
    }
    state["composited_rank1_payload"] = _composited_values(
        finding="APPROVED")
    prediction, detail = decide(state)
    assert prediction["adjudication"] == "DENIED"
    assert detail["reasons"] == ["disqualifying_flag"]
    assert detail["finding_note"] is None


def _local_duplicate_strike_sets(value):
    doc = _strike_doc(value)
    duplicate_page = doc.new_page(width=612, height=792)
    duplicate_page.insert_text((100, 100), value, fontsize=11)
    return _strike_sets(doc)


def _parsed_rank1_authority(line):
    parsed = parse_ocr.parse_page([
        ("Manual Adjudicator Note", 0.99),
        ("Case: MIB-000002", 0.99),
        (line, 0.99),
    ])
    _, doc_notes = parse_ocr.merge_candidates([parsed])
    view = _tag_rank1_view(parsed, {
        "page": 0, "view": "masked_pdf_render",
        "dpi": 150, "pass": "fast",
    })
    if doc_notes.get("finding"):
        doc_notes["finding_authority_origin"] = {
            "view": "masked_pdf_render"}
    return (
        doc_notes,
        _composited_rank1_attestation([view]),
        _rank1_strike_alias_attestation([view]),
    )


@pytest.mark.parametrize("line", [
    "Finding: NOT APPROVED",
    "Finding: NO APPROVED",
    "Finding: NEVER APPROVED",
    "Finding: UNAPPROVED",
    "Finding: UN-APPROVED",
    "Finding: NOAPPROVED",
])
def test_negated_finding_never_acquires_approval_authority(line):
    parsed = parse_ocr.parse_page([
        ("Manual Adjudicator Note", 0.99), (line, 0.99)])
    assert parsed[2]["finding"] is None
    assert parsed[2]["_rank1_aliases"] == []


@pytest.mark.parametrize(("field", "raw"), [
    ("fee_status", "not paid"),
    ("fee_status", "nonpaid"),
    ("visa_class", "NOT-DIP-1"),
    ("sponsor_id", "not SPN-0678"),
    ("home_world", "not Luyten-b"),
])
def test_semantic_negation_never_snaps_to_ordinary_approval_evidence(
        field, raw):
    assert parse_ocr._snap_value(field, raw) == (None, 0.0)


@pytest.mark.parametrize("line", [
    "Manual correction: fee status is not paid",
    "Manual correction: fee status is never paid",
    "Manual correction: visa class is no DIP-1",
    "Manual correction: sponsor is not SPN-0678",
])
def test_negated_manual_correction_never_acquires_authority(line):
    parsed = parse_ocr.parse_page([
        ("Manual Adjudicator Note", 0.99), (line, 0.99)])
    assert parsed[2]["corrections"] == {}


def test_negated_visible_visa_never_creates_dip1_exemption():
    assert extract.extract_from_visible_text(
        "MIB-000002", ["Visa class: NOT-DIP-1"],
        include_raw=True) == {}


@pytest.mark.parametrize(("raw", "line", "field", "canonical"), [
    ("APPROVE0", "Finding: APPROVE0", "finding", "APPROVED"),
    ("APPROV-0", "Finding: APPROV-0", "finding", "APPROVED"),
    ("APPR0V-ED", "Finding: APPR0V-ED", "finding", "APPROVED"),
    ("pald", "Manual correction: fee status is pald",
     "fee_status", "paid"),
    ("pa1d", "Manual correction: fee status is pa1d",
     "fee_status", "paid"),
    ("D1P-1", "Manual correction: visa class is D1P-1",
     "visa_class", "DIP-1"),
    ("DIP-l", "Manual correction: visa class is DIP-l",
     "visa_class", "DIP-1"),
    ("SPN-O678", "Manual correction: sponsor is SPN-O678",
     "sponsor_id", "SPN-0678"),
])
def test_crossed_rank1_ocr_alias_cannot_override_adverse_ordinary_evidence(
        raw, line, field, canonical):
    global_values, authority_values = _local_duplicate_strike_sets(raw)
    assert raw.lower() not in global_values
    assert raw.lower() in authority_values

    notes, payload, aliases = _parsed_rank1_authority(line)
    assert payload["values"][field] == [canonical]
    assert aliases == [{
        "field": field, "raw": raw.lower(), "value": canonical,
        "origin": {"page": 0, "view": "masked_pdf_render",
                   "dpi": 150, "pass": "fast"},
    }]

    state = _approval_state()
    if field == "finding":
        state["pools"]["risk_flags"] = [[
            "active_warrant", "biometric", 3, 95.0, "active_warrant"]]
    elif field == "fee_status":
        state["pools"]["fee_status"] = [[
            "unpaid", "fee_receipt", 2, 95.0, "unpaid"]]
    elif field == "visa_class":
        state["pools"]["home_world"] = [[
            "Wolf-1061c", "registry", 5, 95.0, "Wolf-1061c"]]
        state["pools"]["visa_class"] = [[
            "XW-1", "intake", 2, 95.0, "XW-1"]]
    else:
        state["pools"]["sponsor_id"] = [[
            "SPN-0007", "sponsor_letter", 4, 95.0, "SPN-0007"]]
    state["struck_values"] = sorted(global_values)
    state["struck_authority_values"] = sorted(authority_values)
    state["doc_notes"] = notes
    state["composited_rank1_payload"] = payload
    state["rank1_strike_aliases"] = aliases

    prediction, detail = decide(state)
    assert prediction["adjudication"] == "DENIED"
    assert canonical not in {
        value for values in detail["composited_rank1_payload"][
            "values"].values() for value in values}


@pytest.mark.parametrize(("struck_raw", "line", "field", "canonical"), [
    ("O678", "Manual correction: sponsor is SPN - O678",
     "sponsor_id", "SPN-0678"),
    ("l", "Manual correction: visa class is DIP- l",
     "visa_class", "DIP-1"),
    ("0", "Finding: APPROVE 0", "finding", "APPROVED"),
])
def test_crossed_rank1_fragmented_alias_cannot_open_approval(
        struck_raw, line, field, canonical):
    global_values, authority_values = _local_duplicate_strike_sets(struck_raw)
    notes, payload, aliases = _parsed_rank1_authority(line)
    assert payload["values"][field] == [canonical]
    assert any(record["raw"] == struck_raw.lower()
               and record["field"] == field
               and record["value"] == canonical for record in aliases)

    state = _approval_state()
    if field == "sponsor_id":
        state["pools"][field] = [[
            "SPN-0007", "sponsor_letter", 4, 95.0, "SPN-0007"]]
    elif field == "visa_class":
        state["pools"]["home_world"] = [[
            "Wolf-1061c", "registry", 5, 95.0, "Wolf-1061c"]]
        state["pools"][field] = [[
            "XW-1", "intake", 2, 95.0, "XW-1"]]
    else:
        state["pools"]["risk_flags"] = [[
            "active_warrant", "biometric", 3, 95.0, "active_warrant"]]
    state["struck_values"] = sorted(global_values)
    state["struck_authority_values"] = sorted(authority_values)
    state["doc_notes"] = notes
    state["composited_rank1_payload"] = payload
    state["rank1_strike_aliases"] = aliases

    prediction, _ = decide(state)
    assert prediction["adjudication"] == "DENIED"


@pytest.mark.parametrize(("raw", "line", "field"), [
    ("DIP/1", "Manual correction: visa class is DIP/1", "visa_class"),
    ("pa/id", "Manual correction: fee status is pa/id", "fee_status"),
])
def test_detector_unsupported_slash_alias_never_acquires_rank1_authority(
        raw, line, field):
    # A full-word strike covers every lexical component, but slash-garbled
    # approval-side corrections remain outside the legal signed grammar.
    global_values, authority_values = _strike_sets(_strike_doc(raw))
    assert global_values == authority_values
    assert len(global_values) == 2
    notes, payload, aliases = _parsed_rank1_authority(line)
    assert field not in notes.get("corrections", {})
    assert field not in payload["values"]
    assert aliases == []

    state = _approval_state()
    if field == "visa_class":
        state["pools"]["home_world"] = [[
            "Wolf-1061c", "registry", 5, 95.0, "Wolf-1061c"]]
        state["pools"]["visa_class"] = [[
            "XW-1", "intake", 2, 95.0, "XW-1"]]
    else:
        state["pools"]["fee_status"] = [[
            "unpaid", "fee_receipt", 2, 95.0, "unpaid"]]
    state["doc_notes"] = notes
    state["composited_rank1_payload"] = payload
    state["rank1_strike_aliases"] = aliases

    prediction, _ = decide(state)
    assert prediction["adjudication"] == "DENIED"


def test_crossed_visible_text_alias_retains_raw_and_cannot_create_dip1():
    text_fields = extract.extract_from_visible_text(
        "MIB-000002", ["Visa class: DIP-l"], include_raw=True)
    assert text_fields["visa_class"] == ("DIP-1", "slip_label", "DIP-l")
    global_values, authority_values = _strike_sets(
        _strike_doc("Visa class: DIP-l"))

    state = _approval_state()
    state["struck_values"] = sorted(global_values)
    state["struck_authority_values"] = sorted(authority_values)
    value, source, raw = text_fields["visa_class"]
    state["pools"]["visa_class"] = [[
        value, source, TEXT_SOURCE_RANK[source], 95.0, raw]]
    state["pools"]["home_world"] = [[
        "Wolf-1061c", "registry", 5, 95.0, "Wolf-1061c"]]

    prediction, _ = decide(state)
    assert prediction["adjudication"] == "DENIED"


def test_crossed_visible_text_fragment_retains_suffix_provenance():
    text_fields = extract.extract_from_visible_text(
        "MIB-000002", ["Visa class: DIP- l"], include_raw=True)
    assert text_fields["visa_class"] == ("DIP-1", "slip_label", "DIP- l")
    global_values, authority_values = _strike_sets(_strike_doc("l"))
    state = _approval_state()
    state["struck_values"] = sorted(global_values)
    state["struck_authority_values"] = sorted(authority_values)
    value, source, raw = text_fields["visa_class"]
    state["pools"]["visa_class"] = [[
        value, source, TEXT_SOURCE_RANK[source], 95.0, raw]]
    state["pools"]["home_world"] = [[
        "Wolf-1061c", "registry", 5, 95.0, "Wolf-1061c"]]
    assert decide(state)[0]["adjudication"] == "DENIED"


def test_crossed_paid_amount_cannot_supply_fee_approval_evidence():
    global_values, authority_values = _strike_sets(_strike_doc("$809.00"))
    assert global_values == authority_values == {"809", "00"}
    parsed = parse_ocr.parse_page([
        ("MIB Fee Receipt", 0.99), ("Total: $809.00", 0.99)])
    assert parsed[1]["fee_status"] == ("paid", 90.0, "$809.00")

    state = _approval_state()
    state["struck_values"] = sorted(global_values)
    state["struck_authority_values"] = sorted(authority_values)
    state["pools"]["fee_status"] = [[
        "paid", "fee_receipt", 2, 90.0, "$809.00"]]
    prediction, _ = decide(state)
    assert prediction["adjudication"] == "NEEDS_REVIEW"


def test_canonical_only_fee_reader_cannot_bypass_matching_raw_alias_strike():
    global_values, authority_values = _strike_sets(_strike_doc("pald"))
    state = _approval_state()
    state["struck_values"] = sorted(global_values)
    state["struck_authority_values"] = sorted(authority_values)
    state["pools"]["fee_status"] = [[
        "paid", "fee_roi", 5, 95.0, "paid"]]

    prediction, detail = decide(state)
    assert prediction["adjudication"] == "NEEDS_REVIEW"
    assert detail["reasons"] == ["insufficient_evidence:1"]


@pytest.mark.parametrize(("field", "blocked", "clean"), [
    ("fee_status", "unpaid", "paid"),
    ("visa_class", "TRANSIT-7", "XW-1"),
    ("sponsor_id", "SPN-0007", "SPN-0678"),
    ("risk_flags", "active_warrant", "none"),
])
def test_local_strike_filters_generic_rank1_pool_candidate(
        field, blocked, clean):
    global_values, authority_values = _local_duplicate_strike_sets(clean)
    state = _approval_state()
    state["struck_values"] = sorted(global_values)
    state["struck_authority_values"] = sorted(authority_values)
    state["pools"][field] = [
        [clean, "adjudicator_note", 1, 95.0, clean],
        [blocked, "fee_receipt" if field == "fee_status" else "intake",
         2, 95.0, blocked],
    ]

    prediction, _ = decide(state)
    assert prediction["adjudication"] == "DENIED"


def test_fully_struck_exact_rank1_pool_value_keeps_global_cancellation_rules():
    global_values, authority_values = _strike_sets(_strike_doc("unpaid"))
    assert global_values == authority_values == {"unpaid"}
    state = _approval_state()
    state["struck_values"] = sorted(global_values)
    state["struck_authority_values"] = sorted(authority_values)
    state["pools"]["fee_status"] = [
        ["unpaid", "adjudicator_note", 1, 95.0, "unpaid"],
        ["paid", "fee_receipt", 2, 95.0, "paid"],
    ]
    state["doc_notes"] = {
        "finding": "APPROVED",
        "finding_authority_origin": {"view": "masked_pdf_render"},
    }
    state["composited_rank1_payload"] = _composited_values(
        finding="APPROVED")

    prediction, detail = decide(state)
    assert prediction["adjudication"] == "APPROVED"
    assert detail["reasons"] == ["adjudicator_note"]


def test_struck_alias_taint_cannot_be_reintroduced_by_canonical_paid_reader():
    global_values, authority_values = _local_duplicate_strike_sets("pald")
    state = _approval_state()
    state["struck_values"] = sorted(global_values)
    state["struck_authority_values"] = sorted(authority_values)
    state["pools"]["fee_status"] = [
        ["paid", "adjudicator_note", 1, 95.0, "pald"],
        ["paid", "fee_roi", 5, 95.0, "paid"],
        ["unpaid", "fee_receipt", 2, 95.0, "unpaid"],
    ]

    prediction, detail = decide(state)
    assert prediction["fee_status"] == "unpaid"
    assert prediction["adjudication"] == "DENIED"
    assert detail["reasons"] == ["unpaid_fee"]


def test_local_struck_denial_cannot_erase_unstruck_adverse_authority():
    global_values, authority_values = _local_duplicate_strike_sets(
        "Finding: DENIED")
    assert "denied" not in global_values
    assert "denied" in authority_values

    state = _approval_state()
    state["struck_values"] = sorted(global_values)
    state["struck_authority_values"] = sorted(authority_values)
    state["doc_notes"] = {
        "finding": "DENIED",
        "finding_authority_origin": {"view": "masked_pdf_render"},
    }
    state["composited_rank1_payload"] = _composited_values(
        finding="DENIED")

    prediction, detail = decide(state)
    assert prediction["adjudication"] == "NEEDS_REVIEW"
    assert detail["reasons"] == ["strike_cancellation_guard"]
    assert detail["finding_note"] is None


def test_fully_struck_denial_keeps_unambiguous_cancellation_behavior():
    global_values, authority_values = _strike_sets(
        _strike_doc("Finding: DENIED"))
    assert "denied" in global_values
    assert "denied" in authority_values

    state = _approval_state()
    state["struck_values"] = sorted(global_values)
    state["struck_authority_values"] = sorted(authority_values)
    state["doc_notes"] = {
        "finding": "DENIED",
        "finding_authority_origin": {"view": "masked_pdf_render"},
    }
    state["composited_rank1_payload"] = _composited_values(
        finding="DENIED")

    prediction, detail = decide(state)
    assert prediction["adjudication"] == "APPROVED"
    assert detail["reasons"] == ["clean"]
    assert detail["finding_note"] is None


@pytest.mark.parametrize(("field", "value"), [
    ("fee_status", "unpaid"),
    ("risk_flags", "active_warrant"),
    ("home_world", "Eris Relay"),
    ("visa_class", "TRANSIT-7"),
    ("sponsor_id", "SPN-0007"),
    ("arrival_date", "2025-01-01"),
])
def test_local_strike_cannot_erase_unstruck_adverse_signed_field(field, value):
    global_values, authority_values = _local_duplicate_strike_sets(value)
    assert not global_values
    assert authority_values

    state = _approval_state()
    state["struck_values"] = sorted(global_values)
    state["struck_authority_values"] = sorted(authority_values)
    state["doc_notes"]["corrections"] = {field: value}
    state["composited_rank1_payload"] = _composited_values(
        **{field: value})

    prediction, detail = decide(state)
    assert prediction["adjudication"] == "NEEDS_REVIEW"
    assert detail["reasons"] == ["strike_cancellation_guard"]


def test_surviving_paid_authority_cannot_reconcile_ambiguous_unpaid_strike():
    global_values, authority_values = _local_duplicate_strike_sets("unpaid")
    assert not global_values
    assert "unpaid" in authority_values

    state = _approval_state()
    state["struck_values"] = sorted(global_values)
    state["struck_authority_values"] = sorted(authority_values)
    state["doc_notes"]["corrections"] = {"fee_status": "paid"}
    state["composited_rank1_payload"] = {
        "values": {"fee_status": ["unpaid", "paid"]},
        "conflicts": [],
        "evidence": {"fee_status": [
            {"value": value, "origin": {
                "page": 0, "view": "masked_pdf_render",
                "dpi": 150, "pass": "fast"}}
            for value in ["unpaid", "paid"]]},
    }

    prediction, detail = decide(state)
    assert prediction["fee_status"] == "paid"
    assert prediction["adjudication"] == "NEEDS_REVIEW"
    assert detail["reasons"] == ["strike_cancellation_guard"]


def test_trusted_approval_cannot_exempt_ambiguous_adverse_finding_strike():
    global_values, authority_values = _local_duplicate_strike_sets("DENIED")
    assert not global_values
    assert "denied" in authority_values

    state = _approval_state()
    state["struck_values"] = sorted(global_values)
    state["struck_authority_values"] = sorted(authority_values)
    state["doc_notes"] = {
        "finding": "APPROVED",
        "finding_authority_origin": {"view": "masked_pdf_render"},
    }
    state["composited_rank1_payload"] = {
        "values": {"finding": ["APPROVED", "DENIED"]},
        "conflicts": [],
        "evidence": {"finding": [
            {"value": value, "origin": {
                "page": 0, "view": "masked_pdf_render",
                "dpi": 150, "pass": "fast"}}
            for value in ["APPROVED", "DENIED"]]},
    }

    prediction, detail = decide(state)
    assert detail["finding_note"] == "APPROVED"
    assert prediction["adjudication"] == "NEEDS_REVIEW"
    assert detail["reasons"] == ["strike_cancellation_guard"]


def test_struck_signed_fee_correction_cannot_override_unpaid_evidence():
    state = _approval_state()
    state["pools"]["fee_status"] = [[
        "unpaid", "fee_receipt", 2, 95.0, "unpaid"]]
    state["struck_values"] = ["paid"]
    state["doc_notes"]["corrections"] = {"fee_status": "paid"}
    state["composited_rank1_payload"] = _composited_values(
        fee_status="paid")
    prediction, detail = decide(state)
    assert prediction["fee_status"] == "unpaid"
    assert prediction["adjudication"] == "DENIED"
    assert detail["reasons"] == ["unpaid_fee"]
    assert detail["composited_rank1_payload"]["values"] == {}


def test_struck_name_correction_cannot_override_ordinary_name():
    state = _approval_state()
    state["pools"]["applicant_name"] = [[
        "Tekdane Ixovara", "intake", 2, 95.0, "Tekdane Ixovara"]]
    state["struck_values"] = ["ari"]
    state["doc_notes"]["name_correction"] = "Ari Vale"
    state["composited_rank1_payload"] = _composited_values(
        applicant_name="Ari Vale")
    prediction, detail = decide(state)
    assert prediction["applicant_name"] == "Tekdane Ixovara"
    assert prediction["adjudication"] == "APPROVED"
    assert "applicant_name" not in detail["rank1_payload"]["fields"]


@pytest.mark.parametrize("visa_class", ["XW-1", "DIP-1"])
def test_struck_waiver_code_cannot_open_fee_unread_approval(visa_class):
    control = _approval_state(candidate_visa=visa_class)
    control["pools"].pop("fee_status")
    control["doc_notes"]["waiver_code"] = "DIP-WAIVER"
    control_prediction, _ = decide(control)
    assert control_prediction["fee_status"] == "waived"
    assert control_prediction["adjudication"] == "APPROVED"

    attacked = _approval_state(candidate_visa=visa_class)
    attacked["pools"].pop("fee_status")
    attacked["doc_notes"]["waiver_code"] = "DIP-WAIVER"
    attacked["struck_values"] = ["dip-waiver"]
    prediction, detail = decide(attacked)
    assert prediction["adjudication"] == "NEEDS_REVIEW"
    assert detail["reasons"] == ["insufficient_evidence:1"]
    assert detail["waiver_code"] is None


def test_struck_recovered_approval_cannot_override_ordinary_denial(
        monkeypatch):
    monkeypatch.setenv("MIB_NOTE_ROI_APPROVE", "1")
    state = _approval_state()
    state["pools"]["risk_flags"] = [[
        "active_warrant", "biometric", 3, 95.0, "active_warrant"]]
    state["struck_values"] = ["approved"]
    state["doc_notes"]["recovered_finding"] = "APPROVED"
    prediction, detail = decide(state)
    assert prediction["adjudication"] == "DENIED"
    assert detail["reasons"] == ["disqualifying_flag"]


# ----------------------------------------------------- registry status blocker
def test_registry_embargo_blocks_approval():
    lines = [("Planetary Registry Extract", 0.99),
             ("Registry Status: EMBARGO REVIEW", 0.99)]
    ptype, _, notes = parse_ocr.parse_page(lines)
    assert ptype == "registry" and notes["registry_embargo"]


def test_registry_clear_is_not_evidence():
    lines = [("Planetary Registry Extract", 0.99),
             ("Registry Status: CLEAR", 0.99)]
    _, fields, notes = parse_ocr.parse_page(lines)
    assert not notes["registry_embargo"]
    assert "risk_flags" not in fields   # CLEAR never becomes a flags read


def test_registry_embargo_fragmented_ocr():
    lines = [("Planetary Registry Extract", 0.99),
             ("Registry Status:", 0.9), ("EMB", 0.6), ("BARGOREVIEW", 0.6)]
    _, _, notes = parse_ocr.parse_page(lines)
    assert notes["registry_embargo"]


# --------------------------------------------------- batch sponsor signature
def _sponsor_state(cid, spn):
    return {"case_id": cid,
            "pools": {"sponsor_id": [[spn, "sponsor_letter", 4, 95.0, spn]]}}


def _approval_state(candidate_sponsor="SPN-5678", candidate_visa="XW-1",
                    baseline_context=None):
    state = {
        "case_id": "MIB-000002",
        "pools": {
            "sponsor_id": [[candidate_sponsor, "sponsor_letter", 4, 95.0]],
            "risk_flags": [["none", "biometric", 3, 90.0]],
            "fee_status": [["paid", "fee_receipt", 2, 95.0]],
            "home_world": [["Luyten-b", "registry", 5, 95.0]],
            "visa_class": [[candidate_visa, "intake", 2, 95.0]],
            "arrival_date": [["2026-06-01", "intake", 2, 95.0]],
        },
        "doc_notes": {}, "injection": {}, "mean_ocr_conf": 0.9,
    }
    if baseline_context is not None:
        state["baseline_batch_context"] = baseline_context
    return state


def _composited_values(**values):
    origin = {"page": 0, "view": "masked_pdf_render",
              "dpi": 150, "pass": "fast"}
    return {
        "values": {field: [value] for field, value in values.items()},
        "conflicts": [],
        "evidence": {
            field: [{"value": value, "origin": origin}]
            for field, value in values.items()
        },
    }


def test_batch_frequent_sponsor_detected_and_blocks_approval():
    states = [_sponsor_state(f"MIB-{i:06d}", "SPN-1234") for i in range(8)]
    states += [_sponsor_state(f"MIB-1{i:05d}", f"SPN-{5000+i:04d}")
               for i in range(150)]
    frequent = batch_frequent_sponsors(states)
    assert frequent == frozenset({"SPN-1234"})

    state = {"case_id": "MIB-000002",
             "pools": {"sponsor_id": [["SPN-1234", "sponsor_letter", 4, 95.0]],
                       "risk_flags": [["none", "biometric", 3, 90.0]],
                       "fee_status": [["paid", "fee_receipt", 2, 95.0]],
                       "home_world": [["Luyten-b", "registry", 5, 95.0]],
                       "visa_class": [["XW-1", "intake", 2, 95.0]],
                       "arrival_date": [["2026-06-01", "intake", 2, 95.0]]},
             "doc_notes": {}, "injection": {}, "mean_ocr_conf": 0.9}
    pred, detail = decide(state, batch_revoked=frequent)
    assert pred["adjudication"] == "NEEDS_REVIEW"
    assert detail["reasons"] == ["batch_frequent_sponsor"]


def test_batch_sponsor_needs_scale():
    states = [_sponsor_state(f"MIB-{i:06d}", "SPN-1234") for i in range(8)]
    assert batch_frequent_sponsors(states) == frozenset()   # n<100: no signal


def test_default_off_batch_frequency_keeps_all_high_confidence_candidates():
    states = []
    for index in range(150):
        unique = f"SPN-{5000 + index:04d}"
        candidates = [[
            unique, "sponsor_letter", 4, 95.0, unique]]
        if index < 8:
            candidates.append([
                "SPN-1234", "intake", 2, 95.0, "SPN-1234"])
        states.append({
            "case_id": f"MIB-{index:06d}",
            "pools": {"sponsor_id": candidates},
        })
    assert batch_frequent_sponsors(states) == frozenset({"SPN-1234"})


def test_selected_sponsor_uses_same_value_support_confidence():
    raw = [
        ["SPN-1234", "sponsor_letter", 2, 90.0, "SPN-1234"],
        ["SPN-1234", "intake", 3, 99.0, "SPN-1234"],
    ]
    collapsed, _, ambiguous = _select_baseline_supported_candidate(
        "sponsor_id", raw)
    assert collapsed[:4] == ["SPN-1234", "sponsor_letter", 2, 99.0]
    assert ambiguous is False
    states = []
    for index in range(150):
        sponsor = "SPN-1234" if index < 8 else f"SPN-{5000 + index:04d}"
        context = [list(collapsed)] if index < 8 else [[
            sponsor, "sponsor_letter", 2, 95.0, sponsor]]
        states.append({
            "case_id": f"MIB-{index:06d}", "pools": {},
            "baseline_batch_context": {"sponsor_id": context},
        })
    assert batch_frequent_sponsors(states) == frozenset({"SPN-1234"})


def test_different_value_confidence_does_not_support_selected_sponsor():
    states = []
    for index in range(150):
        selected = "SPN-1234" if index < 8 else f"SPN-{5000 + index:04d}"
        context = [[
            selected, "sponsor_letter", 2, 90.0 if index < 8 else 95.0,
            selected]]
        if index < 8:
            context.append([
                "SPN-5678", "intake", 3, 99.0, "SPN-5678"])
        states.append({
            "case_id": f"MIB-{index:06d}", "pools": {},
            "baseline_batch_context": {"sponsor_id": context},
        })
    assert batch_frequent_sponsors(states) == frozenset()


@pytest.mark.parametrize(
    ("field", "signed_value", "ordinary_value", "ordinary_confidence",
     "expected_confidence"), [
        ("sponsor_id", "SPN-1234", "SPN-1234", 95.0, 99.0),
        ("visa_class", "DIP-1", "DIP-1", 100.0, 100.0),
        ("visa_class", "DIP-1", "XW-1", 100.0, 99.0),
    ])
def test_singleton_signed_rank1_context_keeps_manual_override_and_support(
        field, signed_value, ordinary_value, ordinary_confidence,
        expected_confidence):
    retained = _retained_baseline_context_candidate(field, [[
        ordinary_value, "adjudicator_note", 1, ordinary_confidence,
        ordinary_value]], [signed_value])
    assert retained == [
        signed_value, "manual_correction", 1, expected_confidence,
        signed_value]


@pytest.mark.parametrize(("field", "signed_values", "ordinary_confidence"), [
    ("sponsor_id", ["SPN-1234", "SPN-5678"], 95.0),
    ("visa_class", ["DIP-1", "XW-1"], 100.0),
])
def test_conflicting_signed_rank1_context_omits_field(
        field, signed_values, ordinary_confidence):
    assert _retained_baseline_context_candidate(field, [[
        signed_values[0], "adjudicator_note", 1, ordinary_confidence,
        signed_values[0]]], signed_values) is None


def test_native_batch_sponsor_union_cannot_drop_composited_frequency():
    states = [_sponsor_state(f"MIB-{i:06d}", f"SPN-{5000+i:04d}")
              for i in range(150)]
    for index, state in enumerate(states):
        if index < 8:
            state["baseline_batch_context"] = {
                "sponsor_id": [[
                    "SPN-1234", "sponsor_letter", 4, 95.0, "SPN-1234"]]}
    assert batch_frequent_sponsors(states) == frozenset({"SPN-1234"})


def test_native_batch_frequency_ignores_candidate_only_sponsor_expansion():
    states = []
    for index in range(150):
        candidate = "SPN-1234" if index < 8 else f"SPN-{6000 + index:04d}"
        baseline = f"SPN-{5000 + index:04d}"
        states.append({
            "case_id": f"MIB-{index:06d}",
            "pools": {"sponsor_id": [[
                candidate, "sponsor_letter", 4, 95.0, candidate]]},
            "baseline_batch_context": {"sponsor_id": [[
                baseline, "sponsor_letter", 2, 95.0, baseline]]},
        })
    assert batch_frequent_sponsors(states) == frozenset()


def test_lower_rank_baseline_sponsor_residue_cannot_create_batch_guard():
    states = []
    for index in range(150):
        selected = f"SPN-{5000 + index:04d}"
        context = [[
            selected, "sponsor_letter", 4, 95.0, selected]]
        if index < 8:
            context.append([
                "SPN-1234", "registry", 5, 99.0, "SPN-1234"])
        states.append({
            "case_id": f"MIB-{index:06d}",
            "pools": {},
            "baseline_batch_context": {"sponsor_id": context},
        })
    assert batch_frequent_sponsors(states) == frozenset()

    state = _approval_state(baseline_context={
        "sponsor_id": [
            ["SPN-5678", "sponsor_letter", 4, 95.0, "SPN-5678"],
            ["SPN-1234", "registry", 5, 99.0, "SPN-1234"],
        ],
        "visa_class": [["XW-1", "intake", 3, 95.0, "XW-1"]],
    })
    prediction, _ = decide(
        state, batch_revoked=frozenset({"SPN-1234"}))
    assert prediction["adjudication"] == "APPROVED"


def test_tied_baseline_sponsor_is_neither_counted_nor_selected_as_guard():
    states = []
    for index in range(150):
        selected = f"SPN-{5000 + index:04d}"
        context = [[selected, "intake", 3, 95.0, selected]]
        if index < 8:
            context.append([
                "SPN-1234", "intake", 3, 95.0, "SPN-1234"])
        states.append({
            "case_id": f"MIB-{index:06d}", "pools": {},
            "baseline_batch_context": {"sponsor_id": context},
        })
    assert batch_frequent_sponsors(states) == frozenset()

    state = _approval_state(baseline_context={
        "sponsor_id": [
            ["SPN-5678", "intake", 3, 95.0, "SPN-5678"],
            ["SPN-1234", "intake", 3, 95.0, "SPN-1234"],
        ],
        "visa_class": [["XW-1", "intake", 3, 95.0, "XW-1"]],
    })
    prediction, _ = decide(
        state, batch_revoked=frozenset({"SPN-1234"}))
    assert prediction["adjudication"] == "APPROVED"


@pytest.mark.parametrize("reverse_groups", [False, True])
def test_equal_agreement_group_sponsors_are_ambiguous_in_both_orders(
        reverse_groups):
    states = []
    for index in range(150):
        unique = f"SPN-{5000 + index:04d}"
        groups = [
            [["SPN-1234", "intake", 3, 95.0, "SPN-1234"],
             ["SPN-1234", "registry", 3, 95.0, "SPN-1234"]],
            [[unique, "intake", 3, 95.0, unique],
             [unique, "registry", 3, 95.0, unique]],
        ] if index < 8 else [[
            [unique, "intake", 3, 95.0, unique]]]
        if reverse_groups:
            groups.reverse()
        states.append({
            "case_id": f"MIB-{index:06d}", "pools": {},
            "baseline_batch_context": {
                "sponsor_id": [candidate for group in groups
                               for candidate in group]},
        })
    assert batch_frequent_sponsors(states) == frozenset()


@pytest.mark.parametrize("candidate_visa", ["XW-1", "DIP-1"])
def test_native_candidate_cannot_escape_composited_batch_sponsor_guard(
        candidate_visa):
    state = _approval_state(
        candidate_visa=candidate_visa, baseline_context={
            "sponsor_id": [[
                "SPN-1234", "sponsor_letter", 4, 95.0, "SPN-1234"]],
        })
    pred, detail = decide(state, batch_revoked=frozenset({"SPN-1234"}))
    assert pred["adjudication"] == "NEEDS_REVIEW"
    assert detail["reasons"] == ["baseline_evidence_guard"]


@pytest.mark.parametrize(
    ("baseline_visa", "native_correction", "expected"), [
        ("DIP-1", None, "APPROVED"),
        ("DIP-1", "XW-1", "NEEDS_REVIEW"),
        ("XW-1", "DIP-1", "NEEDS_REVIEW"),
        ("DIP-1", "DIP-1", "APPROVED"),
    ])
def test_batch_sponsor_uses_full_correction_aware_dip1_matrix(
        baseline_visa, native_correction, expected):
    state = _approval_state(
        candidate_visa=native_correction or "XW-1", baseline_context={
            "sponsor_id": [[
                "SPN-1234", "sponsor_letter", 2, 95.0, "SPN-1234"]],
            "visa_class": [[
                baseline_visa, "intake", 3, 95.0, baseline_visa]],
        })
    if native_correction is not None:
        state["doc_notes"]["corrections"] = {
            "visa_class": native_correction}
    state["composited_rank1_payload"] = _composited_values()
    prediction, detail = decide(
        state, batch_revoked=frozenset({"SPN-1234"}))
    assert prediction["adjudication"] == expected
    if expected == "NEEDS_REVIEW":
        assert detail["reasons"] == ["baseline_evidence_guard"]


def test_baseline_dip1_exemption_survives_candidate_visa_change():
    state = _approval_state(
        candidate_visa="XW-1", baseline_context={
            "sponsor_id": [[
                "SPN-1234", "sponsor_letter", 4, 95.0, "SPN-1234"]],
            "visa_class": [["DIP-1", "sponsor_letter", 4, 95.0, "DIP-1"]],
        })
    prediction, _ = decide(
        state, batch_revoked=frozenset({"SPN-1234"}))
    assert prediction["adjudication"] == "APPROVED"


def test_baseline_non_dip_visa_blocks_candidate_dip1_exemption():
    state = _approval_state(
        candidate_visa="DIP-1", baseline_context={
            "sponsor_id": [[
                "SPN-1234", "sponsor_letter", 4, 95.0, "SPN-1234"]],
            "visa_class": [["XW-1", "intake", 3, 95.0, "XW-1"]],
        })
    prediction, detail = decide(
        state, batch_revoked=frozenset({"SPN-1234"}))
    assert prediction["adjudication"] == "NEEDS_REVIEW"
    assert detail["reasons"] == ["baseline_evidence_guard"]


def test_ambiguous_baseline_visa_cannot_invent_dip1_exemption():
    state = _approval_state(
        candidate_visa="DIP-1", baseline_context={
            "sponsor_id": [[
                "SPN-1234", "sponsor_letter", 4, 95.0, "SPN-1234"]],
            "visa_class": [
                ["DIP-1", "intake", 3, 95.0, "DIP-1"],
                ["XW-1", "intake", 3, 95.0, "XW-1"],
            ],
        })
    prediction, detail = decide(
        state, batch_revoked=frozenset({"SPN-1234"}))
    assert prediction["adjudication"] == "NEEDS_REVIEW"
    assert detail["reasons"] == ["baseline_evidence_guard"]


@pytest.mark.parametrize("reverse_groups", [False, True])
def test_equal_agreement_group_visas_are_non_exempt_in_both_orders(
        reverse_groups):
    groups = [
        [["DIP-1", "intake", 3, 95.0, "DIP-1"],
         ["DIP-1", "registry", 3, 95.0, "DIP-1"]],
        [["XW-1", "intake", 3, 95.0, "XW-1"],
         ["XW-1", "registry", 3, 95.0, "XW-1"]],
    ]
    if reverse_groups:
        groups.reverse()
    state = _approval_state(
        candidate_visa="DIP-1", baseline_context={
            "sponsor_id": [[
                "SPN-1234", "sponsor_letter", 2, 95.0, "SPN-1234"]],
            "visa_class": [candidate for group in groups
                           for candidate in group],
        })
    prediction, detail = decide(
        state, batch_revoked=frozenset({"SPN-1234"}))
    assert prediction["adjudication"] == "NEEDS_REVIEW"
    assert detail["reasons"] == ["baseline_evidence_guard"]


@pytest.mark.parametrize(
    ("baseline_sponsor", "corrected_sponsor", "expected_decision"), [
        ("SPN-1234", "SPN-5678", "APPROVED"),
        ("SPN-5678", "SPN-1234", "NEEDS_REVIEW"),
    ])
def test_composited_sponsor_correction_updates_field_and_counterfactual(
        baseline_sponsor, corrected_sponsor, expected_decision):
    state = _approval_state(baseline_context={
        "sponsor_id": [[baseline_sponsor, "intake", 3, 95.0,
                        baseline_sponsor]],
        "visa_class": [["XW-1", "intake", 3, 95.0, "XW-1"]],
    })
    state["doc_notes"]["corrections"] = {
        "sponsor_id": corrected_sponsor}
    state["composited_rank1_payload"] = _composited_values(
        sponsor_id=corrected_sponsor)
    prediction, _ = decide(
        state, batch_revoked=frozenset({"SPN-1234"}))
    assert prediction["sponsor_id"] == corrected_sponsor
    assert prediction["adjudication"] == expected_decision


@pytest.mark.parametrize(
    ("baseline_visa", "corrected_visa", "expected_decision"), [
        ("XW-1", "DIP-1", "APPROVED"),
        ("DIP-1", "XW-1", "NEEDS_REVIEW"),
    ])
def test_composited_visa_correction_updates_field_and_exemption(
        baseline_visa, corrected_visa, expected_decision):
    state = _approval_state(baseline_context={
        "sponsor_id": [[
            "SPN-1234", "intake", 3, 95.0, "SPN-1234"]],
        "visa_class": [[baseline_visa, "intake", 3, 95.0, baseline_visa]],
    })
    state["doc_notes"]["corrections"] = {"visa_class": corrected_visa}
    state["composited_rank1_payload"] = _composited_values(
        visa_class=corrected_visa)
    prediction, _ = decide(
        state, batch_revoked=frozenset({"SPN-1234"}))
    assert prediction["visa_class"] == corrected_visa
    assert prediction["adjudication"] == expected_decision


def test_candidate_only_corrections_cannot_weaken_baseline_sponsor_guard():
    state = _approval_state(baseline_context={
        "sponsor_id": [[
            "SPN-1234", "intake", 3, 95.0, "SPN-1234"]],
        "visa_class": [["XW-1", "intake", 3, 95.0, "XW-1"]],
    })
    state["doc_notes"]["corrections"] = {
        "sponsor_id": "SPN-5678", "visa_class": "DIP-1"}
    state["composited_rank1_payload"] = _composited_values()
    prediction, detail = decide(
        state, batch_revoked=frozenset({"SPN-1234"}))
    assert prediction["sponsor_id"] == "SPN-5678"
    assert prediction["visa_class"] == "DIP-1"
    assert prediction["adjudication"] == "NEEDS_REVIEW"
    assert detail["reasons"] == ["baseline_evidence_guard"]


def test_struck_baseline_dip1_falls_through_to_non_exempt_visa():
    visa_candidates = [
        ["DIP-1", "sponsor_letter", 4, 95.0, "DIP-1"],
        ["XW-1", "intake", 3, 95.0, "XW-1"],
    ]
    state = _approval_state(baseline_context={
        "sponsor_id": [[
            "SPN-1234", "intake", 3, 95.0, "SPN-1234"]],
        "visa_class": [list(candidate) for candidate in visa_candidates],
    })
    state["pools"]["visa_class"] = [
        list(candidate) for candidate in visa_candidates]
    state["struck_values"] = ["dip-1"]
    prediction, detail = decide(
        state, batch_revoked=frozenset({"SPN-1234"}))
    assert prediction["visa_class"] == "XW-1"
    assert prediction["adjudication"] == "NEEDS_REVIEW"
    assert detail["reasons"] == ["baseline_evidence_guard"]


@pytest.mark.parametrize(
    ("origin", "expected", "reason"), [
        ("native_full_page_image", "NEEDS_REVIEW",
         "native_finding_vs_baseline_guard"),
        ("masked_pdf_render", "APPROVED", "adjudicator_note"),
    ])
def test_rank1_approved_preserves_only_historical_composited_precedence(
        origin, expected, reason):
    state = _approval_state(baseline_context={
        "sponsor_id": [[
            "SPN-1234", "intake", 3, 95.0, "SPN-1234"]],
        "visa_class": [["XW-1", "intake", 3, 95.0, "XW-1"]],
    })
    state["doc_notes"].update({
        "finding": "APPROVED",
        "finding_authority_origin": {"view": origin},
    })
    prediction, detail = decide(
        state, batch_revoked=frozenset({"SPN-1234"}))
    assert prediction["adjudication"] == expected
    assert detail["reasons"] == [reason]


@pytest.mark.parametrize("blocker", [
    "baseline_adverse", "frequent_sponsor", "registry_embargo",
    "absent_arrival", "absent_sponsor",
])
@pytest.mark.parametrize("origin", [
    "native_full_page_image", "masked_pdf_render",
])
def test_post_finding_preserves_named_blockers_but_not_composited_precedence(
        blocker, origin):
    context = {
        "sponsor_id": [[
            "SPN-5678", "intake", 3, 95.0, "SPN-5678"]],
        "visa_class": [["XW-1", "intake", 3, 95.0, "XW-1"]],
    }
    state = _approval_state(
        candidate_visa="DIP-1" if blocker == "absent_sponsor" else "XW-1",
        baseline_context=context)
    state["doc_notes"].update({
        "finding": "APPROVED",
        "finding_authority_origin": {"view": origin},
    })
    batch_revoked = frozenset()
    if blocker == "baseline_adverse":
        state["doc_notes"]["baseline_approval_guards"] = [{
            "field": "fee_status", "value": "unpaid",
            "origin": "masked_pdf_render", "source": "fee_receipt",
        }]
    elif blocker == "frequent_sponsor":
        context["sponsor_id"] = [[
            "SPN-1234", "intake", 3, 95.0, "SPN-1234"]]
        batch_revoked = frozenset({"SPN-1234"})
    elif blocker == "registry_embargo":
        state["doc_notes"]["registry_embargo"] = True
    elif blocker == "absent_arrival":
        state["doc_notes"]["absent_fields"] = ["arrival_date"]
    elif blocker == "absent_sponsor":
        state["doc_notes"]["absent_fields"] = ["sponsor_id"]

    prediction, detail = decide(state, batch_revoked=batch_revoked)
    expected = "NEEDS_REVIEW" if origin == \
        "native_full_page_image" else "APPROVED"
    reason = "native_finding_vs_baseline_guard" if origin == \
        "native_full_page_image" else "adjudicator_note"
    assert prediction["adjudication"] == expected
    assert detail["reasons"] == [reason]


@pytest.mark.parametrize("generic_gate", ["insufficiency", "hidden_only"])
def test_native_finding_may_resolve_generic_non_preserved_ocr_gate(
        generic_gate):
    state = _approval_state(baseline_context={
        "sponsor_id": [[
            "SPN-5678", "intake", 3, 95.0, "SPN-5678"]],
        "visa_class": [["XW-1", "intake", 3, 95.0, "XW-1"]],
    })
    if generic_gate == "insufficiency":
        state["pools"].pop("risk_flags")
        state["pools"].pop("fee_status")
    else:
        state["pools"].pop("sponsor_id")
        state["hidden_field_mentions"] = {"sponsor": True}
    state["doc_notes"].update({
        "finding": "APPROVED",
        "finding_authority_origin": {"view": "native_full_page_image"},
    })
    prediction, detail = decide(state)
    assert prediction["adjudication"] == "APPROVED"
    assert detail["reasons"] == ["adjudicator_note"]


@pytest.mark.parametrize(
    ("baseline_visa", "native_correction", "expected"), [
        ("DIP-1", None, "APPROVED"),
        ("DIP-1", "XW-1", "NEEDS_REVIEW"),
        ("XW-1", "DIP-1", "NEEDS_REVIEW"),
        ("DIP-1", "DIP-1", "APPROVED"),
    ])
def test_absent_sponsor_uses_correction_aware_baseline_dip1_exemption(
        baseline_visa, native_correction, expected):
    state = _approval_state(
        candidate_visa=native_correction or "XW-1", baseline_context={
            "visa_class": [[
                baseline_visa, "intake", 3, 95.0, baseline_visa]],
        })
    state["doc_notes"].update({
        "finding": "APPROVED", "absent_fields": ["sponsor_id"],
        "finding_authority_origin": {"view": "native_full_page_image"},
    })
    if native_correction is not None:
        state["doc_notes"]["corrections"] = {
            "visa_class": native_correction}
    prediction, detail = decide(state)
    assert prediction["adjudication"] == expected
    reason = ("adjudicator_note" if expected == "APPROVED"
              else "native_finding_vs_baseline_guard")
    assert detail["reasons"] == [reason]


@pytest.mark.parametrize(
    ("composited_visa", "expected"), [
        ("DIP-1", "APPROVED"),
        ("XW-1", "NEEDS_REVIEW"),
    ])
def test_absent_sponsor_preserves_composited_visa_correction_authority(
        composited_visa, expected):
    state = _approval_state(baseline_context={
        "visa_class": [[composited_visa, "manual_correction", 1, 99.0,
                        composited_visa]],
    })
    state["composited_rank1_payload"] = _composited_values(
        visa_class=composited_visa)
    state["doc_notes"].update({
        "finding": "APPROVED", "absent_fields": ["sponsor_id"],
        "corrections": {"visa_class": composited_visa},
        "finding_authority_origin": {"view": "native_full_page_image"},
    })
    prediction, detail = decide(state)
    assert prediction["adjudication"] == expected
    reason = ("adjudicator_note" if expected == "APPROVED"
              else "native_finding_vs_baseline_guard")
    assert detail["reasons"] == [reason]


# ------------------------------------------------------------- sanitization
@pytest.mark.parametrize("raw,clean", [
    ("ＳＰＮ－００１２", "SPN-0012"),
    ("un​paid", "unpaid"),
    ("TRANSIT⁠-7", "TRANSIT-7"),
    ("plain", "plain"),
])
def test_sanitize_text(raw, clean):
    assert sanitize_text(raw) == clean


# ------------------------------------------------------- damaged note verdict
def test_bare_verdict_on_damaged_note_page():
    lines = [("Manual Adjudicator Note", 0.99), ("g:NEEDS_REVIEW", 0.8),
             ("Reason: arrival date missing", 0.9)]
    ptype, _, notes = parse_ocr.parse_page(lines)
    assert ptype == "adjudicator_note" and notes["finding"] == "NEEDS_REVIEW"


def test_bare_verdict_ignored_on_watermarked_page():
    lines = [("Manual Adjudicator Note", 0.99), ("SAMPLE DENIAL", 0.9),
             ("DENIED", 0.9)]
    _, _, notes = parse_ocr.parse_page(lines)
    assert notes["finding"] is None


# ------------------------------------------------------------- absent markers
@pytest.mark.parametrize("marker", [
    "[VISA CLASS TORN]", "[SPECIES WHITEOUT]", "[PURPOSE ILLEGIBLE]",
    "[REGISTRY LOST]", "[FEE STATUS OBSCURED]",
])
def test_new_absent_markers(marker):
    assert parse_ocr.ABSENT_RE.match(marker)
