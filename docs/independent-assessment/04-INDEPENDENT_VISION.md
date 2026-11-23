# 04 — Independent Vision: YomiScan as I Would Build It

This is a recommendation document. Facts it relies on are labelled with references to 01–03.

---

## 0. Short answers to the five questions

| Question | My answer |
|---|---|
| Would I fundamentally change the architecture? | **Partly.** I would keep the browser extension + local engine split, because it is the right shape. I would change *what flows through it*: structured text (blocks, OCR, analysis) instead of rendered PNGs. I would also change *how the engine runs*: auto-started, token-authenticated, Torch-free by default, GPU-capable. |
| Would I approach OCR and translation differently? | **OCR: same recogniser, different pipeline.** Keep manga-ocr's original weights. Always detect first, including on manual selections, and OCR *every page in the background* so text is ready before the user asks. **Translation: different role and different default.** It becomes an on-demand answer key per bubble. Hy-MT2 (GPU/CPU) is the default where hardware allows, and OPUS is the light fallback. |
| Would I design a different reading and learning experience? | **Yes, this is the biggest change.** Pages become *readable Japanese with an interactive text layer*: hover or tap any bubble. A persistent **side panel** holds the study card: furigana, meaning units, grammar notes, a hidden translation, and save-to-Anki. Erase-and-typeset English becomes an optional later mode. |
| Simplify or expand? | **Simplify the infrastructure and the translation mode. Expand the learning depth.** I would remove roughly a third of the current surface (glossary system, engine zoo, PT/ES, ZIP diagnostics, lineage caching, 30-button panel) and add a proper lexical engine, OCR correction, and a capture/review loop. |
| What would my version look like? | Sections 1–7 below. |

---

## 1. Product principles

1. **Japanese stays on the page.** The learner reads Japanese. The tool reduces the
   cost of *understanding* it and never hides it by default.
2. **Zero-effort text.** The OCR is ready before the user asks. A tap costs nothing.
3. **One best answer, depth on demand.** Show the likely meaning first, and fold the rest.
4. **Trustworthy before clever.** Deterministic grammar notes beat fluent LLM
   explanations that might be wrong. Machine translation is always labelled and secondary.
5. **Fix the input.** OCR errors are correctable in one click, and everything downstream recomputes.
6. **Capture what you learn.** Every word and sentence is one click from Anki or a local list.
7. **Local and private.** No cloud and no account. Model downloads are explicit, pinned and verified.

## 2. Product experience

### 2.1 The core loop

```text
Open a manga reader page
  → YomiScan icon shows "Reading mode available (12 pages)"
  → Enable for this site (once)  ── grants image-host permission
  → Visible pages are detected+OCR'd in the background (≈1–2 s/page GPU, 3–6 s CPU)
  → Each bubble gets a subtle outline on hover
  → Hover + Shift: quick gloss tooltip of the word under the cursor
  → Click a bubble: side panel shows the Study Card for that bubble
  → J / K: next / previous bubble in reading order (panel follows)
  → S on a word: save to deck  ·  T: reveal translation  ·  E: edit OCR
```

### 2.2 Surfaces

| Surface | Purpose | Why |
|---|---|---|
| **Page text layer** (content script) | Invisible, positioned Japanese text over each detected block. Hover outlines. Click targets. | Turns images into text. It also makes the page compatible with **Yomitan** and other popup dictionaries the user already has, at no cost. |
| **Side panel** (`chrome.sidePanel`, Chrome 114+) | Study Card, page bubble list, deck, settings, setup. | It does not cover the art. It persists while scrolling and has room for depth, and it removes the drag/resize popup machinery. |
| **Quick tooltip** | One-line word gloss on hover+modifier. | Fast lookups without opening the panel. |
| **Region select** (existing, improved) | Fallback for unsupported readers (canvas/WebGL), SFX, and anything the detector missed. | The selection runs *detection on the crop* and returns all blocks. |
| **Glance mode** (optional, later) | Existing erase-and-typeset renderer, toggled per page. | For "just get me through this page". It reuses the current renderer. |

### 2.3 Study Card (side panel) — wireframe

