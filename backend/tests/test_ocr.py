import sys
from types import SimpleNamespace
from unittest.mock import Mock

from PIL import Image
import pytest

from yomiscan.ocr import (
    MangaOCREngine, OCREngine, OCRInitializationError, OCRRecognitionError, OCRResult,
)


def test_adapter_reuses_model_and_returns_contract(monkeypatch):
    model = Mock(return_value="面白い")
    factory = Mock(return_value=model)
    monkeypatch.setitem(sys.modules, "manga_ocr", SimpleNamespace(MangaOcr=factory))
    engine: OCREngine = MangaOCREngine(force_cpu=True)
    with Image.new("RGB", (10, 10)) as image:
        first = engine.recognize(image)
        second = engine.recognize(image)
    factory.assert_called_once_with(force_cpu=True)
    assert model.call_count == 2
    assert first.text == second.text == "面白い"
    assert first.engine == "manga-ocr"
    assert first.processing_time_ms >= 0
    first.metadata["test"] = True
    assert second.metadata == {}


def test_initialization_failure_preserves_cause(monkeypatch):
    cause = OSError("weights unavailable")
    monkeypatch.setitem(sys.modules, "manga_ocr", SimpleNamespace(MangaOcr=Mock(side_effect=cause)))
    with pytest.raises(OCRInitializationError, match="weights unavailable") as caught:
        MangaOCREngine()
    assert caught.value.__cause__ is cause


def test_recognition_failure_preserves_cause(monkeypatch):
    cause = RuntimeError("inference failed")
    factory = Mock(return_value=Mock(side_effect=cause))
    monkeypatch.setitem(sys.modules, "manga_ocr", SimpleNamespace(MangaOcr=factory))
    engine = MangaOCREngine()
    with Image.new("RGB", (10, 10)) as image:
        with pytest.raises(OCRRecognitionError, match="inference failed") as caught:
            engine.recognize(image)
    assert caught.value.__cause__ is cause


def test_result_supports_engine_metadata():
    result = OCRResult("日本語", "alternative", 12.5, {"device": "cpu"})
    assert result.metadata["device"] == "cpu"
    assert result.text == "日本語"
