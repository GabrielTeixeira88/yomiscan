"""Local comic-trained RT-DETR-v2 adapter; weights are never executed as Python."""

import math
from collections.abc import Sequence
from PIL import Image
from yomiscan.translation.base import Device
from .base import BoundingBox, TextRegion, DetectionError, DetectionInitializationError

MODEL_ID = "ogkalu/comic-text-and-bubble-detector"
MODEL_REVISION = "16e8a622f91fabc6b5b65c96d32d1183f8843546"


def decode_regions(boxes: Sequence[Sequence[float]], scores: Sequence[float],
                   labels: Sequence[int], size: tuple[int, int]) -> list[TextRegion]:
    """Drop bubble outlines; retain text blocks in stable spatial order."""
    candidates = []
    for box, score, label in zip(boxes, scores, labels, strict=True):
        if int(label) not in (1, 2) or not all(math.isfinite(v) for v in [*box, score]):
            continue
        bbox = BoundingBox(math.floor(box[0]), math.floor(box[1]),
                           math.ceil(box[2]), math.ceil(box[3])).clipped(*size)
        if bbox.width <= 0 or bbox.height <= 0:
            continue
        candidates.append((bbox, float(score), int(label)))
    candidates.sort(key=lambda item: (item[0].top, -item[0].right, item[0].bottom, item[0].left, -item[1]))
    return [TextRegion(i, box, score, metadata={"class": "text_bubble" if label == 1 else "text_free",
                                               "granularity": "block"})
            for i, (box, score, label) in enumerate(candidates, 1)]


class ComicTextDetector:
    def __init__(self, *, device: Device = "auto", threshold: float = 0.5) -> None:
        if device not in ("auto", "cpu", "cuda") or not 0 < threshold <= 1:
            raise ValueError("Use device auto/cpu/cuda and threshold in (0, 1].")
        self.threshold = threshold
        try:
            import torch
            from transformers import RTDetrV2ForObjectDetection, RTDetrImageProcessorPil
            if device == "cuda" and not torch.cuda.is_available():
                raise RuntimeError("CUDA unavailable; use cpu or install a compatible PyTorch CUDA build")
            self.device = "cuda" if device != "cpu" and torch.cuda.is_available() else "cpu"
            self._torch = torch
            self._processor = RTDetrImageProcessorPil.from_pretrained(MODEL_ID, revision=MODEL_REVISION)
            self._model = RTDetrV2ForObjectDetection.from_pretrained(
                MODEL_ID, revision=MODEL_REVISION, use_safetensors=True,
            ).to(self.device).eval()
        except Exception as exc:
            raise DetectionInitializationError(
                f"Cannot load {MODEL_ID}. Run uv sync; check Hugging Face cache/download, memory and device: {exc}"
            ) from exc

    def detect(self, image: Image.Image) -> list[TextRegion]:
        if not isinstance(image, Image.Image) or min(image.size) < 1:
            raise ValueError("Detector expects a nonempty Pillow image")
        try:
            inputs = self._processor(images=image.convert("RGB"), return_tensors="pt").to(self.device)
            with self._torch.inference_mode():
                outputs = self._model(**inputs)
            result = self._processor.post_process_object_detection(
                outputs, threshold=self.threshold, target_sizes=[(image.height, image.width)],
            )[0]
            return decode_regions(result["boxes"].cpu().tolist(), result["scores"].cpu().tolist(),
                                  result["labels"].cpu().tolist(), image.size)
        except Exception as exc:
            raise DetectionError(f"Comic text detection failed on {self.device}: {exc}") from exc