```text
┌───────────────────────────────────────────────┐
│ Bubble 4 of 13 · p.2              ◀ J   K ▶   │
├───────────────────────────────────────────────┤
│   おれ    い                                    │
│   俺は 行かなきゃいけない んだ                   │  ← furigana (unknown kanji only)
│   ───── ──────────────── ───                  │  ← meaning units, clickable
│                                    ✎ Edit OCR  │
├───────────────────────────────────────────────┤
│ 俺  おれ   I, me (male, rough)           ★ save │
│ 行かなきゃいけない                               │
│   行く  いく  to go                       ★     │
│   〜なきゃいけない  "have to …"  N4 grammar  ⓘ  │
│     なきゃ = なければ (colloquial contraction)  │
│ んだ  explanatory "it's that…" (casual)    ⓘ   │
├───────────────────────────────────────────────┤
│ ▸ Show translation (machine, Hy-MT2)          │
│ ▸ Other dictionary entries (3)                │
├───────────────────────────────────────────────┤
│ [Save sentence card]   [Copy JP]   [Copy EN]  │
└───────────────────────────────────────────────┘
```

Design decisions:

- **Particles and auxiliaries** appear inline as grammar notes, not as dictionary
  cards. は is labelled "topic particle", and the list of homographs is never shown.
- **Furigana policy** can be all kanji, unknown kanji only, or none. "Known" comes from
  the user's known-word list or a JLPT threshold the user picks.
- **The translation is collapsed by default.** The user can choose to always show it.
  The engine name is always visible.
- **OCR edit**: an inline editable field. Saving it re-runs analysis and translation
  for that block only, in about 20 ms plus translation time. The correction is cached
  against the image hash, so it survives reloads.
- **Kanji**: tapping a kanji in the sentence opens KANJIDIC2 data (meanings,
  on/kun readings, stroke count, JLPT/grade where licensed).

### 2.4 Capture and review

- **Save word**: stores lemma, reading, chosen sense, the sentence, page URL (optional,
  off by default), a cropped bubble image, and the date.
- **Export**: to Anki through **AnkiConnect** (local HTTP; note the port issue in 02
  §3.5), with a configurable note type and field mapping. CSV export is also available.
- **Known words**: one click marks a lemma as known. Known words lose furigana and highlighting.
- **Page summary**: "This page: 34 words, 6 new to you". This is a cheap way to make
  progress visible.
- I would **not** build an internal SRS scheduler. Anki already does this well, and
  learners already use it.

### 2.5 What changes for "Translate Chapter"

It becomes **Reading mode**: background OCR of visible and upcoming pages, with
results held as text. The existing queue, viewport priority and acquisition chain carry
over almost unchanged. They are good. Only the payload changes, from PNG to JSON, and
the overlay changes, from an image to a text layer. Erase-and-typeset returns later as
**Glance**, an explicit per-page toggle that reuses the current renderer.

## 3. Architecture

### 3.1 Overview

```text
┌────────────────────────── Chrome extension (MV3, TypeScript + Preact) ──────────────────────────┐
│ content/page-layer   image discovery (reuse) · acquisition chain (reuse) · text layer · hover   │
│ sidepanel/           Study Card · bubble list · deck · settings · setup/model manager           │
│ background (SW)      router · engine handshake (native messaging) · AnkiConnect client          │
└───────────────┬─────────────────────────────────────────────────────────────────────────────────┘
                │ 1) chrome.runtime.connectNative("com.yomiscan.engine") → {port, token}
                │ 2) HTTP on 127.0.0.1:<port>, header Authorization: Bearer <token>, JSON
                ▼
┌──────────────────────────── YomiScan Engine (Python 3.13, local) ───────────────────────────────┐
│ launcher (native-messaging host): start-if-needed, return port+token, idle shutdown             │
│ api/        /v2/pages (image → blocks) · /v2/analyze (text → units) · /v2/translate            │
│             /v2/deck · /v2/models · /v2/health                                                  │
│ scheduler   one worker, two-priority queue: interactive > background                           │
│ vision/     detector (ONNX INT8) · orderer · OCR (manga-ocr, ONNX export; Torch optional)       │
│ language/   tokenizer (fugashi+UniDic) · lexicon (JMdict v2) · deinflector · grammar patterns   │
│             · kanji (KANJIDIC2) · furigana aligner                                             │
│ translate/  engines: hy-mt2 (llama.cpp) · opus (CTranslate2 int8) · [experimental LLM]         │
│ store/      user.db (deck, known, corrections, settings) · cache.db · dict DBs (read-only)      │
│ models/     manifest (pinned URLs + SHA-256) · downloader with consent · verifier               │
└─────────────────────────────────────────────────────────────────────────────────────────────────┘
```

### 3.2 Key decisions and reasons

