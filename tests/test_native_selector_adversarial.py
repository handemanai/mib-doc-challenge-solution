"""Adversarial fail-closed tests for direct native-image authorization."""
import builtins
import io

import fitz
import numpy as np
import pytest
from PIL import Image

from mib import forensics


def _png(array):
    buffer = io.BytesIO()
    Image.fromarray(array).save(buffer, format="PNG")
    return buffer.getvalue()


def _scan():
    image = np.full((1584, 1224), 245, np.uint8)
    image[500:560, 120:800] = 25
    return image


def _insert_scan(page, rect=None):
    xref = page.insert_image(rect or page.rect, stream=_png(_scan()))
    page.parent.xref_set_key(xref, "ColorSpace", "/DeviceGray")
    # PNG insertion adds an empty DecodeParms dictionary; eligible controls
    # model the corpus's default direct decode instead.
    page.parent.xref_set_key(xref, "DecodeParms", "null")
    return xref


def _reopen(doc):
    buffer = io.BytesIO()
    doc.save(buffer)
    doc.close()
    return fitz.open(stream=buffer.getvalue(), filetype="pdf")


def _eligible_doc():
    doc = fitz.open()
    page = doc.new_page(width=612, height=792)
    xref = _insert_scan(page)
    doc = _reopen(doc)
    assert forensics.native_full_page_scan(doc[0]) is not None
    return doc, xref


def test_selector_audit_reports_stable_first_rejection_category():
    eligible, _ = _eligible_doc()
    assert forensics.native_full_page_scan_audit(eligible[0])["reason"] == \
        "eligible"
    eligible.close()

    empty = fitz.open()
    empty.new_page()
    result = forensics.native_full_page_scan_audit(empty[0])
    assert result == {"eligible": False, "reason": "image_count_not_one"}
    assert set(forensics.NATIVE_SCAN_SELECTOR_OUTCOMES) >= {
        "eligible", "nondefault_user_unit", "unsafe_graphics_state",
        "evidence_bearing_overlay", "inspection_exception",
    }
    empty.close()


def _mutate_content(doc, transform):
    contents = doc[0].get_contents()[0]
    doc.update_stream(contents, transform(doc.xref_stream(contents)))
    return _reopen(doc)


@pytest.mark.parametrize("crop_relative", [True, False])
def test_shifted_cropbox_uses_only_crop_relative_full_bleed(crop_relative):
    doc = fitz.open()
    page = doc.new_page(width=812, height=992)
    page.set_cropbox(fitz.Rect(100, 100, 712, 892))
    rect = page.rect if crop_relative else fitz.Rect(100, 100, 712, 892)
    _insert_scan(page, rect=rect)
    doc = _reopen(doc)
    placement = doc[0].get_image_rects(
        doc[0].get_images(full=True)[0][0], transform=True)[0][0]
    assert (placement.x0 == pytest.approx(0)) is crop_relative
    selected = forensics.native_full_page_scan(doc[0])
    assert (selected is not None) is crop_relative
    doc.close()


@pytest.mark.parametrize("rect", [
    fitz.Rect(0.5, 0, 612, 792),
    fitz.Rect(-0.5, 0, 612, 792),
    fitz.Rect(0, 0, 611.5, 792),
    fitz.Rect(0, 0, 612.5, 792),
])
def test_substantial_inset_or_outset_never_authorizes_resized_native_pixels(
        rect):
    doc = fitz.open()
    page = doc.new_page(width=612, height=792)
    _insert_scan(page, rect=rect)
    doc = _reopen(doc)
    assert forensics.native_full_page_scan_audit(doc[0])["reason"] == \
        "not_full_bleed"
    doc.close()


def test_partial_later_image_coverage_never_hides_painted_text_for_selector():
    text = fitz.Rect(0, 100, 100, 120)
    sixty_percent_cover = fitz.Rect(0, 100, 60, 120)
    assert forensics._covered(text, [sixty_percent_cover])
    assert not forensics._fully_covered(text, [sixty_percent_cover])


@pytest.mark.parametrize("unit,eligible", [(1, True), (2, False), (0.5, False)])
def test_inherited_user_unit_must_resolve_to_default(unit, eligible):
    doc, _ = _eligible_doc()
    parent = int(doc.xref_get_key(doc[0].xref, "Parent")[1].split()[0])
    doc.xref_set_key(parent, "UserUnit", str(unit))
    doc = _reopen(doc)
    assert (forensics.native_full_page_scan(doc[0]) is not None) is eligible
    doc.close()


@pytest.mark.parametrize(("key", "value"), [
    ("Decode", "[1 0]"),
    ("DecodeParms", "<<>>"),
    ("SMaskInData", "1"),
    ("Filter", "/JPXDecode"),
    ("Filter", "[/FlateDecode]"),
])
def test_image_decode_ambiguity_is_rejected(key, value):
    doc, xref = _eligible_doc()
    doc.xref_set_key(xref, key, value)
    doc = _reopen(doc)
    assert doc.xref_get_key(xref, key)[0] != "null"
    assert forensics.native_full_page_scan(doc[0]) is None
    doc.close()


