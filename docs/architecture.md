# YomiScan architecture

Phases 1–7 below describe the existing MVP boundaries and retain their historical names.
Post-MVP increments use descriptive feature branches, not a new numbered phase.

## Stage 1 foundation (independent-assessment Option C)

Strategy and gate: [independent assessment](independent-assessment/README.md),
[Stage 2 gate](decisions/stage-2-feasibility-gate.md).

**Study selections read every block.** `ImageAnalysisService.analyze_image` runs the
page detector on the selection (`PageAnalysisService.detect_blocks`). With two or more
blocks, each padded block is OCR'd separately in reading order (`recognize_blocks`),
translated as one ordered batch, and tokenized per block. `analysis.analyze_recognized_blocks`
joins texts and translations with newlines, keeping the existing Study response contract.
With zero or one block, or with detection off/unavailable/failed, the whole selection is
read as before. The response's `provenance.study_ocr` records `mode`, `blocks` and an
optional text-free `reason`. `YOMISCAN_STUDY_DETECTION=auto|off` (default `auto`) is read
by the composition root. An unprepared or failed detector is remembered, so Study
does not retry its initialization on every request. Selection reads are not cached.

**Ranked dictionary candidates.** JMdict schema 2 stores `ke_pri`/`re_pri` tags per
exact form (`DictionaryEntry.form_priority`). Schema 1 databases remain readable, with
empty priorities and a startup warning. `lexical_ranking.py` holds deterministic,
data-driven rules. `choose_matches` keeps the first-matching-form lookup for content
words. For particles/auxiliaries it may continue to a later form (ん → lemma の) when
that form's entry is primarily the right part of speech. `rank_entries` orders by
kanji-lemma agreement, then first-sense/later-sense POS agreement (UniDic `pos1` →
JMdict labels), headword, reading, JMdict "common" tags, `nfXX` band, and entry ID.
Particles and auxiliaries drop non-agreeing homophones when an agreeing entry exists.
Sense order within an entry is unchanged. The lexical cache key includes the ranking
module.

**Multi-token units (Stage 3).** `lexical_units.py` finds expressions that span tokens
(かもしれない, しょうがねえ → しょうがない, 主導権を握る) by longest JMdict match. Each candidate is tried
as written, then ending in the last token's dictionary form, then with colloquial
variants. Selection is global, so a longer unit beats an earlier, shorter, overlapping one.
The rules are data in `resources/lexical/units.json`, in a format the browser build can
read too:
- **variants:** colloquial-to-standard spellings;
- **interjections:** allowed only at the start of a clause (しまった in 食べてしまった is not "oh no");
- **particle/auxiliary edges:** only functional entries count (expression, particle,
  conjunction, auxiliary, copula, interjection, pronoun; common adverbs), so は+と is not
  "pigeon" and し+て is not "doer";
- **verb spans:** a span containing a verb is never a bare particle or a pronoun;
- **forbidden starts:** a unit never starts on た, て or を.

Units are an extra layer (`TextAnalysisResult.units`, `units` in API responses). Token
analysis is unchanged, and the Study popup lists them under "Expressions" above the word
breakdown. Known limit: a single-entry でも mid-sentence still shows "but" first.

**Grammar notes (Stage 3).** `grammar_patterns.py` matches constructions that JMdict does
not list (〜てしまう, 〜ている, 〜だろう, 〜ことができる, passive/potential, causative, the two
meanings of 〜そうだ, and about 30 more). The patterns are data in
`resources/lexical/grammar.json`. A pattern is a sequence of token steps (`surface`, `base`, `pos`,
conjugation `form`), with an optional `after` step for the preceding token. The て-patterns
require a verb, adjective or auxiliary before them, so 僕でも is not 〜ても. At one start,
the longest match wins; a match nested inside another is dropped (ば inside
なければならない). Matches are `TextAnalysisResult.grammar` and `grammar` in API responses
(id, name, short learner meaning, token span), and the popup lists them under "Grammar". The
evaluator accepts a grammar note whose forms include an expected unit (てしまう, だろう).

