"""Compose existing engines without tying tokenization to OCR."""

from dataclasses import dataclass, replace
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
from .cache import CacheRequest
from .cache_identity import component_identity, algorithm, result_metadata
from pydantic import TypeAdapter, ValidationError


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

    def translation_metadata(self) -> dict[str, object]:
        describe = getattr(self._translator, "diagnostic_metadata", None)
        metadata = describe() if callable(describe) else {}
        return metadata if isinstance(metadata, dict) else {}

    def analyze(self, text: str) -> TextAnalysisResult:
        translation = self._translator.translate(text) if self._translator and text.strip() else None
        return self._analyze_lexical(text, translation)

    def analyze_many(self, texts: Sequence[str], *, cache: CacheRequest | None = None,
                     lineage: object = None) -> list[TextAnalysisResult | Exception]:
        """Batch sentence translation; isolate known per-block failures in page mode."""
        translations: list[TranslationResult | None | Exception] = [None] * len(texts)
        nonblank = [i for i, text in enumerate(texts) if text.strip()]
        identity = component_identity(self._translator) if cache else None
        key = cache.key("translation", list(texts), lineage, identity, "en", "ordered-native-batch-v1",
                        algorithm("analysis.py")) if cache and identity is not None else None
        encoded = cache.get("translation", key) if cache else None
        restored = False
        if encoded is not None:
            try:
                previous = TypeAdapter(list[TranslationResult | None]).validate_json(encoded)
                if len(previous) != len(texts):
                    raise ValueError("Cached translation batch count mismatch")
                translations = [replace(t, processing_time_ms=0.0) if t is not None else None for t in previous]
                restored = True
            except (ValidationError, ValueError):
                cache.invalid("translation", key)
        batch_failed = False
        translation_start = perf_counter()
        if self._translator and nonblank and not restored:
            try:
                batch = self._translator.translate_many([texts[i] for i in nonblank])
                if len(batch) != len(nonblank):
                    raise TranslationError("Translation batch returned an unexpected number of results")
                for i, result in zip(nonblank, batch, strict=True):
                    translations[i] = result
            except TranslationError:
                batch_failed = True
                logging.getLogger(__name__).exception("Page translation batch failed; retrying individual blocks")
                for i in nonblank:
                    try:
                        translations[i] = self._translator.translate(texts[i])
                    except TranslationError as exc:
                        logging.getLogger(__name__).exception("Page block translation failed")
                        translations[i] = exc
        if cache and not restored:
            cache.stages[-1]["compute_ms"] = (perf_counter()-translation_start)*1000
        if cache and not restored and not batch_failed and not any(isinstance(t, Exception) for t in translations):
            safe = [replace(t, metadata=result_metadata(t.metadata)) if isinstance(t, TranslationResult) else t for t in translations]
            cache.put("translation", key, TypeAdapter(list[TranslationResult | None]).dump_json(safe))
        lexical_identity = [component_identity(self._tokenizer), component_identity(self._dictionary)] if cache else []
        results: list[TextAnalysisResult | Exception] = []
        for text, translation in zip(texts, translations, strict=True):
            if isinstance(translation, Exception):
                results.append(translation)
                continue
            try:
                lexical_key = cache.key("lexical", text, lexical_identity, algorithm("analysis.py")) if cache and all(
                    item is not None for item in lexical_identity) else None
                payload = cache.get("lexical", lexical_key) if cache else None
                lexical = None
                if payload is not None:
                    try:
                        lexical = replace(TypeAdapter(TextAnalysisResult).validate_json(payload), processing_time_ms=0.0)
                    except ValidationError:
                        cache.invalid("lexical", lexical_key)
                if lexical is None:
                    lexical = self._analyze_lexical(text, None)
                    if cache and lexical_identity == [component_identity(self._tokenizer), component_identity(self._dictionary)]:
                        cache.put("lexical", lexical_key, TypeAdapter(TextAnalysisResult).dump_json(lexical))
                results.append(replace(lexical, translation=translation))
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
