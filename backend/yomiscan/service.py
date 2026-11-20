"""Application composition shared by transports; no HTTP-specific logic."""

from contextlib import contextmanager, ExitStack
from collections.abc import Iterator
from pathlib import Path
import os

from PIL import Image

from .analysis import ImageAnalysisResult, TextAnalyzer, analyze_image
from .dictionary import SQLiteDictionary
from .nlp import FugashiTokenizer
from .ocr import MangaOCREngine, OCREngine
from .translation.factory import create_translation_engine
from .translation.base import Device
from .detection import TextDetector
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

    def diagnostic_models(self) -> dict[str, object]:
        from .diagnostics import model_info
        detector = self._page_service.detector if self._page_service is not None else self._detector
        describe_detector = getattr(detector, "diagnostic_metadata", None)
        detection_metadata = describe_detector() if callable(describe_detector) else {"model": None}
        if not isinstance(detection_metadata, dict):
            detection_metadata = {"model": None}
        describe_ocr = getattr(self._ocr, "diagnostic_metadata", None)
        ocr_metadata = describe_ocr() if callable(describe_ocr) else (
            {"engine": "manga-ocr", "revision": None} if isinstance(self._ocr, MangaOCREngine) else {"engine": None})
        if not isinstance(ocr_metadata, dict):
            ocr_metadata = {"engine": None}
        settings: dict[str, object] = {"analysis_device": self._device, "target_language": "en"}
        if self._page_service is not None:
            settings.update(padding=self._page_service.config.padding, minimum_side=self._page_service.config.minimum_side)
        if self._render_service is not None:
            from .rendering.renderer import ConservativePageRenderer
            from .rendering.typesetting import PillowTypesetter
            renderer = self._render_service.renderer
            if isinstance(renderer, ConservativePageRenderer) and isinstance(renderer.typesetter, PillowTypesetter):
                font = renderer.typesetter
                settings.update(minimum_font_size=font.minimum_size, maximum_font_size=font.maximum_size,
                                preferred_font_size=font.preferred_size, font_margin=font.margin)
        return {"translation": model_info(self._analyzer.translation_metadata()),
                "detection": model_info(detection_metadata), "ocr": model_info(ocr_metadata),
                "settings": settings}

    def analyze_image(self, image: Image.Image) -> ImageAnalysisResult:
        return analyze_image(image, self._ocr, self._analyzer)

    def close(self) -> None:
        detector = self._page_service.detector if self._page_service is not None else self._detector
        self._page_service = self._render_service = self._detector = None
        close = getattr(detector, "close", None)
        if callable(close):
            close()

    def analyze_page(self, image: Image.Image) -> PageAnalysisResult:
        # Lazy initialization on the same owning worker: Study Mode never needs this model.
        if self._page_service is None:
            from .detection.factory import create_detector
            detector = self._detector if self._detector is not None else create_detector(device=self._device)
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
    with SQLiteDictionary(dictionary_path) as dictionary, ExitStack() as cleanup:
        tokenizer = FugashiTokenizer()
        translator = create_translation_engine(device=device)
        close = getattr(translator, "close", None)
        if callable(close):
            cleanup.callback(close)
        if os.environ.get("YOMISCAN_OCR", "current") == "current":
            ocr = MangaOCREngine(force_cpu=device == "cpu")
        else:
            from .ocr.factory import create_ocr_engine
            ocr = create_ocr_engine(device=device)
        close = getattr(ocr, "close", None)
        if callable(close):
            cleanup.callback(close)
        service = ImageAnalysisService(ocr, TextAnalyzer(tokenizer, dictionary, translator), device=device)
        cleanup.callback(service.close)
        yield service