**Inflection labels and furigana (Stage 3).** `inflection.py` names how a verb or
adjective is inflected, from rule data in `resources/lexical/inflections.json`. For each
head it reads the head's own form (imperative, volitional), then the auxiliaries and
て/で/ば that follow it, in order: 食べなかった = negative, past; 行きませんでした = polite,
negative, past; 高くなかった = negative, past. An unknown auxiliary such as the copula だ ends
the word. Labels attach to the head (`AnalyzedToken.inflection`, `inflection` in the API),
and the popup shows them as "Form: negative · past". Furigana is aligned in the extension
(`extension/src/furigana.ts`, pure, so a browser engine can reuse it). Kana runs anchor the
reading and each kanji run takes the reading between them (食べ → 食(た)べ). An unalignable
reading is shown over the whole word instead of a wrong split. The word breakdown renders
it as DOM `<ruby>` nodes.

**Correcting OCR in Study (Stage 3).** The popup's "Edit text" button opens a text area
with the recognized text. "Analyze edited text" sends it (1–1,000 characters) through the
background worker to `POST /api/v1/analyze-text`. That endpoint runs
`ImageAnalysisService.analyze_text` on the same single worker and busy guard as images. It
does lexical analysis and sentence translation only, with no screenshot and no OCR. The
security guard bounds its body to 8 KiB. The response is the usual Study JSON with
`analysis_origin: "edited"`, and the popup re-renders in place.

**Choosing the translation engine (Stage 3).** The Setup panel lists translation engines
that readiness reports as installed with their runtime available, and offers "Use" for each.
`POST /api/v1/translation-engine` validates the catalog ID and checks the artifacts on the
model worker. `ImageAnalysisService.select_translation_engine` then creates the new engine
before swapping it into the shared `TextAnalyzer`, so a load failure keeps the previous one,
and the previous engine is closed. The configuration ID changes, so open chapter sessions
restart instead of mixing engines. The cache identity already includes the engine. The
choice lasts until restart; `YOMISCAN_TRANSLATION_ENGINE` remains the startup default.
OPUS stays the default: the Stage 2 blind ratings that would choose another are not done yet.

