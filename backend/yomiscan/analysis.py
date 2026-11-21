"""Compose existing engines without tying tokenization to OCR."""

from dataclasses import dataclass, replace
from collections.abc import Sequence
import logging
from time import perf_counter
from typing import Protocol
from threading import Event
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
from .glossary import GlossaryEntry, applicable_terms
from .translation.options import TranslationOptions, validate_options, capabilities
from .translation.structured import PageTranslationRequest, TranslationSegment, CONTRACT_VERSION, StructuredTranslationError
from .translation.base import TranslationContext


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

    def _lexical_many(self, texts: Sequence[str], cache: CacheRequest | None) -> list[TextAnalysisResult | Exception]:
        lexical_identity = [component_identity(self._tokenizer), component_identity(self._dictionary)] if cache else []
        results: list[TextAnalysisResult | Exception] = []
        for text in texts:
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
                results.append(lexical)
            except (TokenizerError, DictionaryError) as exc:
                logging.getLogger(__name__).exception("Page lexical analysis failed")
                results.append(exc)
        return results

    def analyze_many(self, texts: Sequence[str], *, cache: CacheRequest | None = None,
                     lineage: object = None, options: TranslationOptions | None = None,
                     entries: tuple[GlossaryEntry, ...] = (), block_ids: Sequence[int] | None = None,
                     panel_ids: Sequence[int] | None = None, cancel: Event | None = None) -> list[TextAnalysisResult | Exception]:
        """Reuse lexical work for safe hints, preserve native batching by default.

        A structured request has no implicit per-line fallback. Errors remain bound
        to all requested blocks, never cached as a partial successful page.
        """
        options = options or TranslationOptions(target_language=capabilities(self._translator).targets[0])
        support = validate_options(self._translator, options)
        if cancel is not None and cancel.is_set():
            raise StructuredTranslationError("cancelled", "Page translation cancelled")
        lexical = self._lexical_many(texts, cache)
        ids = list(block_ids) if block_ids is not None else list(range(1, len(texts)+1))
        panels = list(panel_ids) if panel_ids is not None else [1]*len(texts)
        if len(ids) != len(texts) or len(panels) != len(texts) or len(set(ids)) != len(ids):
            raise ValueError("Translation IDs/panels must align uniquely with source text")
        hints = [applicable_terms(text, tuple(t.token.surface for t in result.tokens), entries)
                 if options.glossary_enabled and support.glossary_hints and not isinstance(result, Exception) else {}
                 for text, result in zip(texts, lexical, strict=True)]
        nonblank = [i for i, text in enumerate(texts) if text.strip()]
        segments = tuple(TranslationSegment(f"B{ids[i]:03d}", texts[i], panels[i]) for i in nonblank)
        contract = {"target": options.target_language, "mode": options.mode, "ordering": options.ordering,
                    "context": options.context, "hints": hints, "ids": ids, "panels": panels,
                    "grammar": CONTRACT_VERSION if options.mode != "sentences" else None,
                    "version": algorithm("translation/options.py", "translation/structured.py", "glossary.py")}
        identity = component_identity(self._translator) if cache else None
        key = cache.key("translation", list(texts), lineage, identity, contract, algorithm("analysis.py")) if cache and identity is not None else None
        encoded = cache.get("translation", key) if cache else None
        translations: list[TranslationResult | None | Exception] = [None]*len(texts)
        restored = False
        if encoded is not None:
            try:
                previous = TypeAdapter(list[TranslationResult | None]).validate_json(encoded)
                if len(previous) != len(texts) or any(
                    (t is None and self._translator is not None and bool(text.strip())) or
                    (t is not None and (t.source_text != text or not t.translated_text.strip()))
                    for t, text in zip(previous, texts, strict=True)):
                    raise ValueError("Cached translation does not match exact ordered sources")
                translations = [replace(t, processing_time_ms=0.0) if t is not None else None for t in previous]
                restored = True
            except (ValidationError, ValueError):
                cache.invalid("translation", key)
        def translate(indexes: list[int]) -> list[TranslationResult]:
            if cancel is not None and cancel.is_set():
                raise StructuredTranslationError("cancelled", "Page translation cancelled")
            values = [texts[i] for i in indexes]
            if options.mode != "sentences":
                page = PageTranslationRequest(segments, options.target_language, options.mode, options.context,
                    tuple(sorted({k: v for hint in hints for k, v in hint.items()}.items())),
                    glossary_by_id=tuple((f"B{ids[i]:03d}", tuple(sorted(hints[i].items()))) for i in nonblank))
                return self._translator.translate_page(page, cancel=cancel)
            if any(hints[i] for i in indexes):
                return [self._translator.translate(texts[i], context=TranslationContext(glossary=hints[i])) for i in indexes]
            target_method = getattr(type(self._translator), "translate_many_to", None)
            if options.target_language != "en" and callable(target_method):
                return target_method(self._translator, values, options.target_language)
            return self._translator.translate_many(values)
        batch_failed = False
        started = perf_counter()
        if self._translator and nonblank and not restored:
            try:
                batch = translate(nonblank)
                if len(batch) != len(nonblank) or any(t.source_text != texts[i] for t, i in zip(batch, nonblank, strict=True)):
                    raise TranslationError("Translation batch violated exact source order/cardinality")
                if cancel is not None and cancel.is_set():
                    raise StructuredTranslationError("cancelled", "Page translation cancelled")
                for i, result in zip(nonblank, batch, strict=True):
                    translations[i] = result
            except TranslationError as exc:
                batch_failed = True
                logging.getLogger(__name__).exception("Page translation failed")
                if options.mode != "sentences" or getattr(exc, "code", None) == "cancelled":
                    for i in nonblank:
                        translations[i] = exc
                else:
                    for i in nonblank:
                        try:
                            # Preserve the existing native-English singleton retry contract.
                            translations[i] = self._translator.translate(texts[i]) if options.target_language == "en" and not hints[i] else translate([i])[0]
                        except TranslationError as individual:
                            logging.getLogger(__name__).exception("Page block translation failed")
                            translations[i] = individual
        if cache and not restored:
            cache.stages[-1]["compute_ms"] = (perf_counter()-started)*1000
        if cache and not restored and not batch_failed:
            safe = [replace(t, metadata=result_metadata(t.metadata)) if isinstance(t, TranslationResult) else t for t in translations]
            cache.put("translation", key, TypeAdapter(list[TranslationResult | None]).dump_json(safe))
        result = []
        for text, lex, translation in zip(texts, lexical, translations, strict=True):
            if isinstance(translation, Exception):
                result.append(translation)
            elif isinstance(lex, Exception):
                result.append(lex)
            else:
                if translation is not None:
                    hint = hints[len(result)]
                    translation = replace(translation, metadata={**translation.metadata, "requested_target": options.target_language,
                        "glossary_application": "hints" if hint else "unsupported" if options.glossary_enabled and not support.glossary_hints else "none",
                        "glossary_terms": len(hint)})
                result.append(replace(lex, translation=translation))
        return result

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
