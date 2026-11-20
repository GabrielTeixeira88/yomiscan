# YomiScan vs Yomu — Technical Comparison & Improvement Opportunities

Research date: **20 November 2026**. Scope: source review and recommendations only.

## 1. Executive summary

**Keep YomiScan's architecture and OPUS-MT default. Take Yomu's observability, explicit model capabilities, settings-aware page recall, and carefully constrained page-output contract. Benchmark its detector policy and OCR export before adopting either.**

Yomu is a useful reference for turning local inference into a usable reading product. Its strongest transferable work is around reproducibility, cancellation, setup, model provenance, and handling a page as identifiable translation units. It does **not** establish that its translations are more accurate than YomiScan's. Several sophisticated context and prompting ideas failed its own experiments.

Five findings change the comparison materially:

1. **The current detectors share an upstream repository and pinned revision.** Yomu now downloads the int8 ONNX artifact from ogkalu/comic-text-and-bubble-detector; YomiScan loads its Transformers RT-DETR-v2 checkpoint. Yomu's “v4-s” is an artifact name, not proof of a newer detector architecture. Runtime/export, thresholds and postprocessing are the actual differences. [YomiScan detector][S-detector]; [Yomu detector decision][Y-detector-adr].
2. **Known omitted dialogue is not uniformly a detection problem.** YomiScan's three-page rendering audit improved 8/20 to 12/20 rendered detected blocks. All nine ordinary dialogue bubbles on page one were already detected, OCR'd and translated; renderer changes made them render. Two large SFX on page three were genuinely undetected. Preserved artwork text and undetected text need different remedies. [Coverage audit][S-coverage-doc].
3. **Grammar protects structure, not meaning.** Yomu's literal ID grammar prevents extra structural rows in a completed generation, but an ID's text can still contain the wrong speaker's dialogue, hallucination or mistranslation. A mandatory final newline even caused hallucination until it was made optional. [Bridge][Y-bridge]; [ADR-0013][Y-grammar-adr].
4. **Yomu does not implement persistent page-result caching.** Its current page recall is a 30-entry session LRU. Room persists text history; an old translation-cache table is explicitly unused. Persistent stage caching is a proposed YomiScan improvement, not a feature to copy. [Recall][Y-recall]; [Database][Y-db]; [ADR-0002][Y-context-adr].
5. **YomiScan is already stronger in study analysis and conservative image editing.** It has morphology, readings, JMdict, a draggable/resizable popup, glyph masks, inpainting, transactional rendering and detailed skip provenance. Yomu mostly covers text with fitted white rectangles and offers Japanese/translation inspection. Replacing YomiScan's renderer or backend would lose useful work. [Study popup][S-popup]; [Analysis][S-analysis]; [Renderer][S-renderer]; [Android renderer][Y-overlay].

Recommended order: **page reports and inexpensive CI → controlled detection experiment → cache identity and stage reuse → optional grammar/page-context experiments → measured OCR optimization and scoped terminology → restrained setup/UI improvements → multilingual and learning extensions.** No automatic model replacement, cloud dependency, runtime migration or rewrite is justified.

## 2. Repositories/commits inspected

| Repository | Commit inspected | Access and verification |
|---|---|---|
| GabrielTeixeira88/yomiscan | **6b4bc8c8f9a0612eaf1213a30b81387cbb0df583** | Local working tree inspected first; initially clean. GitHub commit/file reads confirmed the remote snapshot. Commit: 4 October 2026, translation benchmark infrastructure. |
| artsaraiva/yomu | **ace87fef9cdfa3c7a79d3a6b57db02bbbc1b5ce5** | Read second, through the connected GitHub read API: recursive tree, source, tests, ADRs, research, workflows and relevant history. Commit: 14 November 2026, ONNX telemetry-provider removal. |

All repository links below are pinned to these SHAs unless explicitly linking historical commits, issue evidence or upstream documentation. Source labels include exact paths; line anchors identify relevant implementations. Both repositories' READMEs were read, but source and current wiring take precedence over historical documentation.

**Evidence levels:** “implemented” means verified in source and reachable wiring; “documented measurement” means a repository author's recorded run, not reproduced here; “inference” means a conclusion from code; “proposed” means future work. Comparisons marked stronger concern the named capability, not an unmeasured universal quality ranking.

Inspection covered YomiScan's README, AGENTS.md, all phase/benchmark/license reports, pyproject/lockfiles, backend modules and tests, extension modules/tests/fixtures, and recent commits. Yomu coverage included its core/pipeline/ml/app boundaries, model manager/catalog/settings, overlay/capture/history/recall/reports, tests, all relevant decision reversals, model research and CI/release definitions.

**Validation performed for this review:** 190 backend tests passed, with one existing Starlette/httpx deprecation warning; 38 extension tests passed; strict TypeScript checking and package/API/detector/renderer/translation import checks passed. The Python run used existing dependencies with uv --frozen --no-sync and offline dependency resolution. Windows denied the normal pytest temporary directory; rerunning with a fresh ignored workspace temporary directory passed. These tests construct no neural engines and establish no inference accuracy.

**Not performed:** model installation/download, training, inference, Android builds/emulation, live chapter validation or new accuracy/performance measurements. Yomu's APK, native binaries and model tensors were not independently inspected. Its pinned OCR export's Hugging Face card/API could not be fetched through the available web reader; its provenance/license declaration is therefore partly repository evidence. The upstream 2025 OCR card was accessible but largely an unfilled template. Some other pinned HF blob URLs were inaccessible; accessible current upstream cards are identified separately and cannot replace an exact-artifact redistribution audit.

The sole intended tracked-workspace addition is this report. No code, dependencies, lockfiles, branch, commits, push, repository settings or licenses were changed.

## 3. Current YomiScan architecture and capabilities

### 3.1 Production flow and boundaries

Study flow: Chrome selection → screenshot crop → fixed localhost API → reused manga-ocr → independent sentence translation → fugashi/UniDic morphology → read-only indexed JMdict → one study popup.

Chapter flow: DOM image discovery → serial viewport-prioritized queue → source acquisition/fallbacks → one-page API → detection/grouping/OCR/batched analysis → conservative rendering → reversible aligned PNG overlays.

The backend is intentionally single-page. The extension owns chapter scheduling and browser lifecycle. ImageAnalysisService composes engines; FastAPI owns transport, limits and one inference worker. Shared OCR, tokenizer, dictionary and translator instances serve both modes. Detection and rendering initialize lazily for page work. [Composition][S-service]; [FastAPI][S-api]; [Page orchestration][S-page]; [Chapter session][S-session].

### 3.2 Implemented inventory

| Area | Verified implementation and important detail | Evidence |
|---|---|---|
| Region selection/capture | On-demand MV3 injection; drag rectangle; Escape/scroll/resize/visibility invalidation; active-tab/nonce rechecks; crop after repaint; screenshot-to-CSS ratios account for zoom/DPR. Only selected crop goes to Python. | content.start; background.capture; screenshotRect in [content][S-content], [background][S-background], [geometry][S-geometry] |
| Study popup | Closed Shadow DOM dialog; viewport clamping; keyboard dismissal/focus return; scrollable original, translation and token cards; expandable senses. Header drag and right/bottom/corner resize are already implemented. | StudyPopup.bindHandle in [popup.ts][S-popup]; constrainPopup/resizePopup in [geometry.ts][S-geometry] |
| OCR | MangaOCREngine wraps one reused upstream MangaOcr instance with contextual initialization/recognition errors and timing. No per-request reload. | [ocr/manga_ocr.py][S-ocr] |
| Morphology and word breakdown | FugashiTokenizer explicitly uses UniDic-lite; surface, hiragana reading, orthographic base, lemma, POS and conjugation. Translation remains separate from lexical candidates. | [nlp/fugashi.py][S-nlp]; TextAnalyzer in [analysis.py][S-analysis] |
| Local dictionary | Streaming JMdict import into indexed SQLite; atomic replacement; schema/provenance metadata; read-only parameterized lookup. Candidate order favors written base/lemma, then surface/base reading. English glosses and sense restrictions preserved. | [importer.py][S-importer]; SQLiteDictionary in [sqlite.py][S-dictionary] |
| Sentence translation | OPUS-MT by default; real padded batches of up to eight; deterministic generation; source length and real EOS validation; explicit device failures. Other adapters are optional. | MarianTranslationEngine in [marian.py][S-marian]; [factory.py][S-factory] |
| Page discovery | Large loaded images/currentSrc, dominant aligned column, exclusions for navigation/ads/icons; observes DOM and lazy image loads/source changes. Does not force a site's lazy loader to fetch everything. | GenericPageDiscovery in [discovery.ts][S-discovery]; ChapterTranslationSession.observe in [session.ts][S-session] |
| Image acquisition | Direct extension fetch with specific optional host permission → safe canvas → viewport screenshot → opt-in scroll stitching. Bounds MIME/bytes/pixels; records failed attempts; checks source/geometry; restores scroll. | PageImageAcquirer in [acquisition.ts][S-acquisition]; [source-fetch.ts][S-source]; [stitching.ts][S-stitch] |
| Queue, cancellation, retry | ChapterQueue serializes, prioritizes visible/nearby images, isolates failed/skipped pages, explicit Retry, Stop/Clear, source revision invalidation and stale-job disposal. Acquisition aborts; submitted synchronous inference can finish. | [model.ts][S-queue]; [session.ts][S-session]; [offscreen.ts][S-offscreen] |
| Original/English overlays | Fixed pointer-transparent closed-shadow image overlays follow source bounds/object-fit/clipping without rewriting site images. Cached Blob URLs make toggles immediate; clear/navigation revoke resources. Nearby overlays alone retain decoded sources. | ChapterOverlays in [overlay.ts][S-overlay]; [session.ts][S-session] |
| Detection/layout | Pinned comic RT-DETR-v2; keeps text_bubble/text_free; clips/filters geometry, groups qualifying line outputs and contained duplicate blocks; initial right-to-left reading bands. | [rtdetr.py][S-detector]; [page_layout.py][S-layout] |
| Page OCR/analysis | Four-pixel padded block crops, sequential OCR reuse, Japanese-script filtering, one batched TextAnalyzer.analyze_many call; known per-block failures preserve successful neighbors. | PageConfig/PageAnalysisService in [page.py][S-page]; [analysis.py][S-analysis] |
| Mask/inpaint/typeset | Separate glyph masks and layout interiors; safe flat fill/Telea; measured wrapping/hyphen breaks; bundled font; fit before erase; local transaction commits only successful mask/text pixels. | [renderer.py][S-renderer]; [masks.py][S-masks]; [layout_regions.py][S-layout-region]; [inpainting.py][S-inpaint]; [typesetting.py][S-typeset] |
| Coverage/diagnostics | Raw detection→filter/group→block lineage, heuristic categories, per-block stage/skip reasons, mask/layout/font status, debug stage images/JSON, aggregate API coverage header and chapter summaries. | [coverage.py][S-coverage]; [rendering/service.py][S-render-service]; [rendering/cli.py][S-render-cli]; [chapter/coverage.ts][S-front-coverage] |

### 3.3 Partial features, limitations and absent capabilities

| Classification | Actual status |
|---|---|
| **PARTIALLY IMPLEMENTED — context/glossary** | TranslationContext and contextual experimental adapters exist. Production TextAnalyzer.analyze_many calls translate_many without page/neighbor context. Glossary hints are benchmark/adapter infrastructure, not user-managed or per-series glossary. [Contracts][S-translation-base]; [analysis][S-analysis]; [LLM adapters][S-manga] |
| **PARTIALLY IMPLEMENTED — VNTL** | Prompt/parser and mocked tests exist; no configured usable artifact or real inference evidence at the inspected published revision. This is not a working quality mode. [Adapter][S-manga]; [benchmark report][S-benchmark-doc] |
| **PARTIALLY IMPLEMENTED — deferred viewport retry** | Queue supports WaitForViewport and bounded retries. However, PageImageAcquirer catches strategy failures and throws AcquisitionError, which extends SkipPage; the original WaitForViewport type is lost. ChapterTranslationSession rethrows that wrapper, while ChapterQueue sets deferred only for WaitForViewport. Thus the normal exhausted acquisition chain appears unable to activate that automatic mechanism. This is a **static integration finding, not a reproduced browser failure**. Explicit Retry works. [Acquisition][S-acquisition]; [queue][S-queue]; [session][S-session] |
| **PARTIALLY IMPLEMENTED — semantic categories** | bubble/narration/artwork_text/SFX are practical geometry/label/lexicon hints. They are not a trained semantic or speaker classifier. Detector score is not OCR confidence. [Coverage][S-coverage]; [page][S-page] |
| **PARTIALLY IMPLEMENTED — broad reader support** | Image readers and some cross-origin/tall captures work. Canvas/WebGL/background images, frames/shadow readers, transformed layouts, nested scrollers, pinch zoom and unstable/occluded geometry remain limited. [Discovery][S-discovery]; [acquisition validation][S-acquisition-doc] |
| **Known limit — cache** | In-memory results keyed by element/source/dimensions/load revision; no authoritative content hash, restart persistence or LRU eviction. At 128 MiB compressed output, new pages are skipped until Clear. [Session][S-session] |
| **Known limit — Japanese understanding** | Exact-form dictionary candidates; no phrase reconstruction, word-sense disambiguation or automatic grammatical explanations. Compounds may split and unrelated senses remain. [Analysis][S-analysis]; [Phase 2 validation][S-nlp-doc] |
| **Known limit — image processing** | Fixed 640px detector input may lose small text; reading order is not panel understanding; conservative masks intentionally preserve artwork and overflow. Unknown misses are not measurable from detected-block counts alone. [Detector decision][S-detector-doc]; [coverage audit][S-coverage-doc] |
| **MISSING — learning storage** | No vocabulary list, SRS, saved study history, JLPT grading or OCR editing. Existing rich word analysis is already a learning feature; these absences do not make Study Mode incomplete. [AGENTS][S-agents]; [popup][S-popup] |
| **MISSING — product setup** | Manual dictionary import/backend startup/unpacked extension installation. Model selection uses environment/CLI configuration; no integrated model/download UI or resource panel. [README][S-readme]; [factory][S-factory] |
| **MISSING — hosted CI/release automation** | No tracked .github workflows at inspected commit. Existing test and benchmark tooling is substantial, but not automatically run by repository CI. [Repository tree][S-tree]; [dependency configuration][S-pyproject] |

### 3.4 Existing abstractions worth preserving

OCREngine/OCRResult, TextDetector/TextRegion/BoundingBox, JapaneseTokenizer, DictionaryLookup, TranslationEngine/TranslationResult, optional ContextualTranslationEngine/TranslationContext, PageRenderer/InpaintingEngine, PageAnalysisResult and the optional analysis argument to translate_and_render_page already provide appropriate seams. PageDiscoveryStrategy, PageImageAcquirer, ChapterQueue and the transport/overlay split serve the browser side. These are enough to add experiments incrementally; a plugin framework, dependency-injection container or backend rewrite is unnecessary. [OCR contract][S-ocr-base]; [translation contract][S-translation-base]; [composition][S-service]; [render service][S-render-service]; [discovery][S-discovery].

Architectural constraints remain: offline inference after explicit setup; Python >=3.13,<3.14; uv/locked dependencies; Windows paths/processes; one owning worker for SQLite and models; CPU baseline; bounded uploads (10 MiB/12 MP); optional image-host access separated from fixed loopback inference; no copyrighted/model/dictionary/cache artifacts in Git. [AGENTS][S-agents]; [pyproject][S-pyproject]; [API][S-api]; [image validation][S-images].

### 3.5 Engineering, lifecycle and localhost security

FastAPI's create_app initializes, uses and closes the service through a single ThreadPoolExecutor worker, preserving SQLite ownership. Health stays responsive; initialization failure becomes unavailable status with full server logs. A busy guard rejects overlapping analysis with 429, and asyncio.shield retains ownership until inference actually finishes after a client disconnect. HTTP boundaries return safe errors; third-party adapters preserve exception causes, while known block failures are isolated. These targeted boundary catches are different from silently suppressing programming errors. [API lifecycle][S-api]; [service lifecycle][S-service]; [block orchestration][S-page].

The local guard validates Host against loopback names, browser Origin against configured extension origins (or any syntactically valid Chrome extension ID by default), and POST requests against a fixed nonsecret client header. CORS is not wildcard. Streamed body limits apply before multipart parsing; decoding rejects unsupported/animated/oversized images and normalizes EXIF. **This is not authentication against other local processes or every installed extension.** Keep loopback binding and the optional explicit extension-origin allowlist; a new model/cache/report endpoint must preserve the same boundary. [LocalRequestGuard][S-security]; [upload decoding][S-images]; [middleware][S-api].

MV3 requests go to fixed localhost endpoints with bounded transports; chapter requests use an extension-origin offscreen document to survive service-worker request-lifetime limits. Remote image fetch is separate: specific optional host access, active-image tickets rather than arbitrary URLs, credentials governed by Chrome, redirects rejected, and current source rechecked. No backend internet-image proxy or page-script bridge exists. A report feature must not expose the source-fetch ticket or console URL diagnostics as public API data. [Offscreen][S-offscreen]; [source fetch][S-source]; [acquisition][S-acquisition].

Dependencies are deliberately conventional: manga-ocr/PyTorch/Transformers, Pillow/OpenCV/NumPy, fugashi/UniDic-lite, SQLite, FastAPI/Pydantic/Uvicorn; TypeScript/esbuild and Chrome APIs without a frontend runtime framework. uv.lock and package-lock.json pin resolved dependencies, while pyproject keeps Python 3.13. There is no launcher, packaged model supervisor, arbitrary plugin registry or integrated model installer to preserve. Those are opportunities only when reader setup warrants the cost. [Python dependencies][S-pyproject]; [extension package][S-front-package].

### 3.6 Existing validation and benchmark infrastructure

The current test suite separates model-free unit tests from explicitly requested inference. Backend tests inject fake engines, use small hand-authored dictionary data and exercise real lightweight tokenization/render geometry. Extension Node tests mock browser/network boundaries; an opt-in isolated Chrome script covers capture, lazy pages, retry, toggles, restoration and cleanup. The 24-page queue stress test is mocked. [Backend tests][S-tests]; [extension tests/fixture][S-front-tests].

The repository also contains the 46-case/53-line synthetic dialogue JSONL corpus; repeatable engine/context/glossary benchmark runs; load/cold/warm/batch/resource metadata; adjacent human ratings CSVs; a rating summarizer; and committed output JSON. The reports include explicit failed candidates and real-image limitations. These are valuable experiment seams, although independent human quality ratings remain pending. [Benchmark runner/contracts][S-benchmark]; [benchmark report][S-benchmark-doc].

