# 01 — Project Understanding

Assessment date: 2026-11-23. Baseline: `main` at `178e506` (merge of PR #5, Stage 5).
Assessor: independent reviewer, no prior involvement.

**Evidence labels used throughout this assessment**

| Label | Meaning |
|---|---|
| **[Verified]** | I ran it, measured it, or read the code path end-to-end myself during this assessment. |
| **[Repo-reported]** | Stated in the repository's own docs/benchmarks; I did not reproduce it. |
| **[Assumption]** | My inference where information is missing. Listed again in 06-OPEN_QUESTIONS. |
| **[Recommendation]** | My opinion about what should be done. |

---

## 1. What YomiScan is meant to be

YomiScan is meant to be an **offline-first assistant for reading Japanese manga**. It
should help a learner understand Japanese text in manga images without cloud services
or paid APIs. Its stated values, from `AGENTS.md` and `README.md`:

- Local processing and privacy. Nothing leaves the machine except one-time model and dictionary downloads.
- Japanese OCR suited to manga, which means vertical text, stylised fonts and speech bubbles.
- Japanese→English translation run locally.
- **Language learning, not just translation**: readings, dictionary forms, meanings.
- A practical reading workflow in the browser, where people actually read manga.

**Intended users [Assumption]:** Japanese learners from roughly N4 to N2 level who read
manga in a desktop Chrome browser. They are motivated enough to run a local Python
backend. The README's setup flow (Python 3.13, uv, Node, manual JMdict download, two
terminals) points to a technically capable user. In practice, the owner is the primary user today.

## 2. What it actually is today

Today YomiScan contains **two products that share one backend**.

1. **Study Mode** (Phases 1–4). You drag a rectangle over part of a page. The
   extension screenshots the tab and crops it. The backend reads the crop as a *single
   text block* with manga-ocr, translates it with OPUS-MT, and tokenizes it with
   fugashi/UniDic-lite. Each token is then looked up in a local JMdict SQLite database.
   A draggable popup shows the original text, the translation, and a card per token.
2. **Translate Chapter** (Phases 5–7 + Post-MVP Stages 1–5). The extension discovers
   manga page images on a reader site and sends each page to the backend. The backend
   detects text blocks (RT-DETR-v2 comic detector), OCRs each block, translates it,
   then **erases the Japanese and typesets English** into the bubbles (masking, OpenCV
   inpainting, Pillow typesetting). The extension lays the rendered page over the
   original image, with an Original/English toggle.

Most engineering effort since Phase 4 has gone into product 2 and into infrastructure
around it: staged caching, diagnostics export, progress reporting, glossaries,
experimental translation engines, packaging, and the readiness checks.

### Size and shape (Verified, `git ls-files` + `wc`)

| Area | Lines |
|---|---:|
| Backend Python (`backend/yomiscan`) | ~7,400 |
| Backend tests | ~3,900 |
| Extension TypeScript (`extension/src`) | ~2,900 |
| Extension tests | ~1,300 |
| Markdown documentation | ~6,500 |
| Scripts | ~570 |

The project has almost as much documentation as backend code. The code is written
densely: 1,045 source lines exceed 110 characters, and many statements are chained
on one line.

## 3. How it evolved (Verified from Git history)