**A. Keep extension + local engine (not all-in-browser, not desktop-only).**
- *All-in-browser (ONNX Runtime Web/WebGPU).* The INT8 detector (11 MB) would run fine
  in the browser. manga-ocr (~400 MB) is heavy but possible. Translation and a real
  lexical engine with a 100+ MB dictionary in the browser are awkward. Rejected for
  the MVP. Worth revisiting later for *instant in-browser detection boxes*.
- *Desktop reader app only (mokuro-style).* It loses the "read where I already read"
  workflow. Rejected as the primary surface. A local CBZ/folder reader is listed as an
  optional feature that reuses the same engine.

**B. Ship structured text instead of PNGs.** The page response becomes about 5–20 KB of
JSON (blocks with bbox/polygon, orientation, class, OCR text, reading index) instead of
a multi-MB PNG. Several things become simple as a result: the session LRU, the 128 MiB
budgets, the overlay image geometry, region-inspector leases, the diagnostic bundle
format, and render-cache identity.

**C. Engine lifecycle through Chrome native messaging.** A tiny registered host starts
the engine if it is not running and returns `{port, token}`. The benefits:
- The user never opens a terminal.
- The **port is chosen at launch**, so it can't collide with AnkiConnect's 8765.
- A **per-launch bearer token** authenticates the extension. Other local processes and
  web pages can't drive the engine. Today's custom header is not authentication.
- The engine can **shut down after idle** and free RAM/VRAM.
The trade-off is an install step that registers the host (an HKCU registry key on
Windows, a JSON manifest file on Linux/macOS). The installer does it.

**D. Torch-free default runtime: ONNX Runtime + CTranslate2 + llama.cpp.**
- Detector: the INT8 ONNX artifact is already integrated as an option.
  [Repo-reported] It is 10× faster and uses ~380 MiB less RAM, with equal recall on the tested pages.
- OCR: **export the original manga-ocr weights to ONNX** (encoder + decoder with KV
  cache) and gate adoption on **identical text output** against the PyTorch version on
  the evaluation set. The existing `ocr/onnx.py` adapter (for the 2025 weights) gives a
  head start. Until parity is proven, PyTorch manga-ocr stays as an optional extra.
- OPUS-MT: convert with CTranslate2 (int8), MIT-licensed, CPU-fast, no Torch.
- Hy-MT2: llama.cpp server, already implemented in `translation/manga.py`.
- Result: install size drops from ~1.1 GB (venv) to an estimated ~200–300 MB, plus
  models [Assumption, to be measured]. Startup is faster, and the engine becomes
  practical to freeze into an installer.
- GPU: `onnxruntime-gpu` (CUDA) on NVIDIA; DirectML/WinML on Windows for non-NVIDIA
  GPUs, to be benchmarked because the Windows ML stack is changing; llama.cpp CUDA or
  Vulkan builds for translation.

**E. Two-priority scheduler instead of busy → 429.** A click on a bubble, or a manual
selection, preempts the next background page, without interrupting the current
model call. Background OCR of upcoming pages never blocks study.

**F. Lexical engine rewrite** (the heart of the learning value):
1. **JMdict import v2.** Keep kanji and kana forms separate. Keep priority tags,
   `re_restr`, misc tags (colloquial, slang, archaic, uk = "usually kana"), and field tags.
2. **Deinflector.** A rule table maps inflected surfaces to dictionary forms with a
   labelled chain (e.g., `行かなきゃ` → 行く + negative-conditional, colloquial). This
   is the well-known approach used by popup dictionaries. YomiScan should author its
   own rule table rather than copy GPL-3 rules (see 06).
3. **Longest-match scanning.** From each UniDic token boundary, try the longest
   substring in JMdict (raw and deinflected), and prefer longer matches. This finds
   万年, しょうがない and なきゃいけない.
4. **Ranking.** Agreement with UniDic's POS and reading first, then JMdict priority,
   then the "usually kana" flag for kana input. Particles and auxiliaries map to a
   **grammar-word table**, not to JMdict homographs.
5. **Colloquial normaliser.** A small table: ねえ/ねぇ→ない, じゃねえ→ではない,
   〜ちゃう→〜てしまう, 〜てる→〜ている, っす→です, and so on. Each rule is labelled so
   the card can say "casual/rough form of …".
6. **Grammar patterns.** A curated YAML file of about 150 N5–N2 patterns, each with a
   matcher over token/lemma sequences, an English one-liner, a JLPT level and an
   example. These are authored for the project, so licensing is clean. This is the
   largest content task and the highest learner value.
