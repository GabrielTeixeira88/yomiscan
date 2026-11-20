from collections import Counter
from contextlib import contextmanager
from dataclasses import replace
from io import BytesIO
import json
from pathlib import Path

from fastapi.testclient import TestClient
import pytest

from test_processing_cache import resources, page, Translator, Tokenizer
from yomiscan.analysis import TextAnalyzer
from yomiscan.api.main import create_app
from yomiscan.glossary import GlossaryStore
from yomiscan.nlp import JapaneseToken
from yomiscan.service import TranslationConfigurationChanged, PageRefreshError
from yomiscan.translation.base import TranslationResult
from yomiscan.translation.options import TranslationOptions, TranslationCapabilities
from yomiscan.translation.structured import StructuredTranslationError


class CompleteTokenizer(Tokenizer):
    def tokenize(self, text):
        self.counts["lexical"] += 1
        return [JapaneseToken("猫"), JapaneseToken("です")]


class CapableTranslator(Translator):
    fail_structured = False
    last_request = None
    def capabilities(self):
        return TranslationCapabilities(("en", "pt-BR", "es"), True, True, True, ("pt-BR", "es"))
    def translate(self, text, *, context=None):
        if context is None:
            return super().translate(text)
        self.counts["translation"] += 1
        return TranslationResult(text, next(iter(context.glossary.values()))+" is here", "fake", "fake-model", 1)
    def translate_many_to(self, texts, target_language):
        self.counts["translation"] += 1
        return [TranslationResult(text, target_language+" translated", "fake", "fake-model", 1) for text in texts]
    def translate_page(self, request, *, cancel=None):
        self.last_request = request
        self.counts["translation"] += 1
        if self.fail_structured:
            raise StructuredTranslationError("missing_ids", "Fake missing IDs")
        return [TranslationResult(s.text, request.mode+request.context+" translated", "fake", "fake-model", 1,
                                  {"grammar_contract": "id-json-v1", "context_ids": ["B001"]}) for s in request.segments]


def configured(path):
    service, counts, detector, ocr, tokenizer, dictionary, translator, renderer = resources(path/"processing")
    translator = CapableTranslator(counts, "translator")
    tokenizer = CompleteTokenizer(counts, "tokenizer")
    service._analyzer = TextAnalyzer(tokenizer, dictionary, translator)
    service._glossaries = GlossaryStore(path/"user"/"glossaries.sqlite3")
    return service, counts, translator


def test_glossary_hints_and_edited_terms_reuse_ocr_and_lexical_work(tmp_path):
    service, counts, translator = configured(tmp_path)
    store = service.glossaries
    scope = store.create_series("Explicit user series")
    term = store.save_entry(scope, "en", "猫", "Series Cat")
    options = TranslationOptions(series_id=scope, glossary_enabled=True, glossary_version=store.identity(scope, "en"))
    first = service.analyze_page(page(), options=options)
    assert all(b.original_text == "猫です" and b.analysis.translation.translated_text == "Series Cat is here" for b in first.text_blocks)
    assert translator.counts["individual"] == 0
    counts.clear()
    store.save_entry(scope, "en", "猫", "New Cat", entry_id=term)
    with pytest.raises(TranslationConfigurationChanged):
        service.analyze_page(page(), options=options)
    options = replace(options, glossary_version=store.identity(scope, "en"))
    changed = service.translate_and_render_page(page(), options=options)
    assert counts == Counter(translation=2, render=1)
    counts.clear()
    store.save_entry(scope, "en", "犬", "unmatched dog")
    options = replace(options, glossary_version=store.identity(scope, "en"))
    service.translate_and_render_page(page(), options=options)
    assert counts == Counter()  # Only effective matched hints change the translation key.
    counts.clear()
    service.translate_and_render_page(page(), options=replace(options, glossary_enabled=False))
    assert counts["translation"] == 1 and counts["ocr"] == counts["lexical"] == 0
    service.close()


@pytest.mark.parametrize("change", ["target", "context", "mode", "ordering"])
def test_translation_options_invalidate_descendants_without_repeating_extraction(tmp_path, change):
    service, counts, translator = configured(tmp_path)
    options = TranslationOptions(mode="structured-line") if change == "context" else TranslationOptions()
    service.translate_and_render_page(page(), options=options)
    counts.clear()
    if change == "target": options = replace(options, target_language="es")
    if change == "context": options = replace(options, context="neighbor")
    if change == "mode": options = replace(options, mode="structured-page")
    if change == "ordering": options = replace(options, ordering="panels")
    result = service.translate_and_render_page(page(), options=options)
    assert counts["translation"] > 0 and counts["render"] == 1
    assert counts["ocr"] == counts["detection"] == counts["lexical"] == 0
    assert result.diagnostics["translation_settings"]["target_language"] == options.target_language
    if change == "context":
        assert [s.id for s in translator.last_request.segments] == ["B001", "B002"]
    service.close()


