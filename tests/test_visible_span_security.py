"""Visible-evidence boundary tests for PDF crop and paint order.

These fixtures are synthetic. They prove that text which a conforming viewer
cannot see never reaches the rank-1 note parser, while later visible text keeps
its ordinary authority.
"""
import io

import fitz
import pytest

from mib import forensics, parse_ocr


NOTE_LINES = (
    "Manual Adjudicator Note",
    "Case ID: MIB-123456",
    "Finding: APPROVED",
)


def _reopen(doc):
    buffer = io.BytesIO()
    doc.save(buffer)
    doc.close()
    return fitz.open(stream=buffer.getvalue(), filetype="pdf")


def _insert_note(page, x=72):
    for index, text in enumerate(NOTE_LINES):
        page.insert_text((x, 100 + index * 18), text, fontsize=12)


def _parse_visible(doc):
    visible, hidden = forensics.classify_spans(doc)
    parsed = parse_ocr.parse_page([(span.text, 0.99) for span in visible])
    return visible, hidden, parsed


def test_rotated_page_uses_unrotated_crop_frame_for_offcrop_text():
    doc = fitz.open()
    page = doc.new_page(width=612, height=792)
    # x=650 is outside the physical crop width. At 90 degrees page.rect is
    # 792 points wide, which was the vulnerable but incorrect comparison.
    _insert_note(page, x=650)
    page.set_rotation(90)
    doc = _reopen(doc)

    visible, hidden, parsed = _parse_visible(doc)
    assert not {span.text for span in visible} & set(NOTE_LINES)
    assert {span.text for span in hidden} >= set(NOTE_LINES)
    assert all("off_crop" in span.hidden_reasons for span in hidden
               if span.text in NOTE_LINES)
    assert parsed[2]["finding"] is None
    doc.close()


def test_partially_offcrop_span_has_no_text_authority():
    doc = fitz.open()
    page = doc.new_page(width=612, height=792)
    # The glyph bbox has only a sub-point sliver inside the page. Intersection
    # alone used to grant the complete object string authority.
    page.insert_text((-112.5, 100), "Finding: APPROVED", fontsize=12)
    doc = _reopen(doc)

    visible, hidden, parsed = _parse_visible(doc)
    assert "Finding: APPROVED" not in {span.text for span in visible}
    finding = next(span for span in hidden
                   if span.text == "Finding: APPROVED")
    assert fitz.Rect(0, 0, 612, 792).intersects(fitz.Rect(finding.bbox))
    assert "off_crop" in finding.hidden_reasons
    assert parsed[2]["finding"] is None
    doc.close()


def test_later_opaque_fill_path_blocks_rank1_text_authority():
    doc = fitz.open()
    page = doc.new_page(width=612, height=792)
    _insert_note(page)
    page.draw_rect(
        fitz.Rect(60, 75, 300, 145), color=None, fill=(1, 1, 1),
        fill_opacity=1.0, overlay=True)
    doc = _reopen(doc)

    visible, hidden, parsed = _parse_visible(doc)
    assert not {span.text for span in visible} & set(NOTE_LINES)
    assert {span.text for span in hidden
            if "under_fill" in span.hidden_reasons} >= set(NOTE_LINES)
    assert parsed[2]["finding"] is None
    rendered = forensics.composited_page_gray(doc[0], dpi=72)
    assert int(rendered[70:150, 55:305].min()) == 255
    doc.close()


def test_later_opaque_stroke_path_blocks_rank1_text_authority():
    doc = fitz.open()
    page = doc.new_page(width=612, height=792)
    _insert_note(page)
    for y in (95, 113, 131):
        page.draw_line(
            (50, y), (310, y), color=(1, 1, 1), width=30,
            stroke_opacity=1.0, overlay=True)
    doc = _reopen(doc)

    visible, hidden, parsed = _parse_visible(doc)
    assert not {span.text for span in visible} & set(NOTE_LINES)
    assert {span.text for span in hidden
            if "under_stroke" in span.hidden_reasons} >= set(NOTE_LINES)
    assert parsed[2]["finding"] is None
    rendered = forensics.composited_page_gray(doc[0], dpi=72)
    assert int(rendered[75:145, 45:315].min()) == 255
    doc.close()


