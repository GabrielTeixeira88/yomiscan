"""Single-page orchestration. Models and dictionary are injected and reused."""

from dataclasses import dataclass, field, replace
import logging
from time import perf_counter
from typing import Literal
from PIL import Image
from .analysis import TextAnalyzer, TextAnalysisResult
from .detection import BoundingBox, TextDetector, TextRegion
from .japanese import contains_japanese
from .ocr import OCREngine, OCRRecognitionError
from .translation import TranslationError
from .page_layout import group_regions, reading_order
from .cache import CacheRequest, pixel_identity
from .cache_identity import component_identity, algorithm, result_metadata
from pydantic import TypeAdapter, ValidationError
from .ocr import OCRResult
from .translation.options import TranslationOptions, capabilities
from .glossary import GlossaryEntry
from .panel_order import PageOrder, page_order
from threading import Event
from dataclasses import asdict

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class PageConfig:
    padding: int = 4
    minimum_side: int = 3

    def __post_init__(self) -> None:
        if self.padding < 0 or self.minimum_side < 1:
            raise ValueError("padding must be nonnegative; minimum_side must be positive")


@dataclass(frozen=True)
class TextBlock:
    id: int
    region_ids: tuple[int, ...]
    bbox: BoundingBox
    orientation: str
    reading_order: int
    original_text: str = ""
    analysis: TextAnalysisResult | None = None
    confidence: float | None = None
    category: str = "unknown"
    status: Literal["success", "error", "filtered"] = "success"
    error_message: str | None = None
    ocr_engine: str | None = None
    ocr_metadata: dict[str, object] = field(default_factory=dict)
    ocr_ms: float | None = None
    failure_stage: str | None = None
    error_code: str | None = None


@dataclass(frozen=True)
class PageProcessing:
    detection_ms: float
    ocr_ms: float
    translation_ms: float
    analysis_ms: float
    total_ms: float


@dataclass(frozen=True)
class PageAnalysisResult:
    width: int
    height: int
    regions: tuple[TextRegion, ...]
    text_blocks: tuple[TextBlock, ...]
    processing: PageProcessing
    filtered_regions: dict[int, str] = field(default_factory=dict)
    cache: dict[str, object] = field(default_factory=dict)
    translation_settings: dict[str, object] = field(default_factory=dict)
    layout: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class DetectionResult:
    regions: tuple[TextRegion, ...]
    blocks: tuple[TextBlock, ...]
    filtered: dict[int, str]


@dataclass(frozen=True)
class PageExtraction:
    width: int
    height: int
    detection: DetectionResult
    blocks: tuple[TextBlock, ...]
    detection_ms: float
    ocr_ms: float
    lineage: tuple[str | None, ...]


