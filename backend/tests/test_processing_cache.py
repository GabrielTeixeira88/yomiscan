"""Model-free integration tests cross the production stage interfaces and count work."""

from collections import Counter
from contextlib import contextmanager
from dataclasses import asdict
from io import BytesIO
from pathlib import Path
import sqlite3
import threading

from fastapi.testclient import TestClient
from PIL import Image
import pytest

from yomiscan.analysis import TextAnalyzer
from yomiscan.cache import ProcessingCache, CacheRequest, MiB, pixel_identity
from yomiscan.cache_identity import component_identity
from yomiscan.detection import BoundingBox, TextRegion
from yomiscan.dictionary import DictionaryEntry
from yomiscan.dictionary.models import DictionarySense
from yomiscan.nlp import JapaneseToken
from yomiscan.ocr import OCRResult, OCRRecognitionError
from yomiscan.rendering.base import PageRenderResult, RenderProcessing, BlockRenderStatus
from yomiscan.rendering.service import PageTranslationRenderService
from yomiscan.service import ImageAnalysisService, PageRefreshError
from yomiscan.translation import TranslationResult, TranslationError
from yomiscan.api.main import create_app


class Identified:
    def __init__(self, counts: Counter, name: str):
        self.counts, self.name = counts, name
        self.settings = {"artifact": name+"-v1", "parameter": 1}

    def cache_identity(self):
        return dict(self.settings)


class Detector(Identified):
    def detect(self, image):
        self.counts["detection"] += 1
        return [TextRegion(i, BoundingBox(x, 5, x+25, 45), .9, metadata={"class": "text_bubble", "granularity": "block"})
                for i, x in ((1, 70), (2, 10))]


class OCR(Identified):
    fail = False

    def recognize(self, image):
        self.counts["ocr"] += 1
        if self.fail:
            raise OCRRecognitionError("private path")
        return OCRResult("猫です", "fake", 12, {"confidence": .8, "confidence_method": "fake_uncalibrated"})


class Tokenizer(Identified):
    def tokenize(self, text):
        self.counts["lexical"] += 1
        return [JapaneseToken("猫", lemma="猫")]


class Dictionary(Identified):
    def lookup(self, text):
        self.counts["dictionary"] += 1
        return (DictionaryEntry(1, ("猫",), (), (DictionarySense(("cat",), ("noun",)),)),)


class Translator(Identified):
    fail = False

    def diagnostic_metadata(self):
        return {"engine": "fake", "model": self.settings["artifact"]}

    def translate_many(self, texts):
        self.counts["translation"] += 1
        self.counts["batch_items"] += len(texts)
        if self.fail:
            raise TranslationError("private model error")
        return [TranslationResult(text, "Cat "+str(i), "fake", self.settings["artifact"], 7) for i, text in enumerate(texts)]

    def translate(self, text):
        self.counts["individual"] += 1
        if self.fail:
            raise TranslationError("private model error")
        return self.translate_many([text])[0]


class Renderer(Identified):
    fail = False

    def render(self, image, analysis, *, debug=False):
        self.counts["render"] += 1
        details = {b.id: {"region_ids": b.region_ids, "bbox": asdict(b.bbox), "original_text": b.original_text,
                         "translated_text": b.analysis.translation.translated_text if b.analysis else None,
                         "ocr_ms": b.ocr_ms, "ocr_metadata": b.ocr_metadata, "ocr": "success",
                         "inpainting": "error" if self.fail else "success", "render": "rendered"}
                   for b in analysis.text_blocks}
        return PageRenderResult(image.copy(), tuple(BlockRenderStatus(b.id, "rendered") for b in analysis.text_blocks),
                                RenderProcessing(1, 2, 3, 6), diagnostics={"blocks": details})


def resources(path: Path, *, enabled=True, memory=64*MiB):
    counts = Counter()
    detector, ocr, tokenizer, dictionary, translator, renderer = [cls(counts, name) for cls, name in (
        (Detector, "detector"), (OCR, "ocr"), (Tokenizer, "tokenizer"), (Dictionary, "dictionary"),
        (Translator, "translator"), (Renderer, "renderer"))]
    cache = ProcessingCache(path, enabled=enabled, memory_bytes=memory)
    service = ImageAnalysisService(ocr, TextAnalyzer(tokenizer, dictionary, translator), detector=detector, cache=cache)
    service._render_service = PageTranslationRenderService(service, renderer)
    return service, counts, detector, ocr, tokenizer, dictionary, translator, renderer


def page():
    return Image.new("RGB", (120, 80), "white")


