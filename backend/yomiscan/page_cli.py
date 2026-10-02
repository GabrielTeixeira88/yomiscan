"""Developer page commands. Debug artifacts remain opt-in and local."""

import argparse
from dataclasses import asdict
import json
from pathlib import Path
import sys
from time import perf_counter
from PIL import Image, ImageDraw
from .analysis_cli import configure_output
from .detection import ComicTextDetector, TextRegion, DetectionError, DetectionInitializationError
from .dictionary import DictionaryError
from .nlp import TokenizerError
from .ocr import OCRInitializationError
from .ocr.cli import load_image
from .service import open_local_service
from .translation import TranslationInitializationError
from .api.models import PageAnalysisResponse


def draw_regions(image: Image.Image, regions: list[TextRegion], output: Path) -> None:
    with image.copy() as debug:
        draw = ImageDraw.Draw(debug)
        for region in regions:
            box = region.bbox.clipped(*image.size)
            if box.width <= 0 or box.height <= 0:
                continue
            draw.rectangle(box.coordinates(), outline="red", width=2)
            if region.polygon:
                draw.line([*region.polygon, region.polygon[0]], fill="orange", width=2)
            label = str(region.id)
            if region.confidence is not None:
                label += f" ({region.confidence:.2f})"
            draw.text((box.left, max(0, box.top - 12)), label, fill="red", stroke_width=1, stroke_fill="white")
        debug.save(output)


def main(argv: list[str] | None = None, *, detection_only: bool = False) -> int:
    configure_output()
    parser = argparse.ArgumentParser(description="YomiScan text detection" if detection_only else "YomiScan Page Analysis")
    parser.add_argument("image", type=Path)
    parser.add_argument("--device", choices=("auto", "cpu", "cuda"), default="auto")
    parser.add_argument("--output" if detection_only else "--debug-image", type=Path, dest="debug_image",
                        required=detection_only)
    if not detection_only:
        parser.add_argument("--dictionary", type=Path, default=Path("data/jmdict.sqlite3"))
        parser.add_argument("--json-output", type=Path, help="Full local developer diagnostics including raw regions")
    args = parser.parse_args(argv)
    outputs = [args.debug_image, getattr(args, "json_output", None)]
    paths = [p.resolve() for p in outputs if p is not None]
    if args.image.resolve() in paths or len(paths) != len(set(paths)):
        parser.error("Output paths must be distinct and must not overwrite the input image")
    try:
        with load_image(args.image) as image:
            if detection_only:
                detector = ComicTextDetector(device=args.device)
                start = perf_counter()
                regions = detector.detect(image)
                print(f"YomiScan Text Detection\nDevice: {detector.device}\nDetection: {(perf_counter()-start)*1000:.0f} ms")
                for r in regions:
                    print(f"[{r.id}] {r.bbox.coordinates()} confidence={r.confidence:.3f}")
            else:
                with open_local_service(args.dictionary, device=args.device) as service:
                    result = service.analyze_page(image)
                regions = list(result.regions)
                print(f"YomiScan Page Analysis\nDetected regions: {len(regions)}\nText blocks: {len(result.text_blocks)}")
                for block in result.text_blocks:
                    print(f"\n[{block.reading_order}] {block.status}\nCoordinates: {block.bbox.coordinates()}\nJapanese:\n{block.original_text}")
                    if block.analysis and block.analysis.translation:
                        print(f"English:\n{block.analysis.translation.translated_text}")
                    if block.error_message:
                        print(block.error_message)
                print("\nProcessing (ms):", asdict(result.processing))
                if args.json_output:
                    data = PageAnalysisResponse.from_result(result).model_dump()
                    data["debug"] = {"regions": [asdict(r) for r in result.regions],
                                     "filtered_regions": result.filtered_regions}
                    args.json_output.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
            if args.debug_image:
                draw_regions(image, regions, args.debug_image)
                print(f"Raw numbered detections saved to {args.debug_image}")
        return 0
    except (ValueError, OSError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2
    except (DetectionInitializationError, OCRInitializationError, TranslationInitializationError,
            DictionaryError, TokenizerError) as exc:
        print(f"Initialization failed: {exc}", file=sys.stderr)
        return 3
    except DetectionError as exc:
        print(f"Detection failed: {exc}", file=sys.stderr)
        return 4
