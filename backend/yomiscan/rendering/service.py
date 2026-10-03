"""One callable boundary for future page consumers; no browser or chapter logic."""

from typing import Protocol
from time import perf_counter
from PIL import Image
from yomiscan.page import PageAnalysisResult
from .base import PageRenderer, PageRenderResult


class PageAnalyzer(Protocol):
    def analyze_page(self, image: Image.Image) -> PageAnalysisResult: ...


class PageTranslationRenderService:
    def __init__(self, analyzer: PageAnalyzer, renderer: PageRenderer) -> None:
        self.analyzer, self.renderer = analyzer, renderer

    def translate_and_render_page(self, image: Image.Image, analysis: PageAnalysisResult | None = None,
                                  *, debug: bool = False) -> PageRenderResult:
        start = perf_counter()
        if analysis is None:
            analysis = self.analyzer.analyze_page(image)
        result = self.renderer.render(image, analysis, debug=debug)
        result.analysis_processing["pipeline_total_ms"] = (perf_counter()-start)*1000
        # Keep provenance even without debug images: a filtered/dropped region never
        # reaching rendering must not be confused with a renderer safety decision.
        result.diagnostics["raw_regions"] = [
            {"id": region.id, "bbox": region.bbox.coordinates(), "confidence": region.confidence,
             "class": region.metadata.get("class"),
             "filter_reason": analysis.filtered_regions.get(region.id),
             "block_ids": [b.id for b in analysis.text_blocks if region.id in b.region_ids]}
            for region in analysis.regions]
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