def test_midgray_stroke_geometry_blocks_erased_note_despite_pixel_variance():
    doc = fitz.open()
    page = doc.new_page(width=612, height=792)
    _insert_note(page)
    for y in (95, 113, 131):
        page.draw_line(
            (50, y), (310, y), color=(0.5, 0.5, 0.5), width=14,
            stroke_opacity=1.0, overlay=True)
    doc = _reopen(doc)

    visible, hidden, parsed = _parse_visible(doc)
    assert not {span.text for span in visible} & set(NOTE_LINES)
    assert {span.text for span in hidden
            if "under_stroke" in span.hidden_reasons} >= set(NOTE_LINES)
    rendered = forensics.composited_page_gray(doc[0], dpi=144)
    assert int(rendered[75:290, 95:620].max()) > \
        int(rendered[75:290, 95:620].min())
    assert parsed[2]["finding"] is None
    doc.close()


def test_thin_stroked_rectangle_does_not_hide_text_in_its_interior():
    doc = fitz.open()
    page = doc.new_page(width=612, height=792)
    page.draw_rect(
        fitz.Rect(60, 75, 300, 145), color=(0, 0, 0), fill=None,
        width=1.0, stroke_opacity=1.0, overlay=True)
    _insert_note(page)
    doc = _reopen(doc)

    visible, hidden, parsed = _parse_visible(doc)
    assert {span.text for span in visible} >= set(NOTE_LINES)
    assert not {span.text for span in hidden} & set(NOTE_LINES)
    assert parsed[2]["finding"] == "APPROVED"
    doc.close()


def test_dashed_stroke_bbox_never_claims_solid_occlusion():
    doc = fitz.open()
    page = doc.new_page(width=612, height=792)
    _insert_note(page)
    shape = page.new_shape()
    shape.draw_line((50, 113), (310, 113))
    shape.finish(color=(0.5, 0.5, 0.5), width=14, dashes="[2 30] 0")
    shape.commit(overlay=True)
    doc = _reopen(doc)

    visible, hidden, parsed = _parse_visible(doc)
    assert {span.text for span in visible} >= set(NOTE_LINES)
    assert not {span.text for span in hidden} & set(NOTE_LINES)
    assert parsed[2]["finding"] == "APPROVED"
    doc.close()


@pytest.mark.parametrize("phase", [0, -1, -1001])
def test_long_on_dash_pattern_cannot_bypass_stroke_occlusion(phase):
    doc = fitz.open()
    page = doc.new_page(width=612, height=792)
    _insert_note(page)
    for y in (95, 113, 131):
        shape = page.new_shape()
        shape.draw_line((50, y), (310, y))
        shape.finish(
            color=(0.5, 0.5, 0.5), width=14,
            dashes=f"[1000 .001] {phase}")
        shape.commit(overlay=True)
    doc = _reopen(doc)

    visible, hidden, parsed = _parse_visible(doc)
    assert not {span.text for span in visible} & set(NOTE_LINES)
    assert {span.text for span in hidden
            if "under_stroke" in span.hidden_reasons} >= set(NOTE_LINES)
    assert parsed[2]["finding"] is None
    doc.close()


def test_later_opaque_shading_blocks_rank1_text_authority():
    doc = fitz.open()
    page = doc.new_page(width=612, height=792)
    _insert_note(page)

    # Add a full-page, constant-white axial shading after the text. PyMuPDF
    # reports this paint as ``fill-shade`` in the sequence-aware bbox log.
    shade_xref = doc.get_new_xref()
    doc.update_object(shade_xref, (
        "<< /ShadingType 2 /ColorSpace /DeviceRGB /Coords [0 0 612 0] "
        "/Function << /FunctionType 2 /Domain [0 1] /C0 [1 1 1] "
        "/C1 [1 1 1] /N 1 >> /Extend [true true] >>"))
    _, resource_ref = doc.xref_get_key(page.xref, "Resources")
    resource_xref = int(resource_ref.split()[0])
    doc.xref_set_key(
        resource_xref, "Shading/Sh1", f"{shade_xref} 0 R")
    shade_content = doc.get_new_xref()
    doc.update_object(shade_content, "<< >>")
    doc.update_stream(shade_content, b"q /Sh1 sh Q")
    text_contents = " ".join(
        f"{xref} 0 R" for xref in page.get_contents())
    doc.xref_set_key(
        page.xref, "Contents",
        f"[{text_contents} {shade_content} 0 R]")
    doc = _reopen(doc)

    visible, hidden, parsed = _parse_visible(doc)
    assert not {span.text for span in visible} & set(NOTE_LINES)
    assert {span.text for span in hidden
            if "under_fill" in span.hidden_reasons} >= set(NOTE_LINES)
    assert parsed[2]["finding"] is None
    rendered = forensics.composited_page_gray(doc[0], dpi=72)
    assert int(rendered.min()) == 255
    doc.close()


