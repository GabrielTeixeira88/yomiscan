"""Public OCR interface and initial engine implementation."""

from .base import OCREngine, OCRInitializationError, OCRRecognitionError, OCRResult
from .manga_ocr import MangaOCREngine

__all__ = [
    "OCREngine", "OCRResult", "OCRInitializationError", "OCRRecognitionError",
    "MangaOCREngine",
]
