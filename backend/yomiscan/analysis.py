"""Compose existing engines without tying tokenization to OCR."""

from dataclasses import dataclass
from collections.abc import Sequence
import logging
from time import perf_counter
from typing import Protocol
import unicodedata

from PIL import Image

from yomiscan.dictionary import DictionaryEntry
from yomiscan.nlp import JapaneseToken, JapaneseTokenizer
from yomiscan.ocr import OCREngine, OCRResult
from yomiscan.translation import TranslationEngine, TranslationResult
from yomiscan.translation import TranslationError
from yomiscan.nlp import TokenizerError
from yomiscan.dictionary import DictionaryError


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
    translation: TranslationResult | None = None
    processing_time_ms: float = 0.0


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
    def __init__(
        self, tokenizer: JapaneseTokenizer, dictionary: DictionaryLookup,
        translator: TranslationEngine | None = None,
    ) -> None:
        self._tokenizer = tokenizer
        self._dictionary = dictionary
        self._translator = translator

    def analyze(self, text: str) -> TextAnalysisResult:
        translation = self._translator.translate(text) if self._translator and text.strip() else None
        return self._analyze_lexical(text, translation)

    def analyze_many(self, texts: Sequence[str]) -> list[TextAnalysisResult | Exception]:
        """Batch sentence translation; isolate known per-block failures in page mode."""
        translations: list[TranslationResult | None | Exception] = [None] * len(texts)
        nonblank = [i for i, text in enumerate(texts) if text.strip()]
        if self._translator and nonblank:
            try:
                batch = self._translator.translate_many([texts[i] for i in nonblank])
                if len(batch) != len(nonblank):
                    raise TranslationError("Translation batch returned an unexpected number of results")
                for i, result in zip(nonblank, batch, strict=True):
                    translations[i] = result
            except TranslationError:
                logging.getLogger(__name__).exception("Page translation batch failed; retrying individual blocks")
                for i in nonblank:
                    try:
                        translations[i] = self._translator.translate(texts[i])
                    except TranslationError as exc:
                        logging.getLogger(__name__).exception("Page block translation failed")
                        translations[i] = exc
        results: list[TextAnalysisResult | Exception] = []
        for text, translation in zip(texts, translations, strict=True):
            if isinstance(translation, Exception):
                results.append(translation)
                continue
            try:
                results.append(self._analyze_lexical(text, translation))
            except (TokenizerError, DictionaryError) as exc:
                logging.getLogger(__name__).exception("Page lexical analysis failed")
                results.append(exc)
        return results

    def _analyze_lexical(self, text: str, translation: TranslationResult | None) -> TextAnalysisResult:
        start = perf_counter()
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
        return TextAnalysisResult(
            text, tuple(tokens), entries, translation, (perf_counter() - start) * 1000,
        )


def analyze_image(image: Image.Image, ocr: OCREngine, analyzer: TextAnalyzer) -> ImageAnalysisResult:
    result = ocr.recognize(image)
    return ImageAnalysisResult(result, analyzer.analyze(result.text))