7. **Furigana aligner.** Align UniDic readings to kanji spans for ruby display. This
   is standard and has known edge cases (jukujikun such as 今日). Fall back to a
   whole-word reading.

**G. Storage.**

| Store | Owner | Contents | Lifetime |
|---|---|---|---|
| `user.db` (SQLite) | engine | deck entries, known words, OCR corrections, settings | permanent; backed up and exported by the user |
| `cache.db` (SQLite) | engine | page results keyed by `(image SHA-256, pipeline version)`, translations keyed by `(text, engine id)` | disposable, size-capped LRU, **on by default** (text only, no pixels) |
| `jmdict.db`, `kanjidic.db` | engine | read-only, rebuilt by the importer | replaced on update |
| `chrome.storage.local` | extension | per-site enablement, UI preferences only | per browser profile |

Caching text-only results by default is a deliberate change from today's opt-in
pixel cache. The cache holds no images, so the privacy cost is low, and it makes
re-reading a chapter instant. Thumbnails attached to deck entries are explicit user saves.

**H. Model manager.** One manifest file lists every artifact: URL, revision, SHA-256,
size, licence and profile. The side panel's Setup page shows profiles:

| Profile | Contents | Disk | Hardware |
|---|---|---|---|
| **Light** (default without GPU) | ONNX detector, manga-ocr ONNX, OPUS CT2 int8, JMdict, KANJIDIC2 | ~0.8 GB est. | any 64-bit CPU, 4 GB RAM free |
| **Standard** (default with ≥6 GB VRAM) | Light + Hy-MT2 1.8B Q4 GGUF (llama.cpp CUDA/Vulkan) | ~2 GB est. | NVIDIA/AMD GPU or a fast CPU (~270 ms/line on CPU, Repo-reported) |
| **Experimental** | + a 7–8B instruct model for "explain this sentence" | +5 GB | 12 GB VRAM recommended |

Every download is explicit, verified against its hash and resumable. There are no
silent downloads, which keeps the existing project's good policy.

### 3.3 API sketch (v2)

```text
POST /v2/pages          multipart image → {page_id, width, height, blocks:[{id, bbox, polygon?,
                         orientation, kind: bubble|free|manual, order, text, ocr_conf?}]}
                         (cached by image hash; priority=background|interactive)
POST /v2/analyze        {text} → {units:[{surface, start, end, lemma, reading, kind: word|grammar|particle,
                         senses:[ranked], deinflection:[…], pattern?}], furigana:[…]}
POST /v2/translate      {texts:[…], engine?} → {translations:[…], engine, model}
POST /v2/corrections    {page_id, block_id, text} → re-analysed block
GET/POST /v2/deck …     CRUD + export (CSV, AnkiConnect push done by extension)
GET  /v2/models         profiles, installed/verified state;  POST /v2/models/install {profile}
GET  /v2/health         readiness + loaded engines
```

Per-request flags are replaced by separate use cases. Each endpoint maps to one
service function, which avoids recreating today's 11-parameter `analyze_upload`.

### 3.4 Technology choices

| Component | Choice | Why | Trade-offs | Hardware | Offline | Cost |
|---|---|---|---|---|---|---|
| Extension UI | TypeScript + **Preact** (or Lit), esbuild | The side panel needs real state and components. Both are tiny. | One small dependency | — | yes | free |
| Study surface | `chrome.sidePanel` | Persistent, doesn't cover art | Chrome/Edge only; the Firefox sidebar API differs | — | yes | free |
| Engine transport | Native messaging handshake + loopback HTTP + bearer token | Auto-start, auth, no fixed port | Installer must register the host | — | yes | free |
| Engine framework | FastAPI (keep) | Already working and tested | — | — | yes | free |
| Detector | ogkalu comic detector, **INT8 ONNX** (keep model, change runtime) | 10× faster, smaller, same recall on the tested corpus | Weight equivalence with the PyTorch checkpoint unproven; validate on the new corpus | CPU fine | yes | Apache-2.0 (publisher) |
| OCR | **manga-ocr original weights**, exported to ONNX | Most accurate option tested; Torch-free | Export plus parity validation work | CPU ok (~300 ms/block); GPU fast | yes | Apache-2.0 |
| Tokenizer | fugashi + **UniDic-lite** (keep); benchmark full UniDic or SudachiPy later | Works and is reproducible | UniDic-lite is old; casual-speech coverage is limited | CPU | yes | BSD |
| Dictionary | **JMdict** (re-imported with priorities and tags) + **KANJIDIC2** | Standard, free | CC BY-SA 4.0 attribution; derived DB not MIT | — | yes | free |
| Grammar | Project-authored pattern table | Trustworthy, licensable | Authoring effort (~150 patterns) | — | yes | free |
| Translation (default with GPU) | **Hy-MT2 1.8B manga fine-tune**, Q4 GGUF via llama.cpp | Better slang/names, fast on GPU (Repo-reported) | Still makes meaning errors; ~1.1 GB | ≥4 GB VRAM or fast CPU | yes | Apache-2.0 |
| Translation (light) | **OPUS-MT ja-en via CTranslate2 int8** | Tiny and fast on CPU, no Torch | Weak on dialogue | any CPU | yes | Apache-2.0 / CC-BY data caveats |
| Explanations (opt-in) | 7–8B instruct GGUF via llama.cpp | Can explain nuance | Hallucination risk; needs labelling; VRAM | 12 GB VRAM | yes | per model licence |
| Storage | SQLite | Already used well | — | — | yes | free |
| Packaging (Windows first) | Frozen engine (PyInstaller or equivalent) + installer that registers the native host | One-click install | Code-signing cost if distributed publicly (see 06) | — | yes | free unsigned |

