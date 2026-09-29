"""Compose existing engines without tying tokenization to OCR."""

from dataclasses import dataclass
from typing import Protocol
import unicodedata

from PIL import Image

from yomiscan.dictionary import DictionaryEntry
from yomiscan.nlp import JapaneseToken, JapaneseTokenizer
from yomiscan.ocr import OCREngine, OCRResult


class DictionaryLookup(Protocol):
    def lookup(self, text: str) -> tuple[DictionaryEntry, ...]: ...


@dataclass(frozen=True)
class AnalyzedToken:
    token: JapaneseToken
    lookup_form: str | None
    entry_ids: tuple[int, ...]


@dataclass(frozen=True)
class TextAnalysisResult:
    original_text: str
    tokens: tuple[AnalyzedToken, ...]
    dictionary_entries: dict[int, DictionaryEntry]


@dataclass(frozen=True)
class ImageAnalysisResult:
    ocr: OCRResult
    analysis: TextAnalysisResult


def lookup_candidates(token: JapaneseToken) -> tuple[str, ...]:
    if all(unicodedata.category(c)[0] in "PSZ" for c in token.surface):
        return ()
    # orthBase preserves the written base, unlike UniDic lemma labels such as アイス-ice.
    # Never fall back to an inflected surface's reading as if it were a dictionary form.
    return tuple(dict.fromkeys(value for value in (
        token.orthographic_base, token.lemma, token.surface, token.lemma_reading,
    ) if value))


class TextAnalyzer:
    def __init__(self, tokenizer: JapaneseTokenizer, dictionary: DictionaryLookup) -> None:
        self._tokenizer = tokenizer
        self._dictionary = dictionary

    def analyze(self, text: str) -> TextAnalysisResult:
        tokens = []
        entries: dict[int, DictionaryEntry] = {}
        cache: dict[str, tuple[DictionaryEntry, ...]] = {}
        for token in self._tokenizer.tokenize(text):
            matches: tuple[DictionaryEntry, ...] = ()
            matched_form = None
            for candidate in lookup_candidates(token):
                if candidate not in cache:
                    cache[candidate] = self._dictionary.lookup(candidate)
                matches = cache[candidate]
                if matches:
                    matched_form = candidate
                    break
            entries.update((entry.entry_id, entry) for entry in matches)
            tokens.append(AnalyzedToken(token, matched_form, tuple(e.entry_id for e in matches)))
        return TextAnalysisResult(text, tuple(tokens), entries)


def analyze_image(image: Image.Image, ocr: OCREngine, analyzer: TextAnalyzer) -> ImageAnalysisResult:
    result = ocr.recognize(image)
    return ImageAnalysisResult(result, analyzer.analyze(result.text))
