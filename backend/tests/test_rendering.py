from contextlib import contextmanager
from dataclasses import replace
from io import BytesIO
from unittest.mock import Mock

import numpy as np
import pytest
from fastapi.testclient import TestClient
from PIL import Image, ImageDraw, ImageFont

from yomiscan.analysis import TextAnalysisResult
from yomiscan.api.main import create_app
from yomiscan.detection import BoundingBox as Box, TextRegion
from yomiscan.page import PageAnalysisResult, PageProcessing, TextBlock
from yomiscan.rendering import ConservativePageRenderer, InpaintingError, TypesettingError
from yomiscan.rendering.base import MaskGenerationError
from yomiscan.rendering.cli import main, validate_outputs
from yomiscan.rendering.inpainting import OpenCVInpaintingEngine
from yomiscan.rendering.masks import MaskConfig, UniformBackgroundMaskGenerator, safe_text_area
from yomiscan.rendering.service import PageTranslationRenderService
from yomiscan.rendering.typesetting import PillowTypesetter, wrap_text

from yomiscan.translation import TranslationResult


def fixture_page(*, black=False, text="It's okay."):
    background, ink = ("black", "white") if black else ("white", "black")
    image = Image.new("RGB", (240, 160), background)
    draw = ImageDraw.Draw(image)
    draw.rectangle((5, 5, 234, 154), outline=ink, width=2)
    draw.text((65, 60), "SOURCE", fill=ink, font=ImageFont.load_default(size=22))
    box = Box(45, 45, 195, 110)
    region = TextRegion(1, box, .95, metadata={"class": "text_bubble"})
    lexical = TextAnalysisResult("原文", (), {}, TranslationResult("原文", text, "fake", "fake", 0))
    block = TextBlock(1, (1,), box, "unknown", 1, "原文", lexical)
    return image, PageAnalysisResult(240, 160, (region,), (block,), PageProcessing(0, 0, 0, 0, 0))


@pytest.mark.parametrize("black", [False, True])
def test_tight_masks_original_coordinates_dilation_and_borders(black):
    image, analysis = fixture_page(black=black)
    mask = UniformBackgroundMaskGenerator().generate(image, analysis.text_blocks[0].bbox)
    assert mask.safe
    assert mask.crop_box == Box(33, 33, 207, 122)
    raw, final = np.array(mask.raw), np.array(mask.final)
    assert 0 < np.count_nonzero(raw) < 150*65/2
    assert np.count_nonzero(final) > np.count_nonzero(raw)
    global_mask = Image.new("L", image.size)
    global_mask.paste(mask.final, (mask.crop_box.left, mask.crop_box.top))
    assert global_mask.getpixel((5, 5)) == 0
    assert np.array(global_mask)[60:90, 65:155].max() == 255


def test_outline_and_texture_are_rejected():
    image, analysis = fixture_page()
    draw = ImageDraw.Draw(image)
    draw.line((0, 70, 239, 70), fill="black", width=3)
    assert not UniformBackgroundMaskGenerator().generate(image, analysis.text_blocks[0].bbox).safe
    texture = Image.fromarray(np.tile(np.array([0, 255], np.uint8), (160, 120))).convert("RGB")
    assert not UniformBackgroundMaskGenerator().generate(texture, analysis.text_blocks[0].bbox).safe


def test_mask_config_and_clipped_coordinates():
    with pytest.raises(ValueError):
        MaskConfig(dilation=-1)
    image, _ = fixture_page()
    mask = UniformBackgroundMaskGenerator().generate(image, Box(-20, -10, 195, 110))
    assert mask.crop_box.left == mask.crop_box.top == 0
    with pytest.raises(ValueError):
        UniformBackgroundMaskGenerator().generate(image, Box(300, 0, 400, 20))


def test_safe_expansion_stops_at_ink_neighbors_and_page_edge():
    image = Image.new("RGB", (100, 100), "white")
    ImageDraw.Draw(image).line((20, 0, 20, 99), fill="black")
    area = safe_text_area(image, Box(25, 25, 70, 70), (255, 255, 255), [Box(75, 0, 90, 100)], 40)
    assert area.left == 21 and area.right == 75
    assert area.top == 0 and area.bottom == 100
    # Expansion must check newly introduced corner pixels as well as strips.
    image.putpixel((24, 24), (0, 0, 0))
    area = safe_text_area(image, Box(25, 25, 70, 70), (255, 255, 255), [], 1)
    assert not (area.left <= 24 < area.right and area.top <= 24 < area.bottom)


def test_font_fit_wrap_center_and_overflow():
    typesetter = PillowTypesetter()
    box = Box(20, 10, 180, 140)
    layout = typesetter.layout_text("This is a longer English sentence.", box)
    assert layout is not None and "\n" in layout.text
    l, t, r, b = layout.ink_bounds
    assert l >= 25 and r <= 175 and t >= 15 and b <= 135
    assert (l+r)/2 == pytest.approx(100)
    assert (t+b)/2 == pytest.approx(75)
    assert typesetter.layout_text("long sentence "*100, box) is None
    assert wrap_text("unbreakableword", typesetter.font(14), 10) is None
    assert typesetter.font(14) is typesetter.font(14)
    with pytest.raises(TypesettingError):
        typesetter.layout_text("日本語", box)