**Configurable loopback port.** `extension/src/backend.ts` owns the backend address:
`http://127.0.0.1:<port>`, default 47615 (not AnkiConnect's 8765), with an optional
`backendPort` in `chrome.storage.local` (1024–65535), edited in Setup & readiness.
The service worker and content scripts read it from storage. The offscreen document has
no storage access, so the content-side transport sends the origin in its `begin`
message and the offscreen document accepts only a parsed loopback origin.
`yomiscan-server --port` defaults to the same 47615 (`cli.DEFAULT_PORT`).

**Study selection document identity (audit AU-01).** `navigation.documentKey` (origin,
path and query; hash ignored) is recorded at capture. Screenshot verification rejects
a changed document. A reply that arrives after a document change is discarded with an
explanation, and Chrome's Navigation API `navigate` event closes a pending selection or
discards a processing one. The browser fixture reproduces a `pushState` chapter change
during processing.

**Study popup.** Senses of the best-ranked entry are shown first. Other entries are
folded under "N other dictionary entries" with dividers, so another word's senses never
appear as this word's. The footer states how a selection was read
(`provenance.study_ocr`). Text actions (`button.action`) no longer inherit the 30×30
close-button size (audit AU-04).

**Evaluation.** `lexical_evaluation.py` (`scripts/evaluate_lexical.py`) scores ranking
against `benchmarks/lexical-golden.jsonl` without models. See
[evaluation sets](evaluation/README.md). The page-corpus manifest reuses `vision_benchmark`.

**Deferred from Stage 1, with reasons.**
- *ONNX INT8 detector as default:* **evaluated and not adopted** (2026-11-24). On the
  23-page draft corpus its recall was 2.4 regions per 100 below PyTorch (dialogue 1.1;
  held-out 5.7), which fails the adoption rule of 1 per 100. It is about 4× faster per page,
  so it stays selectable, and the rule will be rerun on the reviewed 40-page corpus. See
  [evaluation sets](evaluation/README.md#recorded-baseline-2026-11-24-draft-annotations).
- *CUDA-enabled PyTorch for the owner's GPU:* resolving CUDA wheels in `uv.lock` affects
  every platform and CI download size. Stage 2 may make PyTorch optional (ONNX/browser
  runtimes), so this waits for that decision. A CUDA build installed into the local
  `.venv` with `uv pip` works for experiments, but the next `uv sync` restores the locked CPU build.
- *Expanded translation set:* waits for real lines from the page corpus.

## Stage 4 reading mode

**Read Chapter keeps the Japanese on the page.** It is the chapter session
(`chapter/session.ts`) with `mode: "read"`. It reuses page discovery, the acquisition chain,
viewport priority, the LRU budget and the single-job queue. Pages are still processed
visible first, then the next pages, so upcoming pages are read before the user reaches
them. Instead of `render-page`, each page goes through the offscreen transport with
`kind: "analyze"` to `POST /api/v1/analyze-page`. That call does detection, OCR, ordering,
lexical analysis and sentence translation, but no masking, inpainting or typesetting. It
accepts the same `job_id` (stage progress), `configuration` (409 on a stale session),
`refresh` and `options_json` as `render-page`. Each block also carries the translation
`provenance`. `chapter/reading.ts` validates the JSON: dimensions must equal the acquired
pixels, boxes must lie inside the page, and there are at most 256 blocks. Each successful
block becomes a Study `Analysis` (`analysis_origin: "page"`), sorted by reading order.
Filtered, failed and empty blocks are counted, not shown.

**Text layer.** `chapter/reading-layer.ts` draws one faint outline button per bubble in a
closed shadow root above the page. It maps boxes with `displayedRegion`, clips them to
scroll containers, and refuses transformed or bordered images. Hovering strengthens the
outline. Clicking opens the Study card from the retained analysis: no screenshot, OCR or
request, so the card appears as soon as the page has been read. The layer stops pointer
events at its host, so a bubble click never turns the reader's page. It is hidden
synchronously during viewport captures and Select Text, so the outlines never enter a
screenshot.

**J / K.** A document `keydown` listener (ignored in inputs, text areas, editable content
and with modifiers) steps through bubbles in reading order across pages in document order
(`stepBubble`). It skips pages with no text, and stops with a message at a page that is
still being read instead of jumping over it. Pressed with no card open, it opens the first
bubble on screen in the nearest page. An off-screen bubble is scrolled to a quarter of the
viewport height, in the reader's own scroll container when it has one. The card shows
"Page N · bubble i of n".

**English per page.** Each read page has an English / Japanese toggle at its top-right
corner. The first request queues a refresh of that page. The worker renders it through
`render-page` from the retained page pixels, with no new acquisition. The backend's stage
cache supplies detection, OCR, ordering, lexical analysis and translation from the earlier
analysis, so only rendering runs (measured 1.4 s on CPU against about 3 s for the analysis).
The result keeps the reading data, so bubbles stay clickable over the English image.
Hiding and showing English again reuses the render. The global Original / English buttons
hide all pages or request every read page. Font changes rerender only pages that already
have English. Switching between Read Chapter and Translate Chapter replaces the session;
the backend caches make re-reading cheap.

## Stage 5a browser engine

`extension/src/engine/` runs page vision inside Chrome with ONNX Runtime Web, in the
offscreen document, without the Python backend. Increment 1 covers the detector,
production grouping and band order, and greedy manga-ocr, plus pinned, SHA-256-verified
model installation into Cache Storage from an explicit user action. The extension pages are cross-origin isolated (COEP `require-corp`,
COOP `same-origin`) so WASM runs multi-threaded; the CSP adds only `'wasm-unsafe-eval'`.
Increment 2 adds lexical analysis. `engine/lexical.ts` ports the analyzer, ranking, units,
grammar and inflection over the backend's own rule JSON. `engine/lexicon.ts` adds JMdict
SQLite (sqlite-wasm), the lindera UniDic tokenizer and the Study response. On the golden
set it matches Python token for token and scores the same 96.7%. Increment 3 adds OPUS-MT
(`engine/translation.ts`): fp16 on WASM threads with the backend's exact beam search and the
standalone `@huggingface/tokenizers`. It matched the backend on 175 of 178 real lines.
Increment 4 adds the `engineMode` setting (`engine-mode.ts`).
- Select Text and Edit text are routed to the engine by the service worker.
- Read Chapter uses a `browser` page-port kind that returns analyze-page JSON.
- English is drawn as fitted HTML text boxes by `chapter/reading-layer.ts`.

Increment 5 makes the choice **Automatic** by default. `resolveEngine` picks the browser engine
once its models are installed, otherwise a running backend, otherwise `setup`. The service
worker answers `engine-resolve` for the panel, and Select Text resolves before capturing.
`chapter/engine-setup.ts` is the first-run card: size, source, consent, progress, and models
that Chrome removed. The default model source is `engine/artifact-host.json`, a pinned Hugging
Face commit written by `scripts/publish_browser_artifacts.py`. The engine refuses downloads that
won't fit (`storageShortfall`) and reports quota errors per file.

See the [Stage 5a record](decisions/stage-5a-browser-engine.md) for increments, measurements
and the accepted memory footprint (about 2 GB with every model loaded).

## Stage 5b local engine (in progress)

Stage 5b packages a Torch-free local engine as an optional Windows companion. Increment 1 adds
Torch-free vision, opt-in with `YOMISCAN_DETECTOR=pinned` and `YOMISCAN_OCR=pinned`:
- `engine_models.py` downloads and verifies the files pinned in
  `resources/engine/local-manifest.json`. They come from the same Hugging Face commit as the
  browser bundle (`local-host.json`), via the explicit `yomiscan-prepare-engine` command.
- `detection/pinned.py` runs the fp32 RT-DETR-v2 export and reproduces transformers'
  preprocessing and post-processing. `ocr/pinned.py` runs the int8 manga-ocr export with the
  backend's greedy decoding, always on the CPU.
- `onnx_runtime.session` chooses the device: `YOMISCAN_ONNX_DEVICE=cpu` (default) or `directml`.

On the 23-page corpus, 99.1% of blocks give identical text to the Torch path end to end. With
DirectML, detection takes 143 ms per page instead of about 1 s.

Increment 2 adds Torch-free OPUS-MT ja→en (`YOMISCAN_TRANSLATION_ENGINE=opus-pinned`):
- `translation/opus_onnx.py` runs the fp32 ONNX export with the merged decoder's key/value cache.
- `translation/beam.py` ports transformers' beam search.
- `translation/marian_sentencepiece.py` replaces `MarianTokenizer` with `sentencepiece`.

It matches the Torch translator on all 153 lines of the translation set.

Increment 3 makes these engines the **defaults**:
- **Package:** Torch-free, on ONNX Runtime 1.24.4 (the DirectML build on Windows). PyTorch moves
  to the `reference` dependency group.
- **Entry point:** `engine_main.py` is the frozen engine's entry, with per-user paths and
  `--prepare`.
- **Build:** `scripts/build_engine.py` freezes it with `packaging/engine/yomiscan-engine.spec`.
- **Readiness:** `readiness.ENGINE_DEFAULTS` lists the three default components, and
  `prepare_command()` names the right setup command for the developer backend or the frozen
  engine. See the
[Stage 5b record](decisions/stage-5b-local-engine.md).

## Post-MVP reader controls, readiness and distribution

`rendering/settings.py` validates immutable font scale 0.75–1.5.
`PillowTypesetter.scaled()` retains absolute readable-size limits, margins, fallback
fonts and crop safety. The effective renderer participates in the Stage 3 render key;
`refresh=render` reuses extraction, lexical analysis and translation. The browser keeps
its old result until replacement succeeds. Font refresh losing any previously
rendered ID is rejected, even with unchanged total coverage. New pages still preserve
original pixels where no safe layout fits.

`chapter/region-inspector.ts` owns one explicit pinned page/result lease. It reads
retained diagnostics, separately labels detector/OCR confidence and reveals text only
on request. Pixel-to-image geometry follows scroll/resize, clips hit targets and
rejects transforms/borders/padding. Source, dimensions, session, result and navigation
checks retire stale inspection. Escape/disposal release listeners, pins and focus.
Successful block analysis uses the existing Study response contract under
`block.text.study`; Study Bubble opens the popup without screenshot/OCR/translation.
Missing/evicted/oversized snapshots explain reprocessing. Default report exports still
omit text, Study data and pixels. Extracting a neutral serializer from the API DTO is
optional maintenance, not another analysis pipeline.

`readiness.py` inspects pinned catalogs and local file metadata without downloading,
hashing large files, importing Torch or loading engines. Installed, integrity not
checked, loaded and experimental remain distinct. IDs are checked by component kind.
Catalog device modes do not certify runtime compatibility; observed rejection is
reported. Parent writability, cache enabled state and glossary open/unknown state are
distinct. The existing owning worker publishes snapshots after initialization, image
work and administration; readiness never queues behind neural inference.

`progress.py` holds at most 16 random job IDs, instance identity, monotonic versions
and text-free observations. Terminal records expire after 30 seconds. Actual stage/cache
callbacks report work/reuse/failure without another scheduler. Offscreen polls at
800 ms only while its request is active, with a 2 s read timeout. Content rejects
wrong jobs/instances/versions and stale sources/sessions. The single executor retains
resource ownership after cancellation. New readiness/job GETs use existing host,
origin and client-header protections.

`history.ts` serializes background-owned `chrome.storage.local` operations. History
defaults off and needs explicit Save, whitelists analysis/provenance fields, caps
storage at 100 entries/2 MiB and rejects entries above 128 KiB. It owns no images,
source URLs, processing caches or glossaries. Disable retains; Delete/Clear erase;
Export is an explicit JSON download. Chrome Sync is unused.

`scripts/build_distribution.py` builds an exact runtime-file extension ZIP plus
wheel/sdist from locked tooling, recording source commit, actual project-interpreter
versions and hashes. Clean installation checks both Python formats, CLI/fonts/imports
and protected missing-resource startup. A separate owned Chrome smoke loads the
actual extracted ZIP and activates controls. CI runs packaging after Windows/Linux
and Node gates, with manual dispatch and run-associated unsigned artifacts. Models,
JMdict, private samples and user data remain external. See
[Stage 5 controls](post-mvp-reader-experience-distribution.md),
[installation](installation.md) and [validation](research/stage5-validation-results.md).

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
and preserves third-party exceptions as causes of contextual errors. It decodes greedily
(one beam, no n-gram ban) instead of manga-ocr's published settings (4 beams,
`no_repeat_ngram_size=3`, length penalty 2), which alter genuinely repeated text such as
doubled words and laughter. On the Stage 2 corpus (225 production crops) this lowered
normalized CER from 3.19% to 1.61% with no new failures, and the CPU median fell from 415 to
310 ms per block. The OCR engine name `current-published` keeps the library's own call for
comparisons. The decoding is part of the OCR cache identity, so results cached with the
earlier decoding are not reused. `ocr/cli.py`
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

Full candidate entries are exposed, including restrictions. (Phase 2 record: this version
did not select a context-specific sense, filter homophones by POS, join multi-token
expressions, or apply restrictions as a grammatical interpretation. Ranking and units were
added post-MVP; see the sections above.) Those limitations are visible
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
