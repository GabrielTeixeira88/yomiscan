"""Application composition shared by transports; no HTTP-specific logic."""

from contextlib import contextmanager
from collections.abc import Iterator
from pathlib import Path

from PIL import Image

from .analysis import ImageAnalysisResult, TextAnalyzer, analyze_image
from .dictionary import SQLiteDictionary
from .nlp import FugashiTokenizer
from .ocr import MangaOCREngine, OCREngine
from .translation import MarianTranslationEngine
from .translation.base import Device


class ImageAnalysisService:
    def __init__(self, ocr: OCREngine, analyzer: TextAnalyzer) -> None:
        self._ocr = ocr
        self._analyzer = analyzer

    def analyze_image(self, image: Image.Image) -> ImageAnalysisResult:
        return analyze_image(image, self._ocr, self._analyzer)


@contextmanager
def open_local_service(
    dictionary_path: Path = Path("data/jmdict.sqlite3"), *, device: Device = "auto",
) -> Iterator[ImageAnalysisService]:
    """Create, use, and close this context on the same owning worker thread."""
    with SQLiteDictionary(dictionary_path) as dictionary:
        tokenizer = FugashiTokenizer()
        translator = MarianTranslationEngine(device=device)
        ocr = MangaOCREngine(force_cpu=device == "cpu")
        yield ImageAnalysisService(ocr, TextAnalyzer(tokenizer, dictionary, translator))
