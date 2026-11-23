# 02 — Implementation Audit

Baseline `178e506`. File references are relative to the repository root. Evidence
labels are defined in 01-PROJECT_UNDERSTANDING.

---

## 1. Architecture as built

```text
Chrome MV3 extension (plain TS + esbuild, no framework)
 ├─ content.ts            injected on click: selection overlay, popup, chapter controls (closed Shadow DOM)
 ├─ background.ts         service worker: screenshot+crop, message router, history, permissions
 ├─ offscreen.ts          long-running render-page requests and progress polling
 └─ chapter/*  (~25 modules) discovery, queue, acquisition, overlay, inspector, settings, reports, zip…
        │  fetch http://127.0.0.1:8765  (hard-coded in 7 places)
        ▼
FastAPI (api/main.py) ── one ThreadPoolExecutor(max_workers=1) owns every model and SQLite handle
 └─ ImageAnalysisService (service.py)
     ├─ Study:   OCREngine(whole crop) → TextAnalyzer(translate + tokenize + JMdict)
     └─ Page:    PageAnalysisService(detect → crop OCR → order → analyze_many)
                  → PageTranslationRenderService(mask → inpaint → typeset) → PNG
     + ProcessingCache (RAM LRU + opt-in SQLite stage cache), GlossaryStore (SQLite),
       JobRegistry (progress), readiness snapshots
```

The layering is sound. Models sit behind typed Protocols (`OCREngine`,
`TextDetector`, `TranslationEngine`, `JapaneseTokenizer`). Composition happens in one
place (`service.open_local_service`). HTTP DTOs are separate from domain dataclasses
(`api/models.py`). The extension never sees model-specific objects.

## 2. What is already well designed (keep)

1. **One owning worker thread for all inference and SQLite** (`api/main.py` lifespan).
   This is a simple, correct answer to the thread-affinity of SQLite and Torch, and it
   prevents duplicated model memory. Readiness and health stay responsive while a page runs.
2. **No silent downloads; pinned model revisions; explicit preparation command**
   (`readiness.py`, `cli.py`). This makes offline behaviour predictable and auditable.
3. **Typed adapter boundaries that preserve the exception cause** (`ocr/base.py`,
   `translation/base.py`, `detection/base.py`). Adding engines has not polluted callers.
4. **JMdict importer** (`dictionary/importer.py`). It streams, builds in a temporary
   file and swaps atomically, and records provenance and licence metadata. Lookups are
   parameterised and the connection is read-only.
5. **Conservative, transactional renderer** (`rendering/renderer.py`, `masks.py`,
   `layout_regions.py`). It fits the text before erasing and commits per block. When
   unsure, it leaves the original pixels alone. [Verified] The visual output on a real
   page is clean, and this is the most mature part of the image pipeline.
6. **Image acquisition fallback chain with per-host optional permissions**
   (`chapter/acquisition.ts`, `source-fetch.ts`). This is careful work: there is no
   bypass of site access, and scroll position is restored.
7. **Model-free test discipline.** 316 backend tests and 68 extension tests run in
   about 20 s without weights. Fakes are injected through the Protocols. CI covers
   Windows and Linux.
8. **Benchmark before adopting.** The Stage 2/4 reports refused to switch defaults
   without evidence. The corpus was too small, but the habit is right.
9. **Privacy defaults.** The disk cache is off by default, history is off by default,
   diagnostics contain metadata only unless the user opts in, and no telemetry exists.
10. **Loopback hardening** (`api/security.py`): Trusted Host, CORS restricted to
    extension origins, a custom header to force preflight, and body-size limits before parsing.

## 3. Poorly designed or defective

### 3.1 The dictionary layer undermines the learning feature

This is the most consequential weakness in the codebase.

- **Per-token exact lookup only** (`analysis.lookup_candidates`). There is no
  longest-match scan across tokens. JMdict entries such as `万年`, `しょうがない` and
  `なきゃいけない` exist in the local database [Verified], but they are never shown,
  because UniDic splits them and each piece is looked up alone.
- **Reading-normalised lookup returns every homograph.** `SQLiteDictionary.lookup`
  converts the query to hiragana and matches against an index that contains readings.
  For kana tokens, this returns every kanji word with that reading. [Verified] は → 12
  entries (羽, 歯, 刃, 派 …); よ → 9 (夜, 余, 四 …); しょう → 41.
- **No ranking.** Results are `ORDER BY e.entry_id`. The importer discards JMdict
  priority tags (`ke_pri`/`re_pri`: news1, ichi1, nfXX), so ranking by commonness is
  impossible without a re-import.