def test_text_painted_after_opaque_fill_remains_visible():
    doc = fitz.open()
    page = doc.new_page(width=612, height=792)
    page.draw_rect(
        fitz.Rect(60, 75, 300, 145), color=None, fill=(1, 1, 1),
        fill_opacity=1.0, overlay=True)
    _insert_note(page)
    doc = _reopen(doc)

    visible, hidden, parsed = _parse_visible(doc)
    assert {span.text for span in visible} >= set(NOTE_LINES)
    assert not {span.text for span in hidden} & set(NOTE_LINES)
    assert parsed[2]["finding"] == "APPROVED"
    doc.close()


@pytest.mark.parametrize("color", [(0, 0, 0), (0.1, 0.3, 0.9)])
def test_same_color_text_after_opaque_fill_has_no_authority(color):
    doc = fitz.open()
    page = doc.new_page(width=612, height=792)
    page.draw_rect(
        fitz.Rect(60, 75, 300, 145), color=None, fill=color,
        fill_opacity=1.0, overlay=True)
    for index, text in enumerate(NOTE_LINES):
        page.insert_text(
            (72, 100 + index * 18), text, fontsize=12, color=color)
    doc = _reopen(doc)

    visible, hidden, parsed = _parse_visible(doc)
    assert not {span.text for span in visible} & set(NOTE_LINES)
    assert {span.text for span in hidden
            if "no_visible_color_contrast" in span.hidden_reasons} >= \
        set(NOTE_LINES)
    assert parsed[2]["finding"] is None
    doc.close()


def test_intervening_translucent_fill_keeps_readable_text_visible():
    doc = fitz.open()
    page = doc.new_page(width=612, height=792)
    page.draw_rect(
        fitz.Rect(60, 75, 300, 145), color=None, fill=(0, 0, 0),
        fill_opacity=1.0, overlay=True)
    page.draw_rect(
        fitz.Rect(60, 75, 300, 145), color=None, fill=(1, 1, 1),
        fill_opacity=0.5, overlay=True)
    _insert_note(page)
    doc = _reopen(doc)

    visible, hidden, parsed = _parse_visible(doc)
    assert {span.text for span in visible} >= set(NOTE_LINES)
    assert not {span.text for span in hidden} & set(NOTE_LINES)
    assert parsed[2]["finding"] == "APPROVED"
    doc.close()


def test_intervening_image_keeps_readable_text_visible():
    doc = fitz.open()
    page = doc.new_page(width=612, height=792)
    page.draw_rect(
        fitz.Rect(60, 75, 300, 145), color=None, fill=(0, 0, 0),
        fill_opacity=1.0, overlay=True)
    image = fitz.Pixmap(fitz.csGRAY, fitz.IRect(0, 0, 20, 20), False)
    image.clear_with(180)
    page.insert_image(
        fitz.Rect(60, 75, 300, 145), stream=image.tobytes("png"),
        overlay=True)
    _insert_note(page)
    doc = _reopen(doc)

    assert any(operation == "fill-image"
               for operation, _ in doc[0].get_bboxlog())
    visible, hidden, parsed = _parse_visible(doc)
    assert {span.text for span in visible} >= set(NOTE_LINES)
    assert not {span.text for span in hidden} & set(NOTE_LINES)
    assert parsed[2]["finding"] == "APPROVED"
    doc.close()


def test_complex_fill_bbox_does_not_hide_text_in_unpainted_hole():
    doc = fitz.open()
    page = doc.new_page(width=612, height=792)
    shape = page.new_shape()
    shape.draw_rect(fitz.Rect(40, 55, 320, 165))
    shape.draw_rect(fitz.Rect(60, 75, 300, 145))
    shape.finish(color=None, fill=(0, 0, 0), even_odd=True)
    shape.commit(overlay=True)
    _insert_note(page)
    doc = _reopen(doc)

    visible, hidden, parsed = _parse_visible(doc)
    assert {span.text for span in visible} >= set(NOTE_LINES)
    assert not {span.text for span in hidden} & set(NOTE_LINES)
    assert parsed[2]["finding"] == "APPROVED"
    doc.close()