## 4. Feature direction

### Essential (MVP)

1. Background detection+OCR of visible and upcoming pages on supported image readers
   (reusing discovery, acquisition and queue).
2. Interactive text layer: hover outline, click-to-study, J/K bubble navigation.
3. Side-panel Study Card with lexical engine v2: longest match, deinflection, ranking,
   particle/auxiliary grammar words, colloquial normaliser.
4. Furigana display (all kanji / none; "unknown only" comes with known words in the next phase).
5. OCR correction with instant re-analysis, persisted per image hash.
6. Region select that **runs detection on the selection** and handles several blocks.
7. On-demand per-bubble translation, collapsed by default and labelled with the engine.
8. Engine auto-start through native messaging, random port, token auth; no terminal.
9. Text-only result cache, on by default.
10. A representative evaluation set and learner-output tests (see 05).

### High-value improvements

1. Save word/sentence → local deck; push to Anki via AnkiConnect; CSV export.
2. Known-word tracking, "unknown-only" furigana, and new-word highlighting.
3. Grammar-pattern table expanded to ~150 patterns with JLPT levels.
4. KANJIDIC2 kanji panel.
5. Model manager with Light/Standard profiles and GPU detection.
6. Windows installer, then Linux packaging.
7. Quick hover tooltip (word gloss without opening the panel).
8. Page vocabulary summary ("6 new words on this page").

### Optional future possibilities

1. **Glance mode**: the existing erase-and-typeset renderer as an explicit per-page toggle.
2. Local volume reader (CBZ/folder) in an extension page, using the same engine.
3. "Explain this sentence" with an opt-in local LLM, clearly labelled.
4. In-browser ONNX detection for instant block outlines before engine OCR.
5. Source-furigana capture (ruby → reading hints).
6. Firefox port.
7. Series-specific name/term lists, **only** once an engine honours them.
8. Additional gloss languages. JMdict has some non-English glosses with uneven coverage.

### Explicitly dropped or deferred from the current codebase

| Current feature | Decision |
|---|---|
| Automatic chapter erase+typeset as the main mode | Deferred to Glance (optional) |
| Series glossary editor + invalidation protocol | Dropped until a glossary-capable default engine exists |
| PT/ES targets, NLLB, Qwen2.5, VNTL adapters | Moved to a `research/` package or branch |
| Structured exact-ID page contract | Kept in research; not in the product path |
| Diagnostic ZIP with consent tiers, custom ZIP writer | Replaced by "Copy debug info" (text) + engine log |
| Stage cache with lineage/algorithm-hash identity | Replaced by `(image hash, pipeline version)` cache |
| Job progress registry + polling | Replaced by per-page status events (SSE or simple polling of page state) |
| Font-scale and region-inspector leases | Not needed with a text layer; font scale returns with Glance |

## 5. What I would reuse from the existing code