def test_repeat_and_restart_reuse_every_expensive_stage(tmp_path):
    service, counts, *_ = resources(tmp_path)
    first = service.translate_and_render_page(page())
    assert counts == Counter(detection=1, ocr=2, lexical=1, dictionary=1, translation=1, batch_items=2, render=1)
    baseline = counts.copy()
    second = service.translate_and_render_page(page())
    assert counts == baseline
    assert second.rendered_image.tobytes() == first.rendered_image.tobytes()
    assert second.processing == RenderProcessing(0, 0, 0, 0)
    assert second.analysis_processing["ocr_ms"] == 0
    assert second.analysis_processing["translation_ms"] == 0
    assert all(s["restored"] for s in second.diagnostics["cache"]["stages"])
    service.close()
    restarted, calls, *_ = resources(tmp_path)
    restored = restarted.translate_and_render_page(page())
    assert calls == Counter()
    assert all(s["source"] == "disk" or (s["stage"] == "lexical" and s["source"] == "memory")
               for s in restored.diagnostics["cache"]["stages"])
    assert {r["id"] for r in restored.diagnostics["raw_regions"]} == {1, 2}
    restarted.close()


@pytest.mark.parametrize("changed,expected", [
    ("translator", Counter(translation=1, batch_items=2, render=1)),
    ("ocr", Counter(ocr=2, translation=1, batch_items=2, render=1)),
    ("detector", Counter(detection=1, ocr=2, translation=1, batch_items=2, render=1)),
    ("renderer", Counter(render=1)),
    ("dictionary", Counter(lexical=1, dictionary=1)),
    ("tokenizer", Counter(lexical=1, dictionary=1)),
])
def test_configuration_changes_invalidate_only_affected_stages(tmp_path, changed, expected):
    service, counts, detector, ocr, tokenizer, dictionary, translator, renderer = resources(tmp_path)
    service.translate_and_render_page(page())
    counts.clear()
    selected = {"translator": translator, "ocr": ocr, "detector": detector, "renderer": renderer,
                "dictionary": dictionary, "tokenizer": tokenizer}[changed]
    selected.settings["parameter"] += 1
    service.translate_and_render_page(page())
    assert counts == expected
    assert counts["individual"] == 0
    service.close()


def test_pixels_resolution_and_reencoding_identity(tmp_path):
    service, counts, *_ = resources(tmp_path)
    image = page()
    service.translate_and_render_page(image)
    encoded = BytesIO()
    image.save(encoded, "PNG", compress_level=0)
    with Image.open(BytesIO(encoded.getvalue())) as decoded:
        service.translate_and_render_page(decoded)
    assert counts["detection"] == 1
    image.putpixel((119, 79), (0, 0, 0))
    service.translate_and_render_page(image)
    assert counts["detection"] == 2
    assert pixel_identity(image) != pixel_identity(image.resize((240, 160)))
    service.close()


def test_canonical_identity_preserves_library_alpha_palette_and_mode(tmp_path):
    service, counts, *_ = resources(tmp_path)
    first = Image.new("RGBA", (120, 80), (255, 255, 255, 255))
    second = Image.new("RGBA", (120, 80), (255, 255, 255, 10))
    assert pixel_identity(first) != pixel_identity(second)
    assert service.translate_and_render_page(first).rendered_image.getpixel((0, 0))[3] == 255
    assert service.translate_and_render_page(second).rendered_image.getpixel((0, 0))[3] == 10
    palette = Image.new("P", (1, 1))
    palette.putpalette([255, 0, 0]+[0]*765)
    old = pixel_identity(palette)
    palette.putpalette([0, 255, 0]+[0]*765)
    assert pixel_identity(palette) != old
    assert pixel_identity(first.convert("RGB")) != pixel_identity(first)
    service.close()


def test_translation_and_render_refresh_reuse_extraction_and_lexical(tmp_path):
    service, counts, *_ = resources(tmp_path)
    service.translate_and_render_page(page())
    counts.clear()
    result = service.translate_and_render_page(page(), refresh="translation")
    assert counts == Counter(translation=1, batch_items=2, render=1)
    assert result.diagnostics["cache"]["refresh"] == "translation"
    counts.clear()
    service.translate_and_render_page(page(), refresh="render")
    assert counts == Counter(render=1)
    service.close()


@pytest.mark.parametrize("failed_stage", ["translation", "ocr", "render"])
def test_failed_refresh_does_not_replace_previous_persisted_result(tmp_path, failed_stage):
    service, counts, _, ocr, _, _, translator, renderer = resources(tmp_path)
    service.translate_and_render_page(page())
    selected = {"translation": translator, "ocr": ocr, "render": renderer}[failed_stage]
    selected.fail = True
    with pytest.raises(PageRefreshError):
        service.translate_and_render_page(page(), refresh="all" if failed_stage == "ocr" else "translation")
    selected.fail = False
    counts.clear()
    result = service.translate_and_render_page(page())
    assert counts == Counter()
    assert next(s for s in result.diagnostics["cache"]["stages"] if s["stage"] == "render")["restored"]
    service.close()


