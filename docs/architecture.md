# YomiScan architecture

## Phase 1: implemented OCR boundary

Local cropped image → Pillow decoding → `OCREngine.recognize(image)` → `OCRResult`

The `yomiscan` package lives under `backend/`. `ocr/base.py` defines a structural
Protocol and a dataclass containing text, engine name, inference milliseconds, and
optional metadata (an empty dictionary by default). It does not define bounding boxes.
`ocr/manga_ocr.py` adapts manga-ocr, imports it lazily, initializes once per instance,
and preserves third-party exceptions as causes of contextual errors. `ocr/cli.py`
validates input and formats results; `scripts/ocr_image.py` is its entry point.

Inference runs locally. Initial dependency/model downloads require internet; cached
weights support offline use. Unit tests mock the neural network and cannot establish
recognition accuracy. Phase 1 has successfully run on real screenshots; broader
accuracy evaluation remains required.

## Phase 2: implemented analysis boundary

```text
image → OCREngine → OCRResult.text
                          ↓
text → JapaneseTokenizer → ordered JapaneseToken values
                          ↓
               indexed local SQLite JMdict lookup
                          ↓
                   TextAnalysisResult
```

`nlp/base.py` defines the token dataclass and structural tokenizer protocol.
`FugashiTokenizer` owns one fugashi Tagger using the explicitly selected UniDic-lite
dictionary. It retains lemma, written reading, POS hierarchy, conjugation type/form,
orthographic base, and base reading. Missing UniDic values become `None`.
Kana is normalized to hiragana without inventing long vowels or unknown readings.

`dictionary/importer.py` streams official JMdict XML/XML.gz once into SQLite.
`entries` stores each entry's spellings, readings, English senses, expanded POS labels,
reading/sense restrictions, and notes as JSON. Omitted sense POS inherits the preceding
sense POS. `forms` has a composite primary-key index `(form, entry_id)` for parameterized
exact lookup; normalized forms use NFKC and katakana-to-hiragana conversion. `metadata`
records provenance, source hash, import time, attribution, and the transformation.
The importer builds in a temporary sibling file and replaces the destination only
after a successful complete import; the schema has an explicit version.

`SQLiteDictionary` keeps one read-only connection for its context-manager lifetime.
It never creates an empty database on a missing-file lookup. `TextAnalyzer` accepts
the tokenizer and a small dictionary lookup protocol, so tokenizer benchmarks need
not change the dictionary or OCR adapters. A per-analysis query cache avoids repeating
lookups; no persistent/global cache is needed.

Lookup tries the written base (`orthBase`), UniDic lemma, surface, and base reading in
that order, stopping at the first exact match. There is no substring matching or
handwritten deconjugation. Written base forms avoid UniDic lemma labels with foreign
suffixes. Punctuation/symbol-only tokens are preserved but skipped for lookup.

`TextAnalysisResult` retains original text, ordered `AnalyzedToken` values, and a map
of unique entries keyed by JMdict ID. Each analyzed token contains the morphological
token, matched query, and entry IDs. This avoids copying large entries for repeated
words. `ImageAnalysisResult` combines the OCR result with text analysis. The text CLI
does not construct an OCR engine; the image CLI constructs it once per invocation.

Full candidate entries are exposed, including restrictions. This version does not
select a context-specific sense, filter homophones by POS, join multi-token expressions,
or apply restrictions as a grammatical interpretation. Those limitations are visible
in CLI output. Source XML/databases live in ignored `data/`; they are never committed.

## Phase 4: implemented study mode

```text
Chrome extension action / keyboard command
  ↓
viewport rectangle selection → cropped screenshot
  ↓
localhost FastAPI
  ↓
ImageAnalysisService
  ├── OCREngine
  ├── TranslationEngine
  ├── JapaneseTokenizer
  └── local SQLite JMdict
  ↓
Pydantic JSON response → one detailed study popup
```

The popup contains original Japanese, English sentence translation, readings, lemmas,
dictionary forms, POS, conjugation and dictionary candidates. OCR editing/reanalysis,
grammar explanations, JLPT metadata, vocabulary storage/export remain future work.

`service.py` wraps the existing `analysis.analyze_image` composition in
`ImageAnalysisService`. The composition root `open_local_service` creates a tokenizer,
read-only dictionary, OCR engine and translator once. The service accepts injected
engines; it has no HTTP dependencies. Existing CLI tools remain unchanged.

