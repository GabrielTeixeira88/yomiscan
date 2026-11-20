# YomiScan architecture

Phases 1–7 below describe the existing MVP boundaries and retain their historical names.
Post-MVP increments use descriptive feature branches, not a new numbered phase.

## Post-MVP terminology and experimental translation

`glossary.py` owns persistent user-created series/target terms in a separate SQLite
database. It uses explicit labels/UUIDs, normalized uniqueness, global fallbacks and
per-series overrides. Cache clearing never owns this data. The same single executor
owns its creation/use/closure; corruption fails visibly without deletion.

`translation/options.py` contains immutable per-request options and explicit engine
capabilities. `TextAnalyzer.analyze_many()` retrieves reusable lexical results before
matching normalized complete-token terminology. Only applicable hints reach compatible
adapters; no OCR/output replacement occurs. Native OPUS English batching/retry remains
the default. `NMTTranslationEngine.translate_many_to()` sets verified NLLB target IDs;
separate pinned Marian adapters handle JA→PT/ES without an English pivot.

`translation/structured.py` owns stable segments, complete source/context/hint limits,
minimal exact-ID JSON schema, strict whole-result parsing and bounded context selection.
`MangaTranslationEngine.translate_page()` collects every requested group before
publishing any results. The existing `LlamaServer` uses its owned loopback process,
actual template/token preflight, schema-constrained decoding and explicit termination
checks. Cancellation stops that owned runtime; no partial-page cache or model fallback
is published. This is an optional English-only contract for Hy/Qwen manga fine-tunes,
not a quality claim or support for every model prompt.

`panel_order.py` optionally applies bounded white-gutter XY cuts after extraction.
Stable IDs, crop identities and OCR remain unchanged. Its independently cached ordering
feeds translation/context; ambiguous partitions retain bands without dropping IDs.
No geometry identifies speakers. Cross-page memory is absent.

The extension's `translation-settings.ts` presents only supported targets/contracts
and edits explicit user scopes. Expected glossary hashes accompany page jobs. Changed
options/term broadcasts retire affected sessions and overlays; a successful local edit
invalidates before profile reload, including failure/busy reloads. Backend stale-hash
checks reject old jobs. The transport carries typed `options_json`; legacy uploads and
Study remain supported. Backend engine selection remains the existing environment
setting rather than a new model manager.

Translation cache identity includes effective matched hints, target, model/runtime,
stable source IDs/order, context, prompt and grammar implementations. Rendering inherits
that lineage and font identity. Unchanged extraction/lexical entries stay reusable;
unused glossary edits or unsupported hints do not force neural recomputation. The
bundled OFL Noto fallback handles accents missing from Aileron; ordinary English
continues its existing font, and unsupported scripts are rejected before masking.

Stage 1 diagnostics add only allowlisted target/contract/context IDs/token metadata
and ordering/fallback provenance. Raw replies are a separate opt-in local benchmark
facility, not a default reader export. See [Stage 4 controls](post-mvp-translation-improvements.md),
[primary sources](research/stage4-primary-sources.md) and
[measured decisions](research/stage4-translation-results.md).

## Post-MVP stage caches and chapter memory ownership

`cache.py` owns a worker-local bounded byte LRU and opt-in SQLite BLOB storage.
`cache_identity.py` builds effective artifact/configuration identities independently
of redacted diagnostic metadata. Known adapters use hashes of their actual local
artifacts and effective generation/preprocessing settings; unidentified engines
bypass reuse. Tokenizer/dictionary adapters own their identities. SQLite dictionaries
reopen an atomically replaced file where the platform permits replacement; Windows
normally requires stopping the backend before reimporting its open database.

`PageAnalysisService.extract()` separates detection/grouping and crop OCR from
translation/lexical analysis. `TextAnalyzer.analyze_many()` preserves the existing
ordered native translation batch and known per-block fallback behavior. Lexical
entries are independently reusable and never include sentence translations.
`rendering/cache.py` stores typed metadata plus PNG and keys renderer settings/font,
actual page/translation inputs and extraction/translation lineage. Dictionary-only
changes do not invalidate an otherwise identical rendered page.

The service creates one request trace across stages. Translation refresh bypasses
translation/render entries; failed refreshes leave previous good entries available.
Cached inference timings are zero for the current job; lookup/deserialization and
actual pipeline wall time are observed separately. Stage 1 upload-byte hashes retain
their meaning alongside versioned canonical color/mode/alpha hashes. No URL is a
cache identity. Debug images remain explicit and bypass the normal render cache.

The existing single executor owns inference, dictionary and processing-cache SQLite
creation/use/closure. Guarded cache controls run on that same executor. Disk storage
is disabled until local consent; no telemetry/upload or file-access API is added.