def test_disabled_persistence_never_opens_database_and_unknown_engines_bypass(tmp_path):
    service, counts, detector, *_ = resources(tmp_path, enabled=False)
    service.translate_and_render_page(page())
    assert not list(tmp_path.iterdir())
    service.close()
    assert component_identity(object()) is None
    class Unknown:
        def diagnostic_metadata(self):
            return {"model": "looks-pinned", "revision": "abc"}
    assert component_identity(Unknown()) is None


def test_corrupt_and_missing_database_recover_without_inference_failure(tmp_path):
    service, *_ = resources(tmp_path)
    service.translate_and_render_page(page())
    service.close()
    database = tmp_path / "stages.sqlite3"
    with sqlite3.connect(database) as db:
        db.execute("UPDATE entries SET payload=?", (b"corrupt",))
    db.close()
    recovered, counts, *_ = resources(tmp_path, memory=0)
    recovered.translate_and_render_page(page())
    assert counts["detection"] == 1 and counts["ocr"] == 2
    assert recovered.cache.corruptions > 0
    recovered.close()
    database.unlink()
    missing, calls, *_ = resources(tmp_path)
    missing.translate_and_render_page(page())
    assert calls["detection"] == 1
    missing.close()
    database.write_bytes(b"not sqlite")
    rebuilt, calls, *_ = resources(tmp_path)
    rebuilt.translate_and_render_page(page())
    assert calls["detection"] == 1
    rebuilt.close()


def test_quota_eviction_atomic_rollback_clear_consent_and_shutdown(tmp_path):
    cache = ProcessingCache(tmp_path, enabled=True, memory_bytes=100, disk_bytes=MiB)
    cache.put("test", "one", b"a"*350_000)
    cache.put("test", "two", b"b"*350_000)
    cache.get("test", "one")  # Touch first; second must be evicted.
    cache.put("test", "three", b"c"*350_000)
    assert cache.get("test", "two")[0] is None
    assert cache.get("test", "one")[0] is not None
    assert cache.stats()["disk_bytes"] <= MiB
    db = cache._db
    try:
        with db:
            db.execute("INSERT INTO entries VALUES('test','interrupted',X'00','bad',0)")
            raise RuntimeError("simulated crash before commit")
    except RuntimeError:
        pass
    assert cache.get("test", "interrupted")[0] is None
    cache.configure(False)
    stored_bytes = cache.stats()["disk_bytes"]
    cache.put("test", "disabled", b"z"*200)
    assert cache.stats()["disk_bytes"] == stored_bytes
    cache.close()
    restarted = ProcessingCache(tmp_path)
    assert restarted.enabled is False
    restarted.configure(True)
    restarted.clear()
    assert restarted.stats()["disk_bytes"] == 0
    assert restarted.stats()["memory_bytes"] == 0
    restarted.close()
    # Windows catches leaked SQLite handles here.
    tmp_path.rename(tmp_path.with_name(tmp_path.name+"-closed"))


def test_cache_rejects_cross_thread_access_and_invalid_settings(tmp_path):
    cache = ProcessingCache(tmp_path, enabled=False)
    failures = []
    def other_thread():
        try:
            cache.stats()
        except RuntimeError as exc:
            failures.append(str(exc))
    worker = threading.Thread(target=other_thread)
    worker.start()
    worker.join()
    assert failures and "owning" in failures[0]
    with pytest.raises(ValueError):
        cache.configure(True, 0)


@pytest.mark.parametrize("bad_payload", ["text-in-blob-column", 123])
def test_sqlite_payload_type_corruption_is_a_miss(tmp_path, bad_payload):
    cache = ProcessingCache(tmp_path, enabled=True, memory_bytes=0)
    cache.put("test", "corrupt", b"good bytes")
    with cache._db:
        cache._db.execute("UPDATE entries SET payload=?", (bad_payload,))
    assert cache.get("test", "corrupt")[0] is None
    assert cache.corruptions == 1
    cache.close()


