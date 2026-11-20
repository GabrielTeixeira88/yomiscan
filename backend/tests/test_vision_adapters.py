"""Vision contracts tested with tiny external-runtime doubles, never model weights."""

from types import SimpleNamespace
import numpy as np
from PIL import Image
import pytest


class DetectorSession:
    def get_inputs(self):
        return [SimpleNamespace(name="images", type="tensor(float)", shape=["N", 3, 640, 640]),
                SimpleNamespace(name="orig_target_sizes", type="tensor(int64)", shape=["N", 2])]

    def get_outputs(self):
        return [SimpleNamespace(name=n) for n in ("labels", "boxes", "scores")]

    def run(self, names, feed):
        self.feed = feed
        values = {"labels": np.array([[1, 2, 0]], dtype=np.int64),
            "boxes": np.array([[[-1.4, 2.2, 201, 101], [20, 30, 40, 50], [0, 0, 100, 100]]], dtype=np.float32),
            "scores": np.array([[.35, .4, .99]], dtype=np.float32)}
        return [values[n] for n in names]


def test_onnx_detector_preserves_class_thresholds_rgb_and_original_xy_coordinates():
    from yomiscan.detection.onnx import ONNXComicTextDetector
    session = DetectorSession()
    detector = ONNXComicTextDetector(session=session, bubble_threshold=.25, free_threshold=.5)
    regions = detector.detect(Image.new("RGB", (200, 100), "red"))
    assert len(regions) == 1
    assert regions[0].bbox.coordinates() == (0, 2, 200, 100)
    assert regions[0].metadata["class"] == "text_bubble"
    np.testing.assert_array_equal(session.feed["orig_target_sizes"], [[200, 100]])
    np.testing.assert_array_equal(session.feed["images"][0, :, 0, 0], [1, 0, 0])


class EncoderSession:
    def get_inputs(self):
        return [SimpleNamespace(name="pixel_values", type="tensor(float)", shape=["batch", 3, 224, 224])]

    def get_outputs(self):
        return [SimpleNamespace(name="last_hidden_state")]

    def run(self, names, feed):
        return [np.zeros((1, 197, 192), np.float32)]


class DecoderSession:
    names = [f"past_key_values.{layer}.{part}.{kind}" for layer in range(2)
             for part in ("decoder", "encoder") for kind in ("key", "value")]

    def __init__(self, low_confidence=False):
        self.low_confidence = low_confidence

    def get_inputs(self):
        return [SimpleNamespace(name=n, type="tensor(float)", shape=[1, 12, "past", 64]) for n in self.names]

    def get_outputs(self):
        return [SimpleNamespace(name="logits"), *[SimpleNamespace(name=n.replace("past_key_values", "present")) for n in self.names]]

    def run(self, names, feed):
        cached = bool(feed["use_cache_branch"][0])
        length = feed[self.names[0]].shape[2] + feed["input_ids"].shape[1]
        if cached:
            assert feed["input_ids"].tolist() == [[5]]
            assert feed["past_key_values.0.encoder.key"].shape[2] == 197
        chosen = 3 if length > 1 else 5
        logits = np.full((1, 1, 6), 0 if self.low_confidence else -20, np.float32)
        logits[0, 0, chosen] = .2 if self.low_confidence else 20
        values = {"logits": logits}
        for n in self.names:
            count = length if ".decoder." in n else (0 if cached else 197)
            values[n.replace("past_key_values", "present")] = np.zeros((1, 12, count, 64), np.float32)
        return [values[n] for n in names]


