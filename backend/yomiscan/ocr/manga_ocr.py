"""Adapter for manga-ocr; importing this module does not load the model."""

from time import perf_counter

from PIL import Image

from .base import OCRInitializationError, OCRRecognitionError, OCRResult


class MangaOCREngine:
    def __init__(self, *, force_cpu: bool = False) -> None:
        try:
            from manga_ocr import MangaOcr

            self._model = MangaOcr(force_cpu=force_cpu)
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