- **No filtering by UniDic POS or reading.** The token already knows it is a particle
  (`助詞`) reading は. That information is not used to choose the particle entry.
- **Flattened presentation.** `api/models.py` flattens the senses of *all* entries into
  one list, and `popup.ts` shows the first three. A learner who looks at は therefore
  sees "feather; plume", "tooth" and "edge of a knife" first.
- **No normalisation of colloquial forms.** For example, `ねえ`→`ない` only works by
  luck through UniDic lemma, and `しょうがねえ` does not match.

### 3.2 Study Mode OCR ignores the detector

`analysis.analyze_image` OCRs the whole selection as one image. manga-ocr is a
single-block recogniser, so a selection that covers two bubbles loses one of them with
no warning. [Verified] 2 blocks → 9 characters, against 12 characters when OCR'd per
block. The detector is already loaded for chapter mode. Running it on the crop would
fix this, and the result could return per-block text.

### 3.3 Translation default is weak, and the engine choice is an environment variable

- OPUS-MT ja-en is a small, general news/subtitle-domain model. On manga dialogue it
  produces fluent but wrong English. [Verified] On one real page it mistranslated a character's
  name and an idiom, and turned a "why are you even a sorcerer?" line into "I don't
  know why you're acting like a witch doctor". [Repo-reported] The same pattern
  appears on the 53-line benchmark.
- Engines are selected with `YOMISCAN_TRANSLATION_ENGINE` and a restart, with no UI,
  so the better experimental engines are effectively invisible to users.
- [Repo-reported] Hy-MT2 Q4 on CUDA was *faster* than OPUS on CPU (84 vs 120 ms/line)
  and better on slang. It was kept experimental because it still made errors, which is
  a standard OPUS also fails.

### 3.4 GPU never used by the default stack

`uv.lock` resolves `torch 2.14.0+cpu` [Verified]. manga-ocr, the detector and OPUS all
run on CPU even on the development PC's RTX 4070 SUPER. The README says "GPU-specific
package configuration is deferred". Meanwhile OCR takes ~275 ms per block on CPU, and
3.6 s of a 7.8 s page.

### 3.5 Port 8765 collides with AnkiConnect

The backend URL `http://127.0.0.1:8765` is hard-coded in seven places
(`api.ts:61`, `background.ts:156`, `offscreen.ts:61,66`, `chapter/cache-client.ts`,
`readiness-client.ts`, `translation-client.ts`). **8765 is AnkiConnect's default port.**
Japanese learners are exactly the population that runs Anki with AnkiConnect, often
together with Yomitan. With Anki open, the backend cannot bind its port, and the
extension's health check reaches the wrong service.

### 3.6 Request handling concentrated in one function

`api/main.py::analyze_upload` takes 11 parameters, mostly boolean or optional flags,
and branches across Study, page analysis, render, diagnostics bundle, refresh, options,
cancellation and progress. `handle_upload` repeats the busy, cancellation and logging
plumbing. Separate endpoints call this one dispatcher instead of separate use-case
functions. It works, but every new feature touches this function.

### 3.7 Busy → 429 instead of a queue

`handle_upload` rejects any overlapping request with 429. While a chapter page is
rendering (several seconds on CPU), a Study request fails. The content script
mitigates this by stopping chapter scheduling and waiting. A small priority queue
(interactive before background) would be simpler for clients and better for users.

### 3.8 Confirmed defects

| ID | Defect | Source | Confirmed how |
|---|---|---|---|
| D1 | Multi-block Study selection silently drops text | `analysis.py::analyze_image` | **[Verified]** real crop probe |
| D2 | Homograph flood and unranked senses in the popup | `dictionary/sqlite.py::lookup`, `api/models.py`, `popup.ts` | **[Verified]** real JMdict |
| D3 | Port collision with AnkiConnect default | 7 hard-coded URLs | **[Verified]** source |
| D4 | Save-to-History button inherits 30×30 close-button size, label overflows | `popup.ts` styles (`button{width:30px;height:30px}`), Save has no class | **[Verified]** source; unmerged audit AU-04 measured it |
| D5 | Cancellation not checked between OCR crops | `page.py::PageAnalysisService.extract` loop has no cancel check | **[Verified]** source; audit AU-08 |
| D6 | Line-grouping code unreachable with default detector | `page_layout.nearby_lines` requires `granularity=="line"`; `rtdetr.decode_regions` emits `"block"` | **[Verified]** source |
| D7 | Study capture survives SPA navigation | `content.ts` ticket has no document generation | Audit AU-01 (repo branch); I agree from source, not re-run |
| D8 | Region hit-targets mis-mapped under `rotate`/`object-fit:none`; hidden-ancestor ghost overlays | `chapter/region-geometry.ts`, `overlay.ts`, `discovery.ts` | Audit AU-02/03; not re-run |
| D9 | Failed lazy NMT load reported as loaded | `translation/nmt.py`, `service.runtime_state` | Audit AU-05; not re-run |

