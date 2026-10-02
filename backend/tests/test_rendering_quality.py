"""Geometry and quality regressions; synthetic images only, no neural models."""

from dataclasses import replace
from unittest.mock import Mock

import cv2
import numpy as np
import pytest
from PIL import Image, ImageDraw, ImageFont

from yomiscan.detection import BoundingBox as Box, TextRegion
from yomiscan.page_layout import group_regions
from yomiscan.rendering import ConservativePageRenderer, TypesettingError
from yomiscan.rendering.layout_regions import estimate_layout_region, largest_rectangle
from yomiscan.rendering.masks import UniformBackgroundMaskGenerator
from yomiscan.rendering.service import PageTranslationRenderService
from yomiscan.rendering.typesetting import PillowTypesetter, wrap_text
from test_rendering import fixture_page


@pytest.mark.parametrize("shape", ["ellipse", "rectangle"])
def test_layout_uses_interior_while_mask_stays_tight(shape):
    image = Image.new("RGB", (320, 240), "gray")
    draw = ImageDraw.Draw(image)
    getattr(draw, shape)((20, 20, 300, 220), fill="white", outline="black", width=3)
    draw.text((132, 95), "ABC", fill="black", font=ImageFont.load_default(size=24))
    box = Box(125, 85, 185, 140)
    mask = UniformBackgroundMaskGenerator().generate(image, box)
    mask_before = mask.final.tobytes()
    layout = estimate_layout_region(image, box, mask, [])
    assert layout.enclosed
    assert layout.kind == ("bubble" if shape == "ellipse" else "narration_box")
    assert layout.bbox.width > box.width * 2
    assert layout.bbox.height > box.height
    assert 23 < layout.bbox.left < layout.bbox.right < 298
    assert 23 < layout.bbox.top < layout.bbox.bottom < 218
    assert mask.final.tobytes() == mask_before
    # Every layout pixel is original paper or a masked glyph, never the bubble edge.
    allowed = np.array(image.convert("L")) > 240
    full_mask = Image.new("L", image.size)
    full_mask.paste(mask.final, (mask.crop_box.left, mask.crop_box.top))
    allowed |= np.array(full_mask) > 0
    b = layout.bbox
    assert allowed[b.top:b.bottom, b.left:b.right].all()


def test_open_background_and_page_edge_use_clipped_fallback():
    image = Image.new("RGB", (120, 100), "white")
    ImageDraw.Draw(image).text((5, 25), "A", fill="black", font=ImageFont.load_default(size=22))
    box = Box(0, 15, 30, 65)
    mask = UniformBackgroundMaskGenerator().generate(image, box)
    layout = estimate_layout_region(image, box, mask, [])
    assert layout.kind == "conservative" and not layout.enclosed
    assert layout.bbox.left == 0 and layout.bbox.right <= 42
    assert 0 <= layout.bbox.top < layout.bbox.bottom <= 100


def test_interior_respects_unmasked_artwork_and_neighbor():
    image, analysis = fixture_page()
    box = analysis.text_blocks[0].bbox
    mask = UniformBackgroundMaskGenerator().generate(image, box)
    obstacle = Box(170, 0, 240, 160)
    layout = estimate_layout_region(image, box, mask, [obstacle])
    assert layout.enclosed and layout.bbox.right <= 170
    allowed = np.ones((40, 60), dtype=np.uint8)
    allowed[:, 30:33] = 0
    rectangle = largest_rectangle(allowed)
    assert rectangle.right <= 30 or rectangle.left >= 33


def test_contained_duplicate_group_keeps_raw_ids_without_merging_neighbors():
    meta = {"class": "text_free", "granularity": "block"}
    outer = TextRegion(1, Box(10, 10, 130, 130), .9, metadata=meta)
    inner = TextRegion(2, Box(90, 12, 125, 120), .6, metadata=meta)
    neighbor = TextRegion(3, Box(128, 10, 180, 130), .8, metadata=meta)
    groups = group_regions([inner, neighbor, outer])
    assert len(groups) == 2
    merged = next(group for group in groups if len(group.regions) == 2)
    assert {r.id for r in merged.regions} == {1, 2}
    assert merged.bbox == outer.bbox
    assert len(group_regions([outer, replace(inner, confidence=.95)])) == 2
    assert len(group_regions([outer, replace(inner, metadata={**meta, "class": "text_bubble"})])) == 2