def test_structured_failure_has_no_hidden_line_fallback_or_cache_poisoning(tmp_path):
    service, counts, translator = configured(tmp_path)
    options = TranslationOptions(mode="structured-page")
    service.translate_and_render_page(page(), options=options)
    translator.fail_structured = True
    counts.clear()
    with pytest.raises(PageRefreshError):
        service.translate_and_render_page(page(), options=options, refresh="translation")
    assert counts["translation"] == 1 and counts["individual"] == 0
    translator.fail_structured = False
    counts.clear()
    service.translate_and_render_page(page(), options=options)
    assert counts == Counter()
    service.close()


def test_opus_like_engine_ignores_glossary_without_rewriting_or_new_calls(tmp_path):
    service, counts, *_ = resources(tmp_path/"processing")
    service._glossaries = GlossaryStore(tmp_path/"user.sqlite3")
    service.glossaries.save_entry("global", "en", "猫", "Preferred")
    service.translate_and_render_page(page())
    counts.clear()
    result = service.translate_and_render_page(page(), options=TranslationOptions(glossary_enabled=True))
    assert counts == Counter()
    assert result.diagnostics["translation_settings"]["glossary_application"] == "unsupported"
    with pytest.raises(ValueError, match="target"):
        service.translate_and_render_page(page(), options=TranslationOptions(target_language="es"))
    service.close()


def test_restart_restores_target_context_glossary_entries_and_cache_independently(tmp_path):
    service, _, _ = configured(tmp_path)
    service.glossaries.save_entry("global", "en", "猫", "Cat")
    options = TranslationOptions(mode="structured-line", context="neighbor", glossary_enabled=True)
    service.translate_and_render_page(page(), options=options)
    service.close()
    restarted, counts, _ = configured(tmp_path)
    result = restarted.translate_and_render_page(page(), options=options)
    assert counts == Counter()
    assert result.diagnostics["blocks"]["1"]["translation_metadata"]["context_ids"] == ["B001"]
    restarted.cache.clear()
    assert restarted.glossaries.effective(None, "en")[0].preferred == "Cat"
    restarted.close()


def test_glossary_api_crud_protection_options_and_clear_separation(tmp_path):
    headers = {"X-YomiScan-Client": "study-extension-v1", "Origin": "chrome-extension://"+"a"*32}
    @contextmanager
    def factory():
        service, *_ = configured(tmp_path)
        try: yield service
        finally: service.close()
    image = BytesIO(); page().save(image, "PNG")
    files = {"file": ("page.png", image.getvalue(), "image/png")}
    with TestClient(create_app(factory), base_url="http://localhost") as client:
        assert client.post("/api/v1/glossaries/series", json={"label": "A"}).status_code == 403
        made = client.post("/api/v1/glossaries/series", json={"label": "A"}, headers=headers)
        assert made.status_code == 200
        scope = made.json()["id"]
        saved = client.post("/api/v1/glossaries/term", json={"scope": scope, "target_language": "en", "source": "猫", "preferred": "Cat"}, headers=headers)
        assert saved.status_code == 200
        assert client.get("/api/v1/translation-profile").status_code == 403
        profile = client.get("/api/v1/translation-profile", params={"scope": scope, "target": "en"}, headers=headers).json()
        assert profile["entries"][0]["preferred"] == "Cat"
        options = TranslationOptions(series_id=scope, glossary_enabled=True, glossary_version=profile["glossary_version"])
        from dataclasses import asdict
        response = client.post("/api/v1/render-page", files=files, data={"options_json": json.dumps(asdict(options))}, headers=headers)
        assert response.status_code == 200
        assert client.post("/api/v1/cache/clear", headers=headers).status_code == 200
        assert client.get("/api/v1/translation-profile", params={"scope": scope}, headers=headers).json()["entries"]
        deleted = client.post("/api/v1/glossaries/delete-term", json={"scope": scope, "target_language": "en", "entry_id": saved.json()["id"]}, headers=headers)
        assert deleted.status_code == 200
        assert client.post("/api/v1/render-page", files=files, data={"options_json": json.dumps(asdict(options))}, headers=headers).status_code == 409
        assert client.post("/api/v1/render-page", files=files, data={"options_json": '{"target_language":"xx"}'}, headers=headers).status_code == 422
        assert client.post("/api/v1/render-page", files=files, data={"options_json": '{"arbitrary_path":"secret"}'}, headers=headers).status_code == 422