| Existing module | Reuse |
|---|---|
| `extension/src/chapter/discovery.ts`, `acquisition.ts`, `source-fetch.ts`, `stitching.ts`, `model.ts` (queue) | **Reuse almost as is.** Change the payload and result types. |
| `extension/src/geometry.ts`, `content.ts` selection overlay | Reuse. Add a navigation generation (fixes audit AU-01). |
| `backend/yomiscan/api/security.py`, `api/images.py` | Reuse. Add the bearer token. |
| `backend/yomiscan/api/main.py` lifespan + single worker | Reuse the pattern. Replace the dispatcher and add the priority queue. |
| `detection/onnx.py`, `rtdetr.decode_regions` | Reuse. Make ONNX the default. |
| `ocr/manga_ocr.py`, `ocr/onnx.py` | Reuse. Export the original weights through the ONNX path. |
| `nlp/fugashi.py`, `japanese.py` | Reuse. |
| `dictionary/importer.py` | Extend: schema v2 with priorities and tags; same streaming and atomic swap. |
| `analysis.py` lexical part | **Rewrite** as `language/` (lexicon, deinflector, patterns). |
| `translation/marian.py`, `manga.py` (llama.cpp server mgmt) | Reuse the llama.cpp lifecycle. Port OPUS to CTranslate2. |
| `rendering/*` | Keep intact for Glance mode. |
| `readiness.py`, `vision_models.py`, `translation/setup_models.py` | Fold into one manifest-driven model manager. |
| Test suites and CI | Keep. Add learner-output golden tests. |

## 6. Comparison with the existing project

| Area | Existing implementation | My proposed approach | Reason for change |
|---|---|---|---|
| **Architecture** | MV3 extension + FastAPI on fixed `127.0.0.1:8765`; single worker; PNG results; manual terminal start | Same split; native-messaging launcher; random port + bearer token; two-priority single worker; JSON text results | Auto-start, real local auth, no AnkiConnect collision, far smaller payloads, simpler browser state. **The existing split and worker model were right and are kept.** |
| **Frontend** | Hand-built DOM in closed Shadow DOM; floating draggable popup; 280 px panel with ~30 controls | Preact side panel + lightweight in-page text layer + tooltip; settings and developer tools in the side panel | A dedicated surface fits learning depth; the art is not covered; the UI stays maintainable as it grows. **The existing acquisition/discovery/queue code is better than what I would write fresh, so it is reused.** |
| **Backend** | One service class plus an 11-parameter dispatcher; lineage-keyed stage caches; engine zoo in the runtime package | Use-case endpoints; `vision/`, `language/`, `translate/`, `store/`, `models/` packages; research code moved out | Separation by product capability; less surface; easier to test learner output |
| **OCR** | Detect + per-block manga-ocr for chapters; **whole-crop OCR without detection** for Study | Always detect first (pages *and* manual selections); manga-ocr original weights via ONNX; background OCR ahead of the reader | Fixes silent text loss; zero-wait study; Torch-free. **The recogniser choice is unchanged, because the existing benchmark correctly kept it.** |
| **Translation** | OPUS-MT default for everything; replaces Japanese in the page; experimental engines via env var | Per-bubble answer key, collapsed by default; Hy-MT2 default when hardware allows; OPUS-CT2 light fallback; selectable in the UI | The translation's role changes from output to hint; a better model where affordable; visible engine choice |
| **User experience** | Drag-select per bubble, or translate the whole chapter into English | Page is pre-read; hover/click any bubble; J/K navigation; keyboard actions | Removes repeated selection effort; keeps Japanese in view |
| **Japanese learning** | Per-token UniDic cards with all homograph senses, raw Japanese POS tags, no furigana, no saving | Meaning units (longest match + deinflection), ranked senses, grammar notes, furigana, OCR edit, save to Anki, known words | This is the product's reason to exist; the current output misleads (は → "feather") |
| **Storage** | Opt-in pixel-bearing stage cache; separate glossary DB; `chrome.storage` history (100 entries) | `user.db` (deck, known words, corrections), text-only `cache.db` on by default, read-only dictionary DBs | User data lives where it can grow and be exported; caching that is private enough to enable by default |
| **Performance** | CPU-only Torch; ~20 s startup; 4–8 s/page CPU; detector 1 s | ONNX/CT2/llama.cpp; GPU where present; INT8 detector ~0.1 s; background prefetch hides latency | Measured wins already in the repo, plus hardware the user has |
| **Rendering** | Conservative mask/inpaint/typeset, transactional — **good** | Kept unchanged as optional Glance mode | **The existing implementation is better than anything I would rebuild.** It just shouldn't be the main mode. |
| **Engineering process** | Thorough tests; pinned models; measured adoption decisions; dense docs; purely additive | Keep the tests, pinning and measurement; adopt a "delete or move experiments" rule; shorter docs (a 1-page README, architecture, decision records) | Keeps the good discipline and reduces drag |
