"""Opt-in local page-cache measurements. Uses existing models; never downloads in offline mode.

Only anonymous timings/counters are exported. Pixels/text remain in the explicitly
selected ignored cache directory, whose settings enable persistence for this run.
"""

import argparse
from dataclasses import asdict
import json
import os
import hashlib
import subprocess
import sys
from pathlib import Path
import platform
from time import perf_counter

from yomiscan.api.images import decode_image, MAX_FILE_BYTES
from yomiscan.cache_identity import versions
from yomiscan.page import PageAnalysisService
from yomiscan.rendering.renderer import ConservativePageRenderer
from yomiscan.rendering.service import PageTranslationRenderService
from yomiscan.service import open_local_service


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("images", type=Path, nargs="+")
    parser.add_argument("--dictionary", type=Path, default=Path("data/jmdict.sqlite3"))
    parser.add_argument("--cache-directory", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--threads", type=int, default=4)
    parser.add_argument("--restart-only", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.threads < 1 or not args.images or len(args.images) > 20:
        parser.error("Use 1–20 authorized images and positive threads")
    restart_output = args.output.with_suffix(".restart.json")
    protected = {path.resolve() for path in [*args.images, args.dictionary,
        args.cache_directory/"settings.json", args.cache_directory/"stages.sqlite3"]}
    if args.output.suffix.lower() != ".json" or any(path.resolve() in protected or path.exists()
        for path in (args.output, restart_output)):
        parser.error("Choose new JSON report paths distinct from inputs, dictionary and cache storage")
    if args.cache_directory.exists() and not args.cache_directory.is_dir():
        parser.error("Cache directory must be a directory")
    if not args.restart_only and args.cache_directory.exists() and any(args.cache_directory.iterdir()):
        parser.error("Choose an empty cache directory; the benchmark never clears existing data")
    images = []
    for path in args.images:
        if path.stat().st_size > MAX_FILE_BYTES:
            parser.error("An input exceeds the normal 10 MiB upload limit")
        images.append(decode_image(path.read_bytes()))
    # The benchmark is restricted to the unchanged production selections.
    os.environ["YOMISCAN_CACHE_DIRECTORY"] = str(args.cache_directory)
    for variable in ("YOMISCAN_DETECTOR", "YOMISCAN_OCR", "YOMISCAN_TRANSLATION_ENGINE"):
        if os.getenv(variable, "current") != "current":
            parser.error("Benchmark requires the current production defaults")
    import torch
    torch.set_num_threads(args.threads)
    report = {"platform": platform.system(), "processor": platform.processor(), "threads": args.threads,
              "device": "cpu", "versions": versions("torch", "transformers", "manga-ocr", "pillow"), "pages": []}
    if args.restart_only:
        init = perf_counter()
        with open_local_service(args.dictionary, device="cpu") as restarted:
            report["initialization_ms"] = (perf_counter()-init)*1000
            if not restarted.cache.enabled:
                raise RuntimeError("Restart benchmark requires the explicit persisted consent from its first process")
            for image in images:
                start = perf_counter()
                result = restarted.translate_and_render_page(image)
                report["pages"].append({"wall_ms": (perf_counter()-start)*1000, "analysis": result.analysis_processing,
                    "render": asdict(result.processing), "cache": result.diagnostics["cache"],
                    "output_sha256": hashlib.sha256(result.rendered_image.tobytes()).hexdigest()})
                result.rendered_image.close()
                image.close()
        args.output.write_text(json.dumps(report, indent=2), encoding="utf-8")
        return
    init = perf_counter()
    with open_local_service(args.dictionary, device="cpu") as service:
        report["initialization_ms"] = (perf_counter()-init)*1000
        service.cache.configure(True)
        from yomiscan.detection.factory import create_detector
        detector_start = perf_counter()
        detector = create_detector(device="cpu")
        report["detector_initialization_ms"] = (perf_counter()-detector_start)*1000
        service._detector = detector
        baseline = PageTranslationRenderService(PageAnalysisService(detector, service._ocr, service._analyzer), ConservativePageRenderer())
        for index, image in enumerate(images, 1):
            row = {"sample": index, "width": image.width, "height": image.height}
            start = perf_counter()
            original = baseline.translate_and_render_page(image)
            row["uncached_pipeline_ms"] = (perf_counter()-start)*1000
            row["output_sha256"] = hashlib.sha256(original.rendered_image.tobytes()).hexdigest()
            for name, refresh in (("first", "none"), ("repeat", "none"), ("translation_refresh", "translation"), ("render_refresh", "render")):
                start = perf_counter()
                result = service.translate_and_render_page(image, refresh=refresh)
                row[name] = {"wall_ms": (perf_counter()-start)*1000, "analysis": result.analysis_processing,
                             "render": asdict(result.processing), "cache": result.diagnostics["cache"],
                             "same_pixels_as_uncached": result.rendered_image.tobytes() == original.rendered_image.tobytes(),
                             "rendered": result.blocks_rendered, "preserved": result.blocks_skipped}
                result.rendered_image.close()
            original.rendered_image.close()
            report["pages"].append(row)
            print(json.dumps({"sample": index, "uncached_ms": row["uncached_pipeline_ms"], **{
                name+"_ms": row[name]["wall_ms"] for name in ("first", "repeat", "translation_refresh", "render_refresh")}}), flush=True)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    restart_start = perf_counter()
    subprocess.run([sys.executable, str(Path(__file__).resolve()), *map(str, args.images),
        "--dictionary", str(args.dictionary), "--cache-directory", str(args.cache_directory),
        "--output", str(restart_output), "--threads", str(args.threads), "--restart-only"], check=True,
        creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
    report["restart_process_wall_ms"] = (perf_counter()-restart_start)*1000
    restored = json.loads(restart_output.read_text(encoding="utf-8"))
    report["restart_initialization_ms"] = restored["initialization_ms"]
    for row, reload, image in zip(report["pages"], restored["pages"], images, strict=True):
        reload["same_pixels_as_uncached"] = reload.pop("output_sha256") == row.pop("output_sha256")
        row["restart"] = reload
        image.close()
    args.output.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print("Anonymous timing report written.", flush=True)


if __name__ == "__main__":
    main()