The unmerged audit branch's findings are credible, but they are all *edge-case
correctness* findings. Its conclusion, "architecture is sound, stabilise", is
reasonable for the codebase as a translation tool. It does not address whether the
product is serving learners, which is the main concern of this assessment.

## 4. Unnecessarily complicated

These features are real and tested, but their cost is out of proportion to the value
for a single-user, local, learner-focused tool.

| Area | Files | Why it is over-built |
|---|---|---|
| Stage-cache identity system | `cache.py` (310), `cache_identity.py` (189), `rendering/cache.py`, `service.configuration_id`, extension generations | Five stage keys with lineage, artifact hashes, algorithm-source hashes, and configuration generations that the browser must match. A page costs about 4–8 s on CPU. One cache keyed by `(image SHA-256, pipeline version)` would capture almost all of the value. |
| Diagnostic ZIP export with consent tiers | `diagnostics.py`, `chapter/reports.ts`, `chapter/zip.ts` (a custom ZIP writer), decision doc | Useful for a team triaging user reports. For a personal tool, a "Copy debug info" button and the server log would do. |
| Series glossary system | `glossary.py`, `chapter/translation-settings.ts`, 5 API endpoints, cross-tab invalidation | The default engine **ignores** glossary hints. The system adds cross-tab invalidation and stale-hash 409s to every page job. |
| Experimental engine zoo | `translation/manga.py` (370), `nmt.py`, `experiments.py`, `structured.py`, `benchmark.py` | Five alternatives plus VNTL with no weights. These are benchmark tools that live in the runtime package. They belong in a `research/` package or a branch. |
| PT/ES targets | `translation/options.py`, `nmt.py`, popup | Experimental, and dictionary glosses remain English. This dilutes the product for little value. |
| Job progress registry + polling | `progress.py`, `offscreen.ts` polling at 800 ms | It reports stage names for a 4–8 s operation. A spinner with "detecting / reading / translating" from a streamed response would be enough. |
| Region inspector leases/pins | `chapter/region-inspector.ts`, LRU pin logic in `chapter/model.ts` | The complexity comes from treating the rendered PNG as the source of truth. A text layer (see 04) makes inspection trivial. |
| Chapter control panel | `chapter/controls.ts` and siblings | About 30 buttons in a 280 px panel, including "Log discovery / states", "Refresh Cache Usage" and "Export Page Report" next to "Translate Chapter". |
| Documentation | 6,500 lines | Terse, dense, and repeated across README, architecture, phase docs, stage docs and research. The README alone is 550 lines. It is hard to tell current behaviour from history. |

## 5. Maintainability and technical debt

- **Code density.** 1,045 lines over 110 characters, plus multi-statement one-liners,
  especially in `extension/src/chapter/*.ts`, `background.ts` and `service.py`.
  Example: `api/main.py` writes the failure-code mapping as one nested conditional
  expression. The code is readable to its author and to an AI agent, and hostile to
  a human reviewer.
- **Lazy imports inside methods** are used widely (`service.py`, `api/main.py`) to keep
  imports torch-free. The intent is valid, but it hides the dependency graph. A
  dedicated `engines` composition module would be cleaner.
- **Private attribute reach-through.** For example,
  `self._analyzer._translator` and `self._analyzer._dictionary._path` in `service.py`.
- **Purely additive history.** Nothing was ever deleted. Experiments and their
  scaffolding remain in the default package.
- **The extension has no UI framework.** For the current overlay-style UI that is
  defensible. Every UI element is built by hand with `document.createElement`, and
  styles are inline template strings. That gets painful as the study UI grows. A
  lightweight framework (Preact/Lit) would pay off for a richer learner UI.

## 6. Performance and resources

| Item | Measurement |
|---|---|
| Startup (OCR + OPUS + JMdict, CPU) | **[Verified]** ~20 s; detector loads lazily on first page (+~6 s **[Repo-reported]**) |
| Page 870×1270, CPU | **[Verified]** 3.9–7.8 s; OCR is ~45–50% of it |
| Study crop, CPU | **[Verified]** ~0.5 s warm |
| Detector PyTorch vs INT8 ONNX | **[Repo-reported]** 1,077 ms vs 111 ms warm; RSS ~487 MiB vs ~108 MiB; same recall on the 3-page corpus |
| OCR original vs 2025 ONNX | **[Repo-reported]** original more accurate (1.97% vs 6.9% CER on 19 crops). ONNX is ~5× faster. The faster model is not a free swap. |
| Disk | **[Verified]** ~2.8 GB for the default install (venv 1.1 GB, mostly Torch) |