@pytest.mark.parametrize("ending", [b"\r", b"\n", b"\r\n"])
def test_each_pdf_comment_ending_exposes_later_paint(ending):
    doc, _ = _eligible_doc()
    doc = _mutate_content(
        doc, lambda stream: stream + b"\n% hidden-looking /Other Do" +
        ending + b"/Other Do")
    assert forensics.native_full_page_scan(doc[0]) is None
    doc.close()


@pytest.mark.parametrize("mode", [4, 5, 6, 7])
def test_text_clipping_modes_are_never_native_authorized(mode):
    doc, _ = _eligible_doc()
    doc = _mutate_content(
        doc, lambda stream: f"BT {mode} Tr ET\n".encode() + stream)
    assert forensics.native_full_page_scan(doc[0]) is None
    doc.close()


@pytest.mark.parametrize("wrapper", [
    lambda name: b"BT /" + name + b" Do ET",
    lambda name: b"/Span BMC /" + name + b" Do EMC",
    lambda name: b"/GS0 gs /" + name + b" Do",
])
def test_target_do_inside_unsafe_state_is_rejected(wrapper):
    doc, _ = _eligible_doc()
    image_name = doc[0].get_images(full=True)[0][7].encode("latin1")
    needle = b"/" + image_name + b" Do"
    doc = _mutate_content(
        doc, lambda stream: stream.replace(needle, wrapper(image_name)))
    assert forensics.native_full_page_scan(doc[0]) is None
    doc.close()


@pytest.mark.parametrize("tail", [b"[", b"<<", b"(", b"ET", b"Q"])
def test_malformed_or_unbalanced_content_state_fails_closed(tail):
    doc, _ = _eligible_doc()
    doc = _mutate_content(doc, lambda stream: stream + b"\n" + tail)
    assert forensics.native_full_page_scan(doc[0]) is None
    doc.close()


@pytest.mark.parametrize("extra", [
    b"/Other Do", b"/Shade sh", b"BI /W 1 /H 1 ID x EI",
    b"/Pattern1 scn",
])
def test_only_one_direct_target_image_paint_is_authorized(extra):
    doc, _ = _eligible_doc()
    doc = _mutate_content(doc, lambda stream: stream + b"\n" + extra)
    assert forensics.native_full_page_scan(doc[0]) is None
    doc.close()


def test_duplicate_target_image_paint_is_rejected():
    doc, _ = _eligible_doc()
    image_name = doc[0].get_images(full=True)[0][7].encode("latin1")
    doc = _mutate_content(
        doc, lambda stream: stream + b"\n/" + image_name + b" Do")
    assert forensics.native_full_page_scan(doc[0]) is None
    doc.close()


def test_do_resource_name_must_resolve_to_selected_xref(monkeypatch):
    doc, selected_xref = _eligible_doc()
    image_name = doc[0].get_images(full=True)[0][7]
    original = doc.xref_get_key

    def mismatched(holder, key):
        if key == f"Resources/XObject/{image_name}":
            return "xref", "1 0 R"
        return original(holder, key)

    monkeypatch.setattr(doc, "xref_get_key", mismatched)
    assert selected_xref != 1
    assert forensics.native_full_page_scan(doc[0]) is None
    doc.close()


def test_painted_image_inventory_must_match_selected_xref(monkeypatch):
    doc, selected_xref = _eligible_doc()
    original = fitz.Page.get_image_info

    def mismatched(page, *args, **kwargs):
        inventory = original(page, *args, **kwargs)
        inventory[0] = {**inventory[0], "xref": 1}
        return inventory

    monkeypatch.setattr(fitz.Page, "get_image_info", mismatched)
    assert selected_xref != 1
    assert forensics.native_full_page_scan(doc[0]) is None
    doc.close()


def test_type3_whitespace_glyph_cannot_hide_nested_inline_paint():
    doc, _ = _eligible_doc()
    page = doc[0]
    charproc = doc.get_new_xref()
    doc.update_object(charproc, "<< /Length 0 >>")
    doc.update_stream(
        charproc,
        b"q 500 0 0 500 0 0 cm BI /W 1 /H 1 /CS /DeviceGray "
        b"/BPC 8 ID \x00 EI Q",
    )
    font = doc.get_new_xref()
    doc.update_object(
        font,
        f"<< /Type /Font /Subtype /Type3 /FontBBox [0 0 500 500] "
        f"/FontMatrix [0.001 0 0 0.001 0 0] "
        f"/CharProcs << /space {charproc} 0 R >> "
        f"/Encoding << /Type /Encoding /Differences [32 /space] >> "
        f"/FirstChar 32 /LastChar 32 /Widths [500] /Resources << >> >>",
    )
    resources = int(doc.xref_get_key(page.xref, "Resources")[1].split()[0])
    doc.xref_set_key(resources, "Font", f"<< /Fspace {font} 0 R >>")
    contents = page.get_contents()[0]
    doc.update_stream(
        contents,
        doc.xref_stream(contents) + b"\nBT /Fspace 100 Tf 72 100 Td ( ) Tj ET",
    )
    doc = _reopen(doc)
    assert len(doc[0].get_images(full=True)) == 1
    assert not doc[0].get_drawings()
    visible, hidden = forensics.classify_spans(doc)
    assert not any(not span.text.strip() for span in visible)
    assert any(
        "untrusted_font_context" in span.hidden_reasons
        for span in hidden
    )
    assert forensics.native_full_page_scan(doc[0], visible) is None
    doc.close()