`ChapterQueue` owns result sizes, LRU order, pins, deferred releases and `evicted`
states. `ChapterTranslationSession` reserves 256 KiB for at most three failed reports
within the 128 MiB total; successful contexts and original report pixels have exactly
one result owner. Visible/refreshing/exported results are protected. Eviction never
schedules more work; viewport events can enqueue an eligible evicted result. Overlay
references switch/detach before obsolete URLs are revoked. Export pins bind exact
results even when a source/refresh replaces the page record.

Backend session generations and expected configuration IDs prevent old browser
results from being attached after a changed backend/settings generation. Legacy
backends receive a new browser generation on each Start. Persistence is stage-keyed
and remains reusable across backend generations. See [design decision](decisions/stage-cache.md)
and [controls, limits and validation](post-mvp-caching-performance.md).

## Post-MVP detector/OCR evaluation boundary

The existing TextDetector and OCREngine protocols remain the consumer interfaces.
Factories select the original engines by default; explicit YOMISCAN_DETECTOR/YOMISCAN_OCR
settings opt into local experimental adapters. Detector construction stays lazy on the
owning worker; selected OCR and translation resources share the service lifetime.
ONNX Runtime is an optional dependency and its CPU sessions disable telemetry before
construction. Experimental adapters require pinned, hash-verified cached artifacts;
the separate setup script is the only new download path.

The detector supports independent bubble/free-text thresholds while retaining the
legacy threshold argument and 0.50 defaults. Its ONNX candidate uses a separately
pinned export whose weight equivalence is unproven. OCR controls separate original/2025
weights, grayscale/RGB preprocessing, published/greedy generation and ONNX KV reuse.
Uncalibrated confidence is additive OCR metadata and never an automatic rejection gate.
Experimental token-limit failures are explicit; source text is not silently truncated.
Stage 1 report allowlists carry the optional provenance and confidence method.

vision_benchmark owns local annotation loading, metrics, isolated benchmark entry points
and aggregate summaries. It reuses the existing page/grouping/OPUS/JMdict/renderer path
for downstream measurements. It is not a reader scheduler, model manager or persistent
cache. See [Stage 2 commands and measurement definitions](post-mvp-detection-ocr.md),
[artifact provenance](research/stage2-model-provenance.md) and
[measured decisions](research/stage2-detection-ocr-results.md).

## Post-MVP reliability and diagnostics

Chapter rendering can opt into an in-memory PNG + diagnostic-snapshot transport bundle.
The default render-page PNG and analysis DTOs remain compatible. The existing owning
worker builds the snapshot from its one analysis/render result; no export reruns models.
The extension validates the input byte hash/dimensions and retains the snapshot with the
same page result. A page-level user action builds a local ZIP with allowlisted metadata;
text and original/translated pixels require separate inclusion choices.

diagnostics.py owns the bounded snapshot/transport representation; chapter/reports.ts
owns export consent/redaction, and chapter/zip.ts owns stored ZIP integrity/limits.
There is no dedicated backend report store or new authentication bypass. Stage 3's
separate opt-in processing cache is described above; report inclusion consent is unchanged.
See [privacy/retention decision](decisions/diagnostic-report-privacy.md) and
[usage/schema/validation](post-mvp-reliability-qol.md).

ChapterQueue also supports explicit successful-page refresh. It retains the old result
through queued/processing/failure states, replaces it only after validation, and releases
late/cancelled URLs. Acquisition errors preserve actionable viewport/manual retry types
and causes. The Study popup adds user-gesture clipboard actions without new permissions.

Sentence translation also has opt-in manga adapters and an isolated benchmark.
`translation/factory.py` selects the unchanged Marian default or a lazy local llama.cpp
adapter, or a lazy direct Transformers NMT adapter (`fugumt`, `nllb-600m`).
NMT batches independent sentences, without claiming dialogue context or glossary support.
NLLB explicitly sets Japanese source and forces English target language. Optional
`TranslationContext` capabilities preserve existing `TranslationEngine`
callers and JMdict. The application owns one selected engine and closes its subprocess
or model references with the service lifecycle. Chapter orchestration and rendering are unchanged.
See [benchmark boundaries and evidence](translation-benchmark.md).

Rendering coverage now distinguishes bubble/narration, artwork text and preserved SFX.
Tight masks and placement regions remain separate; a light-edged glyph fallback is
local to rendering. Per-block stage diagnostics and aggregate coverage metrics travel
through `PageRenderResult`; the default PNG API exposes aggregate counts in an additive
header used by chapter summaries. Opt-in diagnostic transport also carries per-block
provenance. See [coverage decisions and validation](phase-7-coverage.md).

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

