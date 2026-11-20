"""Report snapshots reuse processing results; no models or copyrighted fixtures."""

from dataclasses import replace
from io import BytesIO
import json
from zipfile import ZipFile
from contextlib import contextmanager
from hashlib import sha256
from unittest.mock import Mock

import pytest
from PIL import Image

from yomiscan.detection import BoundingBox, TextRegion
from yomiscan.page import PageAnalysisResult, PageProcessing, TextBlock
from yomiscan.rendering import ConservativePageRenderer
from yomiscan.rendering.service import PageTranslationRenderService
from yomiscan.diagnostics import page_snapshot, render_bundle
from yomiscan.api.main import create_app
from yomiscan.service import ImageAnalysisService
from yomiscan.analysis import TextAnalyzer
from yomiscan.ocr import OCRResult, OCRRecognitionError
from yomiscan.translation import TranslationError, TranslationResult
from yomiscan.page import PageAnalysisService
from yomiscan.rendering.base import InpaintingError, MaskGenerationError, TypesettingError
from fastapi.testclient import TestClient


def test_snapshot_and_bundle_preserve_failed_ocr_and_region_lineage_without_inference():
    image = Image.new("RGB", (100, 100), "white")
    box = BoundingBox(10, 10, 50, 70)
    analysis = PageAnalysisResult(100, 100, (TextRegion(7, box, .8),),
        (TextBlock(1, (7,), box, "unknown", 1, status="error", error_message="OCR failed for this block."),),
        PageProcessing(1, 2, 0, 0, 3))

    class ExistingAnalysis:
        def analyze_page(self, image):
            raise AssertionError("Export must not rerun analysis")

    result = PageTranslationRenderService(ExistingAnalysis(), ConservativePageRenderer()).translate_and_render_page(image, analysis)
    snapshot = page_snapshot(image, result, input_sha256="a" * 64)
    assert snapshot["schema_version"] == 1
    assert snapshot["image"]["input_sha256"] == "a" * 64
    assert snapshot["regions"][0]["block_ids"] == [1]
    assert snapshot["blocks"][0]["ocr"]["confidence"] is None
    assert snapshot["blocks"][0]["render"]["reason_code"] == "ocr_failed"
    with ZipFile(BytesIO(render_bundle(result.rendered_image, snapshot))) as archive:
        assert archive.testzip() is None
        assert set(archive.namelist()) == {"rendered.png", "snapshot.json"}
        assert json.loads(archive.read("snapshot.json")) == snapshot
        with Image.open(BytesIO(archive.read("rendered.png"))) as decoded:
            assert decoded.size == (100, 100)


def test_opt_in_render_bundle_keeps_legacy_png_and_localhost_protections():
    image = Image.new("RGB", (20, 30), "white")
    analysis = PageAnalysisResult(20, 30, (), (), PageProcessing(0, 0, 0, 0, 0))
    renderer = PageTranslationRenderService(Mock(), ConservativePageRenderer())
    result = renderer.translate_and_render_page(image, analysis)
    service = ImageAnalysisService(Mock(), TextAnalyzer(Mock(), Mock()))
    service.translate_and_render_page = Mock(return_value=result)
    buffer = BytesIO()
    image.save(buffer, format="PNG")
    data = buffer.getvalue()

    @contextmanager
    def factory():
        yield service

    with TestClient(create_app(factory), base_url="http://127.0.0.1") as client:
        endpoint = "/api/v1/render-page?diagnostics=true"
        assert client.post(endpoint, files={"file": data}).status_code == 403
        headers = {"X-YomiScan-Client": "study-extension-v1"}
        assert client.post(endpoint, files={"file": data}, headers={**headers, "Origin": "https://evil.example"}).status_code == 403
        response = client.post(endpoint, files={"file": data}, headers=headers)
        assert response.status_code == 200
        assert response.headers["content-type"] == "application/zip"
        with ZipFile(BytesIO(response.content)) as archive:
            snapshot = json.loads(archive.read("snapshot.json"))
            assert snapshot["image"]["input_sha256"] == sha256(data).hexdigest()
        assert service.translate_and_render_page.call_count == 1
        response = client.post("/api/v1/render-page", files={"file": data}, headers=headers)
        assert response.headers["content-type"] == "image/png"