@pytest.mark.parametrize("black", [False, True])
def test_real_lightweight_inpaint_removes_glyphs_preserves_unmasked(black):
    image, analysis = fixture_page(black=black)
    mask = UniformBackgroundMaskGenerator().generate(image, analysis.text_blocks[0].bbox)
    crop = image.crop(mask.crop_box.coordinates())
    cleaned = OpenCVInpaintingEngine().inpaint(crop, mask.final)
    before, after, selected = np.array(crop), np.array(cleaned), np.array(mask.final) > 0
    assert np.array_equal(before[~selected], after[~selected])
    assert np.all(after[selected] == (0 if black else 255))


def test_nearly_white_background_avoids_telea_smudges(monkeypatch):
    import cv2

    pixels = np.full((30, 30, 3), 255, dtype=np.uint8)
    pixels[::3] = 245  # Small paper/compression variations, not artwork.
    pixels[12:18, 12:18] = 0
    mask = Image.new("L", (30, 30))
    ImageDraw.Draw(mask).rectangle((12, 12, 17, 17), fill=255)
    fallback = Mock(side_effect=AssertionError("Flat background should use fill"))
    monkeypatch.setattr(cv2, "inpaint", fallback)
    cleaned = np.array(OpenCVInpaintingEngine().inpaint(Image.fromarray(pixels), mask))
    selected = np.array(mask) > 0
    assert np.all(cleaned[selected] == 255)
    assert np.array_equal(cleaned[~selected], pixels[~selected])
    fallback.assert_not_called()


def test_inpaint_validation():
    with pytest.raises(ValueError):
        OpenCVInpaintingEngine().inpaint(Image.new("RGB", (10, 10)), Image.new("L", (5, 5)))


def test_mask_failure_and_analysis_size_mismatch():
    image, analysis = fixture_page()
    masks = UniformBackgroundMaskGenerator()
    masks.generate = Mock(side_effect=MaskGenerationError("private"))
    result = ConservativePageRenderer(masks=masks).render(image, analysis)
    assert result.blocks_skipped == 1 and result.rendered_image.tobytes() == image.tobytes()
    assert "private" not in str(result.metadata())
    with pytest.raises(ValueError, match="dimensions"):
        ConservativePageRenderer().render(image, replace(analysis, width=1))


def test_telea_fallback_only_changes_masked_pixels(monkeypatch):
    import cv2
    pixels = np.zeros((20, 20, 3), np.uint8)
    pixels[:, ::2] = 255
    image = Image.fromarray(pixels)
    mask = Image.new("L", (20, 20)); ImageDraw.Draw(mask).rectangle((8, 8, 12, 12), fill=255)
    original_inpaint = cv2.inpaint
    called = Mock(wraps=original_inpaint)
    monkeypatch.setattr(cv2, "inpaint", called)
    result = OpenCVInpaintingEngine().inpaint(image, mask)
    called.assert_called_once()
    selected = np.array(mask) > 0
    assert np.array_equal(np.array(result)[~selected], pixels[~selected])


def test_render_locality_metadata_debug_and_original_immutability():
    image, analysis = fixture_page()
    before = image.tobytes()
    result = ConservativePageRenderer().render(image, analysis, debug=True)
    assert result.blocks_rendered == 1 and result.blocks_skipped == 0
    assert result.rendered_image.size == image.size
    assert result.rendered_image.tobytes() != before and image.tobytes() == before
    assert result.rendered_image.crop((0, 0, 240, 30)).tobytes() == image.crop((0, 0, 240, 30)).tobytes()
    assert "03-mask" in result.debug_images
    assert result.metadata()["blocks"][0]["font_size"] >= 14
    assert ConservativePageRenderer().render(image, analysis).debug_images == {}


@pytest.mark.parametrize("mode", ["L", "RGBA"])
def test_render_preserves_grayscale_and_alpha(mode):
    image, analysis = fixture_page()
    image = image.convert(mode)
    if mode == "RGBA": image.putalpha(150)
    result = ConservativePageRenderer().render(image, analysis)
    assert result.rendered_image.mode == mode
    if mode == "RGBA": assert result.rendered_image.getchannel("A").tobytes() == image.getchannel("A").tobytes()


@pytest.mark.parametrize("failure", ["inpaint", "draw", "overflow", "sfx", "overlap", "untranslated", "free"])
def test_skipped_blocks_keep_original_pixels(failure):
    image, analysis = fixture_page(text="word "*1000 if failure == "overflow" else "Okay")
    engine = Mock()
    engine.inpaint.side_effect = InpaintingError("private details") if failure == "inpaint" else lambda image, mask: image.copy()
    typesetter = PillowTypesetter()
    if failure == "draw":
        typesetter.draw_text = Mock(side_effect=TypesettingError("private details"))
    block = analysis.text_blocks[0]
    if failure == "sfx": analysis = replace(analysis, text_blocks=(replace(block, category="possible_sfx"),))
    if failure == "overlap": analysis = replace(analysis, text_blocks=(block, replace(block, id=2)))
    if failure == "untranslated": analysis = replace(analysis, text_blocks=(replace(block, analysis=None),))
    if failure == "free":
        analysis = replace(analysis, regions=(replace(analysis.regions[0], metadata={"class": "text_free"}),))
        # Free text on an open background remains uncertain. A verified enclosed
        # bubble may now override the detector's coarse class (tested separately).
        ImageDraw.Draw(image).rectangle((0, 0, 239, 8), fill="white")
    result = ConservativePageRenderer(engine, typesetter).render(image, analysis)
    assert result.blocks_rendered == 0
    assert result.rendered_image.tobytes() == image.tobytes()
    assert "private" not in str(result.metadata())
    if failure not in ("inpaint", "draw"): engine.inpaint.assert_not_called()