@pytest.mark.parametrize("default_name", [
    "DefaultGray", "DefaultRGB", "DefaultCMYK",
])
def test_deeply_indirect_inherited_default_colorspace_is_rejected(default_name):
    doc, _ = _eligible_doc()
    page = doc[0]
    parent = int(doc.xref_get_key(page.xref, "Parent")[1].split()[0])
    resources = int(doc.xref_get_key(page.xref, "Resources")[1].split()[0])
    leaf = doc.get_new_xref()
    doc.update_object(leaf, f"<< /{default_name} /DeviceRGB >>")
    middle = doc.get_new_xref()
    doc.update_object(middle, f"<< /Nested {leaf} 0 R >>")
    doc.xref_set_key(resources, "ColorSpace", f"{middle} 0 R")
    doc.xref_set_key(parent, "Resources", f"{resources} 0 R")
    doc.xref_set_key(page.xref, "Resources", "null")
    doc = _reopen(doc)
    assert forensics.native_full_page_scan(doc[0]) is None
    doc.close()


def test_recursive_resource_transparency_group_is_rejected():
    doc, _ = _eligible_doc()
    resources = int(doc.xref_get_key(doc[0].xref, "Resources")[1].split()[0])
    nested = doc.get_new_xref()
    doc.update_object(nested, "<< /Group << /S /Transparency >> >>")
    doc.xref_set_key(resources, "Properties", f"<< /P0 {nested} 0 R >>")
    doc = _reopen(doc)
    assert forensics.native_full_page_scan(doc[0]) is None
    doc.close()


def test_widget_appearance_forces_composited_render():
    doc, _ = _eligible_doc()
    widget = fitz.Widget()
    widget.field_name = "decision"
    widget.field_type = fitz.PDF_WIDGET_TYPE_TEXT
    widget.rect = fitz.Rect(40, 40, 180, 70)
    doc[0].add_widget(widget)
    doc = _reopen(doc)
    assert doc.xref_get_key(doc[0].xref, "Annots")[0] != "null"
    assert forensics.native_full_page_scan(doc[0]) is None
    doc.close()


@pytest.mark.parametrize(("key", "bad"), [
    ("width", 1223), ("height", 1583), ("bpc", 4), ("colorspace", 3),
])
def test_decoded_metadata_must_match_raw_image(monkeypatch, key, bad):
    doc, _ = _eligible_doc()
    original = doc.extract_image

    def mismatched(xref):
        extracted = original(xref)
        extracted[key] = bad
        return extracted

    monkeypatch.setattr(doc, "extract_image", mismatched)
    assert forensics.native_scan_gray(doc, doc[0]) == (None, None)
    doc.close()


def test_wrong_document_identity_returns_before_optional_imports(monkeypatch):
    doc, _ = _eligible_doc()
    wrong = fitz.open()
    imported = []
    real_import = builtins.__import__

    def guarded_import(name, *args, **kwargs):
        if name == "cv2" or name == "PIL" or name.startswith("PIL."):
            imported.append(name)
            raise AssertionError("optional import occurred before identity check")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", guarded_import)
    assert forensics.native_scan_gray(wrong, doc[0]) == (None, None)
    assert imported == []
    wrong.close()
    doc.close()


def test_selector_inspection_exception_falls_back(monkeypatch):
    doc, _ = _eligible_doc()

    def explode(*_args, **_kwargs):
        raise RuntimeError("inspection failed")

    monkeypatch.setattr(forensics, "_inspect_native_full_page_scan", explode)
    assert forensics.native_full_page_scan(doc[0]) is None
    doc.close()


def test_page_tree_must_terminate_at_catalog_pages():
    doc, _ = _eligible_doc()
    page = doc[0]
    fake_root = doc.get_new_xref()
    doc.update_object(
        fake_root,
        f"<< /Type /Pages /Kids [{page.xref} 0 R] /Count 1 >>",
    )
    doc.xref_set_key(page.xref, "Parent", f"{fake_root} 0 R")
    assert forensics.native_full_page_scan(page) is None
    doc.close()


def test_unambiguous_footer_over_blank_native_pixels_remains_eligible():
    doc, _ = _eligible_doc()
    doc[0].insert_text(
        (50, 764), "Packet MIB-123456 / page 1", fontsize=7)
    doc = _reopen(doc)
    visible, _ = forensics.classify_spans(doc)
    assert forensics.native_full_page_scan(doc[0], visible) is not None
    doc.close()