Takeaway: the cheapest large win already measured is the INT8 ONNX detector, which is
10× faster and smaller with equal recall on the tiny corpus. The second is GPU-enabled
inference for users who have a GPU. Neither was adopted.

## 7. Security and privacy

- Good: loopback-only binding, origin and host checks, no wildcard CORS, upload limits,
  no telemetry, opt-in persistence, and explicit, consented report export.
- The custom header is not authentication. Any local process can call the API.
  A per-install token exchanged through Chrome native messaging would close this
  gap cheaply (see 04).
- `manifest.json` extension-page CSP allows `connect-src http: https:`, which is broad.
  Only loopback and approved image hosts are needed.
- `optional_host_permissions: ["http://*/*","https://*/*"]` is requested per host at
  runtime. This is fine.
- The unmerged audit's AU-06 (local LLM error bodies in default logs) is a minor local
  privacy issue.

## 8. Cross-platform and setup

- Windows and Linux are documented and tested in CI; macOS is not.
- Setup requires Python 3.13, uv, Node (for development), a manual JMdict download and
  import, `yomiscan-prepare-defaults`, and a server started in a terminal on every use.
  Engines are configured with environment variables. **This is a developer setup, not a
  learner product.** The readiness panel explains what is missing but cannot fix it.
- Paths are handled with `pathlib`, and Windows file locking for dictionary
  replacement is documented. Cross-platform care is good.

## 9. Testing

- Breadth is excellent for a project of this age, and the tests are fast and model-free.
- Gap: **there are no quality tests of the learning output.** Nothing asserts that は
  is shown as a particle, or that `しょうがない` is recognised. The tests check
  plumbing, not usefulness.
- Gap: the evaluation corpus for detection, OCR and rendering is 3 pages from one series.
  Every adoption decision rests on it.

## 10. Documentation versus code: contradictions and stale statements

| Statement | Reality |
|---|---|
| README Study setup step 2 points to a specific absolute path for `extension/dist` | That path belongs to a different clone than this working tree; it is a personal path in public docs. |
| README "Initial Windows validation passed … 13 unit tests" | Historical. There are now 316 tests. The section is not marked as history. |
| README roadmap item 6 lists "packaging/automatic local backend startup" as future | Packaging exists (unsigned ZIP/wheel). Automatic startup does not. The status table and roadmap disagree. |
| `docs/yomiscan-vs-yomu-research.md` §3.3 "no restart persistence or LRU eviction … new pages are skipped until Clear" | Superseded by Stage 3 (LRU plus opt-in persistence). The document does not say it is historical. |
| `docs/architecture.md` grouping: "only explicitly line-level detections can be geometrically joined" | Accurate, but it omits that the default detector never produces line-level detections. The feature is dormant. |
| README "Series terminology: Implemented" | True for management only. It has no effect with the default OPUS engine, which the README says elsewhere. |
| `AGENTS.md`: context-aware translation "remain future work" | Experimental bounded context exists (Stage 4). |
| `docs/architecture.md` "Replaceability … future benchmarks may compare PaddleOCR" | No PaddleOCR work exists. That is fine, but it reads like a plan. |

## 11. Summary answers

1. **Well designed:** worker ownership, adapter Protocols, pinned/no-download model
   policy, JMdict importer, conservative renderer, acquisition chain, model-free tests,
   privacy defaults.
2. **Unnecessarily complicated:** stage-cache identity/lineage, diagnostic ZIP tiers,
   glossary series, engine zoo in runtime, job progress registry, region-inspector
   leases, the 30-button panel, documentation volume.
3. **Poorly designed:** dictionary lookup and ranking, Study OCR without detection,
   env-var engine selection, hard-coded port 8765, `analyze_upload` dispatcher, 429
   instead of queueing, CPU-only Torch lock.
4. **Should be rewritten:** the lexical lookup layer (longest-match, deinflection,
   ranking, filtering); the Study popup content model; the extension UI layer; the
   backend API surface (versioned, use-case endpoints, token-based local auth).
5. **Should be preserved:** the items in (1). The renderer should be kept but moved
   out of the critical path (see 04).
6. **Missing:** OCR correction; per-bubble click-to-study while reading; furigana;
   grammar patterns; kanji info; vocabulary/sentence saving, Anki export and known
   words; GPU support; automatic backend lifecycle; installer; a representative
   evaluation set; learner-output quality tests.