`api/main.py` uses FastAPI lifespan to open resources on a dedicated single-worker
executor. Creation, inference, and cleanup all happen on that same thread, preserving
SQLite's thread affinity without weakening its checks. One application process owns
one set of models. Inference does not block the event loop; `/health` remains responsive.
An overlapping request gets 429 instead of accumulating queued work. Cancelling an
HTTP request does not release the busy slot until its running inference finishes.
Initialization failure is logged and leaves `/health` and analysis unavailable (503);
fix resource setup and restart. Run one Uvicorn worker for this local MVP.

The route validates a multipart file, delegates decoding and service execution to the
worker, then maps domain dataclasses to Pydantic DTOs in `api/models.py`. It contains no
tokenization, dictionary search or model generation logic. `original_text` and optional
sentence `translation` remain separate from each token's grouped dictionary senses.
Senses retain entry IDs, POS, restrictions, notes and usage labels. Timing fields are
`ocr_ms`, `translation_ms`, `analysis_ms`, and worker `total_ms` (decode, inference and
analysis; excludes HTTP upload and model startup). No model-specific objects cross HTTP.

Image decoding in `api/images.py` validates actual PNG/JPEG/WebP data, rejects animation,
checks dimensions before loading pixels, applies EXIF orientation and returns RGB.
Limits are 10 MiB per image and 12 megapixels. `api/security.py` bounds the full multipart
body to 10 MiB + 64 KiB before parsing, including streamed requests. Errors: invalid
image 400, oversized upload 413, malformed/missing fields 422, busy 429, unavailable
resources 503, unexpected inference 500. Detailed errors remain in backend logs.

Loopback binding is the default documented deployment. Trusted Host checks accept
localhost/127.0.0.1/[::1]. CORS accepts syntactically valid Chrome extension origins by
default; `YOMISCAN_EXTENSION_ORIGINS` optionally narrows this to explicit origins.
Ordinary webpage origins are denied. A required `X-YomiScan-Client` header prevents
simple cross-origin form submissions from starting inference; it is not a secret or
local-process authentication. No wildcard CORS, accounts, or internet-facing service.

The extension is plain TypeScript with esbuild, no framework. Its action/command injects
`content.ts` into the active main frame. A temporary Shadow DOM overlay tracks pointer
coordinates, clamps the rectangle and supports Escape. The overlay is removed before
two animation frames pass; then `background.ts` verifies the active tab and viewport,
captures the visible tab, crops via OffscreenCanvas and POSTs only the PNG crop.
Screenshot-to-CSS ratios handle normal zoom/scaling without assuming screenshot pixels
equal `devicePixelRatio`. Scroll offsets are already accounted for by viewport coordinates;
they are not added again. Scroll/resize/visibility changes invalidate pending capture.
Pinch zoom is rejected. Selection IDs suppress stale results after close/reselection.

The service worker handles localhost requests with fixed URLs, no credentials, no
redirects, and a 25-second timeout. The extension validates nested JSON shapes before
rendering. `popup.ts` uses text nodes for all response data, one closed Shadow DOM popup,
viewport-clamped placement, internal scroll, × and Escape. Extra senses expand inside
the popup. Original OCR is a dedicated read-only section for future editing.
Cancellation aborts the client fetch, not synchronous backend model work. No history
or screenshots are persisted. See [extension instructions](../extension/README.md).

## Phase 5: implemented single-page analysis

```text
full page -> TextDetector -> raw TextRegion boxes (optional polygons)
  -> clip/filter -> conservative grouping -> initial reading order
  -> padded TextBlock crops -> shared OCREngine
  -> Japanese validation -> shared TextAnalyzer.analyze_many
  -> batched TranslationEngine + tokenizer/JMdict
  -> PageAnalysisResult -> CLI/debug JSON or PageAnalysisResponse
```

`detection/base.py` defines geometry and the detector Protocol; `rtdetr.py` owns all
model-specific preprocessing and original-pixel postprocessing. `page_layout.py` owns
geometry grouping/order; `page.py` owns orchestration and block failures. `page_cli.py`
provides numbered overlays and optional developer JSON. Detection never performs OCR.

`ImageAnalysisService.analyze_page` lazily creates and retains a PageAnalysisService on
its existing owning worker. It shares Study Mode's OCR/analyzer and therefore translator,
tokenizer and dictionary connection. The page endpoint uses the same upload validation,
security, busy guard and cancellation lifecycle; missing detector resources do not change
Study Mode availability. Page and Study requests cannot race the shared models/SQLite.

