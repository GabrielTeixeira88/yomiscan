"""Small opt-in production-model smoke; save aggregate reuse facts, never manga text."""

import argparse
import hashlib
import json
import os
from pathlib import Path
from time import perf_counter

from PIL import Image
from yomiscan.service import open_local_service
from yomiscan.rendering.settings import RenderSettings
from yomiscan.diagnostics import page_snapshot
from yomiscan.api.models import ImageAnalysisResponse


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("image", type=Path)
    parser.add_argument("--dictionary", type=Path, default=Path("data/jmdict.sqlite3"))
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    if args.output.exists() or args.output.resolve() in (args.image.resolve(), args.dictionary.resolve()):
        parser.error("Choose a new aggregate output separate from inputs")
    os.environ.update(HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1", YOMISCAN_TRANSLATION_ENGINE="current",
        YOMISCAN_OCR="current", YOMISCAN_DETECTOR="current", YOMISCAN_DEVICE="cpu",
        YOMISCAN_CACHE_DIRECTORY=str(args.output.parent/"smoke-processing"))
    started = perf_counter()
    with open_local_service(args.dictionary, device="cpu") as service, Image.open(args.image) as source:
        image = source.convert("RGB")
        initialization_ms = (perf_counter()-started)*1000
        observations = []
        first = service.translate_and_render_page(image, progress=lambda stage, state, ms: observations.append({"stage": stage, "state": state}))
        snapshot = page_snapshot(image, first, input_sha256=hashlib.sha256(args.image.read_bytes()).hexdigest())
        candidate = next((b for b in snapshot["blocks"] if b["text"].get("study") and b["text"]["study"]["tokens"]), None)
        if candidate is None:
            raise RuntimeError("No retained analyzed Japanese block on this local page; no reuse claim made")
        bubble = candidate["text"]["study"]
        reused_bubble = ImageAnalysisResponse.model_validate(bubble)
        box = candidate["bbox"]
        with image.crop((box["left"], box["top"], box["right"], box["bottom"])) as crop:
            study = service.analyze_image(crop)
        if not study.analysis.original_text or not study.analysis.tokens:
            raise RuntimeError("The independent Study crop did not produce lexical analysis")
        again = service.translate_and_render_page(image)
        changed = service.translate_and_render_page(image, refresh="render", render_settings=RenderSettings(1.25))
        second_stages, font_stages = again.diagnostics["cache"]["stages"], changed.diagnostics["cache"]["stages"]
        if not all(stage["restored"] for stage in second_stages):
            raise RuntimeError("Repeat did not reuse every page stage")
        if not all(stage["restored"] for stage in font_stages if stage["stage"] != "render") or font_stages[-1]["restored"]:
            raise RuntimeError("Font rerender did not isolate rendering from upstream work")
        report = {"models": service.diagnostic_models(), "initialization_ms": initialization_ms,
            "image_dimensions": list(image.size), "blocks": len(snapshot["blocks"]), "rendered": first.blocks_rendered,
            "preserved": first.blocks_skipped, "study_mode": {"ocr_nonblank": True, "tokens": len(study.analysis.tokens)},
            "bubble_to_study": {"reused": True, "tokens": len(reused_bubble.tokens), "additional_ocr_calls": 0,
                                "mechanism": "Validate the exact retained DTO; no pipeline invocation"},
            "repeat_all_stages_cached": True, "font_upstream_cached": True, "font_render_recomputed": True,
            "stage_observations": observations, "first_timings": first.analysis_processing,
            "font_timings": changed.analysis_processing, "semantic_accuracy": "Not scored; functionality smoke only"}
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(json.dumps({"blocks": report["blocks"], "rendered": report["rendered"], "preserved": report["preserved"],
                          "study_tokens": report["study_mode"]["tokens"], "repeat_and_font_reuse": True}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