def test_verified_bubble_can_override_free_class_without_painting_rectangle():
    image, analysis = fixture_page()
    analysis = replace(analysis, regions=(replace(analysis.regions[0], metadata={"class": "text_free"}),))
    result = ConservativePageRenderer().render(image, analysis, debug=True)
    assert result.blocks_rendered == 1
    details = result.diagnostics["blocks"][1]
    assert details["layout"] == "narration_box"
    assert details["mask_bbox"] != details["layout_bbox"]
    assert details["typesetting"] == details["inpainting"] == "success"
    # Cleaning must preserve every pixel outside the tight mask, including outlines.
    selected = np.asarray(result.debug_images["03-mask"]) > 0
    assert np.array_equal(np.asarray(result.debug_images["04-inpainted"])[~selected], np.asarray(image)[~selected])


def test_font_preferences_balanced_wrap_and_small_bubble():
    typesetter = PillowTypesetter(minimum_size=14, preferred_size=26, maximum_size=30)
    large = typesetter.layout_text("Hmm?", Box(0, 0, 400, 250))
    small = typesetter.layout_text("Hmm?", Box(0, 0, 65, 100))
    assert large.font_size == 26
    assert 14 <= small.font_size <= 26
    font = typesetter.font(26)
    width = round(font.getlength("one two three") + 1)
    wrapped = wrap_text("one two three four", font, width)
    assert wrapped == "one two\nthree four"
    text = "So even if I can't go out with you,"
    wide = typesetter.layout_text(text, Box(0, 0, 240, 150))
    narrow = typesetter.layout_text(text, Box(0, 0, 120, 280))
    assert len(wide.text.splitlines()) < len(narrow.text.splitlines())
    assert wide.font_size <= 26 and narrow.font_size >= 14
    assert PillowTypesetter(maximum_size=20).layout_text("Hi!", Box(0, 0, 300, 100)).font_size == 20


def test_layout_cv_failure_has_cause_and_preserves_block(monkeypatch):
    image, analysis = fixture_page()
    mask = UniformBackgroundMaskGenerator().generate(image, analysis.text_blocks[0].bbox)
    with monkeypatch.context() as context:
        context.setattr(cv2, "connectedComponentsWithStats", Mock(side_effect=cv2.error("bad")))
        with pytest.raises(TypesettingError) as error:
            estimate_layout_region(image, analysis.text_blocks[0].bbox, mask, [])
        assert isinstance(error.value.__cause__, cv2.error)
    import yomiscan.rendering.renderer as renderer_module
    monkeypatch.setattr(renderer_module, "estimate_layout_region", Mock(side_effect=TypesettingError("private")))
    result = ConservativePageRenderer().render(image, analysis)
    assert result.blocks_skipped == 1 and result.rendered_image.tobytes() == image.tobytes()
    assert "private" not in str(result.metadata())


def test_debug_maps_raw_filtered_grouped_and_render_stages():
    image, analysis = fixture_page()
    filtered = TextRegion(2, Box(1, 1, 2, 2), .5)
    analysis = replace(analysis, regions=(*analysis.regions, filtered), filtered_regions={2: "too small"})
    analyzer = Mock()
    analyzer.analyze_page.return_value = analysis
    result = PageTranslationRenderService(analyzer, ConservativePageRenderer()).translate_and_render_page(image, debug=True)
    assert result.diagnostics["raw_regions"][1]["filter_reason"] == "too small"
    assert result.diagnostics["raw_regions"][1]["block_ids"] == []
    assert {"01-detection", "01-grouped-blocks", "06-layout-status"} <= result.debug_images.keys()
