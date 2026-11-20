"""Effective settings of every optional vision adapter, without loading weights."""

from types import SimpleNamespace
from pathlib import Path
import json
import pytest

from yomiscan.cache import digest
from yomiscan.cache_identity import component_identity, loaded_hf_identity
from yomiscan.detection.rtdetr import ComicTextDetector
from yomiscan.detection.onnx import ONNXComicTextDetector
from yomiscan.ocr.manga_ocr import MangaOCREngine
from yomiscan.ocr.onnx import ONNXMangaOCREngine
from yomiscan.ocr.transformers import TransformersOCREngine
from yomiscan.rendering.renderer import ConservativePageRenderer


class Generation:
    num_beams = 2
    def to_dict(self):
        return {"num_beams": self.num_beams, "do_sample": False}


@pytest.mark.parametrize("cls,field,new", [
    (ComicTextDetector, "bubble_threshold", .4), (ComicTextDetector, "free_threshold", .3),
    (ONNXComicTextDetector, "threads", 2), (ONNXComicTextDetector, "bubble_threshold", .4),
    (ONNXComicTextDetector, "free_threshold", .4),
    (TransformersOCREngine, "variant", "ocr-original"), (TransformersOCREngine, "grayscale", True),
    (TransformersOCREngine, "decoding", "greedy"), (TransformersOCREngine, "max_tokens", 64),
    (ONNXMangaOCREngine, "max_tokens", 64), (ONNXMangaOCREngine, "grayscale", True),
    (ONNXMangaOCREngine, "use_kv_cache", False), (ONNXMangaOCREngine, "threads", 2),
])
def test_optional_vision_effective_configuration_changes_identity(cls, field, new):
    engine = object.__new__(cls)
    engine._cache_artifacts = {"weights": "verified-test-digest"}
    engine.threshold = engine.bubble_threshold = engine.free_threshold = .5
    engine.device, engine.threads = "cpu", 4
    engine.variant, engine.grayscale, engine.decoding = "ocr-2025", False, "published"
    engine.max_tokens, engine.use_kv_cache = 128, True
    engine.model = SimpleNamespace(generation_config=Generation())
    first = component_identity(engine)
    assert first is not None
    setattr(engine, field, new)
    second = component_identity(engine)
    # Published decoding uses its fixed limit; a greedy limit matters only in greedy mode.
    if cls is TransformersOCREngine and field == "max_tokens":
        engine.decoding = "greedy"
        second = component_identity(engine)
    assert digest(first) != digest(second)
    engine._cache_artifacts = {"weights": "another-artifact-digest"}
    assert digest(second) != digest(component_identity(engine))
    engine._cache_artifacts = None
    assert component_identity(engine) is None  # Injected/unverified sessions never gain a pin by name.


def test_original_ocr_uses_actual_local_artifact_and_generation(tmp_path):
    folder = tmp_path / "actual-model"
    folder.mkdir()
    (folder / "config.json").write_text("{}", encoding="utf-8")
    weights = folder / "pytorch_model.bin"
    weights.write_bytes(b"fake-model-v1")
    model = SimpleNamespace(config=SimpleNamespace(_name_or_path=str(folder), _commit_hash=None),
                            device="cpu", generation_config=Generation())
    first_hash = loaded_hf_identity(model, "untrusted-name", None)
    engine = object.__new__(MangaOCREngine)
    engine._model = SimpleNamespace(model=model, processor=SimpleNamespace(to_dict=lambda: {"size": 224}))
    engine._cache_artifacts = first_hash
    first = component_identity(engine)
    assert first and first["artifacts"] == first_hash
    model.generation_config.num_beams = 3
    assert digest(first) != digest(component_identity(engine))
    weights.write_bytes(b"fake-model-v2")
    assert loaded_hf_identity(model, "untrusted-name", None) != first_hash
    # The existing loaded engine still describes its immutable loaded weights.
    assert engine._cache_artifacts == first_hash


def test_renderer_font_and_inpainting_settings_are_independent():
    renderer = ConservativePageRenderer()
    first = component_identity(renderer)
    assert first is not None
    renderer.typesetter.preferred_size -= 1
    second = component_identity(renderer)
    assert digest(first) != digest(second)
    renderer.inpainter.radius += 1
    assert digest(second) != digest(component_identity(renderer))