Single-page masking, inpainting and typesetting are implemented in Phase 6 below.
Browser translated overlays now consume this single-page pipeline through Phase 7.

## Phase 6: single-page rendering

```text
ImageAnalysisService.translate_and_render_page(image, optional analysis)
  -> PageTranslationRenderService
     -> reuse supplied PageAnalysisResult OR analyze_page once
     -> PageRenderer.render(image, analysis)
        -> conservative mask + safe text area
        -> Typesetter.layout_text (fit before erasing)
        -> InpaintingEngine (isolated crop)
        -> Typesetter.draw_text (isolated crop)
        -> commit only successful mask/text pixels
  -> PageRenderResult: lossless image, statuses, timings, optional debug images
```

`rendering/base.py` provides the two lightweight image-rendering/inpainting Protocols.
`masks.py` separates connected foreground components from flat light/dark backgrounds,
rejects uncertain outlines/textures. `layout_regions.py` separately estimates enclosed
bubble/narration interiors and inscribed layout rectangles; open backgrounds fall back
to bounded clear-strip expansion. Interior geometry never becomes a white fill mask.
`inpainting.py` uses uniform masked-pixel fill when the surrounding ring is flat, otherwise
OpenCV Telea. Detailed artwork regions are normally skipped. `typesetting.py` owns cached
Pillow Aileron fonts, balanced measured wrapping, preferred/minimum/maximum font sizes,
center alignment and margins. Same-class contained duplicate block predictions share
one OCR crop in `page_layout.py`, preserving raw detector IDs; thresholds are unchanged.
`renderer.py` keeps each edit transactional: layout overflow or mask/inpaint/draw failure
preserves original pixels. Known SFX and overlapping detections are preserved.

The application lazily retains one rendering service alongside the existing page service.
It does not reload any model per block. `POST /api/v1/render-page` uses the same worker,
upload validation and security as existing endpoints; it returns PNG and bounded count/
timing headers, with no disk persistence. CLI debug mode writes numbered stages and JSON.
Rendering depends on structured analysis, not the detector's model implementation.
No additional inpainting model weights or system-installed fonts are required.

The complete page boundary is called by the Phase 7 browser orchestration without
understanding masks/layout. The backend remains single-page only; queues, discovery,
lazy-load observation, session caches and Original/English controls live in the extension. See the
[Phase 6 decision and visual evaluation](phase-6-rendering.md).

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

## Phase 7: implemented Translate Chapter orchestration

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

The user-facing unit is a chapter; the internal processing unit is one page. The extension's
`chapter/discovery.ts` chooses a dominant column of sufficiently large loaded images,
excluding common navigation/ad/avatar contexts. It exposes a small discovery interface
for future strategies. `chapter/model.ts` owns typed page records and a serial queue.
DOM element + selected source + dimensions + same-source reload revision identify a
page. Contained source changes invalidate results; late stale jobs cannot replace newer ones.

`chapter/session.ts` owns health checks, debounced DOM/load observation, viewport
priority, source acquisition, result validation, per-session URL cache and lifecycle.
`acquisition.ts` owns a typed fallback chain: verified extension-worker source fetch,
safe page canvas, viewport crop and opt-in scroll stitching. `source-fetch.ts` resolves
only active loaded-image tickets, enforces host permissions and bounded image responses.
`image-access.html` requests optional host access from a direct extension-page gesture.
`stitching.ts` restores scroll on every exit and keeps capture geometry separate from
discovery/rendering. No backend URL fetching, whole-chapter screenshot or access bypass
is implemented. See [acquisition and real-reader validation](phase-7-acquisition.md).

`chapter/transport.ts` sends bounded image chunks through runtime ports to `offscreen.ts`.
The extension-origin offscreen document makes long localhost render requests, serializes
across chapter tabs, and releases intermediate buffers on completion/disconnect. It
avoids service-worker fetch lifetime limits without exposing a web-accessible iframe
bridge. No chapter-specific backend endpoint was needed. Existing Study Mode remains
on its original worker screenshot/analysis path and shares the backend's busy guard.

`chapter/overlay.ts` uses fixed pointer-transparent images inside closed Shadow DOM;
their geometry follows source bounds, object-fit/position and ancestor clipping on
scroll/resize. Site `src`, `srcset`, layout and original pixels are never rewritten.
Only nearby overlay nodes retain decoded image sources; compressed Blob URLs are cached
for instant Original/English toggles. Stop retains results and lets the current job
finish; Clear/navigation revokes URLs and discards late results. Controls live in their
own Shadow DOM. Study activation stops scheduling and selects Original before capture.

No cross-region conversational context or translation-engine redesign is included.
See [Phase 7 limits, lifecycle and browser validation](phase-7-chapter.md) and the
[translation model decision](phase-3-translation.md).