def test_later_complex_fill_bbox_does_not_hide_text_in_unpainted_hole():
    doc = fitz.open()
    page = doc.new_page(width=612, height=792)
    _insert_note(page)
    shape = page.new_shape()
    shape.draw_rect(fitz.Rect(40, 55, 320, 165))
    shape.draw_rect(fitz.Rect(60, 75, 300, 145))
    shape.finish(color=None, fill=(1, 1, 1), even_odd=True)
    shape.commit(overlay=True)
    doc = _reopen(doc)

    visible, hidden, parsed = _parse_visible(doc)
    assert {span.text for span in visible} >= set(NOTE_LINES)
    assert not {span.text for span in hidden} & set(NOTE_LINES)
    assert parsed[2]["finding"] == "APPROVED"
    doc.close()


def test_missing_bboxlog_withholds_text_layer_authority(monkeypatch):
    doc = fitz.open()
    page = doc.new_page(width=612, height=792)
    _insert_note(page)
    doc = _reopen(doc)

    def unavailable(_page):
        raise RuntimeError("synthetic bbox inventory failure")

    monkeypatch.setattr(fitz.Page, "get_bboxlog", unavailable)
    visible, hidden, parsed = _parse_visible(doc)
    assert not {span.text for span in visible} & set(NOTE_LINES)
    assert {span.text for span in hidden
            if "paint_inventory_ambiguous" in span.hidden_reasons} >= \
        set(NOTE_LINES)
    assert parsed[2]["finding"] is None
    doc.close()


def test_missing_drawing_inventory_withholds_overlapping_path_text(
        monkeypatch):
    doc = fitz.open()
    page = doc.new_page(width=612, height=792)
    _insert_note(page)
    page.draw_rect(
        fitz.Rect(60, 75, 300, 145), color=None, fill=(1, 1, 1),
        fill_opacity=1.0, overlay=True)
    doc = _reopen(doc)

    def unavailable(_page):
        raise RuntimeError("synthetic drawing inventory failure")

    monkeypatch.setattr(fitz.Page, "get_drawings", unavailable)
    visible, hidden, parsed = _parse_visible(doc)
    assert not {span.text for span in visible} & set(NOTE_LINES)
    assert {span.text for span in hidden
            if "paint_geometry_ambiguous" in span.hidden_reasons} >= \
        set(NOTE_LINES)
    assert parsed[2]["finding"] is None
    doc.close()


def test_missing_drawing_inventory_withholds_text_only_page(monkeypatch):
    doc = fitz.open()
    page = doc.new_page(width=612, height=792)
    _insert_note(page)
    doc = _reopen(doc)

    def unavailable(_page):
        raise RuntimeError("synthetic drawing inventory failure")

    monkeypatch.setattr(fitz.Page, "get_drawings", unavailable)
    visible, hidden, parsed = _parse_visible(doc)
    assert not {span.text for span in visible} & set(NOTE_LINES)
    assert {span.text for span in hidden
            if "drawing_inventory_ambiguous" in span.hidden_reasons} >= \
        set(NOTE_LINES)
    assert parsed[2]["finding"] is None
    doc.close()


@pytest.mark.parametrize("opacity", [0.001, 0.01, 0.05])
def test_low_opacity_rank1_note_has_no_authority(opacity):
    doc = fitz.open()
    page = doc.new_page(width=612, height=792)
    for index, text in enumerate(NOTE_LINES):
        page.insert_text(
            (72, 100 + index * 18), text, fontsize=12,
            fill_opacity=opacity)
    doc = _reopen(doc)

    visible, hidden, parsed = _parse_visible(doc)
    assert not {span.text for span in visible} & set(NOTE_LINES)
    assert {span.text for span in hidden
            if "low_opacity" in span.hidden_reasons} >= set(NOTE_LINES)
    assert parsed[2]["finding"] is None
    doc.close()


