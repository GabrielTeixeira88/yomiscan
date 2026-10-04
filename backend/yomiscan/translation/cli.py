import argparse
import sys

from . import MarianTranslationEngine, TranslationError, TranslationInitializationError
from .base import validate_text
from .factory import ENGINE_NAMES, create_translation_engine


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="YomiScan local Japanese → English translation")
    parser.add_argument("texts", nargs="+", help="One or more complete sentences/text regions")
    parser.add_argument("--device", choices=("auto", "cpu", "cuda"), default="auto")
    parser.add_argument("--engine", choices=ENGINE_NAMES, default="current")
    args = parser.parse_args(argv)
    try:
        for text in args.texts:
            validate_text(text)
        engine = (MarianTranslationEngine(device=args.device) if args.engine == "current"
                  else create_translation_engine(args.engine, device=args.device))
        try:
            results = engine.translate_many(args.texts)
        finally:
            close = getattr(engine, "close", None)
            if close is not None:
                close()
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2
    except TranslationInitializationError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 3
    except TranslationError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 4
    print("YomiScan Translation\n")
    for result in results:
        print(f"Engine: {result.engine}\nModel: {result.model}\nDevice: {engine.device}")
        scope = result.metadata.get("timing_scope", "batch")
        print(f"Processing time: {result.processing_time_ms:.0f} ms ({scope} elapsed)\n")
        print(f"Original:\n{result.source_text}\n\nTranslation:\n{result.translated_text}\n")
    return 0
