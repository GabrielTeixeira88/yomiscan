# YomiScan — Complete Post-MVP Application Audit

Audit date: **21 November 2026**, America/Sao_Paulo. Reviewed application baseline:
**`178e506f8bc03ef541f4c4f8d60ecb44476f023a`**, the actual Stage 5 merge into main.
This branch changes audit documentation/evidence only. Findings below were not fixed.

## 1. Executive summary

**The ordinary integrated application works, and the architecture remains sound.
Enter stabilization before adding features or presenting this as a public release.**
Fresh model-free suites, actual packaged installation, the existing Chrome integration
fixture, real offline API requests and a real Chrome/production-model composition
smoke all passed. Stage-aware reuse, separate user data, conservative image editing,
glossary invalidation and exact retained Study analysis are substantial working features.

Passing those tests did not cover several important browser boundaries. Targeted probes
reproduced Study capture surviving SPA navigation and analyzing the replacement page,
and region hit targets attached to the wrong visible location under unsupported image
presentation. Other confirmed defects affect hidden-image overlays, the history Save
button, failed-model readiness, default logging, configuration precedence, cancellation
between OCR crops, readiness-response ordering and current setup documentation.

**Confirmed findings: P0: 0; P1: 2; P2: 6; P3: 2.** No remote unauthorized-data-access
or user-data-loss exploit was demonstrated. This is not a security guarantee. The local
LLM error-log disclosure in AU-06 needs correction despite protected HTTP responses.

| Question | Assessment |
| --- | --- |
| Integrated application functioning? | Yes for ordinary supported-reader/Study flows; important edge-case failures remain. |
| Architecture sound? | Yes. Preserve MV3/FastAPI and the single owning worker; improve narrow lifecycle/presentation contracts. |
| Useful as a local reading/study tool? | Yes, with partial rendering, fallible translation and explicit setup expectations. |
| Broader testing? | Conditional go for a small informed cohort, with known issues and private diagnostics. |
| Public release? | No-go until P1 fixes and release qualification; CI alone does not establish readiness. |
| Most important work? | Capture/page identity, safe image presentation, failure/privacy boundaries, then recovery and usability. |

Evidence: [browser observations][E-browser], [real API measurements][E-measurements],
[negative API/adapter observations][E-api]. Model-quality limitations are separate
from the newly confirmed application defects.

## 2. Verified baseline

### Merge and repository integrity

