"""One callable boundary for future page consumers; no browser or chapter logic."""

from typing import Protocol
from time import perf_counter
from PIL import Image
from yomiscan.page import PageAnalysisResult
from .base import PageRenderer, PageRenderResult
from ..cache import CacheRequest
from .cache import cached_render
from dataclasses import asdict
from .settings import RenderSettings


class PageAnalyzer(Protocol):
    def analyze_page(self, image: Image.Image) -> PageAnalysisResult: ...


class PageTranslationRenderService:
    def __init__(self, analyzer: PageAnalyzer, renderer: PageRenderer) -> None:
        self.analyzer, self.renderer = analyzer, renderer

    def translate_and_render_page(self, image: Image.Image, analysis: PageAnalysisResult | None = None,
                                  *, debug: bool = False, cache: CacheRequest | None = None,
                                  settings: RenderSettings = RenderSettings()) -> PageRenderResult:
        start = perf_counter()
        if analysis is None:
            analysis = self.analyzer.analyze_page(image)
        renderer = self.renderer
        if settings.font_scale != 1.0:
            from .renderer import ConservativePageRenderer
            from .typesetting import PillowTypesetter
            if not isinstance(renderer, ConservativePageRenderer) or not isinstance(renderer.typesetter, PillowTypesetter):
                raise ValueError("Selected renderer does not support reader font scaling")
            renderer = ConservativePageRenderer(renderer.inpainter, renderer.typesetter.scaled(settings.font_scale), renderer.masks)
        result = cached_render(renderer, image, analysis, cache, debug=debug)
        result.analysis_processing = asdict(analysis.processing)
        result.analysis_processing["pipeline_total_ms"] = (perf_counter()-start)*1000
        # Keep provenance even without debug images: a filtered/dropped region never
        # reaching rendering must not be confused with a renderer safety decision.
        result.diagnostics["raw_regions"] = [
            {"id": region.id, "bbox": region.bbox.coordinates(), "confidence": region.confidence,
             "class": region.metadata.get("class"),
             "filter_reason": analysis.filtered_regions.get(region.id),
             "block_ids": [b.id for b in analysis.text_blocks if region.id in b.region_ids]}
            for region in analysis.regions]
        result.diagnostics["translation_settings"] = analysis.translation_settings
        result.diagnostics["layout"] = analysis.layout
        result.diagnostics["render_settings"] = asdict(settings)
        # Reuse the lexical and translation results from this exact analysis.
        # It is transported inside the existing explicit text-consent section.
        from ..api.models import ImageAnalysisResponse
        details = result.diagnostics.get("blocks", {})
        for block in analysis.text_blocks:
            detail = details.get(block.id, details.get(str(block.id))) if isinstance(details, dict) else None
            if isinstance(detail, dict) and block.analysis is not None:
                detail["study"] = ImageAnalysisResponse.from_analysis(block.analysis, ocr_ms=block.ocr_ms or 0, origin="page").model_dump()
        if cache:
            # OCR timing belongs to this job, including when the layout came from disk.
            details = result.diagnostics.get("blocks", {})
            for block in analysis.text_blocks:
                detail = details.get(block.id, details.get(str(block.id))) if isinstance(details, dict) else None
                if isinstance(detail, dict):
                    detail["ocr_ms"] = block.ocr_ms
                    if block.analysis and block.analysis.translation:
                        translation = block.analysis.translation
                        detail["translation_metadata"] = {"engine": translation.engine, "model": translation.model, **translation.metadata}
                    detail["translation_error_code"] = block.error_code
            result.diagnostics["cache"] = cache.metadata()
        if debug:
            # Debug drawing is opt-in; normal HTTP rendering saves nothing to disk.
            from PIL import ImageDraw
            overlay = image.convert("RGB")
            draw = ImageDraw.Draw(overlay)
            for region in analysis.regions:
                draw.rectangle(region.bbox.coordinates(), outline="red", width=2)
                draw.text((region.bbox.left, region.bbox.top), str(region.id), fill="red")
            result.debug_images["01-detection"] = overlay
            grouped = image.convert("RGB")
            draw = ImageDraw.Draw(grouped)
            for block in analysis.text_blocks:
                draw.rectangle(block.bbox.coordinates(), outline="orange", width=2)
                draw.text((block.bbox.left, block.bbox.top), f"B{block.id} raw:{','.join(map(str, block.region_ids))}",
                          fill="orange", stroke_width=1, stroke_fill="black")
            result.debug_images["01-grouped-blocks"] = grouped
        return result