| Date | Commit(s) | Step | Notes |
|---|---|---|---|
| 2026-09-28 | `9bb1571` | Phase 1: manga-ocr CLI | `OCREngine` protocol, lazy model loading |
| 09-29 | `a5faac2` | Phase 2: fugashi + UniDic-lite + JMdict SQLite | Exact-form lookup, no deinflection beyond UniDic lemma |
| 09-30 | `61a9378` | Phase 3: OPUS-MT translation | Marian adapter, batching |
| 09-30 | `e788c06` | Phase 4: Chrome Study Mode + FastAPI | Screenshot crop → popup |
| 10-01 | `96c70a5` | Phase 5: page text detection | ogkalu RT-DETR-v2 comic detector |
| 10-02 | `38d8059` | Phase 6: masking/inpainting/typesetting | Conservative, transactional renderer |
| 10-03 | `545a99e` | Phase 7: Translate Chapter + coverage fixes | Discovery, queue, acquisition, overlays |
| 10-04 | `6b4bc8c` | Translation benchmark (Hy-MT2, Qwen2.5, VNTL, Fugu, NLLB) | OPUS kept as default |
| 11-20 | PR #1 `c651a3c` | Stage 1: reliability/QoL | Diagnostics ZIP, CI, copy buttons, page refresh |
| 11-20 | PR #2 `7a7ece7` | Stage 2: detection/OCR experiments | ONNX detector, 2025 OCR (both optional, not default) |
| 11-20 | PR #3 `4b51ce5` | Stage 3: caching | Session LRU, opt-in persistent stage cache |
| 11-20 | PR #4 `78dd83b` | Stage 4: translation | Series glossaries, structured LLM contract, PT/ES experiments |
| 11-21 | PR #5 `178e506` | Stage 5: reader UX + distribution | Font scale, region inspector, readiness, history, unsigned ZIP/wheel |
| 11-21 | `ecb51ca` (unmerged branch `audit/post-mvp-full-review`) | Defect audit | 10 findings (2 × P1); not fixed |

Observations about the history:

- **Purely additive.** The five post-MVP merges add ~12,500 lines and delete only ~480.
  No experiment was ever removed: Qwen2.5, VNTL (which has no published weights),
  NLLB (non-commercial licence), PT/ES targets, the ONNX detector and the 2025 OCR are all still in the tree.
- **Very fast pace.** All five post-MVP stages were merged within about 24 hours, and
  the commit style and documentation density suggest AI-agent-driven development.
  This explains both the strengths (thorough tests, pinned artifacts, careful
  boundaries) and the weaknesses (scope sprawl, no pruning, documentation that records
  everything but is hard to read).
- **Direction drifted.** Phase 4 delivered the learning core. Every phase since has
  invested in automatic image translation, which a learner needs least. The Study
  popup's linguistic quality has not changed since Phase 2.
- An earlier comparison with a sibling project ("Yomu", `docs/yomiscan-vs-yomu-research.md`)
  generated the P01–P20 backlog that Stages 1–5 executed almost item by item.

## 4. Functionality inventory

Classification key: **Functional** = implemented and works for its stated scope;
**Incomplete** = works, but an important part is missing; **Unreliable** = works
sometimes, or quality is too low to depend on; **Planned** = not implemented;
**Obsolete** = present but superseded or unused.

### 4.1 Core pipeline