PR [#5](https://github.com/GabrielTeixeira88/yomiscan/pull/5) was still at
`28f93651b8665f31bcfcf26c23dc78b3abd5ad13`, targeting main `78dd83ba…`, with eight
successful push/PR checks, no review submissions/threads and a clean mergeable state.
The 55-file diff was text/documentation, with no weights, databases, manga samples,
credentials or packaged build directories. The working tree was clean.

Separate Standards and Spec reviews found no critical merge blocker. Standards found
the setup-documentation discrepancy now recorded as AU-10 and nonblocking coupling
advisories. Spec identified image-presentation cases for post-merge reproduction.
Those axes were kept separate; a standards pass was not treated as a functional pass.

PR #5 was merged through GitHub using the normal merge method and an expected-head
check. Local main was fast-forwarded to **`178e506f8bc03ef541f4c4f8d60ecb44476f023a`**.
Its first-parent history contains Stage 1 `c651a3c`, Stage 2 `7a7ece7`, Stage 3
`4b51ce5`, Stage 4 `78dd83b`, and Stage 5 `178e506`. The audit branch
`audit/post-mvp-full-review` starts at that merge. No application implementation,
model selection, existing user database or historical report was changed for the audit.

### Environment and available resources

| Item | Observed environment |
| --- | --- |
| OS / CPU | Windows 11 build 26300, AMD64; Intel Core i7-14700K, 20 cores/28 logical processors |
| Python / uv / Node | 3.13.9 / 0.12.19 / 22.19.0 |
| Chrome | 157.0.8103.79, fresh task-owned headless profiles |
| Main neural stack | Torch 2.14.0, Transformers 5.17.0, original manga-ocr; CPU selected explicitly |
| Production OCR | `kha-white/manga-ocr-base@aa6573bd10b0d446cbf622e29c3e084914df9741`; cached artifact set present |
| Detector | `ogkalu/comic-text-and-bubble-detector@16e8a622f91fabc6b5b65c96d32d1183f8843546`; PyTorch, .50/.50 |
| Translator | `Helsinki-NLP/opus-mt-ja-en@0770961a39ba6bd66305b149c3f4110bcafca2e6`; English OPUS |
| Dictionary | Existing local English JMdict SQLite database, opened read-only; schema/open/lookups exercised |
| Optional files | 2025 PyTorch/ONNX OCR, ONNX detector, Fugu and NLLB cache sets present by metadata inspection |
| Optional runtimes | ONNX Runtime and psutil absent from the default synchronized environment; no extras installed |
| Other optional selections | PT/ES OPUS files absent at their pins; GGUF engines not configured in this process. This is not a disk-wide claim that no GGUF exists. |

No weights were downloaded. Existing dependency installation/build commands used their
normal locked caches. Model-card/license web reads fetched documentation, not tensors.
Neural validation used two previously authorized local pages; only aliases, dimensions,
byte lengths and hashes appear in [aggregate evidence][E-measurements]. No page pixels,
raw OCR/translations, model replies, personal paths or browsing URLs are published here.
The one committed screenshot is a wholly synthetic solid-color fixture with fake text.

### Executed checks and evidence limits

| Check | Verified in this audit | Limit |
| --- | --- | --- |
| `uv sync --frozen`; full pytest | **316 passed, 1 skipped**, 24.58 s; imports passed without Torch being imported | Model-free; synthetic/injected engines do not prove model accuracy. |
| `npm ci`; tests; strict build | **68 passed**; installation/build passed; npm reported zero vulnerabilities in its small dependency set | Not a Python dependency-advisory audit. |
| Existing isolated browser fixture | **37 checks passed**; 24-page/192 MiB cumulative queue in **24,961 ms** | Mocked neural backend; retention stayed within the 128 MiB result budget, not measured total Chrome RSS. |
| Targeted Chrome probes | SPA capture/result navigation, rotate/object-fit mapping, ancestor opacity, Save layout, response ordering reproduced | Synthetic fixtures; presentation/navigation evidence, not OCR quality. |
| Real offline API | Startup, Study/repeat, two pages, exact repeat, translation refresh, font rerender, separate-process disk restoration | Small single-run measurement; OS caches/CPU scheduling not controlled. |
| Real Chrome + production API | Actual chapter overlay; Bubble Study reused five retained tokens with **zero additional analyze-image calls**; native screenshot Study returned six tokens with **one actual analyze-image call** | One authorized page; first chapter result reused the prepared processing cache. |
| Additional API/storage probes | 17 negative/boundary cases, cache-clear/glossary independence, cancellation reproduction, four missing-resource preflight cases | Fake engines/files for negative cases; no destructive penetration tests. |
| Adapter failure probes | Three model-free reproductions: loaded-state error, device precedence, synthetic private upstream body in ordinary logs | No LLM/NMT inference performed by these probes. |
| Actual distributions | Clean merged-commit ZIP/wheel/sdist; fresh isolated installation of both Python formats, six CLI helps, fonts/OFL/imports/version, protected missing-resource startup, actual ZIP Chrome activation | Default models/JMdict were already prepared; first-ever large downloads were not repeated. |

The existing Windows skip is atomic replacement of an open dictionary database;
Windows locks that file. The existing Starlette/httpx TestClient deprecation warning
remains. It is not a test failure and was not hidden with an unrelated dependency change.

Merged-main [hosted run 44866442388](https://github.com/GabrielTeixeira88/yomiscan/actions/runs/44866442388)
also passed all four jobs. Its logs were checked: **317 tests passed on Linux**,
**316 plus one skip on Windows**, Node/build succeeded, and actual distribution
installation/Chrome activation/upload succeeded. These are newly inspected hosted
results for this merge, not a claim of local Linux execution. Stage 2/4 research
matrices and optional-model inference were **not rerun**; their earlier measurements
remain historical evidence only.

## 3. Feature-by-feature audit

PASS means the stated bounded behavior passed the identified checks, not every site,
language or model combination. PARTIAL includes a working normal flow plus a defect,
limited semantic evidence or an untested important boundary. UNVERIFIED is used for
unexecuted claims; it is not silently counted as failure.

| Feature / claim | Verified behavior and evidence | Problems / remaining gaps | Status |
| --- | --- | --- | --- |
| Study selection and capture | Actual screenshot crop → real API → popup; DPI/zoom/scroll/cancel cases in 37-check fixture. [content][S-content], [background][S-background] | AU-01: SPA URL/content replacement survives capture verification; arbitrary browser/OS DPI combinations not exhausted. | PARTIAL |
| Morphology/JMdict breakdown | Real crop: six tokens with readings and dictionary matches; written-form lookup, POS/conjugations/senses covered by tests. [analyzer][S-analysis], [dictionary][S-dictionary] | Definitions are candidates, not contextual word-sense decisions. No new linguistic accuracy score. | PASS |
| Popup/copy/drag/resize | Real result displayed; mock-browser clipboard user gesture, movement, boundaries and Escape passed. [popup][S-popup] | AU-04; pointer-only move/resize and very narrow layouts need additional accessibility work. | PARTIAL |
| Chapter discovery/acquisition | Loaded/currentSrc/lazy images, DOM changes, host permission, canvas/viewport/stitch fallbacks and deferred retry passed. [session][S-session], [acquisition][S-acquisition] | Generic aligned-image readers only; no exhaustive live-site survey; AU-02/03. | PARTIAL |
| Queue, refresh, cancellation | Serial priority, stale result rejection, previous-result retention, Stop/Retry/Clear, LRU/export pins passed. [queue][S-queue] | AU-08: cancellation does not stop the next OCR crop; real independent-tab contention remains less exercised than unit/job isolation. | PARTIAL |
| Production detection | Actual PyTorch .50/.50 output fed OCR/rendering on two pages. [detector][S-detector] | Recall/merged-bubble accuracy was not rescored. Earlier tiny corpus does not certify all manga. | PASS |
| Original OCR | Actual vertical Japanese crop/page OCR and six-token Study result; no duplicate OCR in Bubble Study. [OCR][S-ocr] | Original engine exposes no calibrated confidence/termination detail; blank/non-Japanese hallucination risk is a quality limit. | PASS |
| Experimental vision adapters | Factories, pinned-file checks, runtime rejection and model-free tests inspected. [vision catalog][S-vision] | ONNX runtime absent; no 2025/ONNX inference here. Earlier Stage 2 accuracy tradeoffs still apply. | UNVERIFIED for new inference |
| Sentence/page translation | Real OPUS, native batch/source alignment, target/capability validation and strict-ID rejection tests passed. [Marian][S-marian], [structured][S-structured] | Semantic errors visible in spot review; optional engines/targets/context not newly inferred; AU-06/07. | PARTIAL |
| Conservative rendering | Real 9 rendered/4 preserved; atomic mask/layout/inpaint/draw failures and accents/overflow tested. [renderer][S-renderer] | Two-page visual scope only; preserve-vs-miss remains distinct; no general artwork-safety or coverage guarantee. | PASS within checked scope |
| Original/English overlays | Real overlay and 37-check switching/source/navigation coverage passed. [overlay][S-overlay] | AU-02/03: unsupported presentation/ancestor hiding not consistently respected. | PARTIAL |
| Glossaries | CRUD/target/series matching and stale-version retirement tests; browser cross-reader broadcasts and failed-profile-reload cases passed. [glossary][S-glossary] | OPUS does not enforce hints; no new real Hy/Qwen glossary run. | PASS for management/invalidation |
| Stage caching | Real repeat/restoration hits; selective refresh; checksum/type/schema/quota/ownership tests. [cache][S-cache], [identity][S-identity] | Startup still loads models; cache hit has real lookup/serialization/transport cost. User data must stay outside disposable caches. | PASS |
| Diagnostics | Mock-browser metadata-only default, opt-in text/images, stale export rejection and size limits passed. [reports][S-reports] | Exact raw rejected replies unavailable in normal reports by design; AU-06 is ordinary logging, not default report export. | PASS |
| Font settings | Bounds/reset, cache-only rerender and retention checks passed. Actual scale 1.25 candidate preserved an additional block. [font settings][S-font] | Reader correctly rejects coverage-losing replacement, so some pages retain the older scale. | PASS |
| Progress/resources | Actual job callbacks/hits during real requests; responsive protected GET; instance/version/bounds/expiry tests. [progress][S-progress] | Fast stages can complete between polls; no percentage/ETA/RSS/VRAM promise. AU-08 affects cancellation latency. | PASS |
| Setup/readiness | Real initialized/missing-dictionary API plus isolated missing-artifact/runtime cases; catalog/paths/no-download guards. [readiness][S-readiness] | AU-05/07/09/10; full clean online model/JMdict preparation not repeated. | PARTIAL |
| Optional history | Off/Save/CRUD/restart/quota/whitelist/export tests; actual Chrome Save/reopen/delete/clear in the existing fixture. [history][S-history] | AU-04; ordinary extension-version upgrade/restart was not conclusively validated through the experimental CDP reload path. | PARTIAL |
| Region inspection/Bubble Study | Actual retained lexical result opened in Chrome without another analysis request; exact result/source leases, missing/evicted data tested. [inspector][S-inspector] | AU-02; clipped/rotated presentation can map a click to the wrong source block. | PARTIAL |
| Distribution | Actual clean build/install/font/CLI/API/ZIP checks locally and merged-main CI. [builder][S-builder], [validator][S-validator] | Unsigned; external preparation; wheel-range installs and nontechnical first-run recovery need qualification. | PASS for development artifacts |

### Actual call graph and ownership

```text
Study: action/shortcut → content selection ticket → background verified screenshot
       → cropped PNG → guarded analyze-image → owning worker → reused OCR
       → TextAnalyzer.analyze (translation, then lexical/JMdict) → Study DTO → popup

Chapter: controls → session discovery → serial ChapterQueue → source/capture acquisition
         → offscreen chunk transport → guarded render-page → same owning worker
         → service → detection/grouping → crop OCR → optional ordering
         → lexical lookup + aligned native/structured translation → conservative renderer
         → PNG/snapshot bundle → exact queue result → reversible overlay

Both page paths use stage keys where supported; Study screenshot analysis has no
page-stage cache. Retained page analysis → explicit region inspector → same Study
popup. Explicit Save → background-owned Chrome local history. Worker callbacks →
bounded text-free job registry → protected status GET; readonly readiness reads a
published runtime snapshot rather than entering the inference queue.
```

The worker owns SQLite connections and neural lifetimes. The browser owns page
generations, candidate/result identities, LRU pins and Blob URLs. Retired results are
released after overlay/export/inspection ownership ends. User glossaries, history,
downloaded models and disposable processing storage have separate owners and clearing
operations. These boundaries work in the tested normal paths; AU-01 is a missing
Study-navigation identity boundary, not evidence that the entire queue design is wrong.

## 4. Findings

Effort: Low = a focused change; Medium = coordinated code plus regression/browser
coverage; High = broader validation. These are scope estimates, not calendar promises.
All ten items below are confirmed by source plus the described observation/probe.
Improvements and unverified possibilities are kept outside the defect count.

### AU-01 — P1 — Study capture/result survives SPA chapter navigation

- **Feature / source:** Study; `extension/src/content.ts:107–125,141–145`
  ([capture][S-content-capture], [verification][S-content-verify]); background capture verification uses that response.
- **Problem:** request ID, viewport and visibility are checked, but no URL/document
  generation is bound to the Study ticket. Cleanup listens for pagehide; pushState
  does not produce it.
- **Reproduction:** on the synthetic red reader, select a rectangle; pause the native
  capture boundary; pushState to chapter B and replace its pixels with blue at the
  same viewport. Release capture. Separately navigate after capture while delaying OCR.
- **Expected:** abort capture and discard a pending response when its reader/document
  generation changes. Explicitly opened history is a separate retained-sentence action.
- **Actual:** the API received blue `[20,20,220,255]` pixels selected on the red page;
  the Study result appeared after navigation. A delayed pre-navigation result also
  appeared after a second SPA replacement. Reproduced in separate owned profiles.
- **Impact:** a user can study the wrong page's crop or see stale text attached to a
  replacement chapter. This is stronger than merely retaining an already-read sentence.
- **Suggested fix:** bind a navigation/document generation to selection, both capture
  verifications and completion; cancel/close on relevant SPA navigation. Preserve
  explicit history reuse. Add deterministic before-capture and during-OCR navigation tests.
- **Effort / confidence:** Medium / High. [Runtime evidence][E-browser].

### AU-02 — P1 — Presentation guards allow incorrectly mapped region targets

- **Feature / source:** region Study/overlays; `chapter/region-geometry.ts:4–16`,
  `region-inspector.ts:81–83`, `session.ts:292`, `overlay.ts:65–68`
  ([geometry][S-region-geometry], [inspector][S-inspector], [session][S-session], [overlay][S-overlay]).
- **Problem:** checking CSS `transform` and rectangle aspect ratio does not establish
  a one-to-one proportional mapping of all source pixels to the displayed rectangle.
- **Reproduction A:** an 800×1100 image displayed at 600×825 uses independent
  `rotate:180deg`, leaving computed `transform:none`. Activate Inspect Regions.
- **Actual A:** B1's hit target stayed at `(75,75)` although its rotated source box
  starts at `(375,637.5)`; it remained clickable. The guard did not reject rotation.
- **Reproduction B / actual B:** display the same source in a 400×550 box with
  `object-fit:none`. Source B1 lies above the visible centered crop, but a clickable
  hit target still appears at `(50,50)`, size 100×75.
- **Expected:** correctly map source content, including clipping, or clearly reject
  unsupported presentation. Independent CSS transforms are separate from `transform`.
- **Impact:** a click can open another source region's Japanese/translation; ordinary
  image overlays can also disagree with the reader's presentation.
- **Suggested fix:** share a small explicit presentation contract across acquisition,
  overlay and inspection. Initially reject unsupported independent/ancestor transforms
  and non-proportional content mapping; support additional cases only with geometry tests.
- **Effort / confidence:** Medium / High for these two cases. Other transform variants
  need tests rather than an assumed pass. [Evidence][E-browser]; [CSS specification][U-css].

### AU-03 — P2 — Hidden image ancestor leaves a visible translated overlay

- **Feature / source:** discovery and overlay; `discovery.ts:35`, `overlay.ts:53–67`
  ([discovery][S-discovery], [overlay][S-overlay]).
- **Problem:** effective visibility uses the image's own opacity, not ancestor opacity.
  The fixed overlay lives outside the reader's hidden subtree.
- **Reproduction:** translate a page, then set its containing main/carousel element to
  `opacity:0` and wait for observation/painting.
- **Expected / actual:** the translation should disappear with its source. Instead,
  ancestor opacity was 0 while the overlay remained `display:block`, opacity 1 with src set.
- **Impact:** ghost pages can cover reader transitions or inactive carousel/preload content.
- **Suggested fix:** include relevant ancestor presentation/visibility in admission and
  overlay paint; share the same supported-presentation policy as AU-02 and test hide/show.
- **Effort / confidence:** Medium / High. [Evidence][E-browser].

### AU-04 — P2 — Save to History is an overflowing 30×30 action

- **Feature / source:** popup history action; `popup.ts:23–26,248` ([popup][S-popup]).
- **Problem:** the generic close-button size applies to Save; Copy buttons have an
  explicit width/height override, but Save does not.
- **Reproduction:** open an ordinary or retained Study result and inspect its Save action.
- **Expected / actual:** an understandable full-label action versus a 30×30 button
  with 28 px client height and **148 px scroll height**. Its label spills down the popup.
- **Impact:** hard-to-read/discoverable saving, poor target layout and confusing extra scrolling.
- **Suggested fix:** give normal actions their own sizing/style, reserving icon-button
  dimensions for close. Add computed-size/overflow and narrow-viewport browser assertions.
- **Effort / confidence:** Low / High. [Synthetic screenshot][E-popup], [measurements][E-browser].

### AU-05 — P2 — Failed lazy NMT loading can be reported as loaded

- **Feature / source:** readiness; `translation/nmt.py:78–93`, `service.py:136–141`
  ([NMT loader][S-nmt], [runtime snapshot][S-runtime]).
- **Problem:** NMT sets its device before loading succeeds; runtime_state infers loaded
  from diagnostic device rather than successful resource ownership.
- **Reproduction:** raise a synthetic tokenizer OSError during `NMTTranslationEngine.load()`;
  inspect the owning service's runtime snapshot.
- **Expected / actual:** failed/not loaded versus `_model is None` and `loaded:true`.
- **Impact:** readers receive misleading recovery information after corrupt/incompatible
  optional artifacts, despite a failed important initialization step.
- **Suggested fix:** publish explicit successful-load/failure observations; diagnostic
  labels must not control lifecycle. Reset partial state safely and test failure/retry.
- **Effort / confidence:** Medium / High. [Model-free evidence][E-api].

### AU-06 — P2 — Native LLM HTTP errors can disclose upstream content in default logs

- **Feature / source:** experimental native LLM failure handling;
  `translation/manga.py:166–169`, `analysis.py:186,198`
  ([HTTP boundary][S-llm-http], [page failure logging][S-analysis-logging]).
- **Problem:** the native `LlamaServer.generate()` HTTPError path embeds up to
  2,000 response-body characters in TranslationError. Page analysis logs the full
  exception, including causes, even when `record_debug=False`.
- **Reproduction:** inject a synthetic HTTP 400 whose body contains a private marker;
  run native page translation with ordinary logging and debug recording disabled.
- **Expected / actual:** a safe status/code in ordinary logs, sensitive upstream
  detail only under explicit diagnostic consent, versus the marker in the error log.
- **Impact:** a local model/proxy that echoes its request can put manga dialogue or
  prompt content into terminal/service logs that users later share. No external
  upload or direct private HTTP-response disclosure was demonstrated.
- **Suggested fix:** sanitize both the public exception and normal traceback path;
  retaining an HTTPError cause can still print its message. Preserve actionable code
  and causal structure without response content. Add caplog tests using synthetic
  source/prompt/path markers with debug disabled; separately test explicit debug limits.
- **Effort / confidence:** Medium / High for the synthetic upstream-body case. The
  structured path already uses a generic wrapper; do not generalize this finding to
  every engine or infer that an actual user's text was leaked. [Evidence][E-api].

### AU-07 — P2 — Explicit CPU selection can be rejected by stale environment configuration

- **Feature / source:** local service and page CLI setup;
  `service.py:202–208,169–171`, `page_cli.py:64`
  ([service preflight][S-service-open], [page CLI][S-page-cli]).
- **Problem:** `open_local_service(device=...)` and lazy detector setup validate raw
  `os.environ`, rather than an effective configuration incorporating the caller's device.
- **Reproduction:** use an isolated valid tiny dictionary, set
  `YOMISCAN_DEVICE=bogus`, and call `open_local_service(..., device="cpu")`.
- **Expected / actual:** the explicit CPU selection controls that invocation, versus
  `SetupUnavailable("invalid_configuration")` before any engine is constructed.
- **Impact:** documented CPU recovery can fail on page-analysis/embedded service paths
  because of a stale shell setting. The server CLI sets the effective environment first,
  so this is not a demonstrated failure of ordinary `yomiscan-server --device cpu`.
- **Suggested fix:** resolve effective settings once and pass them to both resource
  preflights and factories. Keep validation for genuinely unsupported selections;
  test explicit argument precedence, environment fallback and lazy detector construction.
- **Effort / confidence:** Low–Medium / High. [Model-free evidence][E-api].

### AU-08 — P2 — Stop still runs subsequent OCR crops before observing cancellation

- **Feature / source:** page processing; `PageAnalysisService.extract()` and
  `analyze_page()`, `page.py:102,124,179,206` ([extraction][S-page-extract]).
- **Problem:** cancellation reaches text translation, but `extract()` has no cancel
  parameter/check between detector/OCR operations.
- **Reproduction:** a fake two-region detector; first OCR call sets the page's Event.
  Analyze the page with that Event. No neural models are involved.
- **Expected / actual:** finish the already-running atomic crop and skip later work,
  versus **two OCR calls**, then a terminal cancelled outcome.
- **Impact:** Stop can leave the single owning worker occupied by the remaining page's
  OCR, delaying subsequent Study/Chapter requests. Old browser results are rejected;
  this is cancellation latency and unnecessary work, not evidence of stale publication.
- **Suggested fix:** thread the existing Event through extraction and check before
  detection, each crop and downstream stages. Preserve successful reusable cache entries
  and consistent terminal progress; do not attempt unsafe interruption of native inference.
- **Effort / confidence:** Medium / High. [Counter/progress evidence][E-api].

### AU-09 — P3 — An older readiness response overwrites a newer successful check

- **Feature / source:** `SetupControls.load()`,
  `extension/src/chapter/setup-controls.ts:29–39` ([setup controls][S-setup]).
- **Problem:** opening the section and clicking Check Setup permit concurrent loads
  without a request generation or response-order check.
- **Reproduction:** delay an initial `initializing` response by 1.2 seconds; let a
  second check return `ready` immediately; release the old response.
- **Expected / actual:** retain the newest observation versus display `initializing`
  after the backend has already reported ready.
- **Impact:** confusing setup/recovery advice; another Check Setup recovers.
- **Suggested fix:** accept only the latest request generation, matching existing
  settings/progress patterns. An older success or failure must not overwrite newer state.
- **Effort / confidence:** Low / High. [Chrome observation][E-browser].

### AU-10 — P3 — Current translation instructions still promise first-use downloads

- **Feature / source:** current README translation section and Marian load failure;
  `README.md:447`, `translation/marian.py:44,62`
  ([README][S-readme-translation], [loader][S-marian]).
- **Problem:** the current guide says the first translation invocation downloads the
  model; the loader always requests `local_files_only=True`, and its recovery message
  still says first use requires internet.
- **Reproduction / actual:** compare the current command instructions/error with the
  pinned explicit preparation process. An uncached invocation cannot do that download.
- **Expected:** the current section and error direct users to the actual preparation
  command and distinguish dependency installation from model preparation.
- **Impact:** avoidable setup loops for new users and misleading offline expectations.
  Historical Phase reports should remain historical, not be rewritten to hide the change.
- **Suggested fix:** reconcile this current README paragraph and loader error with
  `docs/installation.md`; add a model-free check that the missing-artifact guidance
  names a real installed CLI. Do not add implicit downloads as the fix.
- **Effort / confidence:** Low / High, static implementation/documentation mismatch.

## 5. Security and privacy findings

### Local API and extension trust boundaries

The loopback server uses trusted host validation and explicit origin/client-header
checks, including private reads, administrative operations and bounded job status.
The header identifies the application protocol; it is **not a secret authentication
credential against another local process**. Default extension-origin acceptance can
be narrowed using the documented extension allowlist. Do not describe localhost as
safe from every extension or local program. [Middleware][S-security], [API][S-api].

Fresh model-free negative requests produced the expected outcomes:

| Boundary | Observed outcome |
| --- | --- |
| Host/rebinding-shaped value | 400 |
| Unrelated website or opaque `null` origin | 403 |
| Private read/write without required client header | 403 |
| Other extension with explicit allowlist configured | 403; allowed extension 200 |
| Oversized administrative request | 413 |
| Unknown cache field, coercible boolean, out-of-range font, malformed job ID/target | 422 |
| Invalid image / 16 MP decoded image | 400 |
| 11 MiB upload | 413 |

The complete observations, including expected status, are in [API evidence][E-api].
Existing tests also cover multipart/image checks, busy-worker rejection, job identity,
bounded registry lifecycle and cancellation. They do not constitute a destructive
penetration test, authentication audit of the operating system, or vulnerability-advisory
scan of every Python wheel.

The Chrome worker validates extension message shapes and tab/document ownership.
Acquisition resolves a nonce to the currently owned image rather than accepting an
arbitrary URL from website JavaScript. Source fetching uses Chrome's optional granted
hosts and rejects redirects; cookies remain subject to browser policy. Content text is
assigned as text nodes/textContent within the UI, not interpreted as translated HTML.
The shadow root prevents casual styling interference; it is not an origin/security
boundary from a fully compromised extension. [Worker][S-background], [source fetch][S-source-fetch],
[popup][S-popup]. No exploitable website-text injection was demonstrated in this review.

AU-01 is a real tab-content identity gap: the capture remains in the same tab but can
come from a different SPA page. Fix that lifecycle without weakening the existing
capture permissions or replacing precise verification with a permissive fallback.

### Content retention and logs

The [diagnostic ADR][D-privacy] is reflected in code: no automatic report upload,
metadata-only export by default, explicit text/original/translated-image consent,
bounded snapshots, fixed safe ZIP paths and source/result rechecks. Default reports
avoid raw exceptions, browsing URLs and personal paths. Image attachments are re-encoded;
text remains private even after pattern redaction. User-requested downloads remain on
disk and are not silently removed. A report with images/text is not automatically
safe to publish merely because it is called diagnostic. [Exports][S-reports].

Persistent processing cache is opt-in and can contain reversible derived page/text
data; it is not encryption or secure deletion. Cache clearing uses code-owned stores,
not arbitrary filesystem traversal. Database quota/eviction, corruption handling,
checksums and cache/user-data ownership are covered by tests. The fresh clear-cache
probe retained its synthetic glossary entry. Chrome history is off by default and saves
only explicit selected Study data, not page screenshots/URLs. Clear History, glossary
edits, processing clear and model preparation remain independent. [Cache ADR][D-cache],
[cache][S-cache], [history][S-history], [glossary][S-glossary].

**Confirmed privacy defect: AU-06.** Native optional-model errors can put upstream
content in ordinary logs. Correct the exception/log boundary before asking testers
to share server logs. No actual private transcript is committed as proof; the probe
used an invented marker. Other exceptions that interpolate third-party messages
deserve the same marker-based regression scan, but are not additional proven disclosures.

No cloud OCR, paid inference API or telemetry path was identified in the inspected
production flow. Model/dictionary preparation is an explicit network step; runtime
offline validation forced Hugging Face offline and succeeded with prepared resources.
This does not prevent the browser from loading its original manga website/CDN.

### Licensing and redistribution boundaries

The MIT application license does not cover JMdict, model weights, fonts or dependency
binaries. The actual wheel/sdist/extension ZIP checks found application resources and
font/OFL notices without manga pages, processing caches, dictionaries or model tensors.
No Yomu AGPL implementation was vendored; independent Python/TypeScript designs remain
separate. [Notices][D-notices], [build rules][S-builder], [package rules][S-pyproject].

| Component | Relevant boundary / audit result |
| --- | --- |
| Noto font | OFL notice packaged with the font and verified in installed wheel/sdist. Retain notices when redistributing the font; rendered page images are not thereby licensed OFL. [Official OFL][U-ofl]. |
| JMdict SQLite / exported senses | Derived dictionary data remains subject to EDRDG/CC BY-SA terms; read-only local DB was not bundled. Existing app/docs attribute the source. A standalone shared Study-history JSON deserves a provenance/license envelope; its absence is a redistribution improvement, not a demonstrated legal violation of private local use. [EDRDG][U-edrdg]. |
| OPUS / default detector | Publisher cards declare Apache-2.0; preserve artifact provenance and applicable license/NOTICE material if later shipping weights. Current artifacts ship neither weight set. [OPUS card][U-opus], [detector card][U-detector]. |
| Optional FuguMT | Publisher card declares CC BY-SA 4.0; it is not MIT. Exact pinned README could not be independently fetched in this audit, so current-card verification is narrower than a complete pinned-artifact legal audit. [Fugu card][U-fugu]. |
| Optional NLLB | Pinned model card declares CC BY-NC 4.0. Keep noncommercial warning and experimental opt-in; no commercial-compatible default claim. [Pinned card][U-nllb]. |
| Optional ONNX / llama.cpp | Separately licensed runtimes and artifacts; preserve source/export revision and dependency notices. No optional runtime installation or new weight redistribution occurred here. [Existing provenance][D-stage2-provenance], [translation sources][D-translation-benchmark]. |

The exact pinned OPUS/detector card bodies were not retrievable through the web reader
in this audit; their existing repository provenance and accessible current cards support
the stated publisher declarations, not an absolute legal guarantee. Dependency wheels
carry their own notices; the build is not a standalone installer that has re-audited
every transitive binary license. Recheck those obligations with specialist review before
bundling models/derived dictionaries or publishing a self-contained installer. No license
change is proposed by this audit.

## 6. Performance measurements

### Method and measurement validity

Actual CPU production engines, both authorized local pages and the existing dictionary
were used with forced offline model resolution. The harness owned its Uvicorn subprocess,
isolated synthetic glossary and processing directory; it did not edit user databases.
Client wall time was measured around the real HTTP request in its request thread.
Protected job status was polled at 800 ms separately, matching the extension interval.
Stage times came from the same result's diagnostics. Published [JSON][E-measurements]
contains aliases/hashes and numeric/model metadata, without page pixels or transcripts.

Fresh process does not mean cold OS file cache. An initial fresh-process trial took
**26,602.87 ms** to readiness; a corrected measurement run took **10,693.72 ms**, and
its restart **9,750.75 ms**. Imports, OS caching and other machine activity varied.
The initial trial sampled the Windows launcher PID, producing invalid memory numbers;
those numbers were discarded. The corrected run sampled the Uvicorn application PID
using Windows process APIs. This correction is measurement hygiene, not an application bug.

### Actual requests

| Operation | HTTP/client wall ms | Relevant backend timing ms | What actually happened |
| --- | ---: | --- | --- |
| Fresh server, corrected run | 10,693.72 to ready | First readiness response at 884.99 | Explicit setup check responsive while models initialize; not fully cold disk. |
| First screenshot Study | 539.62 | Total 513.90; OCR 273.06; translation 226.74; lexical 3.29 | Six tokens/readings/dictionary matches and English output. |
| Repeated same Study crop | 551.49 | OCR 284.62; translation 238.54; lexical 2.75 | Real inference again; this endpoint does not use page-stage cache. |
| First page A | 8,134.51 | Pipeline 7,979.90; detection 750.53; OCR 3,360.89; translation 2,036.68; render 522.45 | 9 rendered / 4 preserved; first detector/page-specific initialization included elsewhere in pipeline wall. |
| Exact repeat A | 295.36 | Pipeline 160.16; before packing 179.96; inference stages 0 | Detection/OCR/lexical/translation/render restored. |
| New page B | 2,041.48 | Pipeline 1,952.05; detection 814.81; OCR 523.68; translation 279.84; render 128.21 | 1 rendered / 1 preserved; fewer recognized regions, not equal-work throughput. |
| Translation-only refresh A | 2,862.70 | Pipeline 2,723.13; translation 2,005.29; render 463.82 | Detector/OCR/lexical reused; translation and dependent render recomputed. |
| Font-only 1.25 rerender A | 844.77 | Pipeline 697.03; render 438.79; upstream inference 0 | Candidate 8 rendered / 5 preserved. Browser retention guard must keep prior 9/4 result; guard separately passed in Chrome fixture. |
| Restarted server | 9,750.75 to ready | First readiness response at 814.52 | Different backend/browser configuration generation observed. |
| A restored from disk after restart | 1,144.70 | Pipeline 1,002.32; before packing 1,036.27; inference stages 0 | Real cross-process stage hits, same 9/4 coverage. Lazy component initialization/identity checks still cost time. |

Do not sum every diagnostic interval: some intervals contain other stages and some
initialization/serialization work sits outside the named compute counters. Exact-repeat
wall time is not “zero because cache hit.” Its approximately 115.4 ms after the
before-packing observation combines bundle packing, response serialization, loopback
transport and client work; it is not an isolated network-latency estimate.

The real Chrome composition took **1,302 ms** from chapter action to overlay, using
the already prepared page cache. Bubble Study reused five tokens with no new image
analysis. Native screenshot Study then made one actual request and displayed six tokens.
This verifies actual browser/backend composition, not fresh-page translation latency.
[Browser evidence][E-browser].

### Resources, responsiveness and browser retention

- Corrected process working set: **1,173,671,936 bytes** at readiness (~1,119 MiB),
  **1,470,320,640 bytes** after the first page (~1,402 MiB). Observed lifetime peak
  working set reached **1,571,590,144 bytes** (~1,499 MiB). These are process figures
  on this machine, not minimum-RAM specifications or total system/browser consumption.
- First-page CPU time increased by **67.765625 CPU-seconds** during 8.13451 wall
  seconds. Multithreading explains CPU time exceeding wall time; it is not a fabricated
  system CPU percentage. No reliable VRAM measurement was taken; inference selected CPU.
- Eleven first-page status samples had **2.05 ms median**, **38.93 ms maximum** latency.
  No polling-induced inference blocking was apparent in this small run.
- The 24-page mocked queue processed **192 MiB cumulatively in 24.961 seconds**,
  retained **128 MiB** under its result-budget policy and returned to zero retained
  result bytes on Clear. This verifies accounting/ownership and eviction; it does not
  measure total Chrome RSS, long-term leak freedom or neural page throughput.

### Measured priorities and limits

Page A's OCR and translation dominate measured steady work; page rendering is smaller
but measurable. Startup remains a seconds-scale cost because the production service
loads OCR/OPUS even if a later request could restore a page. The cache already avoids
the expensive repeated stages; a new cache rewrite or model replacement is unsupported.
First fix AU-08's avoidable post-cancel crop work. If startup/cache-hit latency becomes
a user complaint, profile component load, verified identity, decode/hash and packing
separately before altering ownership or trusting weaker identities.

These are single exploratory observations, not repeated distributions or a model
ranking. CPU affinity/frequency, background load, OS caches and library thread defaults
were not controlled. Page A/B have different region counts. Do not derive a general
percentage speedup, compare directly with earlier four-thread matrices, or assert
new OCR/translation accuracy from these times. No new model collection, training run,
GPU benchmark or full Stage 2/4 benchmark was executed.

## 7. Architecture assessment

### The existing boundaries remain useful

The owning backend worker serializes neural work and SQLite access. Protected readiness
and bounded job snapshots observe that owner without joining its inference queue. The
browser owns scheduling, page generations and reversible overlays, while the backend
owns recognition/analysis/rendering. This fits a local Chrome reader and avoids giving
Python website credentials or arbitrary source URLs. [Application lifecycle][S-api],
[service][S-service-open], [chapter session][S-session].

Stage cache keys represent actual content and dependencies: canonical pixels; detector
and OCR artifacts/configuration; per-crop identity; dictionary state; exact ordered
source IDs; engine/target/glossary/context/prompt settings; and renderer/font identity.
Checksums, schema validation and exact source cardinality guard restored payloads.
Selective refreshes in section 6 exercised the final Stage 4/5 integration rather than
assuming old cache reports still applied. Keep the DAG and bounded ownership; do not
merge the disposable cache into user terminology/history. [Identity][S-identity],
[analysis][S-analysis], [render service][S-render-service].

The renderer commits an edit only after a safe mask, fitting layout, inpainting and
draw succeed. Uncertain narration/artwork/SFX and unsafe masks remain preserved with
reasons, rather than becoming blank “successful” output. On the inspected first page,
safe English layouts stayed inside the intended bubbles; some original ink remnants
and semantic translation mistakes remained. No erase-without-English failure was
observed on that page. This small visual check does not certify every page.
[Renderer][S-renderer], [mask construction][S-masks].

### Small contracts worth improving

| Observed seam | Concrete cost | Narrow follow-up |
| --- | --- | --- |
| Geometry support checked differently by discovery, acquisition, overlay and inspector | AU-02/03: source-to-display mapping/visibility can disagree | One typed presentation observation with explicit supported/reason state; shared fixtures for real CSS presentation. |
| Load behavior inferred from `diagnostics()["device"]` and class-level `getattr(...,"load")` | AU-05: a display label can misrepresent failure and determine loading notifications | Explicit successful-resource state and a small optional lifecycle operation; retain eager production vs lazy experimental behavior until separately justified. |
| Service/preflight read environment independently of caller arguments | AU-07: recovery settings disagree | Resolve effective settings at composition, pass the same immutable values to preflight/factories. |
| Rendering service imports `ImageAnalysisResponse` from API models | Core-to-transport coupling makes adding a serializer/model change affect core integration | Move the shared analysis contract/serializer to a transport-neutral module only when changing that seam; no broad DTO rewrite. |
| Extraction does not accept the existing cancel Event | AU-08: bounded job control stops at an integration seam | Extend the existing per-page contract and check between atomic operations. |

Evidence: [geometry][S-region-geometry], [readiness runtime][S-runtime],
[analyzer lifecycle][S-analysis-load], [render service][S-render-service]. These are
correctness/testability-driven changes, not requests to introduce a framework, event
bus, plugin system or asynchronous rewrite. Private-field access between service and
analyzer should shrink when working on the affected boundary; extracting every field
behind a one-line accessor would add ceremony without resolving ownership.

Structured translation has exact ID/cardinality/type limits, source alignment and
bounded context. It can reject malformed/partial generations and avoid attaching
extra IDs. It cannot detect a wrong name, negation, speaker or plausible invented
dialogue inside a permitted string. Panel grouping is geometric, not narrative
understanding, and no cross-page speaker memory is established. Existing
[Stage 4 results][D-stage4] include failed context contrasts and capped Qwen outputs;
those limitations remain, and this audit supplies no semantic winner.

## 8. UX assessment

The ordinary task sequence is usable: start a prepared backend, activate Study and
select a bubble, or translate discovered images and switch Original/English. Stage 5's
inspect-preserved-region and Bubble Study actions are valuable: the actual browser
smoke reached retained lexical results without another OCR request. Explicit refresh,
retaining old output after a failed refresh, and showing preservation reasons provide
useful recovery rather than requiring a full chapter restart.

The largest sources of friction are specific:

1. **Trust in the selected content.** AU-01/02 can show text from the wrong page or
   source box. Fix before promoting additional history/context features.
2. **History Save layout.** AU-04 is visible in the [synthetic screenshot][E-popup].
   Give labeled actions ordinary dimensions; keep the close action compact.
3. **Too much configuration in one panel.** With sections opened at a 1100×900 test
   viewport, the panel had 263 px client width, 718 px client height and 3,046 px scroll
   height, with 28 buttons and eight selects. This measurement is not a claim that all
   controls are always visible. Keep Translate/Stop/Original/Retry prominent; leave
   cache, diagnostics, optional models and advanced translation collapsed. Clarify
   current page vs whole-session actions. Test task completion before redesigning.
4. **Setup advice and terminology.** Pinned preparation is more reliable than implicit
   downloads, but AU-05/07/09/10 undermine recovery. “Installed,” “loaded,” “compatible”
   and “verified” have different meanings; the UI should keep those distinctions and
   surface the selected component's next action before listing every optional model.
   Plain local file paths in explanatory text are not clickable help in a packaged UI.
5. **Accessibility.** Ordinary buttons/inputs are keyboard reachable, but popup move/
   resize is pointer-driven and the close action's visible “×” is not a descriptive
   accessible name. Add an explicit close label, initial focus/focus restoration and
   keyboard alternatives when working on popup layout. Check font scaling, narrow
   viewports and screen-reader order manually. No full WCAG or physical HiDPI audit
   was performed; emulated DPR/zoom checks are narrower evidence.

Target labels correctly distinguish sentence target from English JMdict definitions.
Keep PT-BR/Spanish and structured/context models visibly experimental. A translated
language label is not proof of native Brazilian register or reliable negation.
Do not bury preservation warnings to create an appearance of complete coverage.

History is intentionally opt-in and explicit-save. Disabled means stop new saves,
not silently erase existing notes. Retaining a sentence explicitly reopened from
history is useful; it must not be confused with AU-01's stale in-flight capture/result.
Before broad testing, validate a normal stable-folder extension update and a browser
restart with saved synthetic notes. The audit's experimental CDP reload test was
inconclusive and is not evidence that ordinary updates lose data.

## 9. Test coverage gaps

### What the tests actually establish

The suites do more than count calls: tests verify exact source/ID alignment, conservative
render rollback, malformed cache rejection and stage invalidation, ownership/eviction,
job isolation, missing setup resources and private API boundaries. The Chrome fixture
exercises native extension activation, acquisition fallbacks, scrolling, permissions,
clipboard user gestures, stale profiles, session retirement and retention. Fresh package
validation installs real artifacts outside the source import path and activates the
actual ZIP. Those are useful behavior checks. [Python tests][S-python-tests],
[extension tests][S-extension-tests], [browser fixture][S-browser-test], [CI][S-ci].

Normal CI deliberately uses empty offline model storage and does not prove detector
recall, OCR quality, translation meaning or GPU compatibility. Injected snapshots can
exercise the inspector while still missing how real CSS maps pixels; AU-02 passed
through that gap. Synthetic happy-path statuses do not prove failure-state lifecycle;
AU-05 and AU-09 passed through those gaps. Keep model-free CI, but add behavior regressions
at the seam where each failure was actually observed.

### Risk-ranked missing validation

| Order | Gap / scenario | Required evidence before claiming resolution |
| --- | --- | --- |
| 1 | Study SPA change before native capture and during pending OCR | Real isolated Chrome fixture changes URL and pixels independently; assert no new-page crop submission and no old result popup. Include same-URL reader-content replacement policy explicitly. |
| 2 | Independent rotate/scale/translate, ancestor transforms, object-fit/object-position clipping and visibility | Known source boxes on synthetic images; verify exact mapped targets or explicit rejection, plus overlay hide/show after ancestor opacity changes. Browser zoom/scroll must retain those invariants. |
| 3 | Private upstream text in exceptions/logs | Model-free HTTPError/URLError fixtures with unique private markers; assert ordinary log/response/export absence and bounded opt-in detail. |
| 4 | Failed optional load and argument/env precedence | Inject tokenizer/model failure and retry; readiness reflects actual resource state. Cover direct service/page CLI and server argument paths separately. |
| 5 | Cancellation after detection and each crop/stage | Counter fake proves no subsequent crop starts; terminal job state and old-result rejection remain correct; cached completed stages survive. |
| 6 | Popup action sizing and stale setup replies | Computed button bounds/overflow, latest-response wins for both success/failure; narrow viewport and keyboard smoke. |
| 7 | Stable-folder upgrade, normal browser restart, rollback | Seed synthetic glossary/history, install matching newer artifacts without changing identity, restart and reopen; processing clear never removes those data. No ordinary upgrade completion claim from experimental CDP reload. |
| 8 | Plain wheel dependency resolution | Test documented standalone wheel commands against resolved dependency ranges in a fresh environment; record resolved versions alongside a locked reproduction. Current install smoke used locked cached dependencies. |
| 9 | Broader reader compatibility / contention | Authorized ordinary lazy-reader sites, source changes, unsupported layouts and two active tabs; record explicit failures rather than teaching adapters to guess. Current coverage is primarily controlled fixtures. |
| 10 | Quality and long-term resources | Repeated small fixed authorized corpus, annotated misses/merged regions, bilingual meaning/speaker review, extended total-process memory observations. Current timings/retained-byte counts are not these claims. |

Missing OCR/translator/detector/runtime scenarios in this audit used isolated preflight
files or injected availability, avoiding large downloads/deleting prepared weights.
Missing-dictionary startup was also tested through an actual installed protected API.
The complete first-ever online download/import and fresh optional-model inference were
not repeated. Backend-unavailable/restarted UI states have unit/browser fixture coverage
and the real restart measurement; an existing live external reader left open across a
real server restart remains a useful explicit tester scenario.

One standards audit subagent stopped at its usage limit after returning three useful
model-free probes; all three were independently rerun and source-checked for this report.
Its partial work is not represented as a completed second full independent audit.
The source review, complete test runs and targeted reproductions reported here remain
valid observations regardless of that limit.

## 10. Release readiness

| Audience | Decision | Evidence and conditions |
| --- | --- | --- |
| Developer source usage | **GO** | Locked Python/Node workflows, offline prepared defaults, functioning Study/Chapter and clean package tooling. Know supported geometry, semantic limits and AU-01/02. |
| Small external tester cohort | **CONDITIONAL GO** | Actual installable artifacts and normal workflows pass. Provide matching commit-stamped backend/extension, explicit setup commands and known-issue list. Prefer fixing AU-01/02/06 before expanding the cohort; keep experiments opt-in and avoid sharing raw logs/pages. |
| First public release | **NO-GO** | Fix high-severity identity/presentation errors, default private logging and broken recovery/Save behavior; qualify update/data retention and standalone dependency resolution; finish first-run/accessibility checks. Passing CI is necessary but insufficient. |

The actual merged-baseline build had `dirty_source:false` and commit provenance. Its
unsigned artifacts were installed and checked locally; merged-main hosted Linux CI
also built/installed/activated them. The following hashes identify this audit's build,
not a promise that another OS's ZIP or another build must have identical bytes:

| Artifact | Bytes | SHA-256 |
| --- | ---: | --- |
| `yomiscan-0.1.0-py3-none-any.whl` | 1,358,054 | `8d6586c5afb9c97007f549757bfab7052ebdd1d870662593c4d50f0925f13e2d` |
| `yomiscan-0.1.0.tar.gz` | 1,548,116 | `86c91073680c4233956c05ca7d2864e3fb5273c71296595603ea4e4bd7754895` |
| `yomiscan-extension-0.1.0-178e506f8bc0.zip` | 60,710 | `dce3827aefeef78c9f71f3dee54b168aff1babfeb88c9d77360d78c0b9897c77` |

The fresh package environment installed 59 locked runtime packages from local caches
and then the wheel/sdist separately. Version/import/resource checks, the six installed
CLI helps, bundled font/OFL, protected missing-resource API and actual MV3 ZIP worker/
controls passed. This checks artifacts rather than source-only imports. The distribution
manifest carries tools/lock provenance, unsigned status and external setup requirements.
[Builder][S-builder], [Python validator][S-validator], [Chrome ZIP validator][S-zip-validator].

The pure Python wheel still needs platform-specific dependency wheels; it is not a
self-contained signed installer. Documented wheel installation can resolve dependency
ranges rather than reproduce `uv.lock`, so it needs its own compatibility qualification.
Prepared models and JMdict are external setup, and optional extras remain external.
Windows was executed locally; Linux support is the newly inspected hosted CI result.
No macOS, CUDA, store submission, release tag, package publication or signed update was
tested or performed. Same-version `0.1.0` development updates need the documented
reinstall and matching commit-stamped extension; that is explained, not automatically
solved by a version string. [Installation/update instructions][D-installation].

## 11. Recommended fixes

### Confirmed defects, in recommended order

| Priority | Issue | User impact | Suggested solution | Effort | Dependencies |
| --- | --- | --- | --- | --- | --- |
| 1 / P1 | AU-01: Study navigation ownership | Wrong/stale crop or result after reader changes | Bind capture/completion to document/page generation; retire on relevant SPA changes | Medium | Controlled Chrome navigation regression |
| 2 / P1 | AU-02: presentation mapping | Wrong block opens; overlay can disagree with source | Shared supported-presentation observation; fail closed on unsupported clipping/independent transforms | Medium | Synthetic geometry fixtures; shared with AU-03 |
| 3 / P2 | AU-06: private upstream error logging | Sensitive dialogue/prompt may enter shared logs | Safe exception/log boundary with marker tests | Medium | No model downloads required |
| 4 / P2 | AU-03: hidden ancestor overlay | Translation remains over invisible source | Effective visibility observation and coordinated repaint/cleanup | Medium | Same presentation tests as AU-02 |
| 5 / P2 | AU-04: overflowing Save button | Broken visible history action | Separate normal-action and close-button styling; browser sizing/keyboard check | Low | Existing popup fixture |
| 6 / P2 | AU-05: false loaded state | Misleading recovery after optional load failure | Explicit successful-resource state; reset partial failure safely | Medium | Synthetic loader failure/retry |
| 7 / P2 | AU-07: device precedence | Explicit CPU recovery rejected | Compose effective configuration once | Low–Medium | Direct service/page CLI plus server tests |
| 8 / P2 | AU-08: cancellation between crops | Wasted remaining OCR delays next request | Check existing cancel Event between atomic stages/crops | Medium | Fake counter and job terminal-state checks |
| 9 / P3 | AU-10: setup download claims | First-run instructions contradict offline-only loader | Correct current README/error with explicit preparation CLI | Low | Check packaged CLI help/guidance |
| 10 / P3 | AU-09: readiness race | Older initializing/failure state replaces ready | Latest-request generation acceptance | Low | Delayed-response Chrome test |

Severity and sequencing differ slightly: the privacy boundary is cheap to validate and
should be repaired alongside the P1 work; related presentation fixes belong together.
Low-effort Save/documentation fixes can land in parallel without delaying identity work.
None of these corrections requires changing model defaults, cache format or runtime.

### Improvements / qualification work, not additional confirmed defects

| Priority | Issue | User impact | Suggested solution | Effort | Dependencies |
| --- | --- | --- | --- | --- | --- |
| Before wider testing | Upgrade/dependency qualification | Confidence that installation and notes survive normal updates | Stable-folder upgrade/browser restart with synthetic data; standalone wheel resolution smoke | Medium | Two matching development builds; isolated environment/profile |
| Before public release | First-run and accessibility qualification | Readers can recover and operate core actions | Task-based new-user walkthrough, keyboard/labels/narrow viewport checks | Medium | Recovery/Save fixes |
| Next UX pass | Chapter control hierarchy | Less scrolling and technical clutter | Keep frequent controls prominent, advanced groups collapsed; measure completion | Low–Medium | Existing state/controls, no redesign |
| When touching the seam | Lifecycle/serializer coupling | More reliable failure tests and fewer cross-layer edits | Small explicit lifecycle state; transport-neutral analysis serialization | Medium | Concrete AU-05 work, unchanged DTO compatibility |
| Before sharing history data publicly | Attribution/provenance envelope | Clear meaning/source/terms for exported dictionary senses | Include dictionary attribution and schema/provenance; specialist review of redistribution | Low–Medium | Existing export whitelist and notices |
| Only after a measured complaint | Startup/cache-hit work | Lower wait for a cached page | Profile model initialization, identity/restore, encoding/packing before selective optimization | Medium–High | Repeated timings on representative hardware |
| Ongoing evidence | Semantic/reader/resource coverage | Honest compatibility/quality claims | Small authorized fixed corpus, bilingual checks, multi-tab and longer retention runs | Medium | Consent and independent review; no default model change |

## 12. Recommended development order

Use a dedicated stabilization effort. The groups below describe coherent fixes and
acceptance criteria; they are not arbitrary new feature versions.

### Reader identity and presentation

**Objective:** every accepted crop, popup, overlay and region target belongs to the
same still-valid visible source. Include AU-01/02/03. They belong together because
navigation identity and presentation mapping are both prerequisites for trusting any
otherwise correct OCR/translation result. Complexity Medium; no model change needed.

Acceptance: deterministic Chrome tests reject both pre-capture and pending-result SPA
replacements; source replacement still retires old chapter results; independent rotate
and centered clipped content are accurately mapped or explicitly disabled; ancestor
hide/show cannot leave a ghost overlay. Existing acquisition/zoom/scroll/switching,
inspection reuse and 37-check fixture must remain green. Keep these changes small and
review capture permission behavior explicitly.

### Failure privacy, setup recovery and responsive Stop

**Objective:** private errors stay private and failed initialization has an honest,
actionable recovery state. Include AU-05/06/07/08/09/10. Complexity Medium; can proceed
alongside browser work using injected engines and synthetic markers.

Acceptance: private markers absent from ordinary logs/responses/default exports;
failed load never reports loaded, retry can succeed; explicit CPU reaches both preflight
and factories; an older readiness reply cannot overwrite newer success/failure; current
guide/error names real preparation commands; after cancel during crop 1, crop 2 never
starts and completed cache stages remain usable. Do not promise interruption of an
already-running native inference call.

### Popup polish and release qualification

**Objective:** informed testers can install, complete the core tasks and update without
losing explicitly saved notes. Include AU-04, small accessibility/control hierarchy
work, actual stable-folder upgrade/restart and standalone wheel qualification.
Complexity Medium, following the identity/recovery fixes; no history schema expansion
or general UI redesign is needed.

Acceptance: Save label fits its computed button at supported widths; keyboard users
can reach/dismiss core actions with focus restored; a new tester completes prepare →
Study → Chapter → inspect → Save/reopen without source edits; updating matching
artifacts retains a seeded glossary/history; clearing processing leaves both intact.
Locked and standalone install paths record their dependency versions and pass package
resource/CLI/API checks on Windows and Linux CI. Repeat a small real offline defaults
smoke separately from model-free CI.

### Reassess measured bottlenecks after correctness

**Objective:** make only evidence-backed performance/quality commitments. Complexity
depends on the profile and is not yet a selected refactor. Use repeated startup/warm/
cache timings and wider authorized content; inspect semantic errors with qualified
reviewers. Accept a performance change only if its selected interval improves without
weakening exact cache identities, retained-result safety or resource bounds. A larger
model, automatic page context or a new detector is not an automatic next increment.

Do not merge this audit PR as authorization to implement these fixes. Each follow-up
should describe its selected findings, tests and remaining risks on its own feature/
fix branch. This audit branch contains documentation and sanitized evidence only.

## 13. What NOT to change

| Existing decision | Verdict and reason |
| --- | --- |
| Chrome MV3 + local FastAPI | Preserve. Actual browser/backend/package composition works. Android/Kotlin migration or replacing FastAPI would not repair the observed seams. |
| Single owning inference worker | Preserve. It gives bounded jobs/SQLite/model ownership; improve cancellation checks instead of unsafe parallel model access. |
| English OPUS default | Preserve. It is functional and affordable with known semantic limits. Stage 4 and this spot review establish no superior replacement; structured formatting is not meaning accuracy. |
| Original manga-ocr + current PyTorch detector .50/.50 | Preserve. Real current-path smoke works. Optional alternatives have past tradeoffs and no new paired accuracy evidence here. |
| Stage-aware cache and exact dependencies | Preserve. Real selective refresh and cross-process restore work. Do not weaken artifact, glossary, target, dictionary or font identity for faster hits. |
| Conservative renderer | Preserve. Losing some coverage is preferable to committing an unsafe edit. Keep prior successful output when a font refresh loses rendered coverage. |
| Experimental adapters/targets/context separation | Preserve. Strict IDs, bounds and opt-in experiments are useful; do not promote Hy/Qwen/NLLB/PT-BR/context to a quality guarantee. |
| Processing cache vs glossary/history/model ownership | Preserve. Clear actions remain independent and were tested. Do not combine user notes with evictable intermediates. |
| Explicit pinned preparation and offline runtime | Preserve. Fix misleading current instructions and recovery state; do not restore surprise first-use model downloads. |
| Consent-based local diagnostics/history | Preserve. Metadata-only defaults and explicit saves are appropriate. Fix logging separately; do not auto-attach copyrighted pages or private text to issues. |
| Model-free CI plus separate real inference | Preserve. Broaden behavior regression fixtures and small opt-in smoke evidence, not automatic heavyweight downloads in ordinary tests. |

Do not make a cache rewrite, general service framework, model manager, new learning
system, automatic OCR correction, cross-page character memory or architectural migration
part of this stabilization effort. No new audit evidence makes those necessary to fix
the confirmed defects. Preserve historical benchmark reports and their negative results.

## 14. Final verdict

**If feature development stopped today, YomiScan would still need a focused stabilization
pass around content identity, browser presentation, private failure handling and honest
setup/recovery, followed by update/install and usability qualification.**

The core is already useful: actual offline OCR/morphology/JMdict/translation/rendering
and Chrome flows work, selective caching saves inference, and the artifacts can be
installed. The two P1 failures can attach otherwise valid analysis to the wrong visible
content, so those are the first correctness fixes. Repair the log boundary and small
Save/readiness/configuration/cancellation defects while retaining the working architecture.

Begin with a small informed tester cohort under explicit limitations, preferably after
AU-01/02/06. Use that cohort to validate first-run recovery and stable-folder upgrades.
Do not call this public-release ready until those gates pass. Performance profiling and
incremental UI simplification can follow; another feature/model stage or a rewrite would
not resolve the concrete reliability gaps found here.

Reproduction commands, safe fixture construction and evidence interpretation are in
[the accompanying audit notes][D-reproduction]. All proposed fixes remain unimplemented.

[S-content]: https://github.com/GabrielTeixeira88/yomiscan/blob/178e506f8bc03ef541f4c4f8d60ecb44476f023a/extension/src/content.ts#L16
[S-content-capture]: https://github.com/GabrielTeixeira88/yomiscan/blob/178e506f8bc03ef541f4c4f8d60ecb44476f023a/extension/src/content.ts#L107
[S-content-verify]: https://github.com/GabrielTeixeira88/yomiscan/blob/178e506f8bc03ef541f4c4f8d60ecb44476f023a/extension/src/content.ts#L141
[S-background]: https://github.com/GabrielTeixeira88/yomiscan/blob/178e506f8bc03ef541f4c4f8d60ecb44476f023a/extension/src/background.ts#L65
[S-analysis]: https://github.com/GabrielTeixeira88/yomiscan/blob/178e506f8bc03ef541f4c4f8d60ecb44476f023a/backend/yomiscan/analysis.py#L61
[S-analysis-load]: https://github.com/GabrielTeixeira88/yomiscan/blob/178e506f8bc03ef541f4c4f8d60ecb44476f023a/backend/yomiscan/analysis.py#L155
[S-analysis-logging]: https://github.com/GabrielTeixeira88/yomiscan/blob/178e506f8bc03ef541f4c4f8d60ecb44476f023a/backend/yomiscan/analysis.py#L186
[S-dictionary]: https://github.com/GabrielTeixeira88/yomiscan/blob/178e506f8bc03ef541f4c4f8d60ecb44476f023a/backend/yomiscan/dictionary/sqlite.py#L26
[S-popup]: https://github.com/GabrielTeixeira88/yomiscan/blob/178e506f8bc03ef541f4c4f8d60ecb44476f023a/extension/src/popup.ts#L23
[S-session]: https://github.com/GabrielTeixeira88/yomiscan/blob/178e506f8bc03ef541f4c4f8d60ecb44476f023a/extension/src/chapter/session.ts#L292
[S-acquisition]: https://github.com/GabrielTeixeira88/yomiscan/blob/178e506f8bc03ef541f4c4f8d60ecb44476f023a/extension/src/chapter/acquisition.ts#L1
[S-queue]: https://github.com/GabrielTeixeira88/yomiscan/blob/178e506f8bc03ef541f4c4f8d60ecb44476f023a/extension/src/chapter/model.ts#L1
[S-detector]: https://github.com/GabrielTeixeira88/yomiscan/blob/178e506f8bc03ef541f4c4f8d60ecb44476f023a/backend/yomiscan/detection/rtdetr.py#L1
[S-ocr]: https://github.com/GabrielTeixeira88/yomiscan/blob/178e506f8bc03ef541f4c4f8d60ecb44476f023a/backend/yomiscan/ocr/manga_ocr.py#L10
[S-vision]: https://github.com/GabrielTeixeira88/yomiscan/blob/178e506f8bc03ef541f4c4f8d60ecb44476f023a/backend/yomiscan/vision_models.py#L18
[S-marian]: https://github.com/GabrielTeixeira88/yomiscan/blob/178e506f8bc03ef541f4c4f8d60ecb44476f023a/backend/yomiscan/translation/marian.py#L41
[S-structured]: https://github.com/GabrielTeixeira88/yomiscan/blob/178e506f8bc03ef541f4c4f8d60ecb44476f023a/backend/yomiscan/translation/structured.py#L93
[S-renderer]: https://github.com/GabrielTeixeira88/yomiscan/blob/178e506f8bc03ef541f4c4f8d60ecb44476f023a/backend/yomiscan/rendering/renderer.py#L1
[S-overlay]: https://github.com/GabrielTeixeira88/yomiscan/blob/178e506f8bc03ef541f4c4f8d60ecb44476f023a/extension/src/chapter/overlay.ts#L53
[S-glossary]: https://github.com/GabrielTeixeira88/yomiscan/blob/178e506f8bc03ef541f4c4f8d60ecb44476f023a/backend/yomiscan/glossary.py#L1
[S-cache]: https://github.com/GabrielTeixeira88/yomiscan/blob/178e506f8bc03ef541f4c4f8d60ecb44476f023a/backend/yomiscan/cache.py#L46
[S-identity]: https://github.com/GabrielTeixeira88/yomiscan/blob/178e506f8bc03ef541f4c4f8d60ecb44476f023a/backend/yomiscan/cache_identity.py#L1
[S-reports]: https://github.com/GabrielTeixeira88/yomiscan/blob/178e506f8bc03ef541f4c4f8d60ecb44476f023a/extension/src/chapter/reports.ts#L1
[S-font]: https://github.com/GabrielTeixeira88/yomiscan/blob/178e506f8bc03ef541f4c4f8d60ecb44476f023a/extension/src/chapter/font-settings.ts#L9
[S-progress]: https://github.com/GabrielTeixeira88/yomiscan/blob/178e506f8bc03ef541f4c4f8d60ecb44476f023a/backend/yomiscan/progress.py#L17
[S-readiness]: https://github.com/GabrielTeixeira88/yomiscan/blob/178e506f8bc03ef541f4c4f8d60ecb44476f023a/backend/yomiscan/readiness.py#L132
[S-history]: https://github.com/GabrielTeixeira88/yomiscan/blob/178e506f8bc03ef541f4c4f8d60ecb44476f023a/extension/src/history.ts#L1
[S-inspector]: https://github.com/GabrielTeixeira88/yomiscan/blob/178e506f8bc03ef541f4c4f8d60ecb44476f023a/extension/src/chapter/region-inspector.ts#L81
[S-builder]: https://github.com/GabrielTeixeira88/yomiscan/blob/178e506f8bc03ef541f4c4f8d60ecb44476f023a/scripts/build_distribution.py#L1
[S-validator]: https://github.com/GabrielTeixeira88/yomiscan/blob/178e506f8bc03ef541f4c4f8d60ecb44476f023a/scripts/validate_distribution.py#L1
[S-region-geometry]: https://github.com/GabrielTeixeira88/yomiscan/blob/178e506f8bc03ef541f4c4f8d60ecb44476f023a/extension/src/chapter/region-geometry.ts#L11
[S-discovery]: https://github.com/GabrielTeixeira88/yomiscan/blob/178e506f8bc03ef541f4c4f8d60ecb44476f023a/extension/src/chapter/discovery.ts#L35
[S-nmt]: https://github.com/GabrielTeixeira88/yomiscan/blob/178e506f8bc03ef541f4c4f8d60ecb44476f023a/backend/yomiscan/translation/nmt.py#L71
[S-runtime]: https://github.com/GabrielTeixeira88/yomiscan/blob/178e506f8bc03ef541f4c4f8d60ecb44476f023a/backend/yomiscan/service.py#L136
[S-llm-http]: https://github.com/GabrielTeixeira88/yomiscan/blob/178e506f8bc03ef541f4c4f8d60ecb44476f023a/backend/yomiscan/translation/manga.py#L166
[S-service-open]: https://github.com/GabrielTeixeira88/yomiscan/blob/178e506f8bc03ef541f4c4f8d60ecb44476f023a/backend/yomiscan/service.py#L202
[S-page-cli]: https://github.com/GabrielTeixeira88/yomiscan/blob/178e506f8bc03ef541f4c4f8d60ecb44476f023a/backend/yomiscan/page_cli.py#L64
[S-page-extract]: https://github.com/GabrielTeixeira88/yomiscan/blob/178e506f8bc03ef541f4c4f8d60ecb44476f023a/backend/yomiscan/page.py#L102
[S-setup]: https://github.com/GabrielTeixeira88/yomiscan/blob/178e506f8bc03ef541f4c4f8d60ecb44476f023a/extension/src/chapter/setup-controls.ts#L29
[S-readme-translation]: https://github.com/GabrielTeixeira88/yomiscan/blob/178e506f8bc03ef541f4c4f8d60ecb44476f023a/README.md#L447
[S-security]: https://github.com/GabrielTeixeira88/yomiscan/blob/178e506f8bc03ef541f4c4f8d60ecb44476f023a/backend/yomiscan/api/security.py#L16
[S-api]: https://github.com/GabrielTeixeira88/yomiscan/blob/178e506f8bc03ef541f4c4f8d60ecb44476f023a/backend/yomiscan/api/main.py#L1
[S-source-fetch]: https://github.com/GabrielTeixeira88/yomiscan/blob/178e506f8bc03ef541f4c4f8d60ecb44476f023a/extension/src/chapter/source-fetch.ts#L11
[S-pyproject]: https://github.com/GabrielTeixeira88/yomiscan/blob/178e506f8bc03ef541f4c4f8d60ecb44476f023a/pyproject.toml#L1
[S-render-service]: https://github.com/GabrielTeixeira88/yomiscan/blob/178e506f8bc03ef541f4c4f8d60ecb44476f023a/backend/yomiscan/rendering/service.py#L22
[S-masks]: https://github.com/GabrielTeixeira88/yomiscan/blob/178e506f8bc03ef541f4c4f8d60ecb44476f023a/backend/yomiscan/rendering/masks.py#L1
[S-browser-test]: https://github.com/GabrielTeixeira88/yomiscan/blob/178e506f8bc03ef541f4c4f8d60ecb44476f023a/extension/tests/browser-chapter.mjs#L1
[S-ci]: https://github.com/GabrielTeixeira88/yomiscan/blob/178e506f8bc03ef541f4c4f8d60ecb44476f023a/.github/workflows/ci.yml#L1
[S-zip-validator]: https://github.com/GabrielTeixeira88/yomiscan/blob/178e506f8bc03ef541f4c4f8d60ecb44476f023a/scripts/validate_extension_package.mjs#L1
[D-privacy]: https://github.com/GabrielTeixeira88/yomiscan/blob/178e506f8bc03ef541f4c4f8d60ecb44476f023a/docs/decisions/diagnostic-report-privacy.md#L1
[D-cache]: https://github.com/GabrielTeixeira88/yomiscan/blob/178e506f8bc03ef541f4c4f8d60ecb44476f023a/docs/decisions/stage-cache.md#L1
[D-notices]: https://github.com/GabrielTeixeira88/yomiscan/blob/178e506f8bc03ef541f4c4f8d60ecb44476f023a/docs/third-party-licenses.md#L1
[D-stage2-provenance]: https://github.com/GabrielTeixeira88/yomiscan/blob/178e506f8bc03ef541f4c4f8d60ecb44476f023a/docs/research/stage2-model-provenance.md#L1
[D-translation-benchmark]: https://github.com/GabrielTeixeira88/yomiscan/blob/178e506f8bc03ef541f4c4f8d60ecb44476f023a/docs/translation-benchmark.md#L1
[D-stage4]: https://github.com/GabrielTeixeira88/yomiscan/blob/178e506f8bc03ef541f4c4f8d60ecb44476f023a/docs/research/stage4-translation-results.md#L1
[D-installation]: https://github.com/GabrielTeixeira88/yomiscan/blob/178e506f8bc03ef541f4c4f8d60ecb44476f023a/docs/installation.md#L1
[S-python-tests]: https://github.com/GabrielTeixeira88/yomiscan/tree/178e506f8bc03ef541f4c4f8d60ecb44476f023a/backend/tests
[S-extension-tests]: https://github.com/GabrielTeixeira88/yomiscan/tree/178e506f8bc03ef541f4c4f8d60ecb44476f023a/extension/tests
[E-api]: evidence/post-mvp-audit-api.json
[E-browser]: evidence/post-mvp-audit-browser.json
[E-measurements]: evidence/post-mvp-audit-measurements.json
[E-popup]: evidence/post-mvp-audit-synthetic-popup.png
[D-reproduction]: post-mvp-audit-reproduction.md
[U-css]: https://drafts.csswg.org/css-transforms-2/#individual-transforms
[U-ofl]: https://openfontlicense.org/open-font-license-official-text/
[U-edrdg]: https://www.edrdg.org/edrdg/licence.html
[U-opus]: https://huggingface.co/Helsinki-NLP/opus-mt-ja-en
[U-detector]: https://huggingface.co/ogkalu/comic-text-and-bubble-detector
[U-fugu]: https://huggingface.co/staka/fugumt-ja-en
[U-nllb]: https://huggingface.co/facebook/nllb-200-distilled-600M/blob/f8d333a098d19b4fd9a8b18f94170487ad3f821d/README.md
