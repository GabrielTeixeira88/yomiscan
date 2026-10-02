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
from .page_layout import group_regions, reading_order

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


class PageAnalysisService:
    def __init__(self, detector: TextDetector, ocr: OCREngine, analyzer: TextAnalyzer,
                 *, config: PageConfig = PageConfig()) -> None:
        self.detector, self.ocr, self.analyzer, self.config = detector, ocr, analyzer, config

    def analyze_page(self, image: Image.Image) -> PageAnalysisResult:
        start = perf_counter()
        raw = self.detector.detect(image)
        detection_ms = (perf_counter() - start) * 1000
        valid, filtered = [], {}
        for region in raw:
            box = region.bbox.clipped(*image.size)
            if min(box.width, box.height) < self.config.minimum_side:
                filtered[region.id] = "Region too small or outside image"
            else:
                valid.append(replace(region, bbox=box))
        blocks = []
        ocr_ms = translation_ms = analysis_ms = 0.0
        for index, group in enumerate(reading_order(group_regions(valid)), 1):
            confidences = [r.confidence for r in group.regions if r.confidence is not None]
            orientations = {r.orientation for r in group.regions}
            block = TextBlock(index, tuple(r.id for r in group.regions), group.bbox,
                              orientations.pop() if len(orientations) == 1 else "unknown", index,
                              confidence=min(confidences) if confidences else None)
            # A grouped crop preserves visual line layout for manga-ocr sentence reconstruction.
            box = group.bbox.clipped(*image.size, padding=self.config.padding)
            ocr_start = perf_counter()
            try:
                with image.crop(box.coordinates()) as crop:
                    recognized = self.ocr.recognize(crop)
                block = replace(block, original_text=recognized.text)
            except OCRRecognitionError:
                logger.exception("Page block %s OCR failed", index)
                block = replace(block, status="error", error_message="OCR failed for this block.")
            finally:
                ocr_ms += (perf_counter() - ocr_start) * 1000
            if block.status == "error":
                blocks.append(block)
                continue
            if not contains_japanese(block.original_text):
                blocks.append(replace(block, status="filtered", error_message="No Japanese script in OCR output."))
                continue
            blocks.append(block)
        eligible = [i for i, block in enumerate(blocks) if block.status == "success"]
        analysis_start = perf_counter()
        results = self.analyzer.analyze_many([blocks[i].original_text for i in eligible])
        elapsed = (perf_counter() - analysis_start) * 1000
        for i, result in zip(eligible, results, strict=True):
            if isinstance(result, Exception):
                blocks[i] = replace(blocks[i], status="error", error_message="Text analysis failed for this block.")
            else:
                analysis_ms += result.processing_time_ms
                blocks[i] = replace(blocks[i], analysis=result)
        # Batch results share batch latency; summing it per block would overcount.
        translation_ms = max(0.0, elapsed - analysis_ms) if eligible else 0.0
        return PageAnalysisResult(image.width, image.height, tuple(raw), tuple(blocks),
                                  PageProcessing(detection_ms, ocr_ms, translation_ms, analysis_ms,
                                                 (perf_counter() - start) * 1000), filtered)
