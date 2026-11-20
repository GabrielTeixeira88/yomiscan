"""Explicit selection behind the existing TextDetector interface."""

import os
from ..translation.base import Device
from .base import TextDetector, DetectionInitializationError

DETECTOR_NAMES = ("current", "onnx-int8")


def create_detector(name: str | None = None, *, device: Device = "auto", bubble_threshold: float = .5,
                    free_threshold: float = .5, threads: int | None = None) -> TextDetector:
    name = name or os.environ.get("YOMISCAN_DETECTOR", "current")
    if name == "current":
        from .rtdetr import ComicTextDetector
        if threads is not None:
            import torch
            torch.set_num_threads(threads)
        return ComicTextDetector(device=device, bubble_threshold=bubble_threshold, free_threshold=free_threshold)
    if name == "onnx-int8":
        if device == "cuda":
            raise DetectionInitializationError("The experimental ONNX detector is CPU-only; select --device cpu")
        from .onnx import ONNXComicTextDetector
        return ONNXComicTextDetector(bubble_threshold=bubble_threshold, free_threshold=free_threshold, threads=threads or 4)
    raise ValueError(f"Unknown detector {name!r}; choose {DETECTOR_NAMES}")
