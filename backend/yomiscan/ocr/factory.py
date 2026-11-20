"""Opt-in OCR experiments; ordinary startup preserves the original manga-ocr path."""

import os
from .base import OCREngine, OCRInitializationError

OCR_NAMES = ("current", "original-rgb", "2025", "2025-greedy", "2025-onnx", "2025-onnx-no-cache")


def create_ocr_engine(name: str | None = None, *, device: str = "auto", threads: int | None = None,
                      pinned: bool = False) -> OCREngine:
    name = name or os.environ.get("YOMISCAN_OCR", "current")
    if name not in OCR_NAMES:
        raise ValueError(f"Unknown OCR engine {name!r}; choose {OCR_NAMES}")
    if device not in ("auto", "cpu", "cuda"):
        raise ValueError("OCR device must be auto, cpu or cuda")
    if name == "current" and device == "cuda":
        import torch
        if not torch.cuda.is_available():
            raise OCRInitializationError("CUDA was explicitly requested but is unavailable; select CPU")
    if name.startswith("2025-onnx"):
        if device == "cuda":
            raise OCRInitializationError("The experimental ONNX OCR is CPU-only; select --device cpu")
        from .onnx import ONNXMangaOCREngine
        return ONNXMangaOCREngine(use_kv_cache=name != "2025-onnx-no-cache", threads=threads or 4)
    if threads is not None:
        import torch
        torch.set_num_threads(threads)
    if name == "current":
        from .manga_ocr import MangaOCREngine
        from ..vision_models import model_directory
        return MangaOCREngine(force_cpu=device == "cpu", model_path=model_directory("ocr-original") if pinned else None)
    from .transformers import TransformersOCREngine
    return TransformersOCREngine(variant="ocr-original" if name == "original-rgb" else "ocr-2025", device=device,
                                 decoding="greedy" if name == "2025-greedy" else "published")