def test_cache_api_consent_localhost_validation_refresh_and_generation(tmp_path):
    origin = "chrome-extension://"+"a"*32
    headers = {"X-YomiScan-Client": "study-extension-v1", "Origin": origin}
    @contextmanager
    def factory():
        service, *_ = resources(tmp_path, enabled=False)
        try:
            yield service
        finally:
            service.close()
    data = BytesIO()
    page().save(data, "PNG")
    files = {"file": ("page.png", data.getvalue(), "image/png")}
    with TestClient(create_app(factory), base_url="http://localhost") as client:
        initial = client.get("/api/v1/cache").json()
        assert initial["persistent_enabled"] is False
        assert initial["disk_bytes"] == 0
        config = initial["configuration_id"]
        assert len(config) == 64
        assert client.post("/api/v1/cache/settings", json={"enabled": True}).status_code == 403
        assert client.post("/api/v1/cache/settings", json={"enabled": "true"}, headers=headers).status_code == 422
        assert client.post("/api/v1/cache/settings", json={"enabled": True, "path": "secret"}, headers=headers).status_code == 422
        assert client.post("/api/v1/cache/settings", json={"enabled": True, "disk_bytes": 1}, headers=headers).status_code == 422
        assert client.post("/api/v1/cache/settings", content=b"x"*1025, headers=headers).status_code == 413
        assert client.post("/api/v1/cache/clear", headers={**headers, "Origin": "https://attacker.example"}).status_code == 403
        assert client.get("/api/v1/cache", headers={"Host": "attacker.example"}).status_code == 400
        assert client.post("/api/v1/cache/settings", json={"enabled": True}, headers=headers).json()["persistent_enabled"] is True
        rendered = client.post("/api/v1/render-page?configuration="+config, files=files, headers=headers)
        assert rendered.status_code == 200
        assert client.get("/api/v1/cache").json()["configuration_id"] == config
        assert client.post("/api/v1/render-page?refresh=translation", files=files, headers=headers).status_code == 200
        assert client.post("/api/v1/render-page?refresh=wrong", files=files, headers=headers).status_code == 422
        assert client.post("/api/v1/render-page?configuration="+"0"*64, files=files, headers=headers).status_code == 409
        cleared = client.post("/api/v1/cache/clear", headers=headers).json()
        assert cleared["memory_bytes"] == cleared["disk_bytes"] == 0
        assert client.post("/api/v1/cache/settings", json={"enabled": False}, headers=headers).status_code == 200


def test_checked_json_corruption_and_storage_errors_fall_back(tmp_path, monkeypatch):
    service, counts, *_ = resources(tmp_path, memory=0)
    service.translate_and_render_page(page())
    db = service.cache._db
    import hashlib
    with db:
        db.execute("UPDATE entries SET payload=?,checksum=? WHERE stage='ocr'", (b"{}", hashlib.sha256(b"{}").hexdigest()))
    counts.clear()
    service.translate_and_render_page(page())
    assert counts["ocr"] == 2
    service.close()
    # Read-only/unavailable persistence must not prevent normal processing.
    path = tmp_path / "not-a-directory"
    path.write_text("file", encoding="utf-8")
    fallback, calls, *_ = resources(path)
    result = fallback.translate_and_render_page(page())
    assert calls["detection"] == 1
    assert result.diagnostics["cache"]["error_code"] == "storage_unavailable"
    fallback.close()


def test_ordered_translation_contract_and_sensitive_metadata_are_preserved_safely(tmp_path):
    from yomiscan.cache_identity import result_metadata
    assert "C:" not in str(result_metadata({"artifact": "C:\\private\\model.gguf", "token": "secret", "batch_size": 2}))
    assert "secret" not in str(result_metadata({"token": "secret"}))
    service, counts, *_ = resources(tmp_path)
    first = service.analyze_page(page())
    second = service.analyze_page(page())
    assert [b.analysis.translation.translated_text for b in first.text_blocks] == ["Cat 0", "Cat 1"]
    assert [b.analysis.translation.translated_text for b in second.text_blocks] == ["Cat 0", "Cat 1"]
    assert counts["translation"] == 1 and counts["individual"] == 0
    service.close()


def test_performance_runner_rejects_overwriting_input_before_loading_models(tmp_path, monkeypatch):
    import runpy
    import sys
    source = tmp_path/"source.png"
    buffer = BytesIO()
    page().save(buffer, "PNG")
    original = buffer.getvalue()
    source.write_bytes(original)
    monkeypatch.setattr(sys, "argv", ["benchmark_page_cache.py", str(source), "--cache-directory", str(tmp_path/"cache"),
                                     "--output", str(source)])
    with pytest.raises(SystemExit) as exc:
        runpy.run_path(str(Path(__file__).resolve().parents[2]/"scripts"/"benchmark_page_cache.py"), run_name="__main__")
    assert exc.value.code == 2
    assert source.read_bytes() == original
    assert not (tmp_path/"cache").exists()
