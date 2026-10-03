"""Transactional block rendering: a failed/uncertain block keeps its original pixels."""

from dataclasses import asdict, replace
import logging
from time import perf_counter
from PIL import Image, ImageChops, ImageDraw
from yomiscan.detection import BoundingBox
from yomiscan.page import PageAnalysisResult
from .base import BlockRenderStatus, InpaintingEngine, InpaintingError, PageRenderResult, RenderProcessing, TypesettingError, MaskGenerationError
from .inpainting import OpenCVInpaintingEngine
from .masks import UniformBackgroundMaskGenerator, intersects
from .typesetting import PillowTypesetter, Typesetter
from .layout_regions import estimate_layout_region
from .coverage import classify_text, failure_stage, coverage_metrics
from .artwork import edged_text_mask

logger = logging.getLogger(__name__)


class ConservativePageRenderer:
    def __init__(self, inpainter: InpaintingEngine | None = None, typesetter: Typesetter | None = None,
                 masks: UniformBackgroundMaskGenerator | None = None) -> None:
        self.inpainter = inpainter if inpainter is not None else OpenCVInpaintingEngine()
        self.typesetter = typesetter if typesetter is not None else PillowTypesetter()
        self.masks = masks if masks is not None else UniformBackgroundMaskGenerator()

    def render(self, image: Image.Image, analysis: PageAnalysisResult, *, debug: bool = False) -> PageRenderResult:
        if image.size != (analysis.width, analysis.height):
            raise ValueError("Analysis dimensions must match the original image")
        start = perf_counter()
        original = image.convert("RGB")
        output = original.copy()
        statuses: list[BlockRenderStatus] = []
        occupied_areas: list[BoundingBox] = []
        mask_ms = inpaint_ms = typeset_ms = 0.0
        raw_page = Image.new("L", image.size) if debug else None
        final_page = Image.new("L", image.size) if debug else None
        inpainted_page = original.copy() if debug else None
        region_map = {r.id: r for r in analysis.regions}
        details = {}
        layout_overlay = original.copy() if debug else None
        for block in analysis.text_blocks:
            reason = None
            classes = {region_map[r].metadata.get("class", "") for r in block.region_ids if r in region_map}
            category, category_reason = classify_text(block.category, block.original_text, classes)
            translation = block.analysis.translation if block.analysis is not None else None
            detail = details[block.id] = {"region_ids": block.region_ids, "detected": True,
                "ocr": "success" if block.original_text else "failed_or_empty",
                "analysis_status": block.status, "analysis_error": block.error_message,
                "translation": "success" if translation and translation.translated_text.strip() else "unavailable", "mask": "not_attempted",
                "mask_method": "uniform_components", "mask_recovery": "not_attempted",
                "typesetting": "not_attempted", "inpainting": "not_attempted",
                "layout": "not_attempted", "bbox": asdict(block.bbox),
                "original_text": block.original_text,
                "translated_text": translation.translated_text if translation else None,
                "category": category, "category_reason": category_reason,
                "ocr_review": "Extreme crop aspect ratio; inspect OCR against source" if block.bbox.height > 8*max(1, block.bbox.width) else None}
            if block.status != "success" or translation is None or not translation.translated_text.strip():
                reason = "No successful translated text"
            elif category == "sfx":
                reason = "Sound effects preserved"
            box = block.bbox.clipped(*image.size)
            neighbors = [b.bbox for b in analysis.text_blocks if b.id != block.id]
            if reason:
                statuses.append(BlockRenderStatus(block.id, "skipped", reason))
                continue
            if min(box.width, box.height) < 3:
                reason = "Invalid or tiny text region"
            elif any(intersects(box, other) for other in neighbors):
                reason = "Overlapping detections preserved"
            elif any(intersects(box.clipped(*image.size, padding=self.masks.config.text_padding), other) for other in neighbors):
                reason = "Text regions too close for safe mask padding"
            if reason:
                statuses.append(BlockRenderStatus(block.id, "skipped", reason))
                continue
            stage = perf_counter()
            try:
                mask = self.masks.generate(original, box)
                # Free text and outlined lettering can sit over gray screentones.
                # Recover only when every dark stroke is isolated by a light halo.
                if not mask.safe and category != "sfx":
                    recovered = edged_text_mask(original, box)
                    detail["mask_recovery"] = "success" if recovered else "No complete light-edged glyph separation"
                    if recovered is not None:
                        mask = recovered
                        detail["mask_method"] = "light_edged_glyphs"
            except MaskGenerationError:
                detail["mask"] = "error"
                logger.exception("Block %s masking failed", block.id)
                mask_ms += (perf_counter()-stage)*1000
                statuses.append(BlockRenderStatus(block.id, "skipped", "Mask generation failed; original preserved"))
                continue
            mask_ms += (perf_counter()-stage)*1000
            if debug:
                raw_page.paste(mask.raw, (mask.crop_box.left, mask.crop_box.top), mask.raw)
            stage = perf_counter()
            obstacles = [other.clipped(*image.size, padding=self.masks.config.text_padding) for other in neighbors]
            try:
                estimated = estimate_layout_region(original, box, mask, obstacles + occupied_areas)
            except TypesettingError:
                logger.exception("Block %s interior estimation failed", block.id)
                detail["layout"] = "error"
                typeset_ms += (perf_counter()-stage)*1000
                statuses.append(BlockRenderStatus(block.id, "skipped", "Layout region estimation failed; original preserved"))
                continue
            detail["layout"] = estimated.kind
            category, category_reason = classify_text(block.category, block.original_text, classes, estimated)
            detail.update(category=category, category_reason=category_reason)
            detail["layout_bbox"] = asdict(estimated.bbox)
            detail["mask_crop_bbox"] = asdict(mask.crop_box)
            bounds = mask.final.getbbox()
            detail["mask_bbox"] = (asdict(BoundingBox(bounds[0]+mask.crop_box.left, bounds[1]+mask.crop_box.top,
                                        bounds[2]+mask.crop_box.left, bounds[3]+mask.crop_box.top)) if bounds else None)
            # An enclosing interior can certify that rejected connected pixels are borders,
            # rather than rejecting a whole bubble because its detector box grazes them.
            safe = mask.safe or (estimated.enclosed and mask.reason == "Text area intersects an outline or connected artwork")
            # Dense glyphs in a small verified bubble are not textured artwork.
            # Require complete separation and uniform remaining paper before relaxing density.
            safe |= (estimated.enclosed and mask.foreground_complete and mask.background_uniform
                     and mask.reason == "Dense foreground or textured background")
            detail["mask"] = "success" if safe else "unsafe"
            detail["mask_check"] = mask.reason
            if not safe:
                typeset_ms += (perf_counter()-stage)*1000
                statuses.append(BlockRenderStatus(block.id, "skipped", mask.reason))
                continue
            # Ordinary free text uses the same tight glyph mask but only a bounded,
            # verified plain placement area. No requirement for an enclosing bubble.
            area = estimated.bbox
            try:
                layout = self.typesetter.layout_text(translation.translated_text, area)
            except TypesettingError as exc:
                detail["typesetting"] = "error"
                logger.warning("Block %s layout failed: %s", block.id, exc, exc_info=True)
                statuses.append(BlockRenderStatus(block.id, "skipped", "Unsupported font characters or layout failure"))
                typeset_ms += (perf_counter()-stage)*1000
                continue
            typeset_ms += (perf_counter()-stage)*1000
            if layout is None:
                detail["typesetting"] = "overflow"
                statuses.append(BlockRenderStatus(block.id, "skipped", "English overflow at the minimum readable font size"))
                continue
            # All edits stay in an isolated crop until inpainting AND drawing succeed.
            crop_box = BoundingBox(min(area.left, mask.crop_box.left), min(area.top, mask.crop_box.top),
                                   max(area.right, mask.crop_box.right), max(area.bottom, mask.crop_box.bottom))
            crop = original.crop(crop_box.coordinates())
            crop_mask = Image.new("L", crop.size)
            crop_mask.paste(mask.final, (mask.crop_box.left-crop_box.left, mask.crop_box.top-crop_box.top))
            stage = perf_counter()
            try:
                cleaned = self.inpainter.inpaint(crop, crop_mask)
                if cleaned.size != crop.size:
                    raise InpaintingError("Inpainting returned incorrect dimensions")
                # Enforce locality even for an alternate engine that modifies unmasked pixels.
                cleaned = Image.composite(cleaned.convert("RGB"), crop, crop_mask)
            except InpaintingError:
                detail["inpainting"] = "error"
                logger.exception("Block %s inpainting failed", block.id)
                statuses.append(BlockRenderStatus(block.id, "skipped", "Inpainting failed; original preserved"))
                inpaint_ms += (perf_counter()-stage)*1000
                continue
            inpaint_ms += (perf_counter()-stage)*1000
            detail["inpainting"] = "success"
            painted = cleaned.copy()
            local_layout = replace(layout, position=(layout.position[0]-crop_box.left, layout.position[1]-crop_box.top))
            stage = perf_counter()
            try:
                color = (0, 0, 0) if sum(mask.background) > 384 else (255, 255, 255)
                self.typesetter.draw_text(painted, local_layout, fill=color)
            except TypesettingError:
                detail["typesetting"] = "error"
                logger.exception("Block %s typesetting failed", block.id)
                statuses.append(BlockRenderStatus(block.id, "skipped", "Typesetting failed; original preserved"))
                typeset_ms += (perf_counter()-stage)*1000
                continue
            typeset_ms += (perf_counter()-stage)*1000
            # Do not overwrite edits in adjacent blocks with a whole overlapping context crop.
            output.paste(cleaned, (crop_box.left, crop_box.top), crop_mask)
            # Measured text is drawn on its own layer and composited only where ink exists.
            ink = ImageChops.difference(painted, cleaned).convert("L").point(lambda p: 255 if p else 0)
            output.paste(painted, (crop_box.left, crop_box.top), ink)
            if debug:
                final_page.paste(mask.final, (mask.crop_box.left, mask.crop_box.top), mask.final)
                inpainted_page.paste(cleaned, (crop_box.left, crop_box.top), crop_mask)
            statuses.append(BlockRenderStatus(block.id, "rendered", font_size=layout.font_size))
            detail["typesetting"] = "success"
            detail["wrapped_text"] = layout.text
            occupied_areas.append(area)
        # Preserve grayscale and alpha where supplied through the library interface.
        if image.mode == "L":
            output = output.convert("L")
        elif image.mode == "RGBA":
            output.putalpha(image.getchannel("A"))
        diagnostics = {"02-raw-mask": raw_page, "03-mask": final_page, "04-inpainted": inpainted_page} if debug else {}
        for status in statuses:
            detail = details[status.block_id]
            detail.update(render=status.status, reason=status.reason, font_size=status.font_size)
            detail["reason_code"] = failure_stage(detail, status.reason)
            if status.status != "rendered":
                logger.info("Page block %s category=%s stage=%s reason=%s", status.block_id,
                            detail["category"], detail["reason_code"], status.reason)
            if debug:
                draw = ImageDraw.Draw(layout_overlay)
                box = BoundingBox(**detail["bbox"])
                color = "green" if status.status == "rendered" else {"bubble": "red", "narration": "red",
                    "artwork_text": "orange", "sfx": "purple"}.get(detail["category"], "gray")
                draw.rectangle(box.coordinates(), outline=color, width=2)
                if "layout_bbox" in detail:
                    draw.rectangle(BoundingBox(**detail["layout_bbox"]).coordinates(), outline="blue", width=2)
                if detail.get("mask_bbox"):
                    draw.rectangle(BoundingBox(**detail["mask_bbox"]).coordinates(), outline="magenta", width=1)
                draw.text((box.left, box.top), f"B{status.block_id} {detail['category']} {detail['reason_code']}", fill=color,
                          stroke_width=1, stroke_fill="white")
        if debug:
            diagnostics["06-layout-status"] = layout_overlay
        return PageRenderResult(output, tuple(statuses), RenderProcessing(mask_ms, inpaint_ms, typeset_ms,
                                (perf_counter()-start)*1000), asdict(analysis.processing), diagnostics,
                                {"blocks": details, "filtered_regions": analysis.filtered_regions,
                                 "coverage": coverage_metrics(details, analysis.filtered_regions)})