@pytest.mark.parametrize("failure", ["ocr", "translation", "mask", "inpainting", "typesetting", "overflow", None])
def test_pipeline_reports_partial_success_and_exact_failure_stage(failure):
    from PIL import ImageDraw, ImageFont
    image = Image.new("RGB", (500, 160), "white")
    draw = ImageDraw.Draw(image)
    for offset in (0, 260):
        draw.rectangle((5 + offset, 5, 234 + offset, 154), outline="black", width=2)
        draw.text((65 + offset, 60), "SOURCE", fill="black", font=ImageFont.load_default(size=22))
    boxes = (BoundingBox(45, 45, 195, 110), BoundingBox(305, 45, 455, 110))
    detector, ocr, translator, tokenizer, dictionary = (Mock() for _ in range(5))
    detector.detect.return_value = [TextRegion(i, box, .9, metadata={"class": "text_bubble"}) for i, box in enumerate(boxes, 1)]
    calls = 0

    def recognize(image):
        nonlocal calls
        calls += 1
        if failure == "ocr" and calls == 2:
            raise OCRRecognitionError("private-path must not be exported")
        return OCRResult("猫" if calls == 1 else "犬", "fake", 1, {
            "confidence": .42, "confidence_method": "mean_token_probability_including_eos",
            "recognition_status": "success", "model": "fixture/ocr", "revision": "abc123",
            "private_url": "https://private-path.example/?token=private-path"})

    def translate(text):
        if failure == "translation" and text == "犬":
            raise TranslationError("output reached limit: private-path")
        return TranslationResult(text, ("long " * 500 if failure == "overflow" and text == "犬" else "Okay."),
                                 "fake", "fake", 1, {"revision": "abc123", "artifact": "C:/private"})

    ocr.recognize.side_effect = recognize
    translator.translate_many.side_effect = lambda texts: [translate(text) for text in texts]
    translator.translate.side_effect = translate
    tokenizer.tokenize.return_value = []
    analyzer = PageAnalysisService(detector, ocr, TextAnalyzer(tokenizer, dictionary, translator))
    renderer = ConservativePageRenderer()
    if failure in ("mask", "typesetting"):
        component, method, error = (renderer.masks, "generate", MaskGenerationError) if failure == "mask" else (
            renderer.typesetter, "draw_text", TypesettingError)
        real_method = getattr(component, method)
        render_calls = 0
        def fail_second(*args, **kwargs):
            nonlocal render_calls
            render_calls += 1
            if render_calls == 2:
                raise error("private-path")
            return real_method(*args, **kwargs)
        setattr(component, method, fail_second)
    if failure == "inpainting":
        real = renderer.inpainter.inpaint
        render_calls = 0
        def inpaint(image, mask):
            nonlocal render_calls
            render_calls += 1
            if render_calls == 2:
                raise InpaintingError("private-path")
            return real(image, mask)
        renderer.inpainter = Mock(inpaint=inpaint)
    result = PageTranslationRenderService(analyzer, renderer).translate_and_render_page(image)
    before = ocr.recognize.call_count
    snapshot = page_snapshot(image, result, input_sha256="b" * 64)
    render_bundle(result.rendered_image, snapshot)
    assert ocr.recognize.call_count == before == 2
    assert snapshot["counts"]["rendered"] == (2 if failure is None else 1)
    assert snapshot["blocks"][0]["ocr"]["confidence"] == .42
    assert snapshot["blocks"][0]["ocr"]["confidence_method"] == "mean_token_probability_including_eos"
    codes = {b["render"]["reason_code"] for b in snapshot["blocks"]}
    expected = {None: "rendered", "ocr": "ocr_failed", "translation": "translation_or_analysis_failed",
                "mask": "mask_failed", "typesetting": "typesetting_failed",
                "inpainting": "inpainting_failed", "overflow": "overflow"}[failure]
    assert expected in codes
    assert "private-path" not in json.dumps(snapshot)
    assert "C:/private" not in json.dumps(snapshot)
    if failure == "translation":
        failed = next(b for b in snapshot["blocks"] if b["translation"]["failure_stage"] == "translation")
        assert failed["translation"]["status"] == "failed"
        assert failed["translation"]["rejected"] is None
        assert failed["translation"]["complete"] is None


def test_missing_information_and_report_size_limits(monkeypatch):
    import yomiscan.diagnostics as diagnostics
    image = Image.new("RGB", (5, 5), "white")
    from yomiscan.rendering.base import PageRenderResult, RenderProcessing
    result = PageRenderResult(image, (), RenderProcessing(0, 0, 0, 0))
    snapshot = page_snapshot(image, result, input_sha256="c" * 64)
    assert snapshot["regions"] == snapshot["blocks"] == []
    monkeypatch.setattr(diagnostics, "MAX_SNAPSHOT_BYTES", 10)
    limited = page_snapshot(image, result, input_sha256="c" * 64)
    assert limited["unavailable"] == "snapshot_size_limit"
    assert limited["image"] == snapshot["image"]
    assert limited["blocks"] == limited["regions"] == []
    with pytest.raises(ValueError, match="2 MiB"):
        render_bundle(image, snapshot)
    monkeypatch.setattr(diagnostics, "MAX_SNAPSHOT_BYTES", 2 * 1024 * 1024)
    monkeypatch.setattr(diagnostics, "MAX_RENDER_BYTES", 10)
    with pytest.raises(ValueError, match="32 MiB"):
        render_bundle(image, snapshot)
