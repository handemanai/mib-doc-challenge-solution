"""A born-digital text-layer 'Finding: APPROVED' must not open an approval when
the document carries an untrusted container signal (optional-content groups, or
embedded fonts without a ToUnicode map). Those vectors are absent from public
data (byte-neutral there) but can render one thing while the text layer says
another on an adversarial private packet — the injection-opens-an-approval
mechanism. The guard is distrust-direction only: DENIED/NEEDS_REVIEW findings
and non-text-layer (scanned-note) authority are unaffected.
"""

from mib import pipeline


def _state(finding="APPROVED", view="visible_text_layer", container=None):
    return {
        "case_id": "MIB-000123",
        "pools": {},
        "doc_notes": {"finding": finding,
                      "finding_authority_origin": {"view": view}},
        "injection": {},
        "struck_values": [],
        "container": container or {},
        "mean_ocr_conf": 0.9,
        "n_scan_pages": 0,
    }


def _decide(state):
    pred, detail = pipeline.decide(state)
    return pred["adjudication"], detail["reasons"]


def test_clean_container_text_layer_approval_stands():
    adj, _ = _decide(_state(container={}))
    assert adj == "APPROVED"


def test_ocg_text_layer_approval_is_hedged():
    adj, reasons = _decide(_state(container={"has_ocg": True}))
    assert adj == "NEEDS_REVIEW"
    assert reasons == ["untrusted_container_text_layer"]


def test_glyph_remap_text_layer_approval_is_hedged():
    adj, reasons = _decide(_state(container={"fonts_no_tounicode": 2}))
    assert adj == "NEEDS_REVIEW"
    assert reasons == ["untrusted_container_text_layer"]


def test_scanned_note_finding_is_not_gated_by_container():
    # A finding read from the scanned image (not the born-digital text layer)
    # is trusted evidence; the container guard must not touch it.
    adj, _ = _decide(_state(view="masked_pdf_render",
                            container={"has_ocg": True}))
    assert adj == "APPROVED"


def test_denied_finding_under_ocg_still_denies():
    # Distrust-direction only: the guard never relaxes a denial.
    adj, _ = _decide(_state(finding="DENIED", container={"has_ocg": True}))
    assert adj == "DENIED"
