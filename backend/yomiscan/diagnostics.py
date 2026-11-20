"""Bounded, in-memory transport snapshots. Export consent belongs to the browser UI."""

from dataclasses import asdict
from hashlib import sha256
from importlib.metadata import PackageNotFoundError, version
from io import BytesIO
import json
import math
import os
import re
from typing import Any
from zipfile import ZIP_STORED, ZipFile

from PIL import Image
from .rendering.base import PageRenderResult

SCHEMA_VERSION = 1
MAX_SNAPSHOT_BYTES = 2 * 1024 * 1024
MAX_RENDER_BYTES = 32 * 1024 * 1024
MAX_BUNDLE_BYTES = MAX_RENDER_BYTES + MAX_SNAPSHOT_BYTES + 4096

# Code-owned labels, never exception messages, model responses, paths or URLs.
REASONS = {
    "rendered": "Translated text rendered",
    "ocr_failed": "OCR failed or returned no text",
    "ocr_filtered": "OCR did not contain Japanese script",
    "translation_or_analysis_failed": "Translation or lexical analysis failed or was unavailable",
    "likely_sfx": "Likely sound effect preserved",
    "geometry_conflict": "Overlapping or too-close detections preserved",
    "mask_failed": "Mask generation failed",
    "inseparable_mask": "Text could not be separated safely from connected artwork",
    "unsafe_background": "Dense or textured background could not be masked safely",
    "no_layout_region": "Safe layout region estimation failed",
    "overflow": "Translation did not fit at the minimum readable font size",
    "inpainting_failed": "Inpainting failed; original preserved",
    "typesetting_failed": "Font/layout/typesetting failed; original preserved",
    "invalid_geometry_or_unsupported": "Unsupported or invalid rendering geometry",
}


def identifier(value: object) -> str | None:
    """Only short model/engine IDs, not local paths or arbitrary metadata."""
    if isinstance(value, str) and re.fullmatch(r"[\w.-]+(?:/[\w.-]+)?", value, re.ASCII):
        return value[:160]
    return None


def number(value: object) -> float | None:
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) else None


