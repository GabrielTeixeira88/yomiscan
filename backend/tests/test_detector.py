from contextlib import nullcontext
import sys
from types import SimpleNamespace
from unittest.mock import Mock

from PIL import Image
import pytest

from yomiscan.detection import ComicTextDetector, DetectionError, DetectionInitializationError


@pytest.fixture
def runtime(monkeypatch):
    torch, processor_type, model_type = Mock(), Mock(), Mock()
    torch.cuda.is_available.return_value = False
    torch.inference_mode.side_effect = nullcontext
    processor, model = Mock(), Mock()
    processor_type.from_pretrained.return_value = processor
    model_type.from_pretrained.return_value = model
    model.to.return_value = model
    model.eval.return_value = model
    processor.return_value.to.return_value = {"pixel_values": "fake"}
    def tensor(value):
        result = Mock()
        result.cpu.return_value.tolist.return_value = value
        return result
    processor.post_process_object_detection.return_value = [{
        "boxes": tensor([[1, 2, 40, 80]]), "scores": tensor([.9]), "labels": tensor([1]),
    }]
    monkeypatch.setitem(sys.modules, "torch", torch)
    monkeypatch.setitem(sys.modules, "transformers", SimpleNamespace(
        RTDetrV2ForObjectDetection=model_type, RTDetrImageProcessorPil=processor_type,
    ))
    return torch, processor_type, model_type, processor, model


def test_detector_loads_once_reuses_resources_and_maps_original_size(runtime):
    torch, processor_type, model_type, processor, model = runtime
    detector = ComicTextDetector()
    image = Image.new("RGB", (200, 300))
    for _ in range(2):
        assert detector.detect(image)[0].bbox.bottom == 80
    assert detector.device == "cpu"
    assert processor_type.from_pretrained.call_count == model_type.from_pretrained.call_count == 1
    assert model.call_count == 2
    assert processor.post_process_object_detection.call_args.kwargs["target_sizes"] == [(300, 200)]
    assert model_type.from_pretrained.call_args.kwargs["use_safetensors"] is True


def test_detector_cuda_selection_and_unavailable_error(runtime):
    torch, *_ = runtime
    with pytest.raises(DetectionInitializationError, match="CUDA unavailable"):
        ComicTextDetector(device="cuda")
    torch.cuda.is_available.return_value = True
    assert ComicTextDetector().device == "cuda"
    assert ComicTextDetector(device="cpu").device == "cpu"


def test_detector_contextual_errors_keep_cause(runtime):
    _, _, model_type, _, model = runtime
    error = RuntimeError("fixture failure")
    model_type.from_pretrained.side_effect = error
    with pytest.raises(DetectionInitializationError) as caught:
        ComicTextDetector()
    assert caught.value.__cause__ is error
    model_type.from_pretrained.side_effect = None
    detector = ComicTextDetector()
    model.side_effect = error
    with pytest.raises(DetectionError) as caught:
        detector.detect(Image.new("RGB", (20, 30)))
    assert caught.value.__cause__ is error


@pytest.mark.parametrize("kwargs", [{"threshold": 0}, {"threshold": 2}, {"device": "invalid"}])
def test_detector_invalid_configuration(kwargs):
    with pytest.raises(ValueError):
        ComicTextDetector(**kwargs)
