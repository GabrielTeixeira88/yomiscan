"""Application composition shared by transports; no HTTP-specific logic."""

from contextlib import contextmanager, ExitStack
from collections.abc import Iterator
from pathlib import Path
import os
from uuid import uuid4
from time import perf_counter

from PIL import Image

from .analysis import ImageAnalysisResult, TextAnalyzer, analyze_image
from .dictionary import SQLiteDictionary
from .nlp import FugashiTokenizer
from .ocr import MangaOCREngine, OCREngine
from .translation.factory import create_translation_engine
from .translation.base import Device
from .detection import TextDetector
from .page import PageAnalysisService, PageAnalysisResult
from .cache import ProcessingCache, CacheRequest, Refresh, digest
from .cache_identity import component_identity
from typing import TYPE_CHECKING
from threading import Event
from dataclasses import asdict
from .glossary import GlossaryStore, GlossaryEntry
from .translation.options import TranslationOptions, capabilities, validate_options, TARGET_NAMES

if TYPE_CHECKING:
    from .rendering.base import PageRenderResult
    from .rendering.service import PageTranslationRenderService


class PageRefreshError(RuntimeError):
    """A forced refresh failed; the caller must retain its previous output."""


class TranslationConfigurationChanged(ValueError):
    """A reader's glossary snapshot is no longer current."""


