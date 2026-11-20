"""Render cache encoding; image bytes are bounded PNG, metadata is typed JSON."""

from dataclasses import dataclass, asdict
from io import BytesIO
from copy import deepcopy
from time import perf_counter
from PIL import Image
from pydantic import TypeAdapter, ValidationError

from ..cache import CacheRequest, pixel_identity
from ..cache_identity import component_identity, result_metadata
from ..page import PageAnalysisResult
from .base import BlockRenderStatus, PageRenderResult, RenderProcessing, PageRenderer


@dataclass(frozen=True)
class StoredRender:
    blocks: tuple[BlockRenderStatus, ...]
    diagnostics: dict[str, object]


def cached_render(renderer: PageRenderer, image: Image.Image, analysis: PageAnalysisResult,
                  cache: CacheRequest | None, *, debug: bool) -> PageRenderResult:
    identity = component_identity(renderer) if cache and not debug else None
    # Renderer consumes geometry/text/status, not tokens or dictionary definitions.
    # Keep model/extraction lineage so a changed stage also invalidates descendants.
    semantic = [{k: v for k, v in asdict(block).items() if k not in ("analysis", "ocr_ms", "ocr_metadata")} |
                {"ocr_metadata": result_metadata(block.ocr_metadata)} |
                {"translation": {k: v for k, v in asdict(block.analysis.translation).items() if k != "processing_time_ms"}
                 if block.analysis and block.analysis.translation else None} for block in analysis.text_blocks]
    for block in semantic:
        if block["translation"]:
            block["translation"]["metadata"] = result_metadata(block["translation"]["metadata"])
    lineage = [(s["stage"], s["key"]) for s in cache.stages if s["stage"] in ("detection", "ocr", "translation")] if cache else []
    # Unidentified upstream input must not gain a persistent identity at rendering.
    valid = all(key is not None for _, key in lineage)
    key = None
    if cache and identity is not None and valid:
        key = cache.key("render", pixel_identity(image), semantic, [asdict(r) for r in analysis.regions],
                        analysis.filtered_regions, identity, lineage)
    payload = cache.get("render", key) if cache else None
    if payload is not None:
        try:
            length = int.from_bytes(payload[:4], "big")
            if not 0 < length <= 2*1024*1024 or length+4 >= len(payload):
                raise ValueError("Invalid cached render header")
            metadata = TypeAdapter(StoredRender).validate_json(payload[4:4+length])
            with Image.open(BytesIO(payload[4+length:])) as saved:
                if saved.format != "PNG" or saved.size != image.size or saved.mode != image.mode:
                    raise ValueError("Cached render dimensions/mode differ")
                restored = saved.copy()
            result = PageRenderResult(restored, metadata.blocks, RenderProcessing(0, 0, 0, 0),
                                      asdict(analysis.processing), diagnostics=metadata.diagnostics)
            return result
        except (ValidationError, ValueError, OSError):
            cache.invalid("render", key)
    start = perf_counter()
    result = renderer.render(image, analysis, debug=debug)
    if cache:
        cache.stages[-1]["compute_ms"] = (perf_counter()-start)*1000
        details = result.diagnostics.get("blocks", {})
        failed = any(b.status == "error" for b in analysis.text_blocks) or (isinstance(details, dict) and
            any(isinstance(d, dict) and any(d.get(s) == "error" for s in ("mask", "typesetting", "inpainting", "layout")) for d in details.values()))
        if not failed and not debug:
            safe_diagnostics = deepcopy(result.diagnostics)
            for detail in safe_diagnostics.get("blocks", {}).values():
                for field in ("ocr_metadata", "translation_metadata"):
                    if isinstance(detail.get(field), dict):
                        detail[field] = result_metadata(detail[field])
            encoded = TypeAdapter(StoredRender).dump_json(StoredRender(result.blocks, safe_diagnostics))
            png = BytesIO()
            result.rendered_image.save(png, format="PNG")
            if len(encoded) <= 2*1024*1024:
                cache.put("render", key, len(encoded).to_bytes(4, "big")+encoded+png.getvalue())
    return result