def test_exact_public_watermark_opacity_remains_visible():
    doc = fitz.open()
    page = doc.new_page(width=612, height=792)
    for index, text in enumerate(NOTE_LINES):
        page.insert_text(
            (72, 100 + index * 18), text, fontsize=12,
            fill_opacity=0.18)
    doc = _reopen(doc)

    visible, hidden, parsed = _parse_visible(doc)
    assert {span.text for span in visible} >= set(NOTE_LINES)
    assert not {span.text for span in hidden} & set(NOTE_LINES)
    assert parsed[2]["finding"] == "APPROVED"
    doc.close()


@pytest.mark.parametrize("field", ["opacity", "size", "bbox", "color"])
def test_nonfinite_texttrace_metadata_fails_closed(monkeypatch, field):
    doc = fitz.open()
    page = doc.new_page(width=612, height=792)
    page.insert_text((72, 100), "Finding: APPROVED", fontsize=12)
    doc = _reopen(doc)
    raw = dict(doc[0].get_texttrace()[0])
    if field in {"opacity", "size"}:
        raw[field] = float("nan")
    elif field == "bbox":
        raw[field] = (72.0, 90.0, float("nan"), 105.0)
    else:
        raw[field] = (0.0, float("nan"), 0.0)

    monkeypatch.setattr(fitz.Page, "get_texttrace", lambda _page: [raw])
    visible, hidden = forensics.classify_spans(doc)
    assert visible == []
    assert len(hidden) == 1
    assert "nonfinite_span_metadata" in hidden[0].hidden_reasons
    doc.close()


def test_later_opaque_text_overpaint_blocks_earlier_rank1_authority():
    doc = fitz.open()
    page = doc.new_page(width=612, height=792)
    _insert_note(page)
    for index, text in enumerate(NOTE_LINES):
        page.insert_text(
            (72, 100 + index * 18), text, fontsize=12,
            color=(1, 1, 1), fill=(1, 1, 1), render_mode=2,
            border_width=1)
    doc = _reopen(doc)

    visible, hidden, parsed = _parse_visible(doc)
    assert not {span.text for span in visible} & set(NOTE_LINES)
    assert {span.text for span in hidden
            if "under_text" in span.hidden_reasons} >= set(NOTE_LINES)
    rendered = forensics.composited_page_gray(doc[0], dpi=144)
    assert int(rendered.min()) >= 245
    assert int((rendered < 220).sum()) == 0
    assert parsed[2]["finding"] is None
    doc.close()


def test_content_stream_clip_cannot_preserve_hidden_rank1_authority():
    doc = fitz.open()
    page = doc.new_page(width=612, height=792)
    _insert_note(page)
    for content_xref in page.get_contents():
        content = doc.xref_stream(content_xref)
        doc.update_stream(
            content_xref, b"q 0 0 1 1 re W n\n" + content + b"\nQ")
    doc = _reopen(doc)

    visible, hidden, parsed = _parse_visible(doc)
    assert not {span.text for span in visible} & set(NOTE_LINES)
    assert {span.text for span in hidden
            if "unresolved_clip_state" in span.hidden_reasons} >= \
        set(NOTE_LINES)
    rendered = forensics.composited_page_gray(doc[0], dpi=144)
    assert int(rendered.min()) == 255
    assert parsed[2]["finding"] is None
    doc.close()


def test_screen_blend_mode_cannot_preserve_hidden_rank1_authority():
    doc = fitz.open()
    page = doc.new_page(width=612, height=792)
    white = fitz.Pixmap(fitz.csGRAY, fitz.IRect(0, 0, 20, 20), False)
    white.clear_with(255)
    page.insert_image(page.rect, stream=white.tobytes("png"))
    _insert_note(page)
    state_xref = doc.get_new_xref()
    doc.update_object(
        state_xref,
        "<< /Type /ExtGState /BM /Screen /ca 1 /CA 1 >>")
    _, resource_ref = doc.xref_get_key(page.xref, "Resources")
    resource_xref = int(resource_ref.split()[0])
    doc.xref_set_key(
        resource_xref, "ExtGState/GSscreen", f"{state_xref} 0 R")
    for content_xref in page.get_contents()[1:]:
        content = doc.xref_stream(content_xref)
        doc.update_stream(
            content_xref, b"q /GSscreen gs\n" + content + b"\nQ")
    doc = _reopen(doc)

    visible, hidden, parsed = _parse_visible(doc)
    assert not {span.text for span in visible} & set(NOTE_LINES)
    assert {span.text for span in hidden
            if "unresolved_transparency" in span.hidden_reasons} >= \
        set(NOTE_LINES)
    rendered = forensics.composited_page_gray(doc[0], dpi=144)
    assert int(rendered.min()) == 255
    assert parsed[2]["finding"] is None
    doc.close()


