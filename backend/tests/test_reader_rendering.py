from dataclasses import replace
import pytest

from test_processing_cache import resources, page
from yomiscan.service import PageRefreshError
from test_rendering import fixture_page
from yomiscan.rendering.settings import RenderSettings
from yomiscan.rendering.typesetting import PillowTypesetter
from yomiscan.rendering.renderer import ConservativePageRenderer
from yomiscan.diagnostics import page_snapshot


@pytest.mark.parametrize("scale", [0, .74, 1.51, float("nan"), float("inf"), True, "1"])
def test_invalid_font_settings_rejected(scale):
    with pytest.raises(ValueError):
        RenderSettings(scale)


def test_scale_keeps_absolute_safeguards_and_default_wrapping():
    from yomiscan.detection import BoundingBox
    original = PillowTypesetter()
    assert vars(original.scaled(1)) == vars(original)
    for scale in (.75, 1.25, 1.5):
        scaled = original.scaled(scale)
        assert 14 <= scaled.minimum_size <= scaled.preferred_size <= scaled.maximum_size == 30
        layout = scaled.layout_text("Não é impossível! ¿Qué pasó?", BoundingBox(0, 0, 350, 100))
        assert layout and "..." not in layout.text
        assert scaled.layout_text("Long dialogue "*30, BoundingBox(0, 0, 20, 40)) is None


def test_font_changes_reuse_all_upstream_stages_and_study_analysis(tmp_path):
    service, counts, *_ = resources(tmp_path)
    service._render_service.renderer = ConservativePageRenderer()
    first = service.translate_and_render_page(page())
    counts.clear()
    changed = service.translate_and_render_page(page(), render_settings=RenderSettings(1.5), refresh="render")
    assert not counts
    stages = changed.diagnostics["cache"]["stages"]
    assert all(s["restored"] for s in stages if s["stage"] != "render")
    assert not stages[-1]["restored"] and stages[-1]["stage"] == "render"
    snapshot = page_snapshot(page(), changed, input_sha256="a"*64)
    study = snapshot["blocks"][0]["text"]["study"]
    assert study["original_text"] == "猫です" and study["tokens"][0]["meanings"]
    assert snapshot["render_settings"] == {"font_scale": 1.5}
    service.translate_and_render_page(page(), render_settings=RenderSettings(1.5))
    assert not counts
    service.close()


def test_large_text_preserves_original_pixels_when_no_valid_layout():
    image, analysis = fixture_page(text="Long dialogue "*80)
    result = ConservativePageRenderer(typesetter=PillowTypesetter().scaled(1.5)).render(image, analysis)
    assert result.blocks_rendered == 0
    assert result.rendered_image.tobytes() == image.tobytes()


def test_render_refresh_rejects_actual_renderer_failures(tmp_path):
    service, counts, *_, renderer = resources(tmp_path)
    service.translate_and_render_page(page())
    renderer.fail = True
    events = []
    with pytest.raises(PageRefreshError, match="previous translation retained"):
        service.translate_and_render_page(page(), refresh="render", progress=lambda *event: events.append(event))
    assert ("render", "failed", None) in events
    service.close()