def model_info(metadata: dict[str, Any]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key in ("engine", "model", "revision", "model_revision", "expected_revision", "base_model", "base_revision", "device",
                "artifact", "source_revision", "preprocessing", "decoding"):
        if key in metadata:
            result[key] = identifier(metadata[key])
    for key in ("batch_size", "num_beams", "context_tokens", "temperature", "seed", "prompt_version",
                "threshold", "bubble_threshold", "free_threshold", "threads", "max_tokens"):
        if key in metadata:
            result[key] = number(metadata[key])
    if isinstance(metadata.get("kv_cache"), bool):
        result["kv_cache"] = metadata["kv_cache"]
    return result


def page_snapshot(image: Image.Image, result: PageRenderResult, *, input_sha256: str,
                  models: dict[str, object] | None = None) -> dict[str, Any]:
    try:
        package_version = version("yomiscan")
    except PackageNotFoundError:
        package_version = "unknown"
    build = os.getenv("YOMISCAN_BUILD_ID", "")
    details = result.diagnostics.get("blocks", {})
    blocks = []
    for block_id, detail in details.items():
        reason_code = detail.get("reason_code", "invalid_geometry_or_unsupported")
        if reason_code not in REASONS:
            reason_code = "invalid_geometry_or_unsupported"
        confidence = number(detail.get("ocr_confidence"))
        ocr_metadata = detail.get("ocr_metadata", {})
        blocks.append({
            "id": int(block_id), "region_ids": list(detail.get("region_ids", [])),
            "bbox": detail.get("bbox"), "reading_order": detail.get("reading_order"),
            "orientation": detail.get("orientation", "unknown"),
            "detection_confidence": number(detail.get("detection_confidence")),
            "ocr": {"status": "filtered" if detail.get("analysis_status") == "filtered" else detail.get("ocr"),
                    "engine": identifier(detail.get("ocr_engine")),
                    "confidence": confidence if confidence is not None and 0 <= confidence <= 1 else None,
                    "processing_ms": number(detail.get("ocr_ms")),
                    "confidence_method": identifier(ocr_metadata.get("confidence_method")),
                    "recognition_status": identifier(ocr_metadata.get("recognition_status")),
                    "termination": identifier(ocr_metadata.get("termination")),
                    "tokens": number(ocr_metadata.get("tokens")), "uncertainty": identifier(ocr_metadata.get("uncertainty")),
                    **model_info(ocr_metadata)},
            "translation": {"status": "failed" if detail.get("failure_stage") == "translation" else detail.get("translation"),
                            "failure_stage": detail.get("failure_stage"),
                            # TranslationError also covers transport/inference failures. Neither
                            # rejection nor generation completeness can be inferred from it.
                            "rejected": None, "complete": None,
                            **model_info(detail.get("translation_metadata", {}))},
            "render": {"status": detail.get("render"), "reason_code": reason_code, "reason": REASONS[reason_code],
                       "mask": detail.get("mask"), "mask_method": detail.get("mask_method"),
                       "inpainting": detail.get("inpainting"), "layout": detail.get("layout"),
                       "layout_bbox": detail.get("layout_bbox"), "typesetting": detail.get("typesetting"),
                       "font_size": detail.get("font_size"), "category": detail.get("category")},
            # Only this explicit section is eligible for the opt-in text export.
            "text": {"original": detail.get("original_text"), "translation": detail.get("translated_text"),
                     "translation_input": detail.get("translation_input")},
        })
    regions = [
        {"id": r["id"], "bbox": list(r["bbox"]), "confidence": number(r.get("confidence")),
         "class": r.get("class"), "filtered": bool(r.get("filter_reason")), "block_ids": r.get("block_ids", [])}
        for r in result.diagnostics.get("raw_regions", [])
    ]
    snapshot = {
        "schema_version": SCHEMA_VERSION,
        "build": {"version": package_version, "revision": build if re.fullmatch(r"[0-9a-f]{7,40}", build) else None},
        "image": {"width": image.width, "height": image.height, "input_sha256": input_sha256,
                  "pixel_sha256": sha256(f"{image.mode}:{image.width}:{image.height}:".encode() + image.tobytes()).hexdigest()},
        "models": models or {},
        "regions": regions, "blocks": blocks,
        "timings": {"analysis": result.analysis_processing, "rendering": asdict(result.processing)},
        "counts": {"rendered": result.blocks_rendered, "preserved": result.blocks_skipped,
                   "undetected": None},
        "coverage": result.diagnostics.get("coverage", {}),
        "limitations": ["OCR confidence and raw rejected model responses are unavailable unless recorded by the engine."],
    }
    from .cache import pixel_identity
    # These coexist: uploaded-byte identity, historical diagnostic pixel identity,
    # and the versioned canonical pixels used by stage caching.
    snapshot["image"]["canonical_pixels"] = pixel_identity(image)
    cache = result.diagnostics.get("cache")
    if isinstance(cache, dict):
        snapshot["cache"] = {k: cache[k] for k in ("schema", "persistent_enabled", "memory_bytes", "memory_limit",
            "disk_bytes", "disk_limit", "hits", "misses", "evictions", "corruptions", "refresh", "error_code") if k in cache}
        snapshot["cache"]["stages"] = [
            {k: s[k] for k in ("stage", "key", "source", "restored", "lookup_ms", "compute_ms") if k in s}
            for s in cache.get("stages", []) if isinstance(s, dict)]
    if len(json.dumps(snapshot, ensure_ascii=False, allow_nan=False).encode("utf-8")) > MAX_SNAPSHOT_BYTES:
        # Rendering must remain usable even when a page is too large to diagnose in memory.
        return {key: snapshot[key] for key in ("schema_version", "build", "image", "models", "counts", "coverage")} | {
            "unavailable": "snapshot_size_limit", "regions": [], "blocks": [], "timings": snapshot["timings"]}
    return snapshot


def render_bundle(image: Image.Image, snapshot: dict[str, Any]) -> bytes:
    metadata = json.dumps(snapshot, ensure_ascii=False, allow_nan=False, separators=(",", ":")).encode("utf-8")
    if len(metadata) > MAX_SNAPSHOT_BYTES:
        raise ValueError("Diagnostic snapshot exceeds 2 MiB")
    pixels = BytesIO()
    image.save(pixels, format="PNG")
    if pixels.tell() > MAX_RENDER_BYTES:
        raise ValueError("Rendered page exceeds 32 MiB")
    output = BytesIO()
    with ZipFile(output, "w", compression=ZIP_STORED) as archive:
        archive.writestr("rendered.png", pixels.getvalue())
        archive.writestr("snapshot.json", metadata)
    if output.tell() > MAX_BUNDLE_BYTES:
        raise ValueError("Page transport bundle exceeds its size limit")
    return output.getvalue()