def test_onnx_ocr_resolves_tokens_reuses_cache_and_keeps_confidence_diagnostic(tmp_path):
    from yomiscan.ocr.onnx import ONNXMangaOCREngine
    (tmp_path / "vocab.txt").write_text("[PAD]\n[UNK]\n[CLS]\n[SEP]\n[MASK]\n猫\n", encoding="utf-8")
    engine = ONNXMangaOCREngine(model_dir=tmp_path, encoder=EncoderSession(), decoder=DecoderSession())
    first = engine.recognize(Image.new("RGB", (50, 100), "white"))
    second = engine.recognize(Image.new("RGB", (50, 100), "white"))
    assert first.text == second.text == "猫"
    assert first.metadata["confidence"] > .99
    assert first.metadata["termination"] == "eos"
    assert first.metadata["tokens"] == 2
    assert first.metadata["confidence_method"] == "mean_token_probability_including_eos"
    with pytest.raises(ValueError):
        ONNXMangaOCREngine(max_tokens=0)


def test_transformers_ocr_uses_tokenizer_stop_id_when_model_config_lacks_eos(tmp_path):
    import torch
    from yomiscan.ocr.transformers import TransformersOCREngine
    class Processor:
        def __call__(self, image, **kwargs):
            return SimpleNamespace(pixel_values=torch.zeros((1, 3, 224, 224)))
    class Tokenizer:
        cls_token_id, sep_token_id, pad_token_id = 2, 3, 0
        def decode(self, tokens, **kwargs):
            return "猫"
    class Model:
        generation_config = SimpleNamespace(num_beams=4)
        def generate(self, pixels, **kwargs):
            assert kwargs["eos_token_id"] == 3
            assert kwargs["decoder_start_token_id"] == 2
            return SimpleNamespace(sequences=torch.tensor([[2, 5, 3]]))
    engine = TransformersOCREngine(model=Model(), processor=Processor(), tokenizer=Tokenizer())
    result = engine.recognize(Image.new("RGB", (50, 100), "white"))
    assert result.text == "猫"
    assert result.metadata["confidence"] is None
    assert result.metadata["revision"] == "1e64d5beb41ee6bee72c200838ddb93ad541482a"


def test_low_ocr_confidence_is_reported_without_rejection_and_token_limit_is_explicit(tmp_path):
    from yomiscan.ocr.onnx import ONNXMangaOCREngine
    from yomiscan.ocr import OCRRecognitionError
    (tmp_path / "vocab.txt").write_text("[PAD]\n[UNK]\n[CLS]\n[SEP]\n[MASK]\n猫\n", encoding="utf-8")
    engine = ONNXMangaOCREngine(model_dir=tmp_path, encoder=EncoderSession(), decoder=DecoderSession(True))
    result = engine.recognize(Image.new("RGB", (20, 30)))
    assert result.text == "猫"
    assert 0 < result.metadata["confidence"] < .85
    capped = ONNXMangaOCREngine(model_dir=tmp_path, max_tokens=1, encoder=EncoderSession(), decoder=DecoderSession())
    with pytest.raises(OCRRecognitionError, match="token_limit"):
        capped.recognize(Image.new("RGB", (20, 30)))
    no_cache = ONNXMangaOCREngine(model_dir=tmp_path, use_kv_cache=False, encoder=EncoderSession(), decoder=DecoderSession())
    assert no_cache.recognize(Image.new("RGB", (20, 30))).text == "猫"


def test_missing_optional_models_fail_with_setup_guidance_and_preserved_cause(tmp_path):
    from yomiscan.detection.onnx import ONNXComicTextDetector
    from yomiscan.detection import DetectionInitializationError
    from yomiscan.ocr.onnx import ONNXMangaOCREngine
    from yomiscan.ocr import OCRInitializationError
    with pytest.raises(DetectionInitializationError, match="setup_vision_models") as caught:
        ONNXComicTextDetector(model_path=tmp_path / "missing.onnx")
    assert isinstance(caught.value.__cause__, FileNotFoundError)
    with pytest.raises(OCRInitializationError, match="setup_vision_models") as caught:
        ONNXMangaOCREngine(model_dir=tmp_path)
    assert isinstance(caught.value.__cause__, FileNotFoundError)
