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
from .detection import ComicTextDetector, TextDetector
from .page import PageAnalysisService, PageAnalysisResult
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .rendering.base import PageRenderResult
    from .rendering.service import PageTranslationRenderService


class ImageAnalysisService:
    def __init__(self, ocr: OCREngine, analyzer: TextAnalyzer, *,
                 detector: TextDetector | None = None, device: Device = "auto") -> None:
        self._ocr = ocr
        self._analyzer = analyzer
        self._detector = detector
        self._device = device
        self._page_service: PageAnalysisService | None = None
        self._render_service: PageTranslationRenderService | None = None

    def analyze_image(self, image: Image.Image) -> ImageAnalysisResult:
        return analyze_image(image, self._ocr, self._analyzer)

    def analyze_page(self, image: Image.Image) -> PageAnalysisResult:
        # Lazy initialization on the same owning worker: Study Mode never needs this model.
        if self._page_service is None:
            detector = self._detector if self._detector is not None else ComicTextDetector(device=self._device)
            self._page_service = PageAnalysisService(detector, self._ocr, self._analyzer)
        return self._page_service.analyze_page(image)

    def translate_and_render_page(self, image: Image.Image, analysis: PageAnalysisResult | None = None,
                                  *, debug: bool = False) -> "PageRenderResult":
        if self._render_service is None:
            from .rendering.renderer import ConservativePageRenderer
            from .rendering.service import PageTranslationRenderService
            self._render_service = PageTranslationRenderService(self, ConservativePageRenderer())
        return self._render_service.translate_and_render_page(image, analysis, debug=debug)


@contextmanager
def open_local_service(
    dictionary_path: Path = Path("data/jmdict.sqlite3"), *, device: Device = "auto",
) -> Iterator[ImageAnalysisService]:
    """Create, use, and close this context on the same owning worker thread."""
    with SQLiteDictionary(dictionary_path) as dictionary:
        tokenizer = FugashiTokenizer()
        translator = MarianTranslationEngine(device=device)
        ocr = MangaOCREngine(force_cpu=device == "cpu")
        yield ImageAnalysisService(ocr, TextAnalyzer(tokenizer, dictionary, translator), device=device)