| Feature | Status | Evidence |
|---|---|---|
| Manga OCR of a single text block (manga-ocr, original weights) | **Functional** | `ocr/manga_ocr.py`. [Repo-reported] 1.97% normalized CER on 19 real crops (one chapter). [Verified] real crops read correctly in my run. |
| OCR of a Study selection containing **several** text blocks | **Unreliable** | `analysis.analyze_image` OCRs the whole crop as one image, with no detection. [Verified] a crop with 2 detected blocks returned 9 characters; per-block OCR returned 3 + 9. One block was silently dropped. |
| Text detection on full pages (RT-DETR-v2, PyTorch, 0.50/0.50) | **Functional** | `detection/rtdetr.py`. [Verified] 13 and 5 blocks on two real pages. [Repo-reported] 16/16 dialogue units found on the 3-page corpus; 2 large SFX missed. |
| Grouping/merging of line-level detections | **Obsolete in practice** | `page_layout.nearby_lines` only merges `granularity == "line"`. The default detector only emits `"block"`, so the code path is unreachable with the default detector. |
| Reading order (top-to-bottom bands, right-to-left) | **Incomplete** | `page_layout.reading_order`. Heuristic only. Optional white-gutter panel ordering (`panel_order.py`) is experimental. |
| Morphological analysis (fugashi + UniDic-lite) | **Functional** | `nlp/fugashi.py`. [Verified] correct segmentation and readings on test sentences. |
| JMdict lookup | **Unreliable (as a learning aid)** | `analysis.lookup_candidates`, `dictionary/sqlite.py`. [Verified] particle は returns 12 entries, with *feather / tooth / blade* listed first. しょう returns 41 entries. Expressions present in JMdict (万年, しょうがない, なきゃいけない) are never found, because lookup is per token. Priority tags are discarded at import (`dictionary/importer.py`). |
| Sentence translation, OPUS-MT ja→en (default) | **Unreliable** | `translation/marian.py`. [Verified] on a real page: a character name became "Yuki?", 万年４級 ("perpetual grade-4") became "Four-year-olds", and なんで呪術師やってんのって感じ ("like, why are you even a sorcerer?") became "I don't know why you're acting like a witch doctor". [Repo-reported] same class of errors across the 53-line benchmark. |
| Alternative engines (Hy-MT2, Qwen2.5, Fugu, NLLB, VNTL) | **Incomplete / experimental** | `translation/manga.py`, `nmt.py`, `factory.py`. Selected through env vars plus a restart. VNTL has no weights (**Obsolete**). NLLB is CC-BY-NC. |
| Structured exact-ID page translation, bounded context | **Experimental** | `translation/structured.py`. [Repo-reported] no semantic win and context leakage. |
| JA→PT/ES targets | **Experimental** | `translation/nmt.py`, `options.py`. Dictionary glosses stay English. |

### 4.2 Browser: Study Mode

| Feature | Status | Evidence |
|---|---|---|
| Region selection overlay, screenshot, crop (DPR/zoom aware) | **Functional** | `content.ts`, `background.ts`, `geometry.ts`. [Repo-reported] 37-check headless Chrome fixture. Unmerged audit AU-01: capture survives SPA navigation. |
| Study popup: original, translation, tokens, senses, drag/resize, copy | **Functional (UI)** / **Unreliable (content)** | `popup.ts`. The UI works. The content shows unranked homograph senses, raw UniDic Japanese POS labels (e.g. `助詞 / 係助詞`) and raw conjugation codes. |
| OCR correction / edit-and-reanalyze | **Planned** | The README lists it as future work. The popup has a read-only "Original" section. |
| Save to History (local, opt-in) | **Incomplete** | `history.ts`. Works, but the Save button is styled as a 30×30 icon button so its label overflows (code at `popup.ts` sets `button {width:30px;height:30px}` and Save gets no override; unmerged audit AU-04). |
| Vocabulary saving, SRS, Anki export, known-word tracking | **Planned** | Not present. |
| Grammar explanations, furigana display, kanji info, JLPT tags | **Planned** | Not present. |

### 4.3 Browser: Translate Chapter

| Feature | Status | Evidence |
|---|---|---|
| Page discovery (dominant column of large `<img>`s, lazy-load observer) | **Functional for simple image readers** | `chapter/discovery.ts`, `session.ts`. Canvas/WebGL readers and frames are not supported. |
| Image acquisition chain (extension fetch with host permission → canvas → viewport crop → opt-in scroll stitching) | **Functional** | `chapter/acquisition.ts`, `source-fetch.ts`, `stitching.ts`. |
| Serial queue, viewport priority, Stop/Retry/Clear, refresh | **Functional** | `chapter/model.ts`, `session.ts`. Unmerged audit AU-08: cancel does not stop between OCR crops. |
| Mask → inpaint → typeset English | **Functional, partial coverage** | `rendering/*`. [Verified] page 1: 9 of 13 blocks rendered; page 3: 2 of 5. The visual cleaning quality is good. Artwork text and SFX are usually preserved untouched. |
| Original/English overlay toggle | **Functional** | `chapter/overlay.ts`. Unmerged audit AU-02/03 found overlay mapping and visibility defects. |
| Font scale, region inspector, "Study Bubble" | **Functional** | `chapter/region-inspector.ts`, `font-settings.ts`. This is the only bridge from reading to studying, and it sits behind "Inspect Regions". |
| Series glossaries / terminology | **Functional (management)**, **no effect with the default engine** | `glossary.py`, `chapter/translation-settings.ts`. OPUS ignores glossary hints, as the README states. |
| Per-page diagnostic ZIP export | **Functional** | `diagnostics.py`, `chapter/reports.ts`, `chapter/zip.ts`. |

