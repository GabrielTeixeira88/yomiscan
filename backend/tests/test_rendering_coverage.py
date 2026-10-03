from dataclasses import replace
import numpy as np
from PIL import Image, ImageDraw, ImageFont
from yomiscan.detection import BoundingBox as Box
from yomiscan.rendering import ConservativePageRenderer
from yomiscan.rendering.artwork import edged_text_mask
from yomiscan.rendering.coverage import classify_text
from yomiscan.rendering.layout_regions import LayoutRegion
from yomiscan.rendering.masks import MaskConfig, UniformBackgroundMaskGenerator
from yomiscan.rendering.typesetting import PillowTypesetter, wrap_text
from test_rendering import fixture_page


def test_categories_and_sound_patterns_do_not_capture_bubble_interjections():
    box = Box(0, 0, 100, 100)
    assert classify_text('unknown', 'そうだ', {'text_bubble'})[0] == 'bubble'
    assert classify_text('unknown', '原文', {'text_free'}, LayoutRegion(box, 'narration_box', True))[0] == 'narration'
    assert classify_text('unknown', '相手は長物', {'text_free'})[0] == 'artwork_text'
    assert classify_text('unknown', 'ゴゴゴ', {'text_free'})[0] == 'sfx'
    assert classify_text('unknown', 'ドン', {'text_bubble'})[0] == 'bubble'
    assert classify_text('unknown', 'ん？', {'text_free'})[0] == 'artwork_text'


def test_dense_separable_bubble_renders_with_explicit_coverage():
    image, analysis = fixture_page()
    masks = UniformBackgroundMaskGenerator(MaskConfig(minimum_background_fraction=.99))
    assert not masks.generate(image, analysis.text_blocks[0].bbox).safe
    result = ConservativePageRenderer(masks=masks).render(image, analysis)
    assert result.blocks_rendered == 1
    assert result.diagnostics['coverage']['narration_rendered'] == 1
    assert result.diagnostics['blocks'][1]['reason_code'] == 'rendered'


def test_free_text_safe_and_unsafe_outcomes_and_provenance():
    image, analysis = fixture_page()
    analysis = replace(analysis, regions=(replace(analysis.regions[0], metadata={'class':'text_free'}),))
    ImageDraw.Draw(image).rectangle((0,0,239,8),fill='white')
    safe = ConservativePageRenderer().render(image, analysis)
    assert safe.diagnostics['coverage']['artwork_text_rendered'] == 1
    ImageDraw.Draw(image).line((0,70,239,70), fill='black', width=3)
    unsafe = ConservativePageRenderer().render(image, analysis)
    assert unsafe.blocks_skipped == 1
    assert unsafe.rendered_image.tobytes() == image.tobytes()
    detail = unsafe.diagnostics['blocks'][1]
    assert detail['translated_text'] and detail['reason']
    assert detail['reason_code'] == 'inseparable_mask'
    assert unsafe.diagnostics['coverage']['not_detected_estimate'] is None


def test_explicit_sfx_preserved_even_in_enclosed_interior():
    image, analysis = fixture_page()
    analysis = replace(analysis, text_blocks=(replace(analysis.text_blocks[0], category='sfx'),))
    result = ConservativePageRenderer().render(image, analysis)
    assert result.rendered_image.tobytes() == image.tobytes()
    assert result.diagnostics['coverage']['sfx_preserved'] == 1
    assert result.diagnostics['blocks'][1]['reason_code'] == 'likely_sfx'


def test_edged_glyph_mask_does_not_erase_gray_background_or_structural_lines():
    image=Image.new('RGB',(160,100),(220,220,220))
    draw=ImageDraw.Draw(image)
    draw.text((35,35),'TEXT',fill='black',font=ImageFont.load_default(size=24))
    box=Box(25,25,115,75)
    mask=edged_text_mask(image,box)
    assert mask is not None
    selected=np.asarray(mask.final)>0
    assert selected.sum() < box.width*box.height/2
    assert not selected[0].any()
    draw.line((0,48,159,48),fill='black',width=3)
    assert edged_text_mask(image,box) is None


def test_hyphenated_translation_fits_without_invented_word_breaks():
    t=PillowTypesetter()
    result=t.layout_text('Four-year-olds.',Box(0,0,94,139))
    assert result is not None
    assert result.text.replace('\n','') == 'Four-year-olds.'
    assert t.layout_text('unbreakableword'*5,Box(0,0,94,139)) is None
    assert wrap_text('A - B', t.font(14), 200) == 'A - B'


def test_small_text_uses_connected_balloon_interior_and_respects_neighbor():
    from yomiscan.rendering.layout_regions import estimate_layout_region
    from yomiscan.rendering.masks import intersects
    image=Image.new('RGB',(400,280),'gray')
    draw=ImageDraw.Draw(image)
    draw.ellipse((25,90,165,260),fill='white',outline='black',width=2)
    draw.ellipse((115,20,330,230),fill='white',outline='black',width=2)
    draw.rectangle((120,105,155,190),fill='white')
    draw.text((70,150),'A',fill='black',font=ImageFont.load_default(size=25))
    box=Box(60,135,100,200);neighbor=Box(190,80,260,170)
    mask=UniformBackgroundMaskGenerator().generate(image,box)
    layout=estimate_layout_region(image,box,mask,[neighbor])
    assert layout.enclosed and layout.bbox.width>box.width
    assert layout.bbox.height>box.height
    assert not intersects(layout.bbox,neighbor)
