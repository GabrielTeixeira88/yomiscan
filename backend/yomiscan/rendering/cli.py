"""Lossless rendering/debug commands. No files are written by the renderer itself."""

import argparse
import json
from pathlib import Path
import sys
from PIL import Image, ImageOps
from yomiscan.analysis_cli import configure_output
from yomiscan.detection import ComicTextDetector, DetectionError, DetectionInitializationError
from yomiscan.dictionary import DictionaryError
from yomiscan.nlp import TokenizerError
from yomiscan.ocr import OCRInitializationError
from yomiscan.translation import TranslationInitializationError
from yomiscan.service import open_local_service
from .base import TypesettingError, MaskGenerationError
from .masks import UniformBackgroundMaskGenerator

DEBUG_NAMES = ("00-original.png", "01-detection.png", "02-raw-mask.png", "03-mask.png",
               "04-inpainted.png", "05-final.png", "01-grouped-blocks.png", "06-layout-status.png", "metadata.json")


def validate_outputs(source: Path, output: Path, debug_dir: Path | None) -> None:
    if output.suffix.lower() != ".png":
        raise ValueError("Use a .png output for lossless rendering")
    paths = [output.resolve()]
    if debug_dir:
        paths += [(debug_dir / name).resolve() for name in DEBUG_NAMES]
    if source.resolve() in paths or len(set(paths)) != len(paths):
        raise ValueError("Output/debug paths must be distinct and must not overwrite the source image")


def main(argv: list[str] | None = None, *, mask_only: bool = False) -> int:
    configure_output()
    parser = argparse.ArgumentParser(description="YomiScan Text Mask" if mask_only else "YomiScan Page Rendering")
    parser.add_argument("image", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--debug-dir", type=Path)
    parser.add_argument("--device", choices=("auto", "cpu", "cuda"), default="auto",
                        help="Analysis device; masking/inpainting/typesetting use CPU")
    if not mask_only:
        parser.add_argument("--dictionary", type=Path, default=Path("data/jmdict.sqlite3"))
    args = parser.parse_args(argv)
    try:
        validate_outputs(args.image, args.output, args.debug_dir)
        with Image.open(args.image) as source:
            # Match API orientation while retaining grayscale/alpha where possible.
            image = ImageOps.exif_transpose(source).copy()
        if mask_only:
            detector = ComicTextDetector(device=args.device)
            masks = UniformBackgroundMaskGenerator()
            raw = Image.new("L", image.size)
            final = Image.new("L", image.size)
            warnings = []
            for region in detector.detect(image):
                if region.metadata.get("class") == "text_free":
                    warnings.append(f"Region {region.id}: unclassified text outside bubbles")
                    continue
                try:
                    mask = masks.generate(image, region.bbox)
                except MaskGenerationError as exc:
                    import logging
                    logging.getLogger(__name__).exception("Region %s masking failed", region.id)
                    warnings.append(f"Region {region.id}: {exc}")
                    continue
                raw.paste(mask.raw, (mask.crop_box.left, mask.crop_box.top), mask.raw)
                if mask.safe:
                    final.paste(mask.final, (mask.crop_box.left, mask.crop_box.top), mask.final)
                else:
                    warnings.append(f"Region {region.id}: {mask.reason}")
            final.save(args.output, format="PNG")
            if args.debug_dir:
                args.debug_dir.mkdir(parents=True, exist_ok=True)
                image.save(args.debug_dir / "00-original.png")
                raw.save(args.debug_dir / "02-raw-mask.png")
                final.save(args.debug_dir / "03-mask.png")
            print("YomiScan Text Mask\n" + "\n".join(warnings))
        else:
            with open_local_service(args.dictionary, device=args.device) as service:
                result = service.translate_and_render_page(image, debug=args.debug_dir is not None)
            result.rendered_image.save(args.output, format="PNG")
            if args.debug_dir:
                args.debug_dir.mkdir(parents=True, exist_ok=True)
                image.save(args.debug_dir / "00-original.png")
                for name, intermediate in result.debug_images.items():
                    intermediate.save(args.debug_dir / f"{name}.png")
                result.rendered_image.save(args.debug_dir / "05-final.png")
                (args.debug_dir / "metadata.json").write_text(
                    json.dumps(result.metadata(), ensure_ascii=False, indent=2), encoding="utf-8")
            print(f"YomiScan Page Rendering\nText blocks detected: {len(result.blocks)}\n"
                  f"Rendered: {result.blocks_rendered}\nSkipped: {result.blocks_skipped}")
            for block in result.blocks:
                if block.reason:
                    print(f"[{block.block_id}] {block.reason}")
            print("Analysis (ms):", result.analysis_processing)
            print("Rendering (ms):", result.metadata()["processing"])
        print(f"Output: {args.output}")
        return 0
    except (ValueError, OSError, Image.DecompressionBombError) as exc:
        print(f"Input/output error: {exc}", file=sys.stderr)
        return 2
    except (DetectionInitializationError, OCRInitializationError, TranslationInitializationError,
            DictionaryError, TokenizerError, TypesettingError) as exc:
        print(f"Initialization error: {exc}", file=sys.stderr)
        return 3
    except DetectionError as exc:
        print(f"Detection failed: {exc}", file=sys.stderr)
        return 4