### 4.4 Infrastructure

| Feature | Status | Evidence |
|---|---|---|
| Local FastAPI, single owning worker thread, 429 when busy | **Functional** | `api/main.py`. Study requests return 429 while a chapter page is processing. |
| Loopback guard: Trusted Host, CORS limited to extension origins, custom header | **Functional** | `api/security.py`. This is not authentication against other local processes, as the README says. |
| Session LRU (128 MiB) + opt-in persistent stage cache | **Functional** | `cache.py`, `cache_identity.py`, `chapter/model.ts`. |
| Readiness/setup checks, job progress | **Functional** | `readiness.py`, `progress.py`. Unmerged audit AU-05: a failed NMT load is reported as loaded. |
| No automatic downloads; pinned revisions; `yomiscan-prepare-defaults` | **Functional** | `cli.py`, `readiness.py`. |
| CI (Windows/Linux pytest, Node tests, packaging) | **Functional** | `.github/workflows/ci.yml`. |
| Unsigned extension ZIP + wheel/sdist | **Functional (developer artifacts)** | `scripts/build_distribution.py`. |
| GPU acceleration | **Incomplete** | The locked environment installs `torch 2.14.0+cpu` [Verified], so CUDA is never used by default, even on the development PC's RTX 4070 SUPER. Only llama.cpp engines can use the GPU. |
| macOS support | **Planned / unverified** | Windows and Linux are documented. macOS is not tested. |
| Automatic backend start / installer | **Planned** | Manual terminal start. |

## 5. What I verified, and what I could not

| Check | Result |
|---|---|
| Backend tests (`pytest`, isolated temp/cache/dictionary paths, offline) | **[Verified] 316 passed, 1 skipped**, 20 s. Model-free. |
| Extension tests + typecheck (`npm ci`, `npm test`, `tsc`) in a scratch copy | **[Verified] 68 passed**, typecheck clean. |
| Real backend startup (CPU, cached models, real JMdict) | **[Verified] ~20 s** to load OCR + OPUS + dictionary. |
| Real page translate+render, 870×1270 pages, CPU | **[Verified]** page 1: 7.8 s (detect 0.45 s, OCR 3.6 s for 13 blocks, translate 2.3 s); 9 rendered / 4 preserved. Page 3: 3.9 s; 2 / 3. |
| Real Study crop on a multi-bubble region | **[Verified]** one of two text blocks dropped silently (see 4.1). |
| Real lexical analysis with the full JMdict | **[Verified]** severe homograph noise; expressions missed (see 4.1, and 03-PRODUCT_ASSESSMENT §4). |
| Disk footprint of the default install | **[Verified]** venv 1.1 GB; manga-ocr 848 MB; OPUS 582 MB; detector 175 MB; JMdict DB 113 MB. About **2.8 GB** in total. |
| Live browser session in Chrome on a real reader site | **Not verified.** I did not drive Chrome. I relied on the repository's headless fixture results and the unmerged audit's probes. |
| Optional engines (Hy-MT2, Qwen, ONNX OCR/detector) inference | **Not re-run.** I rely on the repository's Stage 2/4 reports. |
| GPU inference | **Not verified.** The installed Torch build is CPU-only. |
| OCR/translation accuracy in general | **Not claimed.** The only evaluation corpus is 3 pages from one chapter of one series, plus synthetic lines. |

For real inference I used locally cached model weights and two sample pages that
already existed in the owner's original working clone. I read them in place and wrote
outputs only to a temporary scratch directory. No page images or extracted text were
copied into this repository.
