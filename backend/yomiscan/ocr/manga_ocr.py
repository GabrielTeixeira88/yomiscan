"""Adapter for manga-ocr; importing this module does not load the model."""

from time import perf_counter
from pathlib import Path

from PIL import Image

from .base import OCRInitializationError, OCRRecognitionError, OCRResult


class MangaOCREngine:
    def __init__(self, *, force_cpu: bool = False, model_path: Path | None = None) -> None:
        try:
            from manga_ocr import MangaOcr

            options = {"pretrained_model_name_or_path": str(model_path)} if model_path is not None else {}
            self._model = MangaOcr(force_cpu=force_cpu, **options)
            from ..cache_identity import loaded_hf_identity
            self._cache_artifacts = loaded_hf_identity(self._model.model, "kha-white/manga-ocr-base", None)
        except Exception as exc:
            # Translate third-party failures at the adapter boundary, preserving cause.
            raise OCRInitializationError(
                f"Could not initialize manga-ocr: {exc}. "
                "Run uv sync and check the model download/cache and available memory."
            ) from exc

    def recognize(self, image: Image.Image) -> OCRResult:
        if not isinstance(image, Image.Image):
            raise TypeError("image must be a Pillow Image")
        start = perf_counter()
        try:
            text = self._model(image)
        except Exception as exc:
            raise OCRRecognitionError(f"manga-ocr recognition failed: {exc}") from exc
        return OCRResult(
            text=text,
            engine="manga-ocr",
            processing_time_ms=(perf_counter() - start) * 1000,
        )

    def close(self) -> None:
        self._model = None
