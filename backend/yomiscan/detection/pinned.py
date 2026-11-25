"""Torch-free RT-DETR-v2 comic text detector on the pinned fp32 ONNX export (Stage 5b).

fp32 reproduced the PyTorch boxes on 225/226 regions on CPU and 226/226 on DirectML; the
browser's fp16 file shifted most boxes by a pixel. The export is the production model (ogkalu/comic-text-and-bubble-detector at MODEL_REVISION),
so preprocessing and decoding reproduce RTDetrImageProcessorPil and
post_process_object_detection (focal loss: sigmoid, top-300 over queries x classes, float32
corners scaled by width/height) before the shared decode_regions.
"""

import math
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image

from .base import DetectionError, DetectionInitializationError, TextRegion
from .rtdetr import MODEL_ID, MODEL_REVISION, decode_regions

COMPONENT = "detector-fp32"
FILE = "detector-fp32/detector.onnx"
SIZE = 640
QUERIES = 300


def detector_pixels(image: Image.Image) -> np.ndarray:
    """RTDetrImageProcessorPil: PIL bilinear resize to 640x640, rescale 1/255, no normalization."""
    resized = np.asarray(image.convert("RGB").resize((SIZE, SIZE), Image.Resampling.BILINEAR), dtype=np.float64)
    return np.ascontiguousarray((resized * (1 / 255)).astype(np.float32).transpose(2, 0, 1)[None])


def post_process(logits: np.ndarray, boxes: np.ndarray, size: tuple[int, int],
                 threshold: float) -> tuple[list[list[float]], list[float], list[int]]:
    """transformers RT-DETR post_process_object_detection (use_focal_loss=True) for one image."""
    logits = np.asarray(logits, dtype=np.float32).reshape(QUERIES, -1)
    classes = logits.shape[1]
    scores = (1 / (1 + np.exp(-logits))).astype(np.float32).reshape(-1)
    order = np.lexsort((np.arange(scores.size), -scores))[:QUERIES]  # score descending, index on ties
    width, height = size
    scale = np.array([width, height, width, height], dtype=np.float32)
    kept_boxes, kept_scores, kept_labels = [], [], []
    for index in order:
        score = scores[index]
        if not score > threshold:
            continue
        cx, cy, w, h = np.asarray(boxes, dtype=np.float32).reshape(QUERIES, 4)[index // classes]
        half = np.float32(.5)
        corners = np.array([cx - half * w, cy - half * h, cx + half * w, cy + half * h], dtype=np.float32) * scale
        kept_boxes.append([float(v) for v in corners])
        kept_scores.append(float(score))
        kept_labels.append(int(index % classes))
    return kept_boxes, kept_scores, kept_labels


class PinnedComicTextDetector:
    def __init__(self, *, device: str = "cpu", threshold: float = .5, bubble_threshold: float | None = None,
                 free_threshold: float | None = None, threads: int = 4, model_root: Path | None = None,
                 session: Any = None) -> None:
        self.bubble_threshold = threshold if bubble_threshold is None else bubble_threshold
        self.free_threshold = threshold if free_threshold is None else free_threshold
        if any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) or not 0 < v <= 1
               for v in (threshold, self.bubble_threshold, self.free_threshold)):
            raise ValueError("Detection thresholds must be in (0, 1]")
        self.threshold, self.device, self.threads = threshold, device, threads
        self._cache_artifacts: dict[str, str] | None = None
        try:
            if session is None:
                from ..engine_models import component_directory, load_bundle
                from ..onnx_runtime import session as onnx_session
                bundle = load_bundle()
                folder = component_directory(COMPONENT, bundle=bundle, root=model_root)
                session = onnx_session(folder / FILE, threads=threads, device=device)  # type: ignore[arg-type]
                self._cache_artifacts = {f.path: f.sha256 for f in bundle.components[COMPONENT].files}
            names = {i.name for i in session.get_inputs()}
            outputs = {o.name for o in session.get_outputs()}
            if names != {"pixel_values"} or not {"logits", "pred_boxes"} <= outputs:
                raise ValueError("Detector export does not have pixel_values -> logits, pred_boxes")
        except Exception as exc:
            raise DetectionInitializationError(f"Cannot initialize the Torch-free detector on {device}: {exc}") from exc
        self._session = session

    def diagnostic_metadata(self) -> dict[str, object]:
        return {"engine": "pinned-onnx", "model": MODEL_ID, "revision": MODEL_REVISION, "artifact": FILE,
                "device": self.device, "threshold": self.threshold, "bubble_threshold": self.bubble_threshold,
                "free_threshold": self.free_threshold, "threads": self.threads}

    def close(self) -> None:
        self._session = None

    def detect(self, image: Image.Image) -> list[TextRegion]:
        if not isinstance(image, Image.Image) or min(image.size) < 1:
            raise ValueError("Detector expects a nonempty Pillow image")
        try:
            logits, boxes = self._session.run(["logits", "pred_boxes"], {"pixel_values": detector_pixels(image)})
            found = post_process(logits, boxes, image.size, min(self.bubble_threshold, self.free_threshold))
            return decode_regions(*found, image.size, bubble_threshold=self.bubble_threshold,
                                  free_threshold=self.free_threshold)
        except Exception as exc:
            raise DetectionError(f"Torch-free comic text detection failed on {self.device}: {exc}") from exc