`TextAnalyzer.analyze_many` batches translation, preserves input order, and isolates known
translation failures by retrying individually. Ordinary `analyze` retains its original
behavior. Page results preserve raw regions, filtered reasons and block membership without
copying raw regions into every block. API DTOs reuse Study Mode token serialization.
Per-block known OCR/analysis errors preserve successful neighbors and safe error messages.
Unexpected programming failures remain overall errors instead of being silently hidden.

Default detections already represent blocks; only explicitly line-level detections can
be geometrically joined. Default orientation/category stay unknown. Reading order is a
band-based top-to-bottom/right-to-left heuristic, not panel understanding. Debug overlays
number raw detections; JSON joins these IDs to final blocks and OCR/status. See the
[Phase 5 model decision and validation](phase-5-page-analysis.md) for exact thresholds,
cache behavior, licensing, measured CPU results, and unresolved full-page evaluation.

Image modification (masking, inpainting, typesetting, translated overlays) remains future.

## Replaceability

Consumers can accept `OCREngine` without depending on manga-ocr. Future benchmarks may
compare PaddleOCR or other Japanese recognizers behind that interface. The
`TranslationEngine` boundary serves the same purpose for translation and is now
implemented. No plugin registry or speculative framework is needed. Benchmark accuracy,
latency, resource use, licenses, and Windows/Python compatibility before choosing major
components. `JapaneseTokenizer` allows a later comparison with SudachiPy without
changing the analysis pipeline. CPU support must remain possible; paid/cloud APIs are
outside the design.

## Phase 3: implemented sentence translation

```text
cropped image → OCREngine → Japanese text
                                ↓
                         TranslationEngine → TranslationResult
                                ↓
                      tokenizer + local JMdict lookup
                                ↓
                         TextAnalysisResult
```

`translation/base.py` defines `TranslationResult` and a structural `TranslationEngine`
protocol with `translate(text)` and `translate_many(texts)`. Results retain the exact
source, translated text, engine/model identifiers, elapsed milliseconds, and metadata.
The sequence contract preserves order and cardinality. Empty batches return `[]`;
blank members reject the request before inference. Exceptions propagate with context.

`MarianTranslationEngine` loads one pinned OPUS-MT tokenizer/model pair, sets eval mode,
and reuses it under PyTorch inference mode. No model imports occur until construction.
The adapter owns whitespace normalization, generation parameters, input length checks,
and device handling. It pads independent regions in bounded batches (default eight),
does not silently truncate source text, and rejects incomplete generated text.
Results within a batch share the complete batch elapsed time; this is not per-item
latency or an amortized estimate. Timing covers tokenization, transfers, generation,
decoding, and CUDA synchronization, excluding model setup/download.

`auto` uses available CUDA, otherwise CPU; explicit unavailable CUDA fails. CUDA
runtime failures do not silently retry on CPU. No global mutable model state, plugin
registry, configuration framework, or cloud service exists. Model instances are used
sequentially; thread-safe concurrent inference is not promised by this interface.

`TextAnalyzer` optionally accepts an existing translator, calls it once per nonblank
region, then performs the unchanged lexical lookup. `TextAnalysisResult.translation`
is a separate optional result; `dictionary_entries` still holds lexical candidates.
`processing_time_ms` on text analysis measures NLP/dictionary work only. Without a
translator, or with blank input, translation is `None`; Phase 2 callers continue to
work. A requested translation failure raises instead of masquerading as lexical-only
success. `ImageAnalysisResult` retains separate OCR and analysis results/times.

The standalone translation CLI accepts multiple quoted regions. Text analysis adds
opt-in `--translate`, while image analysis translates by default with an explicit
`--no-translation` option. Models are constructed once per invocation, never per token.
Dictionary attribution remains visible independently of generated English.

## Translate Chapter: future orchestration only

```text
chapter reader
  → discover manga page images
  → process each page independently
  → detect ordered Japanese text regions
  → OCR / reconstruct complete sentences within those regions
  → translate sentences (existing batch-capable boundary)
  → inpaint Japanese → typeset English
  → overlay translated image; offer Original / English switch
  → continue through chapter and newly lazy-loaded images
```

The user-facing unit is a chapter; the internal image-processing unit is normally one
manga page. A future caller can prioritize visible/current pages, then later pages,
and react to lazy loading. It can associate ordered translation results with region
IDs outside the engine and reuse one model across pages. A batch contains independent
regions, not a concatenated chapter or dictionary tokens. Cross-region conversational
context is not provided by the current translator. Future reading mode may add
context-aware/batched translation. No chapter discovery or page scheduling,
inpainting, typesetting, or image replacement is implemented here. Single-page detection
and analysis are now provided by PageAnalysisService. See the
[model decision and evaluation](phase-3-translation.md).