Historical browser validation reports 20/20 and 38/38 acquired/rendered pages across two supplied readers, all direct fetch; one 38-page CPU loop took about 201 seconds excluding setup/preloading. These are successful page transport/render responses, **not 58 fully translated pages or an OCR accuracy score**; preserved regions were reported on 8 and 34 pages respectively. The three-page renderer audit is narrower still. Neither observation was rerun for this review. [Acquisition record][S-acquisition-doc]; [coverage record][S-coverage-doc].

## 4. Yomu architecture and capabilities

Yomu is an Android 8+ screen-capture translator: Compose UI and foreground overlay service in app; platform-independent-ish data/contracts in core; detection→OCR→context→translation→typesetting in pipeline; ONNX and llama.cpp JNI in ml. Hilt wires dependencies; Room holds models/history/session data; SharedPreferences stores model, language, generation, glossary and recall settings. Android capture/overlay behavior cannot be directly compared with web image acquisition. [Structure][Y-readme]; [pipeline][Y-pipeline]; [service][Y-service].

The current pipeline:

1. Capture a fresh screen frame through MediaProjection; exclude known app overlay/status regions from processing.
2. Detect text using the pinned int8 RT-DETR export; keep two text classes and suppress duplicates.
3. Crop and read each box using the 2025 manga-ocr ONNX encoder/merged decoder with past-key-value reuse; preserve uncertain/non-Japanese reads in reports.
4. Infer straight white-gutter panels and bubble order; assemble one page with stable IDs and panel separators.
5. Use a selected GGUF: grammar-constrained page call when supported, otherwise independent model-specific singleton calls. Stream completed translations; use typed prompt-overflow fallback.
6. Infer white bubble interiors and fit translated text; draw white rounded rectangle overlays. Finished bubbles can open copyable Japanese/translation cards.
7. Recall successful results from a settings-aware 30-page session LRU; save text history; optionally export the last page as a ZIP.

[Capture][Y-capture]; [detector][Y-detector]; [OCR][Y-ocr]; [context][Y-context]; [bridge][Y-bridge]; [typesetter][Y-typeset]; [overlay][Y-overlay]; [recall][Y-recall]; [report][Y-report].

The default is **Qwen2.5 1.5B Instruct Q4_K_M**, not YomiScan's Qwen2.5 7B manga LoRA experiment. CAT-Translate 0.8B remains singleton/English only; CAT 1.4B supports page IDs/English. The catalog also contains experimental Qwen3.5, Qwen3, Ministral, Gemma 4, Hy-MT2, ternary and abliterated variants. Catalog membership/capability flags are not a translation accuracy ranking. [Catalog][Y-catalog]; [model-selection ADR][Y-default-adr]; [experimental-tier ADR][Y-experimental-adr].

The model manager has immutable URLs, SHA-256 checks, multi-file OCR downloads, free-space checks, progress/cancel/delete, selected-versus-pending state and invalidation when a registry pin changes. The fit formula uses file size + 800 MiB shared overhead + per-token KV estimate against a configurable share of total memory; the default is exempt. This is a coarse phone fit estimate, not a measured desktop RAM/VRAM guarantee. [Manager][Y-manager]; [slot selection][Y-slots]; [catalog fit][Y-catalog-fit].

Important reproducibility pins include Bartowski Qwen2.5-1.5B Q4_K_M at 9eadc66189c7641e1ddd226b8267a9119b2ce2d4 (986,048,768 bytes), CAT 0.8B Q4_K_M at 834d0624185e964856a1b3c43eb5e114c9c41df5 and CAT 1.4B Q4_K_M at 2eb35647e57b5981c14611e67b9ad205329b498d. The registry supplies exact hashes for those and every experimental deliverable; full file descriptors should be reused as evidence, not inferred from family names. Android ONNX Runtime is pinned to 1.26.0, and llama.cpp is a submodule at 7fe450e19305b828c199d602c23a8337aaa1f03b. [Registry][Y-manager]; [Android inference dependencies][Y-ml-build]; [submodule pin][Y-llama-pin].

The inspected head also removes ONNX Runtime's Android telemetry initializer in preparation for a later runtime bump; its commit records unchanged detector/OCR fixture outputs. This is evidence that runtime upgrades can change privacy behavior independently of model weights, not a reason to port the Android manifest rule into Python. Any future ONNX adapter should verify its actual installed build/provider behavior and retain the offline-first contract. [Head commit][Y-head]; [manifest][Y-manifest].

Yomu supports EN, pt-BR, ES, FR and DE at the prompt/UI level, with English-only model restrictions. It has no Japanese morphology/JMdict/SRS equivalent. Its broad target support is implemented, but target-specific accuracy is not established by the README. [TargetLanguage][Y-languages]; [language/model compatibility][Y-slots]; [target-language research][Y-register-research].

## 5. Feature-by-feature comparison table

Classifications apply to each row's specific capability. “Stronger” denotes verified functionality, not a claim that an untested model is more accurate.

| Area | YomiScan implementation | Yomu implementation | Actual difference | Recommendation |
|---|---|---|---|---|
| Local/private inference | PyTorch/Transformers and optional loopback llama-server. [S][S-service] | ONNX/llama.cpp on Android. [Y][Y-pipeline] | **ALREADY IMPLEMENTED** — both local after model setup. | Preserve offline design. |
| Screenshot/region study | User crop, invalidation, fixed localhost upload. [S][S-content] | Full-screen manual capture. [Y][Y-capture] | **DIFFERENT APPROACH** — selected study region versus whole screen. | Keep both YomiScan modes. |
| Study analysis | Readings, morphology, dictionary senses and separate sentence translation. [S][S-analysis] | Original/translation inspection and copy. [Y][Y-card] | **YOMISCAN STRONGER** for Japanese learning. | Reuse existing analysis; no replacement. |
| Popup positioning | Draggable/resizable, clamped, focus/Escape. [S][S-popup] | Screen-half-positioned bubble card. [Y][Y-card] | **ALREADY IMPLEMENTED** — movement/resize already covered better for browser study. | Add explicit Copy only if useful. |
| Chapter discovery/lazy images | DOM strategy, observers and viewport-priority queue. [S][S-discovery] [S][S-queue] | One captured page per tap. [Y][Y-service] | **YOMISCAN STRONGER** for supported web chapters. | Keep orchestration. |
| Cross-origin/source pixels | Authorized source fetch plus three capture fallbacks. [S][S-acquisition] | Screen pixels from any Android app. [Y][Y-capture] | **NOT APPLICABLE** to direct platform parity. | Do not replace with screenshot-only capture. |
| Overlay geometry/toggle | Follows page images; Original/English; clipping and cleanup. [S][S-overlay] | One screen overlay; tap/drag dismissal. [Y][Y-overlay] | **DIFFERENT APPROACH** — scroll-following web geometry versus screen snapshot. | Preserve pointer-transparent web behavior. |
| Cancellation | Stop scheduling/acquisition; submitted inference finishes. [S][S-session] [S][S-api] | Coroutine cancel plus native token-decode abort. [Y][Y-bridge] | **PARTIALLY IMPLEMENTED** — client cancellation is already present; compute interruption differs. | Consider cooperative abort only for owned LLM runtime later. |
| Retry/refresh | Explicit failed/skipped retry; successful results retained. [S][S-queue] | Translate again can bypass recall; failed refresh retains the old cache entry for later recall, not necessarily the visible overlay. [Y][Y-service] [Y][Y-recall] | **YOMU STRONGER** in explicit successful-page refresh. | Adapt page-level retranslate and stage selection. |
| Detector family | Pinned RT-DETR-v2 FP32 Transformers, .5 text threshold. [S][S-detector] | Same upstream pin, int8 ONNX, .25 bubble/.5 free floor. [Y][Y-detector-adr] | **DIFFERENT APPROACH** — export/policy, no demonstrated winner over YomiScan. | Controlled experiment. |
| Duplicate/merged boxes | Same-class contained duplicate grouping, conservative line joins. [S][S-layout] | IoU/containment NMS with recovery of some suppressed merged boxes. [Y][Y-detector] | **DIFFERENT APPROACH** — neither universally safer. | Measure crop completeness and merges separately. |
| OCR | Original manga-ocr via upstream generation. [S][S-ocr] | 2025 weights, ONNX KV decoder, token confidence. [Y][Y-ocr] [Y][Y-past] | **DIFFERENT APPROACH** — model/runtime/preprocess all differ. | Factorial accuracy/speed experiment. |
| OCR uncertainty | No populated OCR confidence; detector confidence retained separately. [S][S-page] [S][S-ocr-base] | Sequence confidence and unsure flag with preservation gate. [Y][Y-ocr] | **MISSING FROM YOMISCAN** — sequence-confidence metadata and an uncertainty policy. | Add metadata first; calibrate before automatic rejection. |
| Japanese filtering | Any Japanese script can pass. [S][S-page] | Also drops Latin-majority text to exclude screen toolbar. [Y][Y-detector-adr] | **DIFFERENT APPROACH** — screen contamination versus source-image input. | Do not globally copy Latin-majority rejection. |
| Reading order/panels | Anchored vertical bands, RTL. [S][S-layout] | White-pixel gutter partition and rows, actual ID membership. [Y][Y-context] [Y][Y-paper] | **YOMU STRONGER** in implemented panel heuristic; quality unmeasured against ours. | Optional strategy benchmark. |
| Translation batching | Genuine bounded NMT batches; LLM singleton loops. [S][S-marian] [S][S-manga] | One grammar-constrained page sequence or model-specific singletons. [Y][Y-bridge] | **DIFFERENT APPROACH** — tensor batch is not dialogue context. | Keep NMT batching; optional page capability. |
| Grammar/ID contract | Count/newline checks for experimental LLMs, no grammar. [S][S-manga] | Literal expected IDs/order plus parser and EOG handling. [Y][Y-bridge] | **MISSING FROM YOMISCAN** for experimental page LLMs. | Adapt independent server-side grammar. |
| Page context | Context object/adapters, not wired into normal pages. [S][S-translation-base] [S][S-analysis] | All page bubbles, panel separators, no current cross-page memory. [Y][Y-context] [Y][Y-grammar-adr] | **PARTIALLY IMPLEMENTED** in YomiScan. | Benchmark with contamination-specific review. |
| Default translation quality | OPUS retained after no reliable quality winner. [S][S-benchmark-doc] | Qwen selected through historical phone/emulator comparisons; current quality harness removed. [Y][Y-default-adr] [Y][Y-quality-adr] | **DIFFERENT APPROACH** — no common semantic evaluation. | Retain OPUS; test contenders, not popularity. |
| Glossary | Optional prompt-hint infrastructure. [S][S-manga] | Global editable exact source-name replacement and enable switch. [Y][Y-glossary] [Y][Y-glossary-store] | **PARTIALLY IMPLEMENTED** — management and scoped terminology missing. | Adapt per-series/per-target with immutable OCR. |
| Masking/art preservation | Tight masks, flat-fill/Telea, safety gates, rollback. [S][S-renderer] | Rounded white overlay rectangles. [Y][Y-overlay] | **YOMISCAN STRONGER** in implemented localized editing controls. | Keep renderer. |
| Interior/font fitting | Enclosure inference; measured balanced fit; preserve overflow. [S][S-layout-region] [S][S-typeset] | White enclosure inference; scale, grown boxes, possible ellipsis. [Y][Y-render-box] [Y][Y-typeset] | **DIFFERENT APPROACH** with more aggressive Yomu coverage tradeoff. | Bounded font setting only; reject unsafe growth. |
| Session recall | DOM/source identity, cached PNG URLs, 128 MiB stop. [S][S-session] | 30-entry LRU with fingerprint and complete settings. [Y][Y-recall] [Y][Y-fingerprint] | **YOMU STRONGER** in settings-aware recapture reuse/eviction. | Adapt exact web content keys and byte LRU. |
| Persistent page cache | None. [S][S-session] | None; legacy table unused. [Y][Y-db] | **MISSING FROM YOMISCAN**, also absent from Yomu. | Proposed stage cache; no parity claim. |
| Persistent text history | None. [S][S-popup] | Room sessions and history UI. [Y][Y-history] [Y][Y-home] | **MISSING FROM YOMISCAN**. | Optional later; privacy/learning value first. |
| Diagnostic artifacts | Detailed CLI stage images/metadata, console acquisition/coverage. [S][S-render-cli] [S][S-session] | Shareable capture+JSON+raw reply ZIP. [Y][Y-report] [Y][Y-report-share] | **YOMU STRONGER** in reader repro export; YomiScan richer mask skip detail. | Combine strengths, explicit inclusion controls. |
| Live progress | Chapter/page totals; one finished PNG per page. [S][S-controls] | Stage updates, OCR preview and streamed translated bubbles. [Y][Y-pipeline] [Y][Y-overlay] | **YOMU STRONGER** in within-page feedback. | Stage status first; streaming much later. |
| Model onboarding/resources | Manual import/cache/env selection and benchmark metrics. [S][S-readme] [S][S-factory] | Download UI, pins/hashes/licenses/capabilities/fit/resource panel. [Y][Y-manager] [Y][Y-catalog] | **YOMU STRONGER** in user-facing setup. | Small curated manager, not catalog expansion. |
| Target languages | Implemented adapters hardcode English; English JMdict import. [S][S-nmt] [S][S-importer] | Prompt targets and model compatibility EN/PT-BR/ES/FR/DE. [Y][Y-languages] [Y][Y-slots] | **MISSING FROM YOMISCAN**; accuracy separately unproven. | PT-BR/ES evaluation before release UI. |
| Tests/CI | Extensive model-free tests, real-image reports, ratings tooling; no workflows. [S][S-tree] [S][S-benchmark] | Unit/native tests, CI, report-only speed runs, signed APK releases. [Y][Y-ci] [Y][Y-release] | **YOMU STRONGER** in automation; **YOMISCAN STRONGER** in retained structured human-rating tooling. | Add lightweight CI; retain quality review. |
| Platform architecture | Python/FastAPI/MV3, one worker. [S][S-api] | Kotlin/Compose/Hilt/Room/JNI foreground service. [Y][Y-pipeline] | **NOT APPLICABLE** as a migration target. | Independently implement ideas in current stack. |

## 6. Detection and OCR findings

### 6.1 What the detector evidence actually establishes

YomiScan uses RTDetrV2ForObjectDetection/RTDetrImageProcessorPil at revision 16e8a622f91fabc6b5b65c96d32d1183f8843546, default threshold .5, keeping classes 1/2 and official original-coordinate postprocessing. It does not add adapter-level NMS. Its model decision favored compatibility and block/free-text support, not a comparative full-page accuracy win. [Implementation][S-detector]; [decision][S-detector-doc].

Yomu's current artifact is detector-v4-s_int8.onnx, **11,120,765 bytes**, from that same upstream revision. ADR-0020 calls it an int8 RT-DETR-v2 with ResNet-50-vd. Its parser stretches RGB/255 to 640×640 without mean/std; exported orig_target_sizes receives [width,height]. This order is export-specific and must not be substituted into Transformers postprocessing by analogy. Keep class 1 at the user threshold (.25 default), class 2 at at least .5; drop class 0. NMS uses IoU .80 and containment .90, then a recovery pass can retain a containing detection to recover otherwise uncovered text. [ONNX implementation][Y-onnx]; [NMS][Y-detector]; [ADR][Y-detector-adr].

The author's OpenMantra experiment compared **Yomu's old YOLO26n** with this export:

| Author-reported arm | Annotated boxes hit / 1,592 | Merging predictions | Extra predictions |
|---|---:|---:|---:|
| Old YOLO, .25 | 1,538 | 106 | 25 |
| RT-DETR, both text classes .25 | 1,590 | 1 | 71 |
| RT-DETR, deployed .25 bubble/.5 free | 1,589 | 1 | 21 |

