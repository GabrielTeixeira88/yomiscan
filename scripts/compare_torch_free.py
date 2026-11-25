"""Compare the Torch-free vision engines (Stage 5b) with the Torch path on real pages.

    uv run --extra vision python scripts/compare_torch_free.py samples/vision/*.jpg --device cpu

Both paths run PageAnalysisService.extract (production detection, grouping, padded crops and
OCR) without the processing cache. Region parity compares detector boxes and classes. OCR parity
re-recognizes the Torch path's own blocks with the Torch-free OCR, so detection differences do
not hide or inflate OCR differences. Prints a JSON report with counts and timings only; no
recognized text is printed unless --show-differences is given (keep that output out of Git).
"""

import argparse
import json
import sys
from pathlib import Path
from statistics import median
from time import perf_counter

from PIL import Image

from yomiscan.detection.factory import create_detector
from yomiscan.ocr.factory import create_ocr_engine
from yomiscan.page import PageAnalysisService


def regions_key(regions) -> list[tuple]:
    return [(r.bbox.coordinates(), r.metadata.get("class")) for r in regions]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("pages", nargs="+", type=Path)
    parser.add_argument("--device", choices=("cpu", "directml"), default="cpu", help="Torch-free detector device (OCR stays on CPU)")
    parser.add_argument("--threads", type=int, default=4)
    parser.add_argument("--show-differences", action="store_true")
    arguments = parser.parse_args(argv)

    import os
    os.environ["YOMISCAN_ONNX_DEVICE"] = arguments.device
    started = perf_counter()
    torch_service = PageAnalysisService(create_detector("current", device="cpu", threads=arguments.threads),
                                        create_ocr_engine("current", device="cpu", threads=arguments.threads, pinned=True), None)  # type: ignore[arg-type]
    torch_load = perf_counter() - started
    started = perf_counter()
    free_service = PageAnalysisService(create_detector("pinned", device="auto", threads=arguments.threads),
                                       create_ocr_engine("pinned", device="auto", threads=arguments.threads), None)  # type: ignore[arg-type]
    free_load = perf_counter() - started

    report = {"device": arguments.device, "threads": arguments.threads, "pages": len(arguments.pages),
              "load_s": {"torch": round(torch_load, 2), "torch_free": round(free_load, 2)},
              "regions": {"torch": 0, "identical": 0, "same_class_within_2px": 0}, "pages_with_identical_regions": 0,
              "blocks": {"torch": 0, "identical_text": 0},
              "end_to_end": {"torch_blocks": 0, "pages_with_same_blocks": 0, "identical_text": 0}, "timing_ms": {}}
    detection = {"torch": [], "torch_free": []}
    ocr = {"torch": [], "torch_free": []}
    differences = []
    for page in arguments.pages:
        with Image.open(page) as opened:
            image = opened.convert("RGB")
        reference = torch_service.extract(image)
        candidate = free_service.extract(image)
        detection["torch"].append(reference.detection_ms)
        detection["torch_free"].append(candidate.detection_ms)
        expected, found = regions_key(reference.detection.regions), regions_key(candidate.detection.regions)
        report["regions"]["torch"] += len(expected)
        report["regions"]["identical"] += len(set(expected) & set(found))
        report["pages_with_identical_regions"] += expected == found
        report["regions"]["same_class_within_2px"] += len(expected) == len(found) and sum(
            c1 == c2 and max(abs(a - b) for a, b in zip(b1, b2)) <= 2 for (b1, c1), (b2, c2) in zip(expected, found))
        if expected != found:
            differences.append({"page": page.name, "kind": "regions", "torch_only": sorted(set(expected) - set(found)),
                                "torch_free_only": sorted(set(found) - set(expected))})
        # End to end: each path OCRs its own blocks; blocks are compared in reading order.
        end = report["end_to_end"]
        end["torch_blocks"] += len(reference.blocks)
        if [b.reading_order for b in reference.blocks] == [b.reading_order for b in candidate.blocks]:
            end["pages_with_same_blocks"] += 1
            end["identical_text"] += sum(a.original_text == b.original_text for a, b in zip(reference.blocks, candidate.blocks))
        else:
            differences.append({"page": page.name, "kind": "blocks", "torch": len(reference.blocks), "torch_free": len(candidate.blocks)})
        rerun = free_service.recognize_blocks(image, reference.blocks)
        for before, after in zip(reference.blocks, rerun, strict=True):
            report["blocks"]["torch"] += 1
            same = before.original_text == after.original_text
            report["blocks"]["identical_text"] += same
            ocr["torch"].append(before.ocr_ms or 0)
            ocr["torch_free"].append(after.ocr_ms or 0)
            if not same:
                differences.append({"page": page.name, "kind": "text", "block": before.id,
                                    **({"torch": before.original_text, "torch_free": after.original_text} if arguments.show_differences else {})})
    for name in ("torch", "torch_free"):
        report["timing_ms"][name] = {"detection_median_per_page": round(median(detection[name])),
                                     "ocr_median_per_block": round(median(ocr[name])) if ocr[name] else None}
    report["differences"] = differences
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    print(json.dumps(report, indent=1, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