def test_uniform_image_background_cannot_hide_same_color_rank1_text():
    doc = fitz.open()
    page = doc.new_page(width=612, height=792)
    black = fitz.Pixmap(fitz.csGRAY, fitz.IRect(0, 0, 20, 20), False)
    black.clear_with(0)
    page.insert_image(page.rect, stream=black.tobytes("png"))
    _insert_note(page)
    doc = _reopen(doc)

    visible, hidden, parsed = _parse_visible(doc)
    assert not {span.text for span in visible} & set(NOTE_LINES)
    assert {span.text for span in hidden
            if "no_visible_pixel_contrast" in span.hidden_reasons} >= \
        set(NOTE_LINES)
    rendered = forensics.composited_page_gray(doc[0], dpi=144)
    assert int(rendered.max()) == 0
    assert parsed[2]["finding"] is None
    doc.close()


def test_tounicode_font_mapping_removes_native_text_authority():
    doc = fitz.open()
    page = doc.new_page(width=612, height=792)
    _insert_note(page)
    font_xref = page.get_fonts(full=True)[0][0]
    cmap_xref = doc.get_new_xref()
    doc.update_object(cmap_xref, "<< >>")
    doc.update_stream(cmap_xref, (
        b"/CIDInit /ProcSet findresource begin\n12 dict begin\n"
        b"begincmap\n/CMapType 2 def\n1 begincodespacerange\n"
        b"<00> <FF>\nendcodespacerange\nendcmap\n"
        b"CMapName currentdict /CMap defineresource pop\nend end"))
    doc.xref_set_key(font_xref, "ToUnicode", f"{cmap_xref} 0 R")
    doc = _reopen(doc)

    visible, hidden, parsed = _parse_visible(doc)
    assert not {span.text for span in visible} & set(NOTE_LINES)
    assert {span.text for span in hidden
            if "untrusted_font_context" in span.hidden_reasons} >= \
        set(NOTE_LINES)
    assert parsed[2]["finding"] is None
    doc.close()


def test_same_color_gate_is_not_bypassed_by_contrasting_speck():
    doc = fitz.open()
    page = doc.new_page(width=612, height=792)
    page.draw_rect(
        fitz.Rect(60, 75, 300, 145), color=None, fill=(0, 0, 0),
        fill_opacity=1.0, overlay=True)
    # One white mark creates a nonzero grayscale range inside the note bbox but
    # cannot make same-color black glyphs readable against the black fill.
    page.draw_rect(
        fitz.Rect(80, 92, 82, 94), color=None, fill=(1, 1, 1),
        fill_opacity=1.0, overlay=True)
    _insert_note(page)
    doc = _reopen(doc)

    visible, hidden, parsed = _parse_visible(doc)
    assert not {span.text for span in visible} & set(NOTE_LINES)
    note_spans = {span.text: span for span in hidden
                  if span.text in NOTE_LINES}
    assert set(note_spans) == set(NOTE_LINES)
    assert "no_visible_pixel_contrast" in \
        note_spans["Manual Adjudicator Note"].hidden_reasons
    assert parsed[2]["finding"] is None
    doc.close()


def test_translucent_fill_does_not_claim_opaque_coverage():
    doc = fitz.open()
    page = doc.new_page(width=612, height=792)
    _insert_note(page)
    page.draw_rect(
        fitz.Rect(60, 75, 300, 145), color=None, fill=(1, 1, 1),
        fill_opacity=0.5, overlay=True)
    doc = _reopen(doc)

    visible, hidden, parsed = _parse_visible(doc)
    assert {span.text for span in visible} >= set(NOTE_LINES)
    assert not {span.text for span in hidden
                if "under_fill" in span.hidden_reasons} & set(NOTE_LINES)
    assert parsed[2]["finding"] == "APPROVED"
    doc.close()
