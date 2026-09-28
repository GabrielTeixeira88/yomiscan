"""CLI logic, kept importable for tests without loading neural network weights."""

import argparse
from pathlib import Path
import sys

from PIL import Image, UnidentifiedImageError

from . import MangaOCREngine, OCRInitializationError, OCRRecognitionError


def load_image(path: Path) -> Image.Image:
    """Decode before model initialization and return an image detached from its file."""
    if not path.exists():
        raise ValueError(f"File does not exist: {path}")
    if not path.is_file():
        raise ValueError(f"Expected an image file: {path}")
    try:
        with Image.open(path) as image:
            return image.convert("RGB")
    except (OSError, UnidentifiedImageError, Image.DecompressionBombError) as exc:
        raise ValueError(f"Cannot open image '{path}': {exc}") from exc


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="YomiScan local Japanese OCR")
    parser.add_argument("image", type=Path, help="Path to a cropped manga image")
    parser.add_argument("--cpu", action="store_true", help="Force CPU inference")
    args = parser.parse_args(argv)
    # Windows redirected output may otherwise use a legacy non-Japanese encoding.
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    try:
        image = load_image(args.image)
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2
    with image:
        try:
            engine = MangaOCREngine(force_cpu=args.cpu)
            result = engine.recognize(image)
        except OCRInitializationError as exc:
            print(f"Error: {exc}", file=sys.stderr)
            return 3
        except OCRRecognitionError as exc:
            print(f"Error: {exc}", file=sys.stderr)
            return 4
    print("YomiScan OCR\n")
    print(f"Engine: {result.engine}")
    print(f"Processing time: {result.processing_time_ms:.0f} ms\n")
    print(f"Recognized text:\n{'─' * 24}\n{result.text}\n{'─' * 24}")
    return 0