Source: [#437 results][Y-detector-results], 214 Japanese pages; **not reproduced here**. The hit criterion is at least half containment in either direction, not strict 95% crop containment or a clean one-to-one OCR crop guarantee. Extras include SFX, signs and unannotated dialogue, so “21 false positives” would be inaccurate. Historical ADR-0003 used a different crop-completeness criterion; its numbers must not be combined with this table. Emulator/desktop speed measurements are not Windows/phone promises. No row tests YomiScan's FP32 implementation.

Yomu's old Manga-Bubble-YOLO/Ultralytics model and YOLO letterboxing were removed by ADR-0020. Recommending them as Yomu's present detector would be stale. Both retain text outside bubbles; neither currently uses balloon-outline class 0 to supply a semantic speaker/bubble model. [Current ADR][Y-detector-adr].

### 6.2 Controlled detector benchmark proposed for YomiScan

Use private, owned or authorized pages; keep the corpus out of Git. Include demonstrated real misses, ordinary white/dark bubbles, tiny asides, narration, artwork text, mixed orientations, furigana, low contrast, stylized SFX, dense panels, spreads and blank pages. Separate threshold-tuning and held-out evaluation pages. Annotate tight text regions, dialogue-unit membership, expected order, transcription and intended preservation category.

Compare:

| Arm | Change from baseline | Question answered |
|---|---|---|
| A | Current PyTorch/.5 both | Reproducible baseline |
| B | Same PyTorch, .25 bubble/.5 free | Is gain due to class policy alone? |
| C | Pinned int8 ONNX, B policy | Does export/runtime preserve or improve yield and latency? |
| D | B/C with independently implemented optional duplicate policy | Does suppression reduce duplicates without losing complete neighboring text? |

Hold preprocessing convention, pages, decoded resolution, downstream OCR/translation/rendering and device constant wherever the runtime permits. Record any unavoidable difference explicitly. Feed common canonical regions into later stages as a second isolation test.

Measure localization recall; **95% text-box containment with one-to-one, no-neighbor-merge matching**; manual false-positive categories; merges/splits/duplicates; crop truncation; Japanese OCR yield and CER; successfully translated blocks; renderer success/preservation reasons; inspected artwork damage. Report cold load separately from repeated warm median/p95, process RAM and artifact size. Count missing regions using ground truth; never infer zero misses from the renderer's null estimate.

The old 95% idea is useful as a proposed crop-safety metric even though Yomu retired its gate. Pair it with localization and visual review to distinguish “found text but clipped crop” from “not found.” Do not copy its documented 4%-page padding: **current Yomu crops raw boxes and only clamps**; that old ADR prescription is not verified current behavior. YomiScan already has configurable four-pixel crop padding. [Historical criterion][Y-hit-adr]; [current crop][Y-pipeline]; [YomiScan crop][S-page].

**Decision gate, proposed:** adopt a policy only if held-out complete dialogue/OCR/render yield improves without critical merges or artwork regressions; adopt ONNX only if accuracy remains acceptable and the measured Windows CPU/resource advantage justifies another runtime. No automatic threshold change is recommended.

### 6.3 OCR implementation and experiment

YomiScan locks manga-ocr 0.1.16, whose inspected installed source defaults to kha-white/manga-ocr-base, grayscale→RGB, upstream processor/generation and normalization. MangaOCREngine does not pin the pretrained revision or expose confidence. It returns text/engine/time, with an available metadata dictionary seam. [Lockfile][S-lock]; [adapter][S-ocr]; [upstream OCR][U-manga-ocr]; [contract][S-ocr-base].

Yomu uses a different **2025** model lineage, not just a faster wrapper around a proven identical baseline. It pins artsaraiva/manga-ocr-2025-onnx-past@151898756903f03a2682fa6be4507dfeff71fb7e: encoder 22,279,960 bytes, merged decoder 118,131,111 bytes, vocabulary 24,072 bytes. RGB crops resize to 224² and normalize with mean/std .5. Greedy decoding starts at hardcoded CLS token ID 2, resolves SEP/end from the vocabulary (fallback 102), caps at 128 steps and reuses native past-key-value/cross-attention tensors. These token assumptions need verification for any different export. [Registry/files][Y-manager]; [OCR][Y-ocr]; [decoding][Y-ocr-decode]; [KV state][Y-past].

[#393][Y-ocr-speed] reports 2.1–2.7× emulator acceleration over **Yomu's prior whole-sequence ONNX loop**, with the same fixture readings/confidence. Transformers generation may already reuse decoder state; that speedup is not evidence of the same gain over YomiScan.

Yomu's mean chosen-token probability, including stop, sets unsure below .85. Its own comments describe calibration on 210 reads/18 pages and a half-garbled read scoring .93. Confidence can miss omitted ruby, plausible wrong words and model hallucinations. Do not interpret it as an 85% probability the transcription is correct or reuse the threshold across weights.

Proposed factorial comparison: original versus 2025 weights; original versus matched RGB preprocessing; PyTorch versus ONNX on identical crops; optional calibrated uncertainty policy. Use both ground-truth crops and production detector crops, blinded transcriptions, micro-CER/exact-match, character omissions, blank hallucinations, truncation, confidence-error calibration, warm latency and RAM. Keep confidence diagnostic-only until held-out evaluation shows that preservation improves reader outcomes without discarding good short dialogue. Record unavailable confidence as null.

## 7. Translation architecture and context findings

### 7.1 YomiScan's existing engines and evidence

| Engine | Implemented behavior | Status/resource and quality evidence |
|---|---|---|
| OPUS-MT | Pinned Marian; source-length checks; deterministic four beams; native batch eight; real EOS; independent sentences. | Working default. Small CPU baseline; known casual-dialogue, rank, pronoun and meaning errors. |
| Hy-MT2 manga | Pinned 1.8B manga v5 GGUF; reused owned llama-server; singleton loop; optional glossary hints, no dialogue-context capability. | Real CPU/CUDA benchmark; useful outputs and speed, still semantic mistakes. Not a proven quality winner. |
| Qwen2.5 manga | Pinned 7B base GGUF plus required manga LoRA; one current line with optional neighboring hints; newline/count validation. | Real CUDA/context tests showed invented dialogue, participant-direction mistakes and contamination. Different artifact from Yomu's 1.5B instruct. |
| FuguMT | Pinned staka/fugumt-ja-en; lazy reuse/close; native batches; greedy default after four-beam termination failures; no context/glossary. | Real CPU speed candidate; prohibitions/double negatives/meaning failures remain; CC-BY-SA weights. |
| NLLB-600M | Pinned seq2seq; explicit Japanese/English IDs; native batches, four beams; lazy lifecycle; no context/glossary. | Slower CPU and no established semantic advantage; noncommercial weights. Underlying multilingual model does not make current adapter multilingual. |
| Qwen3.5 VNTL | Prompt/parser/context slicing and mock validation; explicit unavailable state without configured artifact. | No real inference or quality/resource evidence at inspected published pin. Do not list as usable model. |

[Contracts][S-translation-base]; [Marian][S-marian]; [LLM adapters/lifecycle][S-manga]; [NMT adapters][S-nmt]; [factory][S-factory]; [benchmark/model pins][S-benchmark-doc].

For reproducibility, the inspected translation artifacts are:

| YomiScan engine | Repository/artifact | Pinned revision |
|---|---|---|
| OPUS | Helsinki-NLP/opus-mt-ja-en | 0770961a39ba6bd66305b149c3f4110bcafca2e6 |
| Hy manga v5 | fumetodev/Hy-MT2-1.8B-JP-Manga-Finetune-v5-GGUF, manga-v5-Q4_K_M.gguf | e17bc6a8dd92ddf930bd7858ceb916117ee5f916 |
| Qwen manga LoRA | NaelShichida/qwen2.5-7b-manga-translator-full | 4267f42e98fcc2daa36096cea8524a926cbb84d1 |
| Qwen base GGUF | Qwen/Qwen2.5-7B-Instruct-GGUF, both Q4_K_M shards | bb5d59e06d9551d752d08b292a50eb208b07ab1f |
| Qwen base configuration | Qwen/Qwen2.5-7B-Instruct | a09a35458c702b33eeacc393d103063234e8bc28 |
| Fugu | staka/fugumt-ja-en | f7ce11286e1fb7a8e1f1692ff3ab68c0f9c3aecb |
| NLLB | facebook/nllb-200-distilled-600M | f8d333a098d19b4fd9a8b18f94170487ad3f821d |
| VNTL, unavailable at inspected pin | 0xBrandon/Qwen3.5-4B-VNTL-V1 | bf7b11333a9ef958ed4646dcc18dea9f757a6e08 |

Source: [artifact table/conversion details][S-benchmark-doc], [adapter constants][S-manga], [NMT registry][S-nmt]. Approximate downloads: OPUS 303 MB; Hy manga 1.13 GB; Qwen base 4.68 GB plus converted F16 LoRA around 80.7 MB; Fugu 121 MB; NLLB 2.46 GB, before tokenizer/runtime overhead. These are file sizes, not peak RAM/VRAM.

YomiScan's LlamaServer owns one hidden Windows subprocess bound to a random loopback port with a random API key, context 4096, parallel 1 and no web UI/context shift. It probes runtime CUDA availability, reuses the process, validates normal finish, disables prompt-cache reuse for its benchmark path and terminates/kills on close. Generation uses temperature 0/seed 0/repeat penalty 1.0; these differ from Yomu's default sampled .2/top-k40/top-p.9/random-seed page calls. OPUS constructs once at service startup; experimental NMT/GGUF engines load lazily when used; detector is page-lazy. Model lifetime, timing and sampling must be matched before comparing outputs/resources. [Owned runtime][S-manga]; [composition][S-service]; [NMT lifecycle][S-nmt]; [Yomu generation][Y-bridge].

The committed 46-case/53-line synthetic benchmark records the following **historical**, same-run CPU results:

| Engine/configuration | Warm repeated weighted ms/line | Eight-line batch ms |
|---|---:|---:|
| OPUS, four beams | 154 | 588 |
| Fugu, one beam | 68 | 196 |
| NLLB, four beams | 939 | 2,729 |
| Hy manga, singleton loop | 296 | 2,814 |

Source: [2026-10-03 NMT results][S-nmt-results] and [report][S-benchmark-doc], i7-14700K/32 GiB; **not this research run**. Different earlier CPU/CUDA tables must not be merged into a single model ranking. RSS snapshots are not peak private RAM or required capacity; GPU system load is not model VRAM. Fugu's failed four-beam diagnostic arm is not its final greedy result. “Batch” for Hy is sequential calls, unlike the NMT tensor batches.

Independent human ratings are pending. The reports' qualitative examples show semantic errors in every contender; no tested candidate earns a reliable quality-mode recommendation. Previous/page/glossary prompts could improve an isolated phrase while introducing unrelated surrounding dialogue elsewhere. Keep that evidence, including negative cases. [Detailed observations and context failures][S-benchmark-doc]; [ratings tool][S-benchmark].

### 7.2 What Yomu's page contract contributes

LlamaTranslationBridge routes by model capability. General instruct models receive a page of actual detector IDs, ordered Japanese and panel separators; CAT 0.8B/Hy stay singleton. A generated grammar fixes each literal ID exactly once and in order, with one nonempty bounded translation line; parser checks allowed IDs and keeps the first duplicate. The final newline is optional, so EOG can terminate a valid last line. Completed lines stream; an unterminated final buffer is accepted only on normal model termination. [Bridge][Y-bridge]; [UTF-8 splitter][Y-splitter].

Budgeting separates prompt tokens from output allowance, checks native batch/context capacity with a reserve, and emits a typed overflow. **Only prompt overflow** triggers singleton fallback. Partial answered/unanswered status and fallback provenance survive into results. Generation is serialized; cancellation raises the native abort flag and late callbacks check coroutine state. [Prompt budget][Y-budget]; [native decode][Y-native]; [pipeline translation][Y-translation].

There is an important terminal-status weakness: LlamaBridge.generate maps native timeout to Timeout only when returned text is blank. A nonblank timed-out prefix becomes Success with endedByModel=false; complete prefix lines survive, incomplete tails are omitted, and the final page can have outcome SUCCESS. The streaming test explicitly accepts that partial-success behavior. Thus partial successes are useful, but **the timeout cause can disappear and that partial page may be recalled**. YomiScan should preserve terminal reason independently of usable prefix results, with completeness explicit. [Native-result mapping][Y-native-result]; [partial-stream test][Y-stream-test].

Current implementation values are 768 page output tokens, 160 characters per answer, 15-second singleton/120-second batch deadlines, configurable context (default 2048) and native n_batch=2048. They are phone choices, not parameters to copy. Native KV memory clears before every generation: there is no hidden cross-page conversation.

Historical ADR-0013 measured median 3,228 ms singleton, 2,056 unconstrained page and 2,396 grammar page on 17 emulator pages/147 bubbles. Grammar recovered two malformed-ID pages. This supports a structural/latency hypothesis for that setup, **not translation accuracy or a predicted Windows percentage gain**. Its later amendment found mandatory final-newline grammar suppressed an EOG probability of .998 and forced low-probability continuation. Making it optional improved endings in a small desktop test (12/12 versus 5/12) and two emulator fixtures. Strong constraints can create errors as well as prevent them. [ADR-0013][Y-grammar-adr]; [fix commit][Y-eog-fix].

### 7.3 Integration proposed for YomiScan's llama.cpp adapters

Add a small optional page-capable contract beside TranslationEngine, accepting stable IDs, source texts, order/panel grouping and explicit target/context/glossary. Preserve existing scalar/native-batch callers. Independently construct a strict grammar or supported JSON schema and send it through **the existing local llama-server**; do not port Yomu's AGPL JNI code.

The pinned llama.cpp b11380 server documents grammar and schema-constrained output for completion/chat endpoints. Test the exact endpoint and compiled binary used by LlamaServer before relying on it; unsupported schema features can be silently skipped by the converter. Prefer a minimal literal-ID grammar when exact cardinality/order is required. Include the contract in the prompt as well as the sampler; grammar alone does not explain the task to a model. [Server documentation][U-llama-server]; [grammar documentation][U-llama-grammar]; [current server boundary][S-manga].

Validate exact ID set/count, source mapping, nonempty strings and normal termination; retain raw output; represent omissions/failures explicitly. Reject token-limit/timeout partial tails, unknown IDs and duplicates rather than assigning by list position. Use bounded singleton fallback for typed overflow/contract failure with visible provenance; do not silently switch engines or hide systemic failure behind repeated retries. Keep budgets token-based and independently validated; **do not copy Yomu's silent source .take(300)** or its answer cap as a semantic truncation strategy. YomiScan already rejects overlong input. [Yomu source clipping][Y-translation]; [YomiScan checks][S-marian].

Evaluate four separate outcomes: **structural correctness**, **semantic fidelity**, **naturalness/register**, and **context/reference consistency**. A completed grammar can forbid extra rows and preserve key alignment; it cannot stop a permitted line from inventing an explanation or translating another bubble's meaning. The default must remain unchanged until blinded Japanese/target-language review justifies promotion.

### 7.4 Panel/page context without recreating contamination

Yomu's ContextAssembler recursively partitions straight paper-white horizontal gutters into top-down tiers, then vertical gutters into RTL panels; within a panel it sorts overlapping rows RTL. It preserves actual membership and OCR mapping, fixing an earlier duplicate-membership bug. PaperMask uses luminance 200, requiring all tested gutter pixels to be white. Borderless, dark/colored, slanted or artwork-crossed gutters remain weak cases. Panels are prompt markers, not separate model calls or speaker recognition. [Assembler][Y-context]; [mask][Y-paper]; [membership fix][Y-panel-fix].

Test geometry **before** translation: frozen boxes/OCR, manual intended sequence, pairwise/order accuracy, exactly-once IDs, no accidental joins, fallback to current bands. Then compare plain singleton, singleton with a one-ID grammar, flat ordered page with grammar, and panel-separated page with grammar using the same model, seeds and transcripts. Only the one-bubble grammar arm isolates structural constraints from new neighboring dialogue; a multi-ID page prompt already supplies context. Score invented facts, cross-bubble leakage, omitted negation, subjects, pronoun/name consistency and naturalness separately. Keep a held-out contamination suite built from YomiScan's known failures. Better panel order cannot excuse worse semantics.

Do not restore bilingual previous-page memory by default. Yomu withdrew it after 4/17 pages exceeded its **then** 512-token batch budget, surviving pages slowed and no gain was observed; current budget is different, so this does not prove all cross-page context impossible. It does prove that the old design should not be copied as a success. Names/pronouns are currently inferred from page text and optional literal glossary; neither application implements reliable character recognition or narrative coreference. [Withdrawal][Y-grammar-adr]; [older context reversals][Y-context-adr].

Yomu also tested class/gender/register/continuation annotations: inline hints leaked in every run of one 72-run arm; removing content punctuation caused loops/wrong-language output; system hints did not visibly improve address/register consistently. Preserve useful morphology in Study Mode, but do not inject speculative labels into translation prompts as an assumed upgrade. [Target-language research][Y-register-research].

## 8. Rendering findings

YomiScan already implements the useful principle of **separate OCR/text bounds, safe layout bounds and actual erasure mask**. Enclosure inference and inscribed rectangles give English room without turning the whole region into a fill mask. It protects neighbors, rejects unseparated artwork, fits before editing, preserves unsupported characters/overflow and commits locally. Flat backgrounds use fill; otherwise mask-limited Telea. Light-edge artwork recovery is narrow and explicitly incomplete. [Masks][S-masks]; [layout][S-layout-region]; [renderer][S-renderer]; [inpainting][S-inpaint]; [quality audit][S-render-quality].

Yomu's BubbleRenderBox independently recovers white enclosures using white >235, dark dilation, bounded seed/search and an ellipse inset; falls back if open/gray/neighbor-conflicting. This is comparable to an idea YomiScan **already implemented**. Its Typesetter searches font sizes, exposes scale, grows boxes for long words and can ellipsize after bounded height growth. The renderer draws near-opaque white rounded rectangles with black text. There is no glyph segmentation/inpainting, and enlarged typeset bounds are not equivalently checked against artwork/neighbors. [Interior][Y-render-box]; [fit][Y-typeset]; [draw][Y-overlay].

Consequently, visual coverage can increase because Yomu accepts a more aggressive background-covering tradeoff. It does not establish better artwork preservation or complete original-glyph removal. A white box is particularly weak for colored/dark narration and free artwork text. Do not replace YomiScan's renderer or lower its readable font minimum to chase raw rendered-block counts.

Useful adaptations are a modest font scale with rerender-only invalidation, a user-accessible explanation for preserved text, and optional bubble inspection linked to existing Study analysis. Stage progress is less invasive than streaming incomplete raster edits. Pixel-locality, outline preservation, legible full text and unchanged skipped blocks must remain acceptance criteria.

Yomu's two-dimensional-text research found per-column OCR increased historical CER from 4.9% to 6.6%; ruby detection was unresolved, and the default Qwen often ignored/bracketed supplied ruby. Those desktop/old-detector findings are not general OCR scores, but they argue against a new line/ruby pipeline now. [Research and deferred work][Y-2d-research].

## 9. Caching and performance findings

### 9.1 Current implementations

YomiScan caches completed compressed PNG Blob URLs for one DOM session, using element/source/dimension/load revision identity. Nearby decoded overlays reduce rendering memory, but the compressed cache stops at 128 MiB rather than evicting. No backend detection/OCR/translation stage cache persists across process restart. Browser results are lost with session/tab/navigation/reload, while a backend restart alone does not clear an already-live extension's Blob URLs or prevent toggling them. Model objects and fonts are reused, which is a different cache already implemented. [Session][S-session]; [overlays][S-overlay]; [service][S-service].

Yomu's PageFingerprint compares equal screen dimensions and 32×32 mean BT.601 luma cells within 4/255, ignoring cells touching designated overlay/status regions in either capture. PageRecall snapshots detection/OCR/translation model IDs, generation/runtime, threshold, font scale, target and glossary; updates recency and evicts at 30 entries. It remembers only completed successful results with at least one answered bubble, checks settings again after processing, clears on toggle-off/session end and rejects late remember operations from the old generation. A partially answered successful page can recur with the same missing bubbles until explicit refresh. [Fingerprint][Y-fingerprint]; [recall][Y-recall]; [service wiring][Y-service].

That approximate fingerprint is sensible for phone recapture but **not authoritative identity for persistent manga translation**. Inference: a small Japanese edit may preserve cell means within tolerance; ignored areas remove evidence. YomiScan has direct page pixels and should use exact hashes. Yomu's Room history stores text blobs, not reusable source images or page overlays; the cache entity has no active DAO path. Historical source-only caching also corrupted cross-model benchmark results, reinforcing complete settings keys. [Database][Y-db]; [history][Y-history]; [context/cache correction][Y-context-adr].

### 9.2 Persistent stage-cache design proposed

Use SQLite metadata plus bounded local artifacts under an ignored directory, with versioned schemas and atomic publication. Store plain DTOs, never pickled models/services/SQLite handles. Make persistence an explicit setting with quota, clear and refresh controls; do not automatically accumulate a browsing archive.

| Stage | Exact key material | Reuse/invalidation behavior |
|---|---|---|
| Image identity | Canonical decoded pixel SHA-256, dimensions, orientation/color normalization version; acquisition method/resolution provenance | URL is optional navigation metadata, never content authority. Re-encoded identical pixels can reuse; changed pixels cannot. Captured low-resolution pixels must not masquerade as original source pixels. |
| Detection/layout | Image hash; detector artifact/revision; preprocessing, thresholds, filter/group/order versions | Threshold/detector/order changes invalidate this stage and relevant descendants. Keep raw boxes separate from derived grouping/order where practical. |
| OCR | Exact crop-pixel hash, crop bounds/padding/normalization, OCR artifact/preprocess/decode version | Same crop can reuse despite a translation change. Changed crops/weights force OCR; reuse equal crop hashes across changed detector groupings only when truly identical. |
| Translation | Ordered immutable source IDs/text; target; model/base/LoRA hashes; prompt/template/grammar versions; generation; context/order/panels; glossary content/version | Model/language/glossary/context changes retranslate, retaining detection/OCR. Include batch/page contract because composition can affect results. |
| Lexical analysis, if cached | Source text, tokenizer/UniDic versions, dictionary schema/build/source hash | Dictionary refresh must not serve old meanings. Keep this independent from sentence target language. |
| Rendering | Image/analysis identity; actual translations; mask/inpaint/layout versions; font artifact/glyph coverage/scale | Font/layout changes rerender only, without detection/OCR/translation. |

PageAnalysisService currently combines OCR and TextAnalyzer translation/lexical work, so stage reuse requires a **small explicit split**, not serialization of PageAnalysisResult as an opaque universal cache. Existing optional analysis reuse in rendering is a useful starting seam. [Page service][S-page]; [render service][S-render-service].

Use byte-budget LRU, disk and memory accounting, schema migration/corrupt-entry removal, Windows-safe close/atomic replace, and no failed result masquerading as a hit. Keep valid prior output after failed refresh, visibly identify old settings and offer Original. Test call counts across process restart and a key-field invalidation matrix with fakes. Exact retranslation must not rerun detection/OCR; renderer-only changes must not rerun translation. Hashing/caching overhead itself needs measurement.

### 9.3 Resource and latency priorities

Measure end-to-end wait, time to first useful result, cold initialization and stage timings separately. Yomu's per-line translation-duration sum includes successful calls only, so it can understate partial-page wall time; YomiScan's shared batch timing likewise must not be summed per block. Include acquisition/queue/load/cache time in reader-facing totals. [Bridge timing][Y-bridge]; [page timing][S-page]; [resource readout][Y-resource].

Keep one worker and serial shared models. More concurrent requests duplicate/contend for resources rather than automatically improving throughput. Optimize measured bottlenecks (OCR, export/runtime, reuse) before a new scheduler or model family.

## 10. UI/UX and quality-of-life findings

YomiScan already handles the difficult web-specific interactions well: direct source resolution, lazily discovered chapter pages, stable scroll-following overlays, immediate original switching, explicit retries, clear/release, and Study activation on original pixels. Yomu's cross-app Android coverage is useful on its platform but offers no browser reader-adapter implementation to transplant. [Chapter validation][S-chapter-doc]; [acquisition][S-acquisition-doc]; [Yomu service][Y-service].

Useful small differences:

- **Copy original/translation:** Yomu's BubbleCard has explicit copy actions. Add equivalent user-gesture buttons to the existing Study popup with accessible labels and visible failure; text selection already works. Do not copy the card's hardcoded “English” label into multilingual UI. [Card][Y-card]; [popup][S-popup].
- **Retranslate one successful page:** Yomu has a recall-bypass refresh. YomiScan's Retry covers failed/skipped pages only. Add explicit page/stage refresh once cache identity exists, retaining the previous successful result until replacement succeeds. [Recall][Y-recall]; [queue][S-queue].
- **Explain partial coverage:** YomiScan already exposes aggregate category preservation and null unknown misses. Make “page processed” distinct from “all text translated”; expose exact preserved reasons when requested, without inventing an undetected count. [Coverage][S-coverage]; [controls][S-controls].
- **Stage status before streaming:** Yomu streams OCR previews and translated bubbles. For a PNG pipeline, first add bounded stage status so a long page is distinguishable from a stalled request. Streaming transactional image patches adds transport/geometry/cancel complexity and should wait for measured demand. [Pipeline callbacks][Y-pipeline]; [offscreen transport][S-offscreen].
- **Setup recovery:** Yomu explains download bytes, slots, metered connections, permissions and progress. A small YomiScan readiness view should identify missing dictionary/model/backend/host permission separately and provide exact local commands. [Setup][Y-setup]; [manager][Y-manager].
- **Accessibility:** retain existing labels/live region/focus/Escape; add keyboard move/resize/reset if needed, copy targets and bounded font scaling. Yomu's reduced-motion and touch semantics are useful principles, not a reason to import its visual framework. [Popup][S-popup]; [Yomu UI][Y-home].

Yomu persists recent text history and offers page inspection; it has no SRS/JLPT or richer word analysis. Optional local study history/vocabulary is a distinct product decision. A later “study this translated bubble” could reuse retained OCR and the existing TextAnalyzer, avoiding re-OCR, but needs explicit hit-testing and analysis metadata so the default page stays scrollable and pointer-transparent.

## 11. Diagnostics and testing findings

### 11.1 Reproducible page reports

Yomu's implemented report writes **capture.png, page.json and reply.txt**. JSON includes detected boxes; OCR, unsure/dropped reads; glossary-mutated source; answered/outcome/error/fallback status; settings; pipeline-total/stage/translation/time-to-first timings; app/device information. Capture/fingerprint time before processPage is not separately exported. Last-page state retains non-null pipeline results, including translation-failure outcomes; capture/no-frame and whole-pipeline null failures can leave no report. Share uses a ZIP, explicit Android share sheet and scoped FileProvider grants; old report files are replaced with fresh names to avoid an old URI exposing the next page. [Report][Y-report]; [share lifecycle][Y-report-share]; [service wiring][Y-service].

It does **not** provide all desired YomiScan evidence: exact assembled prompt, complete model/runtime hashes, detection/mask debug render and detailed renderer skip codes are not all present. YomiScan already writes more image-processing stages locally; the missing value is unified, reproducible browser-to-backend packaging. [Existing debug stages][S-render-cli]; [provenance][S-render-service]; [browser diagnostics][S-session].

Proposed report manifest: schema/build; image dimensions/hash and acquisition method/resolution; raw detections/group membership/order; OCR/uncertainty; exact model input/output **when explicitly included**; model revisions/base/adapter/runtime/quant/generation; skip/error stage codes; stage/cold/warm/queue/cache timing; optional debug render. Link raw detection IDs to final blocks and translated outputs; distinguish detection confidence from OCR sequence score.

**Safe export design:** default to a local metadata-only preview; image, OCR/raw prompt/response and debug render are separate explicit inclusion choices, marked as potentially containing copyrighted or private content. Strip URLs/query strings/page titles/referrers/cookies/auth tokens/local usernames/paths by default; capture method and normalized error codes suffice for most reports. A hash is not permission to share an image. Keep reports out of Git, size/retention bounded, no automatic upload or GitHub attachment, and allow deletion. Use user-owned/synthetic fixtures for shareable repros; metadata-only exports may still contain sensitive text if enabled. Unlike Yomu's full-screen default report, source-page pixels avoid unrelated browser UI.

The ZIP is for user-controlled sharing, not a promise that arbitrary manga may legally be redistributed. A local manifest-only export is still useful; a report containing complete pixels/inputs can reproduce renderer failures offline without rerunning inference.

### 11.2 Tests, evaluation and development practice

YomiScan's tests cover OCR/translation boundaries with fakes, actual lightweight morphology/dictionary fixtures, upload/origin/Host/body limits, busy/cancel lifecycle, geometry/order/grouping, pixel-local rendering rollback, fonts/wrapping/coverage, browser acquisition/queue/cleanup and model benchmark serialization/lifecycle. Its opt-in Chrome fixture and real-page reports are separate from normal unit tests. [Backend tests][S-tests]; [extension tests][S-front-tests]; [benchmark][S-benchmark].

Yomu adds useful cache/settings races, model download/checksum/repin tests, native prompt/budget tests, streaming UTF-8/overflow/cancel tests, report/share retention tests and CI/release automation. Its page-report script compares before/after detected boxes by nearby center rather than unstable IDs; this is a fixture convenience, not a rigorous detection matcher. Some Android font tests use simplified Robolectric Paint metrics; they do not establish production typography accuracy. [Pipeline tests][Y-tests]; [app cache/report tests][Y-app-tests]; [native tests][Y-native-tests]; [report script][Y-report-script]; [font tests][Y-font-tests].

**Do not copy ADR-0015's abandonment of quality evaluation.** Its current policy is plumbing tests plus report-only speed and human model selection. ADR-0005 OCR and ADR-0006 coherence gates were never implemented; older translation quality machinery was removed. The rationale—an oversized harness with weak/adjudicated metrics—is useful. The right YomiScan response is a small failure-driven, human-reviewed corpus, not an automated exact-string/LLM-judge gate and not no quality measurement. [Quality-policy reversal][Y-quality-adr].

Adopt low-cost CI using pinned/maintained actions, minimum permissions, cancellation of superseded runs, Python 3.13 Windows/Linux locked uv tests/imports and Node 22 locked tests/build. Never download neural artifacts in ordinary CI. Use opt-in separate inference runs with recorded hardware, model hashes, representative cases and private/authorized samples. Yomu's signed APK release pipeline is a packaging principle to adapt later, not Android machinery YomiScan needs. [CI][Y-ci]; [release][Y-release].

Documentation also needs a small consistency pass: older phase reports intentionally describe earlier snapshots, and parts of YomiScan's README still say the extension is Study-only despite the implemented chapter mode. Mark historical scope explicitly and keep one current feature matrix. ADRs should record decisions/reversals, not become mandatory paperwork for every edit. [README][S-readme]; [architecture][S-architecture]; [historical phase report][S-detector-doc].

## 12. Licensing analysis

### 12.1 What can be studied, implemented or reused

YomiScan's original code is MIT. Yomu's inspected source is AGPL-3.0; ADR-0019 records adoption after its old YOLO/Ultralytics licensing conflict. Its subsequent Apache detector switch does **not** relicense Yomu. [YomiScan license][S-license]; [Yomu license][Y-license]; [licensing ADR][Y-license-adr]; [new detector ADR][Y-detector-adr].

| Activity | Practical implication for YomiScan |
|---|---|
| Study architecture, algorithms and observed behavior | This research can inform design. Copyright permission for Yomu's particular source expression is a separate question. |
| Independently implement an idea | Write original Python/TypeScript against YomiScan's contracts and official runtime APIs; retain provenance references. Translating Kotlin/C++ line-by-line is not independent implementation. |
| Use a separately licensed model/runtime | Audit that artifact's own license, base/fine-tune/adapter/conversion lineage and notices. Yomu's application AGPL does not automatically govern independently licensed downloaded weights. |
| Directly copy/adapt Yomu source | Cannot simply label the copied/derived combined work MIT. AGPL distribution obligations and, for modified network-interactive versions, section 13 source-offer requirements require a separate compliance/licensing decision. Avoid this route for the MIT MVP. |
| Redistribute converted/modified weights | Conversion/quantization does not erase upstream terms. Preserve licenses/notices, identify changes where required, and inspect all base/adapter/export artifacts. Downloading to a private cache and bundling/rehosting are different distribution acts. |

AGPL permits commercial use; the conflict is with maintaining an MIT-only distribution of a covered combined work, not a ban on commerce. Do not assume moving copied logic behind localhost automatically avoids obligations. This report recommends independent implementations and no license change. [AGPL text, sections 5/6/13](https://www.gnu.org/licenses/agpl-3.0.html), [GNU FAQ](https://www.gnu.org/licenses/gpl-faq.html#AGPLv3InteractingRemotely).

### 12.2 Candidate artifacts and components

| Component/artifact | Evidence/terms | Recommendation and unresolved issue |
|---|---|---|
| ogkalu detector, pinned 16e8a62, including int8 export | Apache-2.0 declared by [publisher card](https://huggingface.co/ogkalu/comic-text-and-bubble-detector) and [Yomu pin/chain][Y-detector-adr]. | Reasonable experiment; preserve exact revision/hash/export notices. Training-image rights/provenance are not established by a weight license. |
| 2025 manga-ocr ONNX past export, pin 1518987 | Yomu declares Apache-2.0 and pins all files/checksums. [Registry][Y-manager]. Upstream [jzhang533 card](https://huggingface.co/jzhang533/manga-ocr-base-2025) labels Apache-2.0 but has little provenance detail. | Experiment only after checking exact export card/license and conversion lineage. Export card was inaccessible here; do not mark redistribution fully cleared. |
| Original manga-ocr and model | Existing separately licensed upstream, not YomiScan MIT. [Project][U-manga-ocr]; [current notices][S-notices]. | Preserve attribution; pin OCR artifact for reproducibility before packaging/cache guarantees. |
| Qwen2.5 1.5B Instruct / Bartowski Q4_K_M, pin 9eadc66 | [Base card](https://huggingface.co/Qwen/Qwen2.5-1.5B-Instruct) and [GGUF card](https://huggingface.co/bartowski/Qwen2.5-1.5B-Instruct-GGUF) declare Apache-2.0; [registry][Y-manager] provides immutable URL/checksum. | Legally plausible benchmark candidate, no semantic promotion. Other Qwen sizes/adapters need their own review. |
| CAT-Translate 0.8B/1.4B and respective Q4_K_M exports | [CyberAgent model](https://huggingface.co/cyberagent/CAT-Translate-1.4b) and [GGUF publisher](https://huggingface.co/mradermacher/CAT-Translate-1.4b-GGUF) declare MIT; sarashina base lineage documented. [Registry][Y-manager]. | Reasonable small-model experiments. Japanese/English scope; do not offer PT/ES solely by changing prompt. |
| llama.cpp / ONNX Runtime | MIT; [llama.cpp license][U-llama-license], [ONNX Runtime license][U-ort-license]. | Use official runtime APIs independently; verify Python 3.13/Windows/provider compatibility before dependency addition. |
| OPUS / Hy / Qwen manga / VNTL pins already in YomiScan | Exact artifacts and stated Apache terms in [existing report][S-benchmark-doc]; VNTL runtime artifact unverified. OPUS broader project provenance differs from HF card labeling. | Keep current attribution/audit caveats. Do not relicense weights as MIT or promise unavailable artifacts. |
| FuguMT / NLLB | CC-BY-SA-4.0 / CC-BY-NC-4.0 respectively. [Existing licenses/pins][S-notices]. | Fugu adaptations carry ShareAlike conditions; NLLB unsuitable as unrestricted commercial-compatible default. Keep experimental status explicit. |
| Old Manga-Bubble-YOLO / Ultralytics, comic-text-detector, mokuro | Old YOLO has AGPL base despite Apache card label; latter projects GPL-3.0. [Historical conflict][Y-license-adr]; [research][Y-2d-research]. | Do not import as permissive replacements. Current Apache detector avoids needing them; model cards alone do not clear code lineage. |
| OpenMantra evaluation pages | Yomu research records CC-BY-NC-4.0. [Dataset source][U-openmantra]; [research][Y-2d-research]. | Do not bundle casually or use as proof of commercial training rights. Prefer private authorized pages and synthetic public CI fixtures; assess dataset terms for any published benchmark. |
| JMdict / UniDic / font / OpenCV | JMdict CC-BY-SA/EDRDG obligations; UniDic distinct BSD data terms; existing Pillow Aileron and OpenCV notices. [YomiScan notices][S-notices]. | Keep data licenses separate from MIT, including transformed SQLite and future localized dictionary builds. No dictionary-license change is implied by sentence language options. |

Apache redistribution requires license/notice retention and identification of changes as applicable; MIT requires preservation of its notice. A permissive model declaration is not evidence of clean training-data rights. Experimental catalog claims about other families are not fully audited here because they are not recommended for adoption; verify every exact artifact before any future curation. [Apache official license](https://www.apache.org/licenses/LICENSE-2.0).

No Yomu source was copied, no weights redistributed and no licenses changed during this task.

## 13. Features worth adopting

The following is the concrete candidate register. File names described as “new” are proposed boundaries, not files created by this research. Effort is relative to this MVP, without implementation-time promises. Benefits are hypotheses unless a cited run measures them.

### P01 — Reproducible, privacy-controlled page reports

- **What Yomu does:** Export last capture, structured page data and raw reply as an explicit shareable ZIP, including failed/uncertain reads.
- **What YomiScan currently does:** CLI stage images and detailed block metadata; browser acquisition/coverage diagnostics in the console.
- **What's missing or weaker:** No single artifact joins browser acquisition to exact backend configuration, model input/output and rendering provenance.
- **Proposed YomiScan implementation:** Versioned report manifest and local ZIP export reusing existing debug output; inclusion preview for pixels/text/raw response; compare reports using stable source/region lineage.
- **Files/modules affected:** rendering/base.py, rendering/service.py, rendering/cli.py, api/main.py; small new reports module; extension chapter/session.ts, transport.ts, controls.ts.
- **Expected benefit:** Faster diagnosis of “missed” text, fewer repeated inference runs, reproducible renderer comparisons.
- **Estimated complexity:** **Medium**.
- **Risk:** Copyright/private browsing text, oversized archives, leaking local paths/credentials; default redaction, explicit inclusions and bounded retention required.
- **Evidence:** [Yomu PageReport/Share][Y-report] [Y][Y-report-share]; [YomiScan renderer diagnostics][S-render-cli] [S][S-render-service]; section 11.
- **Verdict:** **ADAPT** — first substantive improvement.

### P02 — Lightweight, model-free CI

- **What Yomu does:** Runs lint/unit/build checks on PR/main with pinned actions and minimal permissions; keeps device speed runs separate.
- **What YomiScan currently does:** 190 backend and 38 frontend tests plus build/import tooling; no tracked GitHub workflow.
- **What's missing or weaker:** Automatic regression enforcement, especially Windows/extension integration.
- **Proposed YomiScan implementation:** Windows/Linux Python 3.13 locked uv tests/imports, Node 22 npm ci/test/build, dependency caches only; explicit optional inference workflow later.
- **Files/modules affected:** New .github/workflows/ci.yml; short contribution/validation documentation.
- **Expected benefit:** Prevent regressions while experiments and caches are added; high portfolio/reproducibility value.
- **Estimated complexity:** **Low**.
- **Risk:** Dependency install time and accidental neural downloads; assert ordinary tests stay fake and offline with respect to models.
- **Evidence:** [Yomu CI][Y-ci]; [YomiScan tree][S-tree], [pyproject][S-pyproject], [tests][S-tests].
- **Verdict:** **ADOPT**.

### P03 — Preserve actionable retry/error categories through acquisition

- **What Yomu does:** Uses typed overflow/availability and cancellation outcomes to control fallback, although nonblank partial output can lose a native timeout cause (section 7.2).
- **What YomiScan currently does:** Ordered acquisition-attempt diagnostics and explicit retries; queue has WaitForViewport infrastructure.
- **What's missing or weaker:** AcquisitionError appears to erase viewport-deferred typing before it reaches the queue. This static finding needs reproduction.
- **Proposed YomiScan implementation:** First add a no-model integration fixture for exhausted direct/canvas/offscreen capture; if confirmed, preserve a typed retry disposition without hiding earlier attempt reasons. Retry on visibility only when every relevant condition is transient and attempts remain bounded.
- **Files/modules affected:** chapter/acquisition.ts, model.ts, session.ts; acquisition/chapter tests and browser fixture.
- **Expected benefit:** Avoid needless manual retries for supported viewport-dependent capture and clearer recovery.
- **Estimated complexity:** **Low–Medium**.
- **Risk:** Retry loops or repeated permission/network failures; do not auto-retry permanent failures.
- **Evidence:** [Yomu typed outcomes][Y-bridge]; [YomiScan wrapper][S-acquisition], [queue][S-queue], [session][S-session].
- **Verdict:** **ADAPT**, conditional on reproduction.

### P04 — Copy actions and explicit successful-page refresh

- **What Yomu does:** Copy Japanese/translation from bubble cards; Translate again bypasses page recall and retains the previous successful cache entry after a failed refresh. The failed overlay may disappear; retaining visible old output is an additional YomiScan proposal.
- **What YomiScan currently does:** Selectable popup text, Original/English and retry failed/skipped pages; successful-page refresh requires broader clearing.
- **What's missing or weaker:** Simple copy affordances and a narrow retranslation action.
- **Proposed YomiScan implementation:** Accessible Copy buttons; explicit current-page refresh with old result retained until a new one validates. Add stage-specific refresh when P07 exists.
- **Files/modules affected:** popup.ts; chapter/controls.ts, model.ts, session.ts; geometry/queue/browser fixtures.
- **Expected benefit:** Less friction studying and checking alternative outputs.
- **Estimated complexity:** **Low** for copy; **Medium** for refresh lifecycle.
- **Risk:** Clipboard failure, stale overlays or accidental duplicate jobs; visible error and one-job ownership required.
- **Evidence:** [Yomu card][Y-card], [recall][Y-recall]; [YomiScan popup][S-popup], [queue][S-queue].
- **Verdict:** **ADOPT/ADAPT** in small increments.

### P05 — Current capability matrix and short decision records

- **What Yomu does:** ADRs retain rejected approaches and explicit supersession; artifact decisions link to evidence.
- **What YomiScan currently does:** Detailed phase reports and model benchmark decisions, with some historical language appearing current in README sections.
- **What's missing or weaker:** One unambiguous present-day matrix and concise recorded reversals for new experiments.
- **Proposed YomiScan implementation:** Mark historical reports as snapshots, fix stale Study-only wording, link a small current status table; write short ADRs only for substantive model/cache/context decisions.
- **Files/modules affected:** README.md, docs/architecture.md, relevant existing reports; optional docs/decisions directory.
- **Expected benefit:** Prevent incorrect “missing feature” work and repeated abandoned experiments.
- **Estimated complexity:** **Low**.
- **Risk:** Process overhead if applied to routine edits; keep records short.
- **Evidence:** [Yomu ADR history][Y-quality-adr] [Y][Y-grammar-adr]; [YomiScan README][S-readme], [architecture][S-architecture].
- **Verdict:** **ADOPT**.

### P06 — Reproducible release artifacts

- **What Yomu does:** Builds signed arm64 APKs from tags, verifies signature and publishes through CI.
- **What YomiScan currently does:** Manual uv/backend setup and unpacked extension build with locked dependencies.
- **What's missing or weaker:** Tested downloadable extension bundle, checksums and a dependable installation path.
- **Proposed YomiScan implementation:** After setup/configuration stabilizes, package the extension ZIP and backend source/runtime instructions from tested tags; include dependency/model/dictionary notices and hashes. Evaluate an installer separately rather than bundling every model.
- **Files/modules affected:** extension/build.mjs, release workflow, README/setup and third-party notices.
- **Expected benefit:** Easier evaluation by readers and portfolio reviewers; repeatable releases.
- **Estimated complexity:** **Medium**, **High** if a self-contained Windows runtime is included.
- **Risk:** Large artifacts, platform wheels, unlicensed data/model bundling and installer maintenance.
- **Evidence:** [Yomu release][Y-release]; [YomiScan setup][S-readme], [notices][S-notices].
- **Verdict:** **DEFER** packaging until P02/P11 readiness work.

## 14. Ideas worth adapting rather than copying

### P07 — Persistent cache separated by processing stage

- **What Yomu does:** Session page recall with image fingerprint and settings snapshot; no persistent page-result cache.
- **What YomiScan currently does:** Session PNG cache and reusable analysis input to the renderer.
- **What's missing or weaker:** Restart reuse and retranslation/rerender without unnecessary OCR.
- **Proposed YomiScan implementation:** Exact image/crop hashes, SQLite metadata, bounded artifacts and independent detection/OCR/translation/lexical/render keys as section 9 specifies; explicit persistence/quota/clear/refresh controls.
- **Files/modules affected:** page.py, analysis.py, service.py, rendering/service.py; small cache module and DTO schema; chapter session/controls/API integration.
- **Expected benefit:** Repeated reads and model comparisons avoid expensive unchanged stages.
- **Estimated complexity:** **High** overall; start with extraction→retranslation reuse.
- **Risk:** Stale output, copyrighted/local text retention, corruption, disk growth, Windows file locking.
- **Evidence:** [Yomu settings recall][Y-recall], [unused persistent schema][Y-db]; [YomiScan page][S-page], [render reuse][S-render-service].
- **Verdict:** **ADAPT** the correctness principles; persistent storage is original proposed work.

### P08 — Byte-budget session LRU and complete invalidation

- **What Yomu does:** Capacity-30 LRU, settings-aware hits, on/off generation guards and failed-refresh retention.
- **What YomiScan currently does:** Strong source/DOM/stale-job invalidation and nearby decoded overlays; hard 128 MiB compressed cache ceiling.
- **What's missing or weaker:** Eviction/reprocessing path for long chapters and future setting changes.
- **Proposed YomiScan implementation:** Byte-accounted LRU for compressed results, visible/active pages pinned temporarily, immediate URL revocation for evicted pages, explicit reprocess status, complete configuration generation in job identity.
- **Files/modules affected:** chapter/session.ts, model.ts, overlay.ts and queue tests.
- **Expected benefit:** Long chapters continue within memory budget and settings cannot silently reuse old output.
- **Estimated complexity:** **Medium**.
- **Risk:** Evicting visible pages, flicker, needless recomputation, memory accounting mistakes; keep active results pinned and test late completion.
- **Evidence:** [Yomu recall][Y-recall]; [YomiScan cap/lifecycle][S-session], [overlay][S-overlay].
- **Verdict:** **ADAPT**; do not transplant perceptual screen identity or an arbitrary 30-page desktop limit.

### P09 — Editable, series-scoped name/terminology glossary

- **What Yomu does:** Global persisted glossary, enable switch, literal longest-first one-pass source replacement; original OCR retained separately.
- **What YomiScan currently does:** TranslationContext.glossary hints for selected experimental adapters; no editing/persistence or default-OPUS terminology enforcement.
- **What's missing or weaker:** User control of recurring names and safe scope.
- **Proposed YomiScan implementation:** Per-series/per-target entries, explicit enable, immutable raw OCR, previewed matched spans, literal matching with conservative boundaries/normalization rules; compare source replacement versus model hints. Model capability must determine behavior; do not promise hard OPUS glossary guarantees.
- **Files/modules affected:** translation/base.py, manga.py, analysis/page boundary; small glossary store; extension settings/series identity; cache keys.
- **Expected benefit:** More consistent names and fewer user-visible terminology surprises.
- **Estimated complexity:** **Medium**.
- **Risk:** Homographs/substrings, grammatical corruption, OCR variants and cross-series leakage; never arbitrary whole-output replacement.
- **Evidence:** [Yomu glossary][Y-glossary] [Y][Y-glossary-store]; [YomiScan context][S-translation-base] [S][S-manga]; benchmark name failures [S][S-benchmark-doc].
- **Verdict:** **ADAPT**, with a name/homograph regression corpus.

### P10 — Bounded font accessibility settings and preserved-region inspection

- **What Yomu does:** Font scale, reset and copyable per-bubble inspection; permits enlarged text boxes.
- **What YomiScan currently does:** Readable measured fitting, fixed font parameters, rich Study popup and detailed debug preservation reasons.
- **What's missing or weaker:** User scale preference and normal-reader access to a preserved block's explanation.
- **Proposed YomiScan implementation:** Small safe font-scale range with reset, rerender-only cache invalidation, inspect status/text without editing masks; keep current overflow/artwork preservation.
- **Files/modules affected:** rendering/typesetting.py, renderer.py, API render settings/metadata; chapter controls; fit/coverage/browser tests.
- **Expected benefit:** Legibility and transparency about partial coverage.
- **Estimated complexity:** **Medium**.
- **Risk:** Unreadable density or increased skips at larger scale; never silently truncate to make counts look better.
- **Evidence:** [Yomu fit][Y-typeset], [card][Y-card]; [YomiScan fit][S-typeset], [coverage][S-coverage].
- **Verdict:** **ADAPT** scale/inspection; **REJECT** grown boxes and ellipsis as the default solution.

### P11 — Small model/readiness manager

- **What Yomu does:** Curated downloadable slots, pinned URLs/SHA-256, licenses, pending selections, cancellation, disk/RAM fit estimates and experimental tags.
- **What YomiScan currently does:** Env/CLI engine factory, HF cache, explicit optional GGUF preparation, model-specific lifecycle and benchmark evidence.
- **What's missing or weaker:** Discoverable readiness/selection and useful setup recovery.
- **Proposed YomiScan implementation:** First provide a read-only capability/readiness view and exact setup commands. Later allow explicit pinned downloads and selection from **only validated/default plus clearly experimental choices**, atomic multi-file validation, memory estimates labeled as estimates and idle-boundary model switching.
- **Files/modules affected:** translation/factory.py, service.py, API readiness/config DTOs, prepare_translation_models.py; small manifest; extension setup/settings.
- **Expected benefit:** Lower setup friction and fewer wrong artifact/device/model combinations.
- **Estimated complexity:** **Medium** for readiness, **High** for downloads/hot switching.
- **Risk:** Weight-license mistakes, partial downloads, simultaneous resident models and settings races. Preserve chained failures; Yomu's generic Boolean download error is not ideal recovery UX.
- **Evidence:** [Yomu manager][Y-manager], [slots][Y-slots], [fit][Y-catalog-fit]; [YomiScan factory][S-factory], [lifecycle][S-service], [preparation][S-prepare].
- **Verdict:** **ADAPT** a narrow view soon; **DEFER** full GUI manager/catalog.

### P12 — Reader-facing stage progress and measured resource summaries

- **What Yomu does:** Stage status, first-bubble/total duration and process PSS/CPU/available memory readout.
- **What YomiScan currently does:** Chapter/page progress, post-completion processing and coverage headers, benchmark resource snapshots.
- **What's missing or weaker:** Within-page status and clear cold-start versus steady inference feedback.
- **Proposed YomiScan implementation:** Bounded job/status information correlated to existing requests; display loading/detect/OCR/translate/render, then total/cache-hit status. Optional diagnostics can sample process RSS/owned LLM child and available RAM; VRAM only when accurately available.
- **Files/modules affected:** API/job-status boundary, service/page/render callbacks, offscreen.ts/transport.ts/controls.ts; benchmark metadata.
- **Expected benefit:** Distinguish a long page, model load and stalled request; expose actual bottlenecks.
- **Estimated complexity:** **Medium**; live raster streaming **High** and excluded initially.
- **Risk:** A second scheduler, leaked text in events, misleading CPU/RAM estimates; keep transport simple and status text-free.
- **Evidence:** [Yomu pipeline callbacks][Y-pipeline], [resource monitor][Y-resource]; [YomiScan API][S-api], [offscreen][S-offscreen], [benchmark][S-benchmark].
- **Verdict:** **ADAPT** stage feedback; **DEFER** detailed tuning dashboards.

### P13 — Optional local study history and reader-to-study reuse

- **What Yomu does:** Persistent text-only history; finished bubble opens original/translation card.
- **What YomiScan currently does:** Much richer morphology/dictionary popup, no persistent study list or translated-page word inspection.
- **What's missing or weaker:** Returning to a studied line and learning from an already processed page without selecting/OCR again.
- **Proposed YomiScan implementation:** If learning demand warrants it, opt-in bounded local history and an explicitly activated bubble-inspection mode using retained original OCR/TextAnalyzer, with delete/clear/export. Vocabulary/SRS is a separate later design.
- **Files/modules affected:** analysis/API metadata side channel, popup.ts, chapter/overlay.ts/controls.ts; small local history store.
- **Expected benefit:** Connect reading with existing study strengths; avoid duplicate OCR.
- **Estimated complexity:** **Medium–High**.
- **Risk:** Sensitive/copyrighted transcript retention, extra metadata memory, intercepting reader scrolling/clicks and expanding MVP scope.
- **Evidence:** [Yomu history][Y-history], [card][Y-card]; [YomiScan analysis][S-analysis], [popup][S-popup], [overlay][S-overlay].
- **Verdict:** **DEFER**; useful long-term, not required to solve current quality failures.

## 15. Features to experiment with

### P14 — Class-specific detection thresholds

- **What Yomu does:** .25 default in-bubble text with .5 minimum free text; records much better coverage than its removed YOLO.
- **What YomiScan currently does:** .5 for both text classes on the same upstream detector family/pin.
- **What's missing or weaker:** Evidence that current threshold trades away recoverable dialogue; no shared held-out comparison.
- **Proposed YomiScan implementation:** Arm A/B benchmark in section 6 using existing TextDetector/PageConfig boundaries, frozen downstream stages and per-category annotations.
- **Files/modules affected:** detection/rtdetr.py; optional independent benchmark script/data manifest; detector/page/coverage diagnostics.
- **Expected benefit:** Potential additional small/low-confidence dialogue without a model swap.
- **Estimated complexity:** **Low** code, **Medium** evaluation.
- **Risk:** False detections, duplicate OCR and slower pages; raw rendered-block count can reward bad detections.
- **Evidence:** [Yomu thresholds/results][Y-detector-adr] [Y][Y-detector-results]; [YomiScan detector][S-detector], [actual coverage audit][S-coverage-doc].
- **Verdict:** **EXPERIMENT**, highest-value accuracy investigation.

### P15 — int8 ONNX detector/runtime and duplicate policy

- **What Yomu does:** 11 MB pinned ONNX export, reused sessions, class filtering/NMS/containment recovery.
- **What YomiScan currently does:** About 172 MB FP32 checkpoint through already installed PyTorch/Transformers; conservative contained duplicates.
- **What's missing or weaker:** A measured resource/latency alternative, not evidence of lower detection accuracy.
- **Proposed YomiScan implementation:** Optional TextDetector adapter; compare arms B/C/D with matching image transforms and explicit exported coordinate semantics. Benchmark suppression independently from quantization.
- **Files/modules affected:** new detection adapter, factory/composition option and optional dependency group; same benchmark corpus.
- **Expected benefit:** Potential faster CPU startup/inference and smaller artifacts.
- **Estimated complexity:** **Medium**.
- **Risk:** Export incompatibility, quantization loss, Windows/Python/provider support and unwanted merged-box recovery.
- **Evidence:** [Yomu ONNX][Y-onnx], [NMS][Y-detector], [license/version][Y-detector-adr]; [YomiScan detector][S-detector], [layout][S-layout].
- **Verdict:** **EXPERIMENT**; no automatic replacement.

### P16 — 2025 manga-ocr / ONNX KV decoder

- **What Yomu does:** Pinned 2025 OCR and stateful ONNX decoding; measured acceleration against its own older decoder loop.
- **What YomiScan currently does:** Original manga-ocr via reused Transformers generation; unpinned OCR weight revision.
- **What's missing or weaker:** Reproducible alternative model/runtime evidence.
- **Proposed YomiScan implementation:** Pin baseline first; optional OCREngine benchmark adapter. Factor weight, RGB/grayscale, cap and runtime changes on identical crops, as section 6 specifies.
- **Files/modules affected:** ocr/manga_ocr.py/base.py, optional new adapter and benchmark script; model metadata/manifest.
- **Expected benefit:** Potential transcription and CPU latency/resource improvement.
- **Estimated complexity:** **Medium–High**.
- **Risk:** Confidently wrong reads, changed text normalization, truncation, decoder resource leaks, incomplete export-license verification.
- **Evidence:** [Yomu OCR][Y-ocr], [KV implementation][Y-past], [speed issue][Y-ocr-speed]; [YomiScan OCR][S-ocr].
- **Verdict:** **EXPERIMENT** after report/detection baselines.

### P17 — Calibrated OCR uncertainty

- **What Yomu does:** Stores token-derived sequence confidence and preserves reads below .85.
- **What YomiScan currently does:** OCRResult metadata seam without scores; detector confidence already exposed separately.
- **What's missing or weaker:** Visibility into unreliable OCR before an English rendering covers the original.
- **Proposed YomiScan implementation:** Expose optional confidence/decode-limit/termination metadata, initially in reports only. Calibrate against transcription errors and retained correct dialogue; preserve automatically only after held-out evidence.
- **Files/modules affected:** OCRResult/adapter, page.py, report/coverage metadata and tests.
- **Expected benefit:** Better failure diagnosis; potentially less confidently wrong overpainting.
- **Estimated complexity:** **Medium**.
- **Risk:** Miscalibration, short-text bias, score computation overhead and false reassurance; omission/ruby errors can score highly.
- **Evidence:** [Yomu confidence/limitations][Y-ocr], [ruby study][Y-2d-research]; [YomiScan OCR contract][S-ocr-base], [page confidence][S-page].
- **Verdict:** **ADAPT** diagnostics, **EXPERIMENT** automatic preservation.

### P18 — Grammar-constrained page translation

- **What Yomu does:** Literal ID grammar, actual-ID parser, EOG-compatible completion, typed overflow fallback and per-model capability.
- **What YomiScan currently does:** Unconstrained experimental LLM outputs, count checks and mostly singleton calls; context contract exists.
- **What's missing or weaker:** Structural page guarantee and a clean way to separate formatting failure from translation failure.
- **Proposed YomiScan implementation:** Optional page engine with IDs, server-supported grammar, explicit token budgets/termination, raw provenance and bounded fallback; keep OPUS/native tensor batches unchanged.
- **Files/modules affected:** translation/base.py, manga.py, benchmark.py, analysis/page integration and tests.
- **Expected benefit:** Less malformed/extra structure, clearer bubble mapping, possible page-call throughput improvement.
- **Estimated complexity:** **Medium–High**.
- **Risk:** Well-formed hallucination, incorrect ID content, EOG/limit behavior, worse semantics from context; do not claim accuracy from parser success.
- **Evidence:** [Yomu contract][Y-bridge], [grammar history][Y-grammar-adr]; [YomiScan adapters][S-manga], [failed-context evidence][S-benchmark-doc].
- **Verdict:** **EXPERIMENT**, structurally promising; semantic promotion needs review.

### P19 — Optional pixel-gutter ordering and bounded page context

- **What Yomu does:** White-gutter panel partition and within-panel order, panel separators in one page prompt; no current prior-page memory.
- **What YomiScan currently does:** Anchored bands/RTL plus unused production context infrastructure.
- **What's missing or weaker:** Panel-aware candidate ordering, not reliable character/subject understanding.
- **Proposed YomiScan implementation:** Optional independently written page_layout strategy, current fallback, exactly-once IDs; freeze OCR and validate order first, then no-context/page/panel translation ablation with semantic contamination scoring.
- **Files/modules affected:** page_layout.py, page.py, translation/context benchmark cases and diagnostics.
- **Expected benefit:** Better order on conventional gutters; possible reference consistency.
- **Estimated complexity:** **Medium** geometry, **High** quality evaluation.
- **Risk:** Borderless/dark/slanted layout errors, repeated IDs and dialogue leakage; image grouping does not supply speaker identity.
- **Evidence:** [Yomu assembler][Y-context], [paper mask][Y-paper], [withdrawn memory][Y-grammar-adr]; [YomiScan layout][S-layout], [benchmark][S-benchmark-doc].
- **Verdict:** **EXPERIMENT**; **DEFER** cross-page narrative memory.

### P20 — Japanese → Brazilian Portuguese and Spanish

- **What Yomu does:** Target-language prompt names, compatibility restrictions, multilingual catalog; small research documents wrong-language leakage and weak Spanish/register behavior.
- **What YomiScan currently does:** Working Japanese→English adapters and English JMdict glosses; no target parameter in production.
- **What's missing or weaker:** Reader choice for PT-BR/ES with validated translation, font and terminology behavior.
- **Proposed YomiScan implementation:** Evaluate Japanese→PT-BR first and ES separately; capability-aware engine configuration, target in every result/cache key, bilingual review of meaning/negation/register/names/wrong-language leakage. Consider direct Marian ja-pt/ja-es alongside a licensed multilingual LLM; validate exact language-token conventions. Keep dictionary localization independent.
- **Files/modules affected:** translation contracts/factory/adapters/benchmark, API DTOs, popup/chapter labels, renderer glyph tests; dictionary importer only if gloss localization is separately requested.
- **Expected benefit:** Valuable reader accessibility if meaning is reliable; PT-BR aligns naturally with this project's context.
- **Estimated complexity:** **High** including evaluation.
- **Risk:** Prompt-only “support,” European/Brazilian register mismatch, relay errors, mixed-language output and absent PT/ES dictionary senses.
- **Evidence:** [Yomu language/guards][Y-languages] [Y][Y-slots], [negative research][Y-register-research]; [YomiScan hardcoded target][S-nmt], [English importer][S-importer]. [ja-pt model](https://huggingface.co/Helsinki-NLP/opus-mt-ja-pt), [ja-es model](https://huggingface.co/Helsinki-NLP/opus-mt-ja-es) exist and declare Apache-2.0; neither was tested here.
- **Verdict:** **EXPERIMENT**, release later only with target-specific evidence.

Sentence-model multilingualism, UI localization and dictionary-gloss language are three separate features. Current JMdict_e import deliberately selects English. Portuguese/Spanish gloss availability/coverage must be checked in an appropriate licensed dictionary source; a multilingual JMdict file does not guarantee useful coverage for either target. Translating generated English dictionary glosses would add another error layer, not provide an authoritative localized lexicon. Existing Japanese readings/morphology can remain useful with clearly labeled English meanings.

## 16. Features we should reject

| Idea | Concrete reason and evidence | Verdict |
|---|---|---|
| Copy Yomu Kotlin/JNI/source into MIT modules | AGPL expression/derivative-work obligations are separate from learning an idea. Official runtime facilities and original Python/TS are sufficient. [License][Y-license]; [server facility][U-llama-server] | **REJECT** |
| Migrate to Kotlin, Compose, Hilt, Room or replace FastAPI | Android service/permission/runtime constraints solve a different platform problem. Existing typed Python/MV3 boundaries already support the proposed work. [Yomu pipeline][Y-pipeline]; [YomiScan composition][S-service] | **NOT APPLICABLE / REJECT** |
| Replace source acquisition/chapter queue with screen taps | Loses source resolution, lazy chapter discovery and browser lifecycle. Android cross-app reach does not transfer to web readers. [S][S-acquisition] [Y][Y-capture] | **REJECT** |
| Re-adopt Yomu's old YOLO as a detector upgrade | It was removed after worse author-measured merge/coverage behavior and carries an AGPL base licensing issue. Current Yomu uses our detector family. [ADR-0020][Y-detector-adr] | **REJECT** |
| Replace OPUS with Qwen/CAT/Hy because “LLMs understand context” | No shared semantic-quality study establishes superiority; YomiScan's larger Qwen experiment already contaminated dialogue. Smaller Yomu Qwen is a different candidate, not proof. [S][S-benchmark-doc] [Y][Y-default-adr] | **REJECT** automatic replacement; experiment separately |
| LLM-only translation architecture | Yomu's platform policy would discard YomiScan's fast, genuine seq2seq batches and functioning CPU baseline without evidence. [S][S-marian] [Y][Y-llm-adr] | **REJECT** |
| Grammar as a semantic accuracy guarantee | It constrains allowed structure; wrong meaning/commentary fits inside a line. Mandatory newline previously forced hallucination. [Y][Y-grammar-adr] | **REJECT** claim |
| Restore bilingual prior-page carryover immediately | Removed after old-budget overflow/slowness/no observed gain; YomiScan context also leaked dialogue. [Y][Y-grammar-adr] [S][S-benchmark-doc] | **DEFER** until isolated evidence |
| Inline class/gender/register/continuation labels, or banning content punctuation to hide them | Yomu's tests found leakage, loops/wrong language and little consistent gain. Geometry does not establish speaker gender. [Research][Y-register-research] | **REJECT** current technique |
| Per-column/ruby/aside markup pipeline now | Historical OCR worsened with per-column crops; ruby finder unresolved; markers leaked or were ignored. Yomu itself deferred ruby and rejected aside labels. [Research][Y-2d-research] | **DEFER** specialized research |
| White rectangles, unsafe enlarged placement or ellipsis as default rendering | More drawn blocks can hide artwork or truncate meaning; YomiScan already has localized, reversible safe rendering. [Y][Y-typeset] [Y][Y-overlay] [S][S-renderer] | **REJECT** |
| Perceptual 32×32 fingerprint as persistent identity | Tiny changed text can hash similarly; YomiScan has exact source pixels. [Y][Y-fingerprint] [S][S-session] | **REJECT** authoritative use |
| Treat legacy Room cache schema or old ADR evaluation as implemented | Current DB says cache unused; OCR/coherence gates were never built; quality harness retired. [Y][Y-db] [Y][Y-quality-adr] | **REJECT** false parity claims |
| Copy .85 OCR threshold or Latin-majority rejection globally | Confidence not calibrated to our model; Latin rule addresses Android toolbar contamination and may discard valid mixed-script manga. [Y][Y-ocr] [Y][Y-detector-adr] [S][S-page] | **REJECT** blanket rule |
| Silent 300-character source clipping and generic template/engine fallback | Conceals incomplete translation or wrong model prompting. YomiScan already rejects unsupported source lengths/devices. [Y][Y-translation] [Y][Y-chat-prompt] [S][S-marian] | **REJECT** |
| Expand to every experimental/heavy/abliterated catalog model and sampler slider | Desk-research membership is explicitly not phone validation; more artifacts amplify support, memory, license and quality burden. No current reader need justifies nineteen-plus choices. [Y][Y-experimental-adr] [S][S-benchmark-doc] | **REJECT** wholesale catalog; curate only measured candidates |
| Infer speed or fit from parameter/file size alone | Yomu's own ternary exception contradicts size-derived speed; fixed phone overhead and exempt default are not desktop VRAM guarantees. [Y][Y-catalog-fit] [Y][Y-experimental-adr] | **REJECT** authoritative labels |
| Copy every quality gate, or copy removing all quality measurement | Earlier harness was too complex; no quality check would miss model/preprocessing regressions. Keep a small human-reviewed corpus and structural tests. [Y][Y-quality-adr] [S][S-benchmark] | **REJECT** both extremes |
| Paid/cloud OCR/translation, monetization/auth infrastructure | Conflicts with offline-first scope; Yomu also parked cloud credits/auth paths. [S][S-agents] [Y][Y-offline-adr] [Y][Y-artifact-adr] | **REJECT** |
| Commit page reports, copyrighted fixtures, dictionaries or weights for reproducibility | Reproducibility can use hashes, commands, synthetic data and private local artifacts while preserving rights and privacy. [S][S-agents] [S][S-notices] | **REJECT** |

## 17. Ranked priority table

Ranks express practical execution priority, including experiments that must precede an adoption decision. They are not measured benefit scores. Higher ranks fix known failures, reuse existing seams and create evidence needed by later work.

| Rank | Improvement | Benefit | Effort | Risk | Recommendation |
|---|---|---|---|---|---|
| 1 | P01 unified page reports | High troubleshooting/reproducibility; distinguishes actual failure stage | Medium | Privacy/size | **ADAPT**, high impact |
| 2 | P02 model-free Windows/Linux + extension CI | High regression protection; existing tests already work | Low | Low | **ADOPT**, quick win |
| 3 | P14 class-threshold controlled benchmark | Potential dialogue coverage gain without model migration | Low code / Medium review | False positives/merges | **EXPERIMENT**, decide from held-out results |
| 4 | P07 stage-separated persistent cache | High repeat-read/retranslation speed, avoids unchanged OCR | High | Staleness/privacy/storage | **ADAPT**, dedicated increment after identity/report baseline |
| 5 | P18 grammar-constrained optional page engine | High structural reliability potential; possible throughput | Medium–High | Semantic contamination | **EXPERIMENT**, keep default |
| 6 | P03 typed acquisition retry integration | Concrete suspected end-to-end recovery gap | Low–Medium | Retry loops | **ADAPT** only after reproduction |
| 7 | P04 copy and narrow retranslate controls | Direct low-friction study/recovery | Low–Medium | Stale jobs/clipboard | **ADOPT/ADAPT**, quick win |
| 8 | P08 byte LRU/settings generation | Longer chapters within bounded memory | Medium | Visible-page eviction | **ADAPT** with cache work |
| 9 | P15 int8 detector/export benchmark | Potential CPU/resource improvement | Medium | Export/quantization | **EXPERIMENT** after threshold isolation |
| 10 | P16 OCR weights/runtime benchmark | Potential reading/speed improvement | Medium–High | Accuracy/license/runtime | **EXPERIMENT** |
| 11 | P17 OCR uncertainty metadata/calibration | Diagnose and preserve unreliable reads | Medium | Miscalibration | **ADAPT** metadata; test gate |
| 12 | P09 scoped glossary | Consistent recurring names/terms | Medium | Homograph/grammar damage | **ADAPT** after source identity/cache keys |
| 13 | P19 panel order/page-context ablation | Possible order/reference consistency | Medium–High | Leakage/layout errors | **EXPERIMENT**, geometry first |
| 14 | P05 current capability/docs decisions | Prevent duplicate/misdirected work | Low | Process overhead | **ADOPT**, parallel quick win |
| 15 | P11 readiness view, later model manager | Easier setup and model provenance | Medium→High | Lifecycle/license/memory | **ADAPT** narrow readiness; defer full manager |
| 16 | P10 font scale/preserved-region inspection | Legibility/transparency | Medium | Overflow/artwork regression | **ADAPT** bounded behavior |
| 17 | P12 stage feedback/resource summary | Clearer long-page progress/bottlenecks | Medium | New transport complexity | **ADAPT** status first |
| 18 | P20 PT-BR then ES evaluation | Broader reader value if accurate | High review | Semantic/wrong-language | **EXPERIMENT**, long-term release |
| 19 | P06 tested release packaging | Easier distribution/portfolio evaluation | Medium–High | Packaging/notices | **DEFER** until setup stabilizes |
| 20 | P13 opt-in study history/reader-study bridge | Learning continuity | Medium–High | Retention/interaction/scope | **DEFER**, long-term |
| — | Source/runtime rewrite, copied AGPL logic, automatic LLM replacement, unsafe renderer | No established net advantage | High | High | **REJECT / NOT APPLICABLE** |

**Quick wins:** CI, current documentation, Copy, acquisition retry reproduction and clearer processed/preserved labels. **High-impact increments:** page reports, stage reuse/cache, bounded LRU and scoped glossary. **Experiments:** threshold/export/OCR/uncertainty/page grammar/panels/languages. **Long-term:** full model manager, multilingual release, study history/bridge and polished packaging. **Reject:** section 16's rewrites, unsupported substitutions and abandoned techniques.

## 18. Proposed post-MVP roadmap

All acceptance criteria below are **proposed future gates**, not accomplished results. Maintain the existing Study and Chapter MVP at every increment; no arbitrary version numbering is needed.

### Observe failures and protect the baseline

- **Objective:** Make one failed page diagnosable without guessing or repeatedly re-running models.
- **Features included:** P01 reports; P02 CI; P05 current status documentation; P03 acquisition reproduction; safe small P04 Copy/coverage wording.
- **Why together:** Stable provenance, tests and accurate status are prerequisites for trustworthy model/render/cache changes.
- **Rough complexity:** **Medium** overall.
- **Dependencies:** Existing diagnostics/test seams; no new inference runtime.
- **Test/validation:** Model-free ZIP schema/round-trip/redaction/limits; acquisition→queue integration; current backend/extension suite and opt-in synthetic browser fixture.
- **Measurable acceptance criteria:** Every detected block has raw-ID→OCR→translation→render/error lineage; report identifies model/config/build and acquisition; default export contains no source pixels/URL secrets; cancelled/late jobs cannot attach another page; 190/38 current tests remain green as they evolve; CI loads no model weights. Confirm or close the deferred-retry finding with a reproducible test.

### Establish an accuracy and resource baseline

- **Objective:** Choose the smallest evidence-backed fix for missing text and CPU cost.
- **Features included:** P14 threshold benchmark, P15 export/postprocessing arm; P16/P17 OCR comparison if detection is not the bottleneck.
- **Why together:** These variables affect downstream yield and must be isolated instead of changing detector/OCR/renderer simultaneously.
- **Rough complexity:** **Medium–High**, mostly corpus annotation/review.
- **Dependencies:** Reproducible reports and baseline model artifact pins; authorized local pages.
- **Test/validation:** Held-out annotations, fixed downstream engines, repeated cold/warm runs on stated Windows hardware, visual damage review and OCR ground truth.
- **Measurable acceptance criteria:** Publish counts/denominators for misses, complete crops, merges, extras, CER and rendering outcomes; report p50/p95/load/RAM separately; retain all known dialogue/artwork regression fixtures. No default change without a documented held-out improvement and no critical merge/art damage; a negative result is an acceptable decision.

### Reuse unchanged work safely

- **Objective:** A reader can revisit/retranslate/rerender without unnecessary earlier stages.
- **Features included:** P07 extraction/translation split and opt-in persistence; P08 byte LRU; P04 refresh; exact model/config/source identity.
- **Why together:** Caching without refresh/invalidation is unreliable, and long chapters need a bounded memory policy.
- **Rough complexity:** **High**, delivered as extraction reuse before broad persistence.
- **Dependencies:** Versioned result/report DTOs; explicit engine artifact identity.
- **Test/validation:** Fake invocation counts, restart round-trip, key-field mutation matrix, corrupted/missing/partial entries, Windows replace/close, quotas and late-job races.
- **Measurable acceptance criteria:** Repeated exact input/settings after restart invokes zero detection/OCR/translation; changing translation model/target/glossary reruns translation only; changing font rerenders only; image/OCR changes invalidate relevant descendants; quota is never exceeded after eviction; Clear removes retained artifacts; failed refresh retains identifiable old output and Original remains available.

### Stabilize experimental page translation

- **Objective:** Test whether page LLM inference can improve reliable reading without dialogue contamination.
- **Features included:** P18 optional grammar/IDs/budgets/typed fallback; P19 ordering geometry and controlled page/panel context; P09 terminology experiment.
- **Why together:** Stable identities and source provenance are necessary for judging context; glossary and order must be varied independently.
- **Rough complexity:** **High** including human review.
- **Dependencies:** Page contracts, report/cache keys and pinned llama.cpp/model artifacts.
- **Test/validation:** No-model malformed/duplicate/missing/UTF-8/EOG/limit/timeout/cancel cases; frozen-transcript factorial benchmark; blinded bilingual review, multiple seeds for sampled models.
- **Measurable acceptance criteria:** All completed accepted responses have exact source-ID coverage and no invented structural IDs; partial tails never silently count as complete; overflow fallback is explicit; order emits each input once. Report semantic accuracy, naturalness and contamination separately. Production opt-in requires predeclared non-regression against baseline on critical meaning cases; no quality-mode/default promotion solely on formatting or speed.

### Reduce setup friction and improve reader control

- **Objective:** Readers know what is ready, what a long request is doing and how to recover.
- **Features included:** P11 readiness/capability/notice view, then deliberate downloads if justified; P10 font/inspection; P12 stage status; P06 tested packaging.
- **Why together:** Configuration, lifecycle, progress and distribution share a user-facing readiness contract.
- **Rough complexity:** **Medium**, full download/hot-switch manager **High**.
- **Dependencies:** Stable config generation/cache invalidation; mature runtime/model selection evidence.
- **Test/validation:** Fake downloads/hash mismatch/cancel/repin/disk errors, busy selection, model-close lifecycle, fonts/overflow/scroll, source-notice manifests and clean setup smoke.
- **Measurable acceptance criteria:** Missing dictionary/backend/weights are distinguished; every selectable artifact shows bytes/license/capability/experimental status; changing a model cannot race active inference or invalidate a good selection before download validation; user text/pixels never leave loopback for inference; font overflow preserves original; release bundles reproduce from locked sources.

### Expand languages and learning only with evidence

- **Objective:** Broaden useful reading/study without masking core translation limitations.
- **Features included:** P20 PT-BR/ES evaluation and capability-aware release; optional P13 history/bubble-to-study.
- **Why together:** Both expand product audience/value rather than repair pipeline fundamentals; each can remain independent if only one proves useful.
- **Rough complexity:** **High** for language quality; **Medium–High** for study integration.
- **Dependencies:** Target-aware contracts/cache/fonts; bilingual reviewers; scoped local retention.
- **Test/validation:** Independent PT-BR/ES reference review, Japanese meaning/negation/subject/register/name/wrong-language cases, accented glyphs, dictionary labels, keyboard/input behavior, opt-in storage/delete.
- **Measurable acceptance criteria:** Publish target-specific results; no engine offered for an unsupported language; sentence target never mislabeled as localized dictionary support; no unreviewed EN→target pivot default; history is opt-in, bounded and erasable; Study mode remains functional without history or chapter metadata.

## 19. Top five recommendations with actionable implementation plans

### 1. Build a single page-report boundary from existing diagnostics

Start by defining a versioned plain-data manifest using rendering/service.py's current raw-region/block lineage. Add exact model/config/runtime metadata and acquisition method/resolution; capture raw translation inputs/outputs only in an explicit debug mode. Reuse rendering/cli.py's stage output rather than inventing another image pipeline. Then add user-controlled local ZIP export with redacted metadata preview.

Test synthetic failed OCR, mask overflow, preserved artwork, acquisition fallback and malformed translation in one end-to-end fake report. Verify IDs survive serialization, skipped reasons remain distinct, archives are bounded, and no input URL/cookie/local path slips into default output. This produces a concrete debugging artifact before any model decision. **Stop when a failed page can be explained stage by stage; automatic issue upload is unnecessary.** [Starting seams][S-render-service] [S][S-render-cli]; [reference][Y-report].

### 2. Put existing checks in inexpensive CI

Use the existing uv.lock and package-lock.json. Run Python 3.13 tests/import checks on Windows/Linux and extension tests/typecheck/build on Node 22; cache dependencies, not models/data. Separate optional real inference/browser evaluation from every PR. Pin actions and grant contents-read only.

Accept when a deliberately failing model-free test blocks a branch check and all current checks pass without model artifacts. Do not add a new linter/test framework or reproduce Android's native build matrix for process symmetry. [Reference CI][Y-ci]; [existing dependencies][S-pyproject] [S][S-front-package].

### 3. Benchmark detector policy before shopping for another detector

Take the current three audited pages as regression smoke cases, then annotate a broader held-out set containing actual detector misses. Run current .5/.5 against .25/.5 in the same PyTorch adapter first. Only then compare the int8 ONNX artifact and separate duplicate-suppression arms.

Use crop-completeness/merge/OCR/render outcomes, not a single permissive overlap score. Record annotation disagreements and visually adjudicate extra artwork/SFX predictions. Adopt the smallest change that improves dialogue without new harmful merges; retain baseline if no gain. This answers the user's missed-bubble concern more directly than replacing a detector family Yomu already shares. [Baseline][S-detector]; [reference policy][Y-detector-adr]; [benchmark caveat][Y-detector-results].

### 4. Split extracted page text from translation, then cache by stage

Introduce a plain extraction result for image identity, raw boxes/groups/order, crops/OCR and their provenance. Keep TextAnalyzer's lexical/translation work composable. Reuse the current renderer's optional analysis input while implementing exact-key extraction reuse. Add SQLite/artifact persistence only after the invalidation matrix passes.

Include model/base/adapter/target/prompt/grammar/glossary/context and processing-version identity; font changes must only rerender. Begin with a bounded explicit local cache and Clear/Refresh; test restart, corruption, replacement and failed refresh. Add browser byte LRU so storage limits do not halt an entire long chapter. **Do not use the 32×32 luma match as persistent truth.** [Current page boundary][S-page]; [reuse seam][S-render-service]; [reference recall][Y-recall].

### 5. Add an experimental page-output capability to the owned llama-server boundary

Keep TranslationEngine unchanged for OPUS/Fugu/NLLB. Add an optional page request/result carrying stable IDs, target and context. Independently construct a minimal grammar with exact expected IDs, normal termination after the final translation, bounded text and explicit token budgets. Validate the pinned llama-server endpoint; retain raw replies and typed overflow/timeout/contract status.

Start with model-free structural/fallback/EOG tests. Then benchmark the existing Qwen experiment and one small permissive candidate, such as Yomu's 1.5B Qwen or CAT 1.4B, on the same frozen Japanese cases. Compare plain singleton, singleton with one-ID grammar, flat page with grammar and panel-separated page with grammar; glossary is a separate factor. A new candidate may fail; accept that result. Promote only after human meaning review, and retain OPUS as the default throughout the experiment. [Current adapters][S-manga]; [runtime support][U-llama-server]; [reference contract/history][Y-bridge] [Y][Y-grammar-adr].

## 20. Overall verdict

**YomiScan should take Yomu's disciplined handling of page identity, per-ID outcomes, reproducible reports, model capabilities and setup—not its platform stack or assumptions about model quality.**

The highest-value immediate work is to make failures reproducible and keep regressions out. Next determine whether Yomu's lower bubble threshold helps on YomiScan's actual pages; the current evidence does not justify a new detector family. Reuse unchanged detection/OCR with correct cache keys. Then test a grammar-constrained optional page translator, with meaning and contamination reviewed independently of structure. Investigate the 2025 OCR/ONNX path only through a controlled comparison, and add scoped terminology/readiness features without overwhelming readers with settings.

Keep YomiScan's functioning FastAPI/MV3 composition, genuine NMT batches, direct source-image chapter acquisition, rich Study popup and conservative renderer. Avoid copied AGPL source, white-box artwork coverage, uncalibrated confidence thresholds, removed cross-page memory, speculative class/gender hints, a large unvalidated model menu and automatic OPUS replacement.

PT-BR and Spanish are worthwhile future experiments, especially PT-BR, but accurate sentence translation and dictionary localization require separate evidence. Learning history and a full model manager can follow demonstrated reader demand.

The practical order is therefore **observe and protect → measure coverage → reuse work → constrain experimental output → improve setup/terminology → expand languages and learning**. This extends the MVP through its existing seams and keeps every major commitment conditional on evidence.

### Source index

YomiScan/Yomu source links below resolve to the inspected commits; explicitly identified upstream documentation and issue history have their own references. Exact symbols and relevant lines are named throughout; whole-tree links support absence/coverage findings rather than accuracy claims.

- **YomiScan implementation:** [backend/yomiscan/service.py][S-service], [api/main.py][S-api], [api/security.py][S-security], [analysis.py][S-analysis], [page.py][S-page], [page_layout.py][S-layout], [translation/base.py][S-translation-base], [translation/manga.py][S-manga], [rendering/renderer.py][S-renderer], [extension/src/chapter/session.ts][S-session], [extension/src/popup.ts][S-popup].
- **YomiScan validation:** [docs/translation-benchmark.md][S-benchmark-doc], [benchmarks/results/2026-10-03-nmt.json][S-nmt-results], [docs/phase-7-coverage.md][S-coverage-doc], [docs/phase-7-acquisition.md][S-acquisition-doc], [backend/tests][S-tests], [extension/tests][S-front-tests].
- **Yomu implementation:** [pipeline/TranslationPipeline.kt][Y-pipeline], [bubble/BubbleDetector.kt][Y-detector], [ocr/OcrEngine.kt][Y-ocr], [context/ContextAssembler.kt][Y-context], [ml/LlamaTranslationBridge.kt][Y-bridge], [service/PageRecall.kt][Y-recall], [service/PageReport.kt][Y-report], [service/ModelManager.kt][Y-manager], [translation/LlmModelCatalog.kt][Y-catalog]. These abbreviated labels resolve to their full module paths.
- **Yomu history/evidence:** [ADR-0002][Y-context-adr], [ADR-0013][Y-grammar-adr], [ADR-0014][Y-artifact-adr], [ADR-0015][Y-quality-adr], [ADR-0016][Y-llm-adr], [ADR-0017][Y-experimental-adr], [ADR-0019][Y-license-adr], [ADR-0020][Y-detector-adr], [register-hint research][Y-register-research], [2D text research][Y-2d-research], [detector experiment #437][Y-detector-results].

[S-agents]: https://github.com/GabrielTeixeira88/yomiscan/blob/6b4bc8c8f9a0612eaf1213a30b81387cbb0df583/AGENTS.md#L1
[S-readme]: https://github.com/GabrielTeixeira88/yomiscan/blob/6b4bc8c8f9a0612eaf1213a30b81387cbb0df583/README.md#L1
[S-architecture]: https://github.com/GabrielTeixeira88/yomiscan/blob/6b4bc8c8f9a0612eaf1213a30b81387cbb0df583/docs/architecture.md#L1
[S-license]: https://github.com/GabrielTeixeira88/yomiscan/blob/6b4bc8c8f9a0612eaf1213a30b81387cbb0df583/LICENSE#L1
[S-notices]: https://github.com/GabrielTeixeira88/yomiscan/blob/6b4bc8c8f9a0612eaf1213a30b81387cbb0df583/docs/third-party-licenses.md#L1
[S-pyproject]: https://github.com/GabrielTeixeira88/yomiscan/blob/6b4bc8c8f9a0612eaf1213a30b81387cbb0df583/pyproject.toml#L1
[S-lock]: https://github.com/GabrielTeixeira88/yomiscan/blob/6b4bc8c8f9a0612eaf1213a30b81387cbb0df583/uv.lock#L339
[S-service]: https://github.com/GabrielTeixeira88/yomiscan/blob/6b4bc8c8f9a0612eaf1213a30b81387cbb0df583/backend/yomiscan/service.py#L27
[S-api]: https://github.com/GabrielTeixeira88/yomiscan/blob/6b4bc8c8f9a0612eaf1213a30b81387cbb0df583/backend/yomiscan/api/main.py#L83
[S-security]: https://github.com/GabrielTeixeira88/yomiscan/blob/6b4bc8c8f9a0612eaf1213a30b81387cbb0df583/backend/yomiscan/api/security.py#L20
[S-images]: https://github.com/GabrielTeixeira88/yomiscan/blob/6b4bc8c8f9a0612eaf1213a30b81387cbb0df583/backend/yomiscan/api/images.py#L1
[S-content]: https://github.com/GabrielTeixeira88/yomiscan/blob/6b4bc8c8f9a0612eaf1213a30b81387cbb0df583/extension/src/content.ts#L50
[S-background]: https://github.com/GabrielTeixeira88/yomiscan/blob/6b4bc8c8f9a0612eaf1213a30b81387cbb0df583/extension/src/background.ts#L59
[S-geometry]: https://github.com/GabrielTeixeira88/yomiscan/blob/6b4bc8c8f9a0612eaf1213a30b81387cbb0df583/extension/src/geometry.ts#L8
[S-popup]: https://github.com/GabrielTeixeira88/yomiscan/blob/6b4bc8c8f9a0612eaf1213a30b81387cbb0df583/extension/src/popup.ts#L68
[S-analysis]: https://github.com/GabrielTeixeira88/yomiscan/blob/6b4bc8c8f9a0612eaf1213a30b81387cbb0df583/backend/yomiscan/analysis.py#L58
[S-ocr]: https://github.com/GabrielTeixeira88/yomiscan/blob/6b4bc8c8f9a0612eaf1213a30b81387cbb0df583/backend/yomiscan/ocr/manga_ocr.py#L10
[S-ocr-base]: https://github.com/GabrielTeixeira88/yomiscan/blob/6b4bc8c8f9a0612eaf1213a30b81387cbb0df583/backend/yomiscan/ocr/base.py#L10
[S-nlp]: https://github.com/GabrielTeixeira88/yomiscan/blob/6b4bc8c8f9a0612eaf1213a30b81387cbb0df583/backend/yomiscan/nlp/fugashi.py#L10
[S-importer]: https://github.com/GabrielTeixeira88/yomiscan/blob/6b4bc8c8f9a0612eaf1213a30b81387cbb0df583/backend/yomiscan/dictionary/importer.py#L49
[S-dictionary]: https://github.com/GabrielTeixeira88/yomiscan/blob/6b4bc8c8f9a0612eaf1213a30b81387cbb0df583/backend/yomiscan/dictionary/sqlite.py#L26
[S-nlp-doc]: https://github.com/GabrielTeixeira88/yomiscan/blob/6b4bc8c8f9a0612eaf1213a30b81387cbb0df583/docs/phase-2-validation.md#L1
[S-translation-base]: https://github.com/GabrielTeixeira88/yomiscan/blob/6b4bc8c8f9a0612eaf1213a30b81387cbb0df583/backend/yomiscan/translation/base.py#L11
[S-marian]: https://github.com/GabrielTeixeira88/yomiscan/blob/6b4bc8c8f9a0612eaf1213a30b81387cbb0df583/backend/yomiscan/translation/marian.py#L11
[S-factory]: https://github.com/GabrielTeixeira88/yomiscan/blob/6b4bc8c8f9a0612eaf1213a30b81387cbb0df583/backend/yomiscan/translation/factory.py#L8
[S-manga]: https://github.com/GabrielTeixeira88/yomiscan/blob/6b4bc8c8f9a0612eaf1213a30b81387cbb0df583/backend/yomiscan/translation/manga.py#L21
[S-nmt]: https://github.com/GabrielTeixeira88/yomiscan/blob/6b4bc8c8f9a0612eaf1213a30b81387cbb0df583/backend/yomiscan/translation/nmt.py#L17
[S-prepare]: https://github.com/GabrielTeixeira88/yomiscan/blob/6b4bc8c8f9a0612eaf1213a30b81387cbb0df583/scripts/prepare_translation_models.py#L15
[S-benchmark]: https://github.com/GabrielTeixeira88/yomiscan/blob/6b4bc8c8f9a0612eaf1213a30b81387cbb0df583/backend/yomiscan/translation/benchmark.py#L1
[S-benchmark-doc]: https://github.com/GabrielTeixeira88/yomiscan/blob/6b4bc8c8f9a0612eaf1213a30b81387cbb0df583/docs/translation-benchmark.md#L1
[S-nmt-results]: https://github.com/GabrielTeixeira88/yomiscan/blob/6b4bc8c8f9a0612eaf1213a30b81387cbb0df583/benchmarks/results/2026-10-03-nmt.json#L1
[S-discovery]: https://github.com/GabrielTeixeira88/yomiscan/blob/6b4bc8c8f9a0612eaf1213a30b81387cbb0df583/extension/src/chapter/discovery.ts#L17
[S-session]: https://github.com/GabrielTeixeira88/yomiscan/blob/6b4bc8c8f9a0612eaf1213a30b81387cbb0df583/extension/src/chapter/session.ts#L27
[S-acquisition]: https://github.com/GabrielTeixeira88/yomiscan/blob/6b4bc8c8f9a0612eaf1213a30b81387cbb0df583/extension/src/chapter/acquisition.ts#L10
[S-source]: https://github.com/GabrielTeixeira88/yomiscan/blob/6b4bc8c8f9a0612eaf1213a30b81387cbb0df583/extension/src/chapter/source-fetch.ts#L10
[S-stitch]: https://github.com/GabrielTeixeira88/yomiscan/blob/6b4bc8c8f9a0612eaf1213a30b81387cbb0df583/extension/src/chapter/stitching.ts#L39
[S-queue]: https://github.com/GabrielTeixeira88/yomiscan/blob/6b4bc8c8f9a0612eaf1213a30b81387cbb0df583/extension/src/chapter/model.ts#L26
[S-offscreen]: https://github.com/GabrielTeixeira88/yomiscan/blob/6b4bc8c8f9a0612eaf1213a30b81387cbb0df583/extension/src/offscreen.ts#L8
[S-overlay]: https://github.com/GabrielTeixeira88/yomiscan/blob/6b4bc8c8f9a0612eaf1213a30b81387cbb0df583/extension/src/chapter/overlay.ts#L7
[S-controls]: https://github.com/GabrielTeixeira88/yomiscan/blob/6b4bc8c8f9a0612eaf1213a30b81387cbb0df583/extension/src/chapter/controls.ts#L12
[S-front-coverage]: https://github.com/GabrielTeixeira88/yomiscan/blob/6b4bc8c8f9a0612eaf1213a30b81387cbb0df583/extension/src/chapter/coverage.ts#L1
[S-front-package]: https://github.com/GabrielTeixeira88/yomiscan/blob/6b4bc8c8f9a0612eaf1213a30b81387cbb0df583/extension/package.json#L1
[S-detector]: https://github.com/GabrielTeixeira88/yomiscan/blob/6b4bc8c8f9a0612eaf1213a30b81387cbb0df583/backend/yomiscan/detection/rtdetr.py#L9
[S-page]: https://github.com/GabrielTeixeira88/yomiscan/blob/6b4bc8c8f9a0612eaf1213a30b81387cbb0df583/backend/yomiscan/page.py#L18
[S-layout]: https://github.com/GabrielTeixeira88/yomiscan/blob/6b4bc8c8f9a0612eaf1213a30b81387cbb0df583/backend/yomiscan/page_layout.py#L18
[S-renderer]: https://github.com/GabrielTeixeira88/yomiscan/blob/6b4bc8c8f9a0612eaf1213a30b81387cbb0df583/backend/yomiscan/rendering/renderer.py#L27
[S-masks]: https://github.com/GabrielTeixeira88/yomiscan/blob/6b4bc8c8f9a0612eaf1213a30b81387cbb0df583/backend/yomiscan/rendering/masks.py#L31
[S-layout-region]: https://github.com/GabrielTeixeira88/yomiscan/blob/6b4bc8c8f9a0612eaf1213a30b81387cbb0df583/backend/yomiscan/rendering/layout_regions.py#L45
[S-inpaint]: https://github.com/GabrielTeixeira88/yomiscan/blob/6b4bc8c8f9a0612eaf1213a30b81387cbb0df583/backend/yomiscan/rendering/inpainting.py#L9
[S-typeset]: https://github.com/GabrielTeixeira88/yomiscan/blob/6b4bc8c8f9a0612eaf1213a30b81387cbb0df583/backend/yomiscan/rendering/typesetting.py#L27
[S-coverage]: https://github.com/GabrielTeixeira88/yomiscan/blob/6b4bc8c8f9a0612eaf1213a30b81387cbb0df583/backend/yomiscan/rendering/coverage.py#L10
[S-render-service]: https://github.com/GabrielTeixeira88/yomiscan/blob/6b4bc8c8f9a0612eaf1213a30b81387cbb0df583/backend/yomiscan/rendering/service.py#L18
[S-render-cli]: https://github.com/GabrielTeixeira88/yomiscan/blob/6b4bc8c8f9a0612eaf1213a30b81387cbb0df583/backend/yomiscan/rendering/cli.py#L22
[S-detector-doc]: https://github.com/GabrielTeixeira88/yomiscan/blob/6b4bc8c8f9a0612eaf1213a30b81387cbb0df583/docs/phase-5-page-analysis.md#L8
[S-coverage-doc]: https://github.com/GabrielTeixeira88/yomiscan/blob/6b4bc8c8f9a0612eaf1213a30b81387cbb0df583/docs/phase-7-coverage.md#L1
[S-acquisition-doc]: https://github.com/GabrielTeixeira88/yomiscan/blob/6b4bc8c8f9a0612eaf1213a30b81387cbb0df583/docs/phase-7-acquisition.md#L1
[S-chapter-doc]: https://github.com/GabrielTeixeira88/yomiscan/blob/6b4bc8c8f9a0612eaf1213a30b81387cbb0df583/docs/phase-7-chapter.md#L1
[S-render-quality]: https://github.com/GabrielTeixeira88/yomiscan/blob/6b4bc8c8f9a0612eaf1213a30b81387cbb0df583/docs/phase-6-quality.md#L1
[Y-readme]: https://github.com/artsaraiva/yomu/blob/ace87fef9cdfa3c7a79d3a6b57db02bbbc1b5ce5/README.md#L1
[Y-pipeline]: https://github.com/artsaraiva/yomu/blob/ace87fef9cdfa3c7a79d3a6b57db02bbbc1b5ce5/pipeline/src/main/java/com/yomu/pipeline/TranslationPipeline.kt#L86
[Y-service]: https://github.com/artsaraiva/yomu/blob/ace87fef9cdfa3c7a79d3a6b57db02bbbc1b5ce5/app/src/main/java/com/yomu/app/service/OverlayService.kt#L388
[Y-capture]: https://github.com/artsaraiva/yomu/blob/ace87fef9cdfa3c7a79d3a6b57db02bbbc1b5ce5/app/src/main/java/com/yomu/app/capture/ScreenCaptureManager.kt#L51
[Y-detector]: https://github.com/artsaraiva/yomu/blob/ace87fef9cdfa3c7a79d3a6b57db02bbbc1b5ce5/pipeline/src/main/java/com/yomu/pipeline/bubble/BubbleDetector.kt#L17
[Y-onnx]: https://github.com/artsaraiva/yomu/blob/ace87fef9cdfa3c7a79d3a6b57db02bbbc1b5ce5/ml/src/main/java/com/yomu/ml/OnnxRuntime.kt#L143
[Y-ocr]: https://github.com/artsaraiva/yomu/blob/ace87fef9cdfa3c7a79d3a6b57db02bbbc1b5ce5/pipeline/src/main/java/com/yomu/pipeline/ocr/OcrEngine.kt#L19
[Y-ocr-decode]: https://github.com/artsaraiva/yomu/blob/ace87fef9cdfa3c7a79d3a6b57db02bbbc1b5ce5/pipeline/src/main/java/com/yomu/pipeline/ocr/OcrDecoding.kt#L43
[Y-past]: https://github.com/artsaraiva/yomu/blob/ace87fef9cdfa3c7a79d3a6b57db02bbbc1b5ce5/ml/src/main/java/com/yomu/ml/PastKeyValueDecode.kt#L37
[Y-context]: https://github.com/artsaraiva/yomu/blob/ace87fef9cdfa3c7a79d3a6b57db02bbbc1b5ce5/pipeline/src/main/java/com/yomu/pipeline/context/ContextAssembler.kt#L24
[Y-paper]: https://github.com/artsaraiva/yomu/blob/ace87fef9cdfa3c7a79d3a6b57db02bbbc1b5ce5/pipeline/src/main/java/com/yomu/pipeline/context/PaperMask.kt#L7
[Y-translation]: https://github.com/artsaraiva/yomu/blob/ace87fef9cdfa3c7a79d3a6b57db02bbbc1b5ce5/pipeline/src/main/java/com/yomu/pipeline/translation/TranslationEngine.kt#L72
[Y-bridge]: https://github.com/artsaraiva/yomu/blob/ace87fef9cdfa3c7a79d3a6b57db02bbbc1b5ce5/ml/src/main/java/com/yomu/ml/LlamaTranslationBridge.kt#L54
[Y-splitter]: https://github.com/artsaraiva/yomu/blob/ace87fef9cdfa3c7a79d3a6b57db02bbbc1b5ce5/ml/src/main/java/com/yomu/ml/ReplyLineSplitter.kt#L5
[Y-budget]: https://github.com/artsaraiva/yomu/blob/ace87fef9cdfa3c7a79d3a6b57db02bbbc1b5ce5/ml/src/main/cpp/prompt_budget.h#L1
[Y-native]: https://github.com/artsaraiva/yomu/blob/ace87fef9cdfa3c7a79d3a6b57db02bbbc1b5ce5/ml/src/main/cpp/llama_jni.cpp#L190
[Y-chat-prompt]: https://github.com/artsaraiva/yomu/blob/ace87fef9cdfa3c7a79d3a6b57db02bbbc1b5ce5/ml/src/main/cpp/chat_prompt.cpp#L9
[Y-typeset]: https://github.com/artsaraiva/yomu/blob/ace87fef9cdfa3c7a79d3a6b57db02bbbc1b5ce5/pipeline/src/main/java/com/yomu/pipeline/typesetting/Typesetter.kt#L25
[Y-render-box]: https://github.com/artsaraiva/yomu/blob/ace87fef9cdfa3c7a79d3a6b57db02bbbc1b5ce5/pipeline/src/main/java/com/yomu/pipeline/bubble/BubbleRenderBox.kt#L31
[Y-overlay]: https://github.com/artsaraiva/yomu/blob/ace87fef9cdfa3c7a79d3a6b57db02bbbc1b5ce5/app/src/main/java/com/yomu/app/overlay/TranslationRenderOverlay.kt#L184
[Y-card]: https://github.com/artsaraiva/yomu/blob/ace87fef9cdfa3c7a79d3a6b57db02bbbc1b5ce5/app/src/main/java/com/yomu/app/overlay/BubbleCard.kt#L19
[Y-recall]: https://github.com/artsaraiva/yomu/blob/ace87fef9cdfa3c7a79d3a6b57db02bbbc1b5ce5/app/src/main/java/com/yomu/app/service/PageRecall.kt#L11
[Y-fingerprint]: https://github.com/artsaraiva/yomu/blob/ace87fef9cdfa3c7a79d3a6b57db02bbbc1b5ce5/app/src/main/java/com/yomu/app/service/PageFingerprint.kt#L19
[Y-db]: https://github.com/artsaraiva/yomu/blob/ace87fef9cdfa3c7a79d3a6b57db02bbbc1b5ce5/app/src/main/java/com/yomu/app/db/AppDatabase.kt#L13
[Y-history]: https://github.com/artsaraiva/yomu/blob/ace87fef9cdfa3c7a79d3a6b57db02bbbc1b5ce5/app/src/main/java/com/yomu/app/service/SessionManager.kt#L20
[Y-home]: https://github.com/artsaraiva/yomu/blob/ace87fef9cdfa3c7a79d3a6b57db02bbbc1b5ce5/app/src/main/java/com/yomu/app/ui/home/HomeScreen.kt#L118
[Y-report]: https://github.com/artsaraiva/yomu/blob/ace87fef9cdfa3c7a79d3a6b57db02bbbc1b5ce5/app/src/main/java/com/yomu/app/service/PageReport.kt#L56
[Y-report-share]: https://github.com/artsaraiva/yomu/blob/ace87fef9cdfa3c7a79d3a6b57db02bbbc1b5ce5/app/src/main/java/com/yomu/app/service/PageReportShare.kt#L25
[Y-report-script]: https://github.com/artsaraiva/yomu/blob/ace87fef9cdfa3c7a79d3a6b57db02bbbc1b5ce5/scripts/page-report.py#L1
[Y-catalog]: https://github.com/artsaraiva/yomu/blob/ace87fef9cdfa3c7a79d3a6b57db02bbbc1b5ce5/app/src/main/java/com/yomu/app/translation/LlmModelCatalog.kt#L11
[Y-catalog-fit]: https://github.com/artsaraiva/yomu/blob/ace87fef9cdfa3c7a79d3a6b57db02bbbc1b5ce5/app/src/main/java/com/yomu/app/translation/LlmModelCatalog.kt#L394
[Y-manager]: https://github.com/artsaraiva/yomu/blob/ace87fef9cdfa3c7a79d3a6b57db02bbbc1b5ce5/app/src/main/java/com/yomu/app/service/ModelManager.kt#L61
[Y-slots]: https://github.com/artsaraiva/yomu/blob/ace87fef9cdfa3c7a79d3a6b57db02bbbc1b5ce5/app/src/main/java/com/yomu/app/service/ModelSlotSelection.kt#L66
[Y-resource]: https://github.com/artsaraiva/yomu/blob/ace87fef9cdfa3c7a79d3a6b57db02bbbc1b5ce5/app/src/main/java/com/yomu/app/ui/settings/ResourceMonitor.kt#L9
[Y-setup]: https://github.com/artsaraiva/yomu/blob/ace87fef9cdfa3c7a79d3a6b57db02bbbc1b5ce5/app/src/main/java/com/yomu/app/ui/home/SetupScreen.kt#L23
[Y-languages]: https://github.com/artsaraiva/yomu/blob/ace87fef9cdfa3c7a79d3a6b57db02bbbc1b5ce5/core/src/main/java/com/yomu/core/TargetLanguage.kt#L3
[Y-glossary]: https://github.com/artsaraiva/yomu/blob/ace87fef9cdfa3c7a79d3a6b57db02bbbc1b5ce5/core/src/main/java/com/yomu/core/NameGlossary.kt#L3
[Y-glossary-store]: https://github.com/artsaraiva/yomu/blob/ace87fef9cdfa3c7a79d3a6b57db02bbbc1b5ce5/app/src/main/java/com/yomu/app/translation/NameGlossaryStore.kt#L8
[Y-ci]: https://github.com/artsaraiva/yomu/blob/ace87fef9cdfa3c7a79d3a6b57db02bbbc1b5ce5/.github/workflows/android-ci.yml#L1
[Y-release]: https://github.com/artsaraiva/yomu/blob/ace87fef9cdfa3c7a79d3a6b57db02bbbc1b5ce5/.github/workflows/release.yml#L1
[Y-font-tests]: https://github.com/artsaraiva/yomu/blob/ace87fef9cdfa3c7a79d3a6b57db02bbbc1b5ce5/pipeline/src/test/java/com/yomu/pipeline/typesetting/TypesetterTest.kt#L174
[Y-license]: https://github.com/artsaraiva/yomu/blob/ace87fef9cdfa3c7a79d3a6b57db02bbbc1b5ce5/LICENSE#L1
[Y-detector-adr]: https://github.com/artsaraiva/yomu/blob/ace87fef9cdfa3c7a79d3a6b57db02bbbc1b5ce5/docs/adr/0020-rtdetr-text-detector.md#L3
[Y-grammar-adr]: https://github.com/artsaraiva/yomu/blob/ace87fef9cdfa3c7a79d3a6b57db02bbbc1b5ce5/docs/adr/0013-grammar-constrained-page-level-batch.md#L1
[Y-context-adr]: https://github.com/artsaraiva/yomu/blob/ace87fef9cdfa3c7a79d3a6b57db02bbbc1b5ce5/docs/adr/0002-cross-panel-translation-context.md#L1
[Y-default-adr]: https://github.com/artsaraiva/yomu/blob/ace87fef9cdfa3c7a79d3a6b57db02bbbc1b5ce5/docs/adr/0010-qwen-default-cat-demoted-to-floor.md#L1
[Y-experimental-adr]: https://github.com/artsaraiva/yomu/blob/ace87fef9cdfa3c7a79d3a6b57db02bbbc1b5ce5/docs/adr/0017-experimental-curated-tier.md#L1
[Y-hit-adr]: https://github.com/artsaraiva/yomu/blob/ace87fef9cdfa3c7a79d3a6b57db02bbbc1b5ce5/docs/adr/0003-detection-hit-criterion.md#L1
[Y-quality-adr]: https://github.com/artsaraiva/yomu/blob/ace87fef9cdfa3c7a79d3a6b57db02bbbc1b5ce5/docs/adr/0015-quality-belongs-to-the-model.md#L1
[Y-license-adr]: https://github.com/artsaraiva/yomu/blob/ace87fef9cdfa3c7a79d3a6b57db02bbbc1b5ce5/docs/adr/0019-yomu-is-agpl-open-source.md#L1
[Y-llm-adr]: https://github.com/artsaraiva/yomu/blob/ace87fef9cdfa3c7a79d3a6b57db02bbbc1b5ce5/docs/adr/0016-llm-is-the-only-translator.md#L1
[Y-offline-adr]: https://github.com/artsaraiva/yomu/blob/ace87fef9cdfa3c7a79d3a6b57db02bbbc1b5ce5/docs/adr/0018-translation-stays-on-the-phone.md#L1
[Y-artifact-adr]: https://github.com/artsaraiva/yomu/blob/ace87fef9cdfa3c7a79d3a6b57db02bbbc1b5ce5/docs/adr/0014-quantization-deliverables-and-revision-pinning.md#L1
[Y-register-research]: https://github.com/artsaraiva/yomu/blob/ace87fef9cdfa3c7a79d3a6b57db02bbbc1b5ce5/docs/research/register-hints-target-languages.md#L27
[Y-2d-research]: https://github.com/artsaraiva/yomu/blob/ace87fef9cdfa3c7a79d3a6b57db02bbbc1b5ce5/docs/research/2d-text-structure.md#L1
[S-tree]: https://github.com/GabrielTeixeira88/yomiscan/tree/6b4bc8c8f9a0612eaf1213a30b81387cbb0df583
[S-tests]: https://github.com/GabrielTeixeira88/yomiscan/tree/6b4bc8c8f9a0612eaf1213a30b81387cbb0df583/backend/tests
[S-front-tests]: https://github.com/GabrielTeixeira88/yomiscan/tree/6b4bc8c8f9a0612eaf1213a30b81387cbb0df583/extension/tests
[Y-tests]: https://github.com/artsaraiva/yomu/tree/ace87fef9cdfa3c7a79d3a6b57db02bbbc1b5ce5/pipeline/src/test
[Y-native-tests]: https://github.com/artsaraiva/yomu/tree/ace87fef9cdfa3c7a79d3a6b57db02bbbc1b5ce5/ml/src/test
[Y-detector-results]: https://github.com/artsaraiva/yomu/issues/437#issuecomment-6809408306
[Y-ocr-speed]: https://github.com/artsaraiva/yomu/issues/393
[Y-eog-fix]: https://github.com/artsaraiva/yomu/commit/1ace2ec58a15ecf9cd4637b1f0270906130a236b
[Y-panel-fix]: https://github.com/artsaraiva/yomu/commit/c5ba2cec881b580f2a26e704ad068715b7be5a5f
[U-manga-ocr]: https://github.com/kha-white/manga-ocr/blob/c333b5d36e88d539d6b040b4c4cf90ad5ecd4f69/manga_ocr/ocr.py#L13
[U-llama-server]: https://github.com/ggml-org/llama.cpp/blob/b11380/tools/server/README.md#L1316
[U-llama-grammar]: https://github.com/ggml-org/llama.cpp/blob/b11380/grammars/README.md#L133
[U-llama-license]: https://github.com/ggml-org/llama.cpp/blob/b11380/LICENSE
[U-ort-license]: https://github.com/microsoft/onnxruntime/blob/main/LICENSE
[U-openmantra]: https://github.com/mantra-inc/open-mantra-dataset/blob/main/LICENSE.md
[Y-native-result]: https://github.com/artsaraiva/yomu/blob/ace87fef9cdfa3c7a79d3a6b57db02bbbc1b5ce5/ml/src/main/java/com/yomu/ml/LlamaBridge.kt#L105
[Y-stream-test]: https://github.com/artsaraiva/yomu/blob/ace87fef9cdfa3c7a79d3a6b57db02bbbc1b5ce5/ml/src/test/java/com/yomu/ml/LlamaTranslationBridgeStreamingTest.kt#L87
[Y-app-tests]: https://github.com/artsaraiva/yomu/tree/ace87fef9cdfa3c7a79d3a6b57db02bbbc1b5ce5/app/src/test/java/com/yomu/app/service
[Y-ml-build]: https://github.com/artsaraiva/yomu/blob/ace87fef9cdfa3c7a79d3a6b57db02bbbc1b5ce5/ml/build.gradle.kts#L37
[Y-llama-pin]: https://github.com/artsaraiva/yomu/tree/ace87fef9cdfa3c7a79d3a6b57db02bbbc1b5ce5/ml/llama.cpp
[Y-head]: https://github.com/artsaraiva/yomu/commit/ace87fef9cdfa3c7a79d3a6b57db02bbbc1b5ce5
[Y-manifest]: https://github.com/artsaraiva/yomu/blob/ace87fef9cdfa3c7a79d3a6b57db02bbbc1b5ce5/app/src/main/AndroidManifest.xml#L1