class PageAnalysisService:
    def __init__(self, detector: TextDetector, ocr: OCREngine, analyzer: TextAnalyzer,
                 *, config: PageConfig = PageConfig()) -> None:
        self.detector, self.ocr, self.analyzer, self.config = detector, ocr, analyzer, config

    def extract(self, image: Image.Image, *, cache: CacheRequest | None = None) -> PageExtraction:
        """Detect/group and recognize crops, independently of translation and dictionary."""
        start = perf_counter()
        identity = component_identity(self.detector) if cache else None
        key = cache.key("detection", pixel_identity(image), identity, self.config.minimum_side,
                        algorithm("page.py", "page_layout.py")) if cache and identity is not None else None
        payload = cache.get("detection", key) if cache else None
        detection = None
        if payload is not None:
            try:
                detection = TypeAdapter(DetectionResult).validate_json(payload)
            except ValidationError:
                cache.invalid("detection", key)
        detection_ms = 0.0
        if detection is None:
            detection = self._detect(image)
            detection_ms = (perf_counter() - start) * 1000
            if cache:
                cache.put("detection", key, TypeAdapter(DetectionResult).dump_json(detection))
        blocks, lineage = [], []
        ocr_ms = 0.0
        ocr_identity = component_identity(self.ocr) if cache else None
        for block in detection.blocks:
            box = block.bbox.clipped(*image.size, padding=self.config.padding)
            ocr_start = perf_counter()
            try:
                with image.crop(box.coordinates()) as crop:
                    ocr_key = cache.key("ocr", key, block.id, box.coordinates(), self.config.padding,
                                        pixel_identity(crop), ocr_identity) if cache and key is not None and ocr_identity is not None else None
                    lineage.append(ocr_key)
                    payload = cache.get("ocr", ocr_key) if cache else None
                    recognized = None
                    if payload is not None:
                        try:
                            recognized = replace(TypeAdapter(OCRResult).validate_json(payload), processing_time_ms=0.0)
                        except ValidationError:
                            cache.invalid("ocr", ocr_key)
                    if recognized is None:
                        recognized = self.ocr.recognize(crop)
                        ocr_ms += (perf_counter()-ocr_start)*1000
                        if cache:
                            cache.put("ocr", ocr_key, TypeAdapter(OCRResult).dump_json(replace(recognized, metadata=result_metadata(recognized.metadata))))
                block = replace(block, original_text=recognized.text, ocr_engine=recognized.engine,
                                ocr_metadata=recognized.metadata, ocr_ms=recognized.processing_time_ms)
            except OCRRecognitionError:
                if cache: cache.notify("ocr", "failed")
                logger.exception("Page block %s OCR failed", block.id)
                ocr_ms += (perf_counter()-ocr_start)*1000
                block = replace(block, status="error", error_message="OCR failed for this block.", failure_stage="ocr")
            if block.status != "error" and not contains_japanese(block.original_text):
                block = replace(block, status="filtered", error_message="No Japanese script in OCR output.")
            blocks.append(block)
        return PageExtraction(image.width, image.height, detection, tuple(blocks), detection_ms, ocr_ms, tuple(lineage))

    def _detect(self, image: Image.Image) -> DetectionResult:
        raw = self.detector.detect(image)
        valid, filtered = [], {}
        for region in raw:
            box = region.bbox.clipped(*image.size)
            if min(box.width, box.height) < self.config.minimum_side:
                filtered[region.id] = "Region too small or outside image"
            else:
                valid.append(replace(region, bbox=box))
        blocks = []
        for index, group in enumerate(reading_order(group_regions(valid)), 1):
            confidences = [r.confidence for r in group.regions if r.confidence is not None]
            orientations = {r.orientation for r in group.regions}
            block = TextBlock(index, tuple(r.id for r in group.regions), group.bbox,
                              orientations.pop() if len(orientations) == 1 else "unknown", index,
                              confidence=min(confidences) if confidences else None)
            blocks.append(block)
        return DetectionResult(tuple(raw), tuple(blocks), filtered)

    def analyze_page(self, image: Image.Image, *, cache: CacheRequest | None = None,
                     options: TranslationOptions | None = None, entries: tuple[GlossaryEntry, ...] = (),
                     cancel: Event | None = None) -> PageAnalysisResult:
        start = perf_counter()
        extraction = self.extract(image, cache=cache)
        effective = options or TranslationOptions(target_language=capabilities(self.analyzer._translator).targets[0])
        order_key = cache.key("ordering", pixel_identity(image), [(b.id, asdict(b.bbox)) for b in extraction.blocks],
                              effective.ordering, algorithm("panel_order.py", "page_layout.py")) if cache else None
        payload = cache.get("ordering", order_key) if cache else None
        order = None
        if payload is not None:
            try:
                order = TypeAdapter(PageOrder).validate_json(payload)
                if len(order.block_ids) != len(extraction.blocks) or set(order.block_ids) != {b.id for b in extraction.blocks}:
                    raise ValueError("Cached ordering does not preserve exact block identities")
            except (ValidationError, ValueError):
                cache.invalid("ordering", order_key)
                order = None
        if order is None:
            order = page_order(image, extraction.blocks, effective.ordering)
            if cache:
                cache.put("ordering", order_key, TypeAdapter(PageOrder).dump_json(order))
        by_id = {b.id: b for b in extraction.blocks}
        blocks = [replace(by_id[identifier], reading_order=index) for index, identifier in enumerate(order.block_ids, 1)]
        ocr_lineage = {b.id: key for b, key in zip(extraction.blocks, extraction.lineage, strict=True)}
        analysis_ms = 0.0
        eligible = [i for i, block in enumerate(blocks) if block.status == "success"]
        analysis_start = perf_counter()
        texts = [blocks[i].original_text for i in eligible]
        keywords = {"cache": cache, "lineage": [(blocks[i].id, ocr_lineage[blocks[i].id]) for i in eligible],
                    "options": effective, "entries": entries, "block_ids": [blocks[i].id for i in eligible],
                    "panel_ids": [order.panel_by_block[blocks[i].id] for i in eligible], "cancel": cancel}
        results = self.analyzer.analyze_many(texts, **keywords) if cache or options is not None else self.analyzer.analyze_many(texts)
        elapsed = (perf_counter() - analysis_start) * 1000
        for i, result in zip(eligible, results, strict=True):
            if isinstance(result, Exception):
                blocks[i] = replace(blocks[i], status="error", error_message="Text analysis failed for this block.",
                                    failure_stage="translation" if isinstance(result, TranslationError) else "analysis",
                                    error_code=getattr(result, "code", None))
            else:
                analysis_ms += result.processing_time_ms
                blocks[i] = replace(blocks[i], analysis=result)
        # Batch results share batch latency; summing it per block would overcount.
        translation_ms = max(0.0, elapsed - analysis_ms) if eligible else 0.0
        if cache:
            translation_ms = sum(float(s.get("compute_ms", 0)) for s in cache.stages if s["stage"] == "translation")
        return PageAnalysisResult(image.width, image.height, extraction.detection.regions, tuple(blocks),
                                  PageProcessing(extraction.detection_ms, extraction.ocr_ms, translation_ms, analysis_ms,
                                                 (perf_counter() - start) * 1000), extraction.detection.filtered,
                                  cache.metadata() if cache else {},
                                  {"target_language": effective.target_language, "translation_mode": effective.mode,
                                   "context_policy": effective.context, "ordering": effective.ordering,
                                   "glossary_enabled": effective.glossary_enabled,
                                   "glossary_application": "hints" if effective.glossary_enabled and capabilities(self.analyzer._translator).glossary_hints else
                                        "unsupported" if effective.glossary_enabled else "none"}, asdict(order))
