"""Language contracts and Latin rendering, with no neural models loaded."""

import pytest
from PIL import Image

from test_nmt_translation import upstream as nmt_upstream
from test_translation import upstream as marian_upstream
from yomiscan.translation.base import TranslationInitializationError
from yomiscan.translation.marian import MarianTranslationEngine, OPUS_EXPERIMENTS
from yomiscan.translation.nmt import NMTTranslationEngine
from yomiscan.translation.options import TranslationOptions, capabilities, validate_options
from yomiscan.rendering.typesetting import PillowTypesetter


def test_nllb_switches_forced_target_without_reloading_or_mutating_english(nmt_upstream):
    ids = {"eng_Latn": 256047, "por_Latn": 256141, "spa_Latn": 256161}
    nmt_upstream.tokenizer.convert_tokens_to_ids.side_effect = ids.get
    engine = NMTTranslationEngine("nllb-600m", local_files_only=True)
    for target in ("en", "pt-BR", "es", "en"):
        result = engine.translate_many_to(["知らなかった。"], target)[0]
        assert nmt_upstream.model.generate.call_args.kwargs["forced_bos_token_id"] == ids[{
            "en": "eng_Latn", "pt-BR": "por_Latn", "es": "spa_Latn"}[target]]
        assert result.source_text == "知らなかった。"
        assert result.metadata["requested_target"] == target
        assert result.metadata["regional_variant_verified"] is (target != "pt-BR")
    nmt_upstream.model_factory.from_pretrained.assert_called_once()
    assert engine._target_id == 256047
    with pytest.raises(ValueError, match="does not support"):
        NMTTranslationEngine("fugumt").translate_many_to(["猫"], "es")
    with pytest.raises(ValueError):
        validate_options(engine, TranslationOptions(mode="structured-page"))


@pytest.mark.parametrize("target", ["pt-BR", "es"])
def test_direct_opus_pins_hash_prefix_and_caches_only_selected_target(marian_upstream, monkeypatch, target):
    spec = OPUS_EXPERIMENTS[target]
    monkeypatch.setattr("yomiscan.cache_identity.loaded_hf_identity", lambda *args: {"pytorch_model.bin": spec["weight_sha256"]})
    marian_upstream.tokenizer.unk_token_id = 1
    marian_upstream.tokenizer.convert_tokens_to_ids.return_value = 2
    engine = MarianTranslationEngine(target_language=target)
    result = engine.translate("でも\n大丈夫")
    assert marian_upstream.tokenizer_factory.from_pretrained.call_args.kwargs == {
        "revision": spec["revision"], "local_files_only": True}
    assert marian_upstream.tokenizer.call_args.args[0] == [spec["prefix"]+"でも 大丈夫"]
    assert marian_upstream.model.generate.call_args.kwargs["num_beams"] == 6
    assert result.source_text == "でも\n大丈夫" and result.metadata["target_language"] == target
    assert capabilities(engine).targets == (target,)
    with pytest.raises(ValueError, match="target"):
        validate_options(engine, TranslationOptions())


def test_experimental_opus_rejects_wrong_artifact_or_missing_portuguese_tag(marian_upstream, monkeypatch):
    monkeypatch.setattr("yomiscan.cache_identity.loaded_hf_identity", lambda *args: {"pytorch_model.bin": "wrong"})
    with pytest.raises(TranslationInitializationError, match="checksum"):
        MarianTranslationEngine(target_language="pt-BR")
    monkeypatch.setattr("yomiscan.cache_identity.loaded_hf_identity", lambda *args: {
        "pytorch_model.bin": OPUS_EXPERIMENTS["pt-BR"]["weight_sha256"]})
    marian_upstream.tokenizer.unk_token_id = 1
    marian_upstream.tokenizer.convert_tokens_to_ids.return_value = 1
    with pytest.raises(TranslationInitializationError, match="target tag"):
        MarianTranslationEngine(target_language="pt-BR")


@pytest.mark.parametrize("text", ["Não é impossível! Ação, coração, você, avó, avô.", "¡No sabía! ¿Qué pasó? Mañana, vergüenza, pingüino."])
def test_portuguese_and_spanish_accents_fit_and_paint_without_missing_glyphs(text):
    from yomiscan.detection import BoundingBox
    typesetter = PillowTypesetter()
    layout = typesetter.layout_text(text, BoundingBox(5, 5, 495, 295))
    assert layout is not None
    image = Image.new("RGB", (500, 300), "white")
    typesetter.draw_text(image, layout, fill=(0, 0, 0))
    assert image.getextrema()[0][0] < 255 and layout.text
