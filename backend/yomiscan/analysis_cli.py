import argparse
from pathlib import Path
import sys

from .analysis import TextAnalyzer, TextAnalysisResult, analyze_image
from .dictionary import DictionaryError, SQLiteDictionary
from .nlp import FugashiTokenizer, TokenizerError
from .ocr import MangaOCREngine, OCRInitializationError, OCRRecognitionError
from .ocr.cli import load_image

DEFAULT_DATABASE = Path("data/jmdict.sqlite3")


def configure_output() -> None:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")


def print_analysis(result: TextAnalysisResult) -> None:
    print(f"Original:\n{result.original_text}\n\nTokens:")
    if not result.tokens:
        print("(none)")
    for index, item in enumerate(result.tokens, 1):
        token = item.token
        print(f"\n{index}. {token.surface}")
        print(f"   Reading: {token.reading or 'unavailable'}")
        print(f"   Lemma: {token.lemma or 'unavailable'}")
        print(f"   POS: {token.part_of_speech or 'unavailable'}")
        if token.conjugation_type or token.conjugation_form:
            print(f"   Conjugation: {token.conjugation_type or '-'} / {token.conjugation_form or '-'}")
        print(f"   Lookup: {item.lookup_form or 'no match'}")
        if not item.entry_ids:
            print("   Meanings: no dictionary match")
        for entry_id in item.entry_ids:
            entry = result.dictionary_entries[entry_id]
            print(f"   JMdict {entry_id}: {', '.join(entry.spellings) or '(kana only)'}")
            for reading in entry.readings:
                restriction = f" (only: {', '.join(reading.spellings)})" if reading.spellings else ""
                if reading.no_kanji:
                    restriction += " (independent of kanji spelling)"
                print(f"     Reading: {reading.text}{restriction}")
            for sense in entry.senses:
                print(f"     Meanings [{'; '.join(sense.parts_of_speech) or 'POS unavailable'}]:")
                if sense.spellings or sense.readings:
                    print(f"       Restricted to: {', '.join(sense.spellings + sense.readings)}")
                for gloss in sense.glosses:
                    print(f"       - {gloss}")
                if sense.labels or sense.notes:
                    print(f"       Notes: {'; '.join(sense.labels + sense.notes)}")
    print("\nDictionary candidates, not context-selected meanings or sentence translation.")
    print("JMdict © EDRDG contributors — CC BY-SA 4.0; https://www.edrdg.org/edrdg/licence.html")


def main(argv: list[str] | None = None, *, image_mode: bool = False) -> int:
    configure_output()
    parser = argparse.ArgumentParser(description="YomiScan local Japanese analysis")
    parser.add_argument("input", help="Cropped image path" if image_mode else "Japanese text")
    parser.add_argument("--dictionary", type=Path, default=DEFAULT_DATABASE)
    if image_mode:
        parser.add_argument("--cpu", action="store_true", help="Force CPU OCR")
    args = parser.parse_args(argv)
    try:
        with SQLiteDictionary(args.dictionary) as dictionary:
            analyzer = TextAnalyzer(FugashiTokenizer(), dictionary)
            if image_mode:
                with load_image(Path(args.input)) as image:
                    result = analyze_image(image, MangaOCREngine(force_cpu=args.cpu), analyzer)
                print(f"OCR: {result.ocr.engine} | {result.ocr.processing_time_ms:.0f} ms\n")
                print_analysis(result.analysis)
            else:
                print_analysis(analyzer.analyze(args.input))
        return 0
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2
    except (DictionaryError, TokenizerError, OCRInitializationError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 3
    except OCRRecognitionError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 4