class ImageAnalysisService:
    def __init__(self, ocr: OCREngine, analyzer: TextAnalyzer, *,
                 detector: TextDetector | None = None, device: Device = "auto",
                 cache: ProcessingCache | None = None, glossaries: GlossaryStore | None = None) -> None:
        self._ocr = ocr
        self._analyzer = analyzer
        self._detector = detector
        self._device = device
        self._page_service: PageAnalysisService | None = None
        self._render_service: PageTranslationRenderService | None = None
        self.cache = cache if cache is not None else ProcessingCache(enabled=False)
        self._generation = uuid4().hex
        # This is a browser session generation, not a persistent stage key.
        # Restarts deliberately invalidate browser results; disk entries remain reusable.
        self._initial_detector = detector
        self._glossaries = glossaries

    @property
    def glossaries(self) -> GlossaryStore:
        if self._glossaries is None:
            path = Path(os.getenv("YOMISCAN_GLOSSARY_DATABASE", "data/glossaries.sqlite3"))
            if path.resolve() in {(self.cache.directory/name).resolve() for name in ("stages.sqlite3", "settings.json")} or (
                path.resolve() == getattr(self._analyzer._dictionary, "_path", None)):
                raise ValueError("Glossary user data must use its own database, separate from dictionaries and processing cache")
            self._glossaries = GlossaryStore(path)
        return self._glossaries

    def translation_profile(self, scope: str = "global", target: str | None = None) -> dict[str, object]:
        support = capabilities(self._analyzer._translator)
        selected_target = target or support.targets[0]
        if selected_target not in TARGET_NAMES:
            raise ValueError("Unknown glossary target language")
        if selected_target not in support.targets:
            selected_target = support.targets[0]
        entries = self.glossaries.entries(scope, selected_target)
        return {"engine": self._analyzer.translation_metadata(), "capabilities": asdict(support),
                "default_target": support.targets[0], "series": self.glossaries.series(),
                "scope": scope, "target_language": selected_target, "entries": [asdict(e) for e in entries],
                "glossary_version": self.glossaries.identity(scope, selected_target),
                "dictionary_language": "en", "configuration_id": self.configuration_id()}

    def _prepare_translation(self, options: TranslationOptions | None) -> tuple[TranslationOptions, tuple[GlossaryEntry, ...]]:
        effective = options or TranslationOptions(target_language=capabilities(self._analyzer._translator).targets[0])
        validate_options(self._analyzer._translator, effective)
        entries = ()
        if effective.glossary_enabled:
            entries = self.glossaries.effective(effective.series_id, effective.target_language)
            version = self.glossaries.identity(effective.series_id, effective.target_language)
            if effective.glossary_version is not None and effective.glossary_version != version:
                raise TranslationConfigurationChanged("Glossary changed; reload translation settings before translating this page")
        return effective, entries

    def configuration_id(self) -> str:
        if self._render_service is None:
            from .rendering.renderer import ConservativePageRenderer
            from .rendering.service import PageTranslationRenderService
            self._render_service = PageTranslationRenderService(self, ConservativePageRenderer())
        renderer = self._render_service.renderer
        translation = self._analyzer.translation_metadata().copy()
        translation.pop("device", None)  # Lazy model loading does not change the selected settings.
        return digest([self._generation, self._device, translation,
                       component_identity(self._ocr),
                       component_identity(self._initial_detector) if self._initial_detector is not None else {
                           key: value for key, value in os.environ.items() if key.startswith("YOMISCAN_") and "CACHE" not in key},
                       component_identity(renderer)])

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
        settings: dict[str, object] = {"analysis_device": self._device, "target_language": capabilities(self._analyzer._translator).targets[0]}
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
        self.cache.close()
        if self._glossaries is not None:
            self._glossaries.close()

    def analyze_page(self, image: Image.Image, *, options: TranslationOptions | None = None,
                     cancel: Event | None = None) -> PageAnalysisResult:
        return self._analyze_page(image, CacheRequest(self.cache), options=options, cancel=cancel)

    def _analyze_page(self, image: Image.Image, request: CacheRequest, *, options: TranslationOptions | None = None,
                      cancel: Event | None = None) -> PageAnalysisResult:
        effective, entries = self._prepare_translation(options)
        # Lazy initialization on the same owning worker: Study Mode never needs this model.
        if self._page_service is None:
            from .detection.factory import create_detector
            detector = self._detector if self._detector is not None else create_detector(device=self._device)
            self._page_service = PageAnalysisService(detector, self._ocr, self._analyzer)
        return self._page_service.analyze_page(image, cache=request, options=effective, entries=entries, cancel=cancel)

    def translate_and_render_page(self, image: Image.Image, analysis: PageAnalysisResult | None = None,
                                  *, debug: bool = False, refresh: Refresh = "none",
                                  options: TranslationOptions | None = None, cancel: Event | None = None) -> "PageRenderResult":
        start = perf_counter()
        if self._render_service is None:
            from .rendering.renderer import ConservativePageRenderer
            from .rendering.service import PageTranslationRenderService
            self._render_service = PageTranslationRenderService(self, ConservativePageRenderer())
        request = CacheRequest(self.cache, refresh)
        if analysis is None:
            analysis = self._analyze_page(image, request, options=options, cancel=cancel)
        if options is not None and options.mode != "sentences" and any(b.status == "error" for b in analysis.text_blocks):
            raise PageRefreshError("Structured page failed; original or previous translation retained")
        if refresh in ("translation", "all") and any(b.status == "error" for b in analysis.text_blocks):
            raise PageRefreshError("Page refresh failed; previous translation retained.")
        result = self._render_service.translate_and_render_page(image, analysis, debug=debug, cache=request)
        result.analysis_processing["pipeline_total_ms"] = (perf_counter()-start)*1000
        if refresh != "none":
            details = result.diagnostics.get("blocks", {})
            if isinstance(details, dict) and any(isinstance(d, dict) and any(d.get(s) == "error" for s in (
                "mask", "typesetting", "inpainting", "layout")) for d in details.values()):
                raise PageRefreshError("Page rendering refresh failed; previous translation retained.")
        return result


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
        cache = ProcessingCache(Path(os.getenv("YOMISCAN_CACHE_DIRECTORY", ".cache/processing")))
        service = ImageAnalysisService(ocr, TextAnalyzer(tokenizer, dictionary, translator), device=device, cache=cache)
        cleanup.callback(service.close)
        yield service
