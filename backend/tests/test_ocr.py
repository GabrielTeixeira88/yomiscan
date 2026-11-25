import sys
from types import SimpleNamespace
from unittest.mock import Mock

from PIL import Image
import pytest

from yomiscan.ocr import (
    MangaOCREngine, OCREngine, OCRInitializationError, OCRRecognitionError, OCRResult,
)


@pytest.mark.reference
def test_adapter_reuses_model_and_returns_contract(monkeypatch):
    model = Mock(return_value="面白い")
    factory = Mock(return_value=model)
    monkeypatch.setitem(sys.modules, "manga_ocr", SimpleNamespace(MangaOcr=factory))
    engine: OCREngine = MangaOCREngine(force_cpu=True, decoding="published")
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


@pytest.mark.reference
def test_recognition_failure_preserves_cause(monkeypatch):
    cause = RuntimeError("inference failed")
    factory = Mock(return_value=Mock(side_effect=cause))
    monkeypatch.setitem(sys.modules, "manga_ocr", SimpleNamespace(MangaOcr=factory))
    engine = MangaOCREngine(decoding="published")
    with Image.new("RGB", (10, 10)) as image:
        with pytest.raises(OCRRecognitionError, match="inference failed") as caught:
            engine.recognize(image)
    assert caught.value.__cause__ is cause


def test_result_supports_engine_metadata():
    result = OCRResult("日本語", "alternative", 12.5, {"device": "cpu"})
    assert result.metadata["device"] == "cpu"
    assert result.text == "日本語"


class _Tokens(list):
    def cpu(self):
        return self


class _Pixels:
    def __getitem__(self, index):
        assert index is None  # batch dimension added exactly as MangaOcr.__call__ does
        return self

    def to(self, device):
        assert device == "cpu"
        return self


def _greedy_engine(monkeypatch, generate):
    """manga-ocr stand-in exposing the pieces MangaOcr.__call__ uses; no weights load."""
    images = []

    def preprocess(image):
        images.append(image.mode)
        return _Pixels()

    library = SimpleNamespace(model=SimpleNamespace(device="cpu", generate=generate), _preprocess=preprocess,
                              tokenizer=SimpleNamespace(decode=lambda tokens, skip_special_tokens: " ".join(tokens)))
    library.model.config = SimpleNamespace(_name_or_path="fake", _commit_hash=None)
    monkeypatch.setitem(sys.modules, "manga_ocr", SimpleNamespace(MangaOcr=Mock(return_value=library)))
    monkeypatch.setitem(sys.modules, "manga_ocr.ocr", SimpleNamespace(post_process=lambda text: "".join(text.split())))
    monkeypatch.setattr("yomiscan.cache_identity.loaded_hf_identity", lambda *args: {"weights": "fake"})
    return MangaOCREngine(), images


def test_greedy_is_default_and_disables_repeat_blocking(monkeypatch):
    calls = []

    def generate(pixels, **options):
        calls.append(options)
        return [_Tokens(["ごめん", "ごめん"])]

    engine, images = _greedy_engine(monkeypatch, generate)
    with Image.new("RGB", (10, 10)) as image:
        result = engine.recognize(image)
    # Repeated words survive: no n-gram ban, a single beam, manga-ocr's own length limit.
    assert result.text == "ごめんごめん"
    assert calls == [{"max_length": 300, "num_beams": 1, "do_sample": False, "no_repeat_ngram_size": 0,
                      "length_penalty": 1.0, "early_stopping": False}]
    assert images == ["RGB"]  # grayscale -> RGB conversion happens before preprocessing
    assert engine.diagnostic_metadata()["decoding"] == "greedy"


def test_greedy_failure_preserves_cause(monkeypatch):
    cause = RuntimeError("generate failed")
    engine, _ = _greedy_engine(monkeypatch, Mock(side_effect=cause))
    with Image.new("RGB", (10, 10)) as image:
        with pytest.raises(OCRRecognitionError, match="generate failed") as caught:
            engine.recognize(image)
    assert caught.value.__cause__ is cause


def test_unknown_decoding_is_rejected():
    with pytest.raises(ValueError, match="greedy or published"):
        MangaOCREngine(decoding="beam")  # type: ignore[arg-type]


@pytest.mark.parametrize("name,decoding", [("current", "greedy"), ("current-published", "published")])
def test_factory_selects_decoding(monkeypatch, name, decoding):
    from yomiscan.ocr import factory, manga_ocr
    created = Mock(return_value="engine")
    monkeypatch.setattr(manga_ocr, "MangaOCREngine", created)
    assert factory.create_ocr_engine(name, device="cpu") == "engine"
    assert created.call_args.kwargs == {"force_cpu": True, "model_path": None, "decoding": decoding}