def test_failed_block_does_not_prevent_neighbor_render():
    image, analysis = fixture_page()
    wide = Image.new("RGB", (500, 160), "white")
    wide.paste(image, (0, 0)); wide.paste(image, (260, 0))
    block = analysis.text_blocks[0]
    second = replace(block, id=2, region_ids=(2,), bbox=Box(305, 45, 455, 110))
    analysis = replace(analysis, width=500, text_blocks=(block, second))
    real = OpenCVInpaintingEngine()
    engine = Mock()
    calls = 0
    def inpaint(image, mask):
        nonlocal calls
        calls += 1
        if calls == 1: raise InpaintingError("first failed")
        return real.inpaint(image, mask)
    engine.inpaint.side_effect = inpaint
    result = ConservativePageRenderer(engine).render(wide, analysis)
    assert [b.status for b in result.blocks] == ["skipped", "rendered"]
    assert result.rendered_image.crop((0, 0, 240, 160)).tobytes() == image.tobytes()


def test_analysis_once_or_reused_and_empty_result():
    image, analysis = fixture_page()
    analyzer = Mock()
    analyzer.analyze_page.return_value = analysis
    service = PageTranslationRenderService(analyzer, ConservativePageRenderer())
    assert service.translate_and_render_page(image).blocks_rendered == 1
    service.translate_and_render_page(image, analysis)
    analyzer.analyze_page.assert_called_once()
    result = service.translate_and_render_page(image, replace(analysis, regions=(), text_blocks=()))
    assert result.blocks_rendered == result.blocks_skipped == 0
    assert result.rendered_image.tobytes() == image.tobytes()


def test_neighboring_layout_expansions_do_not_overlap():
    from yomiscan.rendering.masks import intersects
    image = Image.new("RGB", (400, 200), "white")
    draw = ImageDraw.Draw(image)
    draw.text((90, 80), "A", font=ImageFont.load_default(size=20), fill="black")
    draw.text((200, 80), "B", font=ImageFont.load_default(size=20), fill="black")
    _, analysis = fixture_page()
    base = analysis.text_blocks[0]
    blocks = (replace(base, bbox=Box(50, 50, 180, 150)),
              replace(base, id=2, region_ids=(2,), bbox=Box(200, 50, 330, 150)))
    analysis = replace(analysis, width=400, height=200, text_blocks=blocks)
    typesetter = PillowTypesetter()
    original_layout = typesetter.layout_text
    typesetter.layout_text = Mock(wraps=original_layout)
    result = ConservativePageRenderer(typesetter=typesetter).render(image, analysis)
    assert result.blocks_rendered == 2
    areas = [call.args[1] for call in typesetter.layout_text.call_args_list]
    assert not intersects(areas[0], areas[1])


def test_cli_protects_source_and_debug_collision(tmp_path):
    source = tmp_path / "00-original.png"
    with pytest.raises(ValueError): validate_outputs(source, source, None)
    with pytest.raises(ValueError): validate_outputs(source, tmp_path / "out.png", tmp_path)
    assert main([str(tmp_path / "missing.png"), "--output", str(tmp_path / "out.png")]) == 2


def test_render_api_png_headers_invalid_image_and_failure():
    image, analysis = fixture_page()
    service = Mock()
    service.translate_and_render_page.side_effect = lambda im: ConservativePageRenderer().render(im, analysis)
    @contextmanager
    def factory(): yield service
    buffer = BytesIO(); image.save(buffer, format="PNG")
    with TestClient(create_app(factory), base_url="http://127.0.0.1",
                    headers={"X-YomiScan-Client": "study-extension-v1"}) as client:
        response = client.post("/api/v1/render-page", files={"file": ("page.png", buffer.getvalue())})
        assert response.status_code == 200 and response.headers["content-type"] == "image/png"
        assert response.headers["x-yomiscan-blocks-rendered"] == "1"
        assert Image.open(BytesIO(response.content)).size == image.size
        assert client.post("/api/v1/render-page", files={"file": ("bad", b"oops")}).status_code == 400
        assert client.post("/api/v1/render-page", files={"file": ("bad", b"")}).status_code == 400
        service.translate_and_render_page.side_effect = RuntimeError("secret")
        failed = client.post("/api/v1/render-page", files={"file": ("page.png", buffer.getvalue())})
        assert failed.status_code == 500 and "secret" not in failed.text
