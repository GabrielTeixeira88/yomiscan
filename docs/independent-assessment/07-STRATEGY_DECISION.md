# 07 — Strategy Re-evaluation and Final Recommendation

Date: 2026-11-23. This document revisits 04 (vision) and 05 (roadmap) using the
owner's answers to the blocking questions. **It supersedes the roadmap in 05.**

## Owner's answers (inputs to this decision)

| Question | Answer | Consequence |
|---|---|---|
| Q1 Who is it for? | The owner now, and **the public as a Chrome extension** later | Installation, size and hardware tolerance become first-class requirements |
| Q2 Keep automatic English typesetting? | **Not sure** | Don't delete it. Don't invest in it. Keep it as a mode, and decide from usage. |
| Q3 Reading sources? | **Web readers** (raw manga is hard to get from official stores; local files don't fit an extension) | Local-file reader dropped. Web-reader discovery and region selection stay central. |

---

## 1. The factor my first assessment underweighted

My earlier vision treated "extension + local Python engine" as settled and only
improved how it is launched. **For a public Chrome extension, a mandatory Python
backend is the single biggest product risk, bigger than any code-quality issue.**

What a public user would face with the current architecture, even with a polished installer:

- A separate native installer next to the Web Store install. It is unsigned, so
  SmartScreen warns, unless code signing is paid for every year.
- About **2.8 GB** today (1.1 GB Python environment + 1.6 GB models + dictionary).
  Torch-free could bring that to about 1 GB.
- A background process, and a native-messaging registration per OS.
- The extension does nothing until all of that works.

Most Web Store users who install an extension and see "now install this separate
program" leave. Every comparable *public* Japanese-learning extension, Yomitan being
the most successful, runs entirely in the browser.

So the real strategic question is not only "rewrite or improve the code". It is also
**"where does the engine run for public users?"** That question cannot be answered from
the desk. It needs a short, measured feasibility spike (§5, Stage 2).

### What in-browser could plausibly look like (unverified, to be spiked)

| Component | In-browser candidate | Confidence before spike |
|---|---|---|
| Text detection | Same ogkalu INT8 ONNX detector (11 MB) on ONNX Runtime Web (WASM/WebGPU) | High. Small model, standard ops. |
| OCR | manga-ocr (original weights) exported to ONNX, quantized; ONNX Runtime Web with WebGPU, WASM fallback | **Medium–low. The decisive unknown.** About 110–450 MB download, and CPU-WASM latency per block unknown. |
| Tokenizer | kuromoji.js / lindera-wasm / Sudachi-wasm | High. These are mature. |
| Dictionary | JMdict in IndexedDB (the way Yomitan does it) | High. A proven pattern. |
| Translation | **Chrome's built-in on-device Translator API** (free, no paid API, on-device after a one-time model download), and/or OPUS-MT in Transformers.js | Medium. Language-pair availability, quality and hardware requirements must be verified. A built-in browser model is not open source, which is a philosophical trade-off to accept explicitly. |
| Typesetting (English mode) | HTML text boxes over bubbles instead of pixel inpainting | High, but visually cruder than the current renderer |

If the spike succeeds, the public product is a **single Web Store install**. The local
Python engine would then become an *optional power mode* (better OCR speed on GPU,
local LLM translation, the pixel renderer). If the spike fails, the backend stays
mandatory, and I invest in making its installation as painless as possible.

---

## 2. Challenging my own previous assessment

| My earlier claim | Re-examined | Verdict |
|---|---|---|
| The lexical layer needs a rewrite (deinflector, longest-match engine) | **UniDic already deinflects** (行か → 行く, with conjugation type/form). Most of a Yomitan-style deinflector is redundant here. What is missing is *chunking* (verb + auxiliaries → one unit), *ranking* (JMdict priority + POS/reading agreement), a *function-word table*, *longest-match over adjacent tokens*, and *English labels* for UniDic conjugation forms. | **These are targeted fixes, not a rewrite.** About 1.5–2.5 weeks instead of 3–4. The data (rules, tables, golden tests) can be language-neutral, so it survives a later port to TypeScript. |
| The Study popup must become a side panel built with Preact | The popup's *content model* is the problem, not its container. A redesigned popup with ranked units, grammar labels and folded detail fixes about 80% of the issue. | **The side panel is postponed.** It is reconsidered once clickable reading mode exists, because then a persistent panel earns its cost. Preact for new UI only. |
| Automatic page OCR should be the default instead of screenshot selection | Selection works on **every** site, including canvas readers. It needs only `activeTab`, costs compute only on demand, and has no image-host permission prompts. Those properties matter a lot for a public extension. Auto-OCR is better UX *where discovery works*, but costs constant compute and per-host permissions. | **Both, with selection as the universal baseline.** Fix multi-block selection, then add opt-in **"Read this page"** (clickable Japanese) per site. |
| Clickable text regions are a new workflow needing new architecture | `/api/v1/analyze-page` already returns blocks with OCR and full analysis. `chapter/region-inspector.ts` + "Study Bubble" already opens the popup from retained page analysis without new OCR. | **Mostly existing infrastructure.** Reading mode = chapter pipeline with rendering skipped + inspector always on + hover. About 2–3 weeks, not a new subsystem. |
| Remove the rendering system / demote it | It works, it is the best-engineered image code in the repo, and the owner is unsure about it. | **Keep it unchanged as the "English overlay" toggle.** Zero investment until usage data says otherwise. |
| Replace the stage-cache/lineage system, delete the diagnostics ZIP, glossary, progress registry | Deleting working, tested infrastructure costs time and risks regressions. It also delivers nothing to users. The real problem is that they clutter the **UI** and the **runtime defaults**. | **Hide, don't rip out.** Remove the controls from the user panel (move them behind a developer toggle). Move the experimental engines and benchmarks to `research/`. Delete code only when a later change makes it dead. |
| Native-messaging launcher, random port, bearer token | Needed only if the backend stays mandatory for the public. For the owner, making the port configurable (fixing the AnkiConnect clash) is a small change. | **Depends on the Stage 2 gate.** |
| Torch-free engine (ONNX + CTranslate2) | It matters for public install size. Doing it before the gate could be wasted if the engine moves to the browser. The ONNX detector is already integrated and 10× faster. | **Switch the detector default now.** OCR export work happens inside the spike, because the browser needs it too. |
| Grammar-pattern table of ~150 patterns | High authoring cost. Conjugation-chain labels from UniDic cover the most frequent confusion cheaply. | **Start with ~30 high-frequency patterns.** Grow from logged gaps. |
| Model manager with Light/Standard/Experimental profiles | Over-specified before the engine location is known. | **Postponed.** |
| Many of the observed problems are architectural | Re-examined one by one (table below). | **Almost all are implementation-level.** The only truly architectural issue is *distribution*. |

### Problem classification

| Problem (from 02/03) | Root cause | Fix type |
|---|---|---|
| は → "feather/tooth/blade" | Unranked lookup, kana homograph match, priority tags discarded | Targeted (importer v2 + ranking + function-word table) |
| 万年 / しょうがない not found | Per-token lookup | Targeted (longest match over adjacent tokens) |
| Raw Japanese POS and conjugation codes | Presentation | Targeted (label mapping) |
| Multi-block selection drops text | Study path skips the detector | Targeted (run detector on the crop) |
| Weak OPUS translations | Model choice | Targeted (engine selection; Hy-MT2 or Chrome Translator, measured) |
| GPU unused | Lockfile resolves CPU Torch | Targeted (uv index config) — owner-relevant only |
| Port 8765 clash | Hard-coded URL | Targeted (configurable port) |
| 30-button panel, developer tools exposed | UI scope | Targeted (redesign the panel) |
| Repeated drag-selection effort | Workflow | Moderate (reading mode reusing existing pipeline) |
| AU-01..AU-09 edge-case defects | Bugs | Targeted |
| **Public users must install Python + 2.8 GB + a background server** | **Architecture** | **Architectural decision, gated by the Stage 2 spike** |

**Conclusion of the self-review:** a full rewrite (Option A) would solve exactly one
problem the targeted path cannot solve, namely distribution. That one problem doesn't
require rewriting everything. It requires deciding where *inference* runs.

---

## 3. The three options compared

Scores: ●●● strong, ●● adequate, ● weak.

| Criterion | A — Full independent rewrite | B — Improve existing | C — Hybrid (recommended variant) |
|---|---|---|---|
| Final product quality | ●●● if finished; high risk of an unfinished product | ●● good for the owner; the public install remains a barrier | ●●● |
| OCR & translation quality | ●● same models; quality differences come from the pipeline, not a rewrite | ●● with targeted fixes | ●●● targeted fixes + measured engine choice + optional browser engine |
| Japanese learning experience | ●●● | ●●● the fixes are targeted anyway | ●●● |
| UI/UX possibilities | ●●● | ●● constrained by the current panel/popup code | ●●● new UI where it matters; reuse elsewhere |
| Architecture & maintainability | ●●● clean slate | ● keeps current density and sprawl | ●● clean new pieces; legacy hidden/quarantined |
| Development complexity | ● highest | ●●● lowest | ●● |
| Development time to public beta | **~20–28 weeks** | ~8–11 weeks (backend-mandatory product) | **~13–20 weeks**, depending on the gate |
| Technical risk | ● high (re-discovering solved browser/acquisition edge cases) | ●●● low technical risk, ● high adoption risk | ●● spike de-risks the main unknown early |
| Reuse of existing code | ● low by design | ●●● | ●●● (most of the browser infrastructure and pipeline) |
| Long-term extensibility | ●●● | ● | ●●● |

**Why not A.** The parts I'd rewrite for their own sake are mostly the ones that
already work: acquisition, discovery, the queue, the security guard, the renderer.
The acquisition and queue code encodes many browser edge cases (DPR, lazy loading,
stale jobs, scroll restore), and a rewrite would rediscover them slowly. A rewrite also
doesn't change any model's accuracy.

**Why not plain B.** B produces a good tool for the owner and a product the public
mostly won't install. It also keeps the in-place sprawl (30-button panel, experiments
in the runtime package) unless B is stretched into C anyway.

---

## 4. Final recommendation: Option C — "staged hybrid with a distribution gate"

**How it differs from plain C:** an explicit, early **feasibility gate** decides whether
the public product runs inference **in the browser** (backend optional) or **on a local
engine** (backend mandatory, installer required). Everything before the gate is useful
under both outcomes. That keeps throwaway work small.

### 4.1 Preserve

| Component | Why |
|---|---|
| Extension acquisition chain, discovery, queue, overlay geometry, selection overlay (`chapter/acquisition.ts`, `source-fetch.ts`, `stitching.ts`, `discovery.ts`, `model.ts`, `overlay.ts`, `content.ts`, `geometry.ts`) | Hard-won browser edge-case handling; engine-agnostic |
| Popup shell (drag/resize/Escape/Shadow DOM) | Works; only its content changes |
| Backend worker model, security guard, image validation (`api/main.py` lifespan, `api/security.py`, `api/images.py`) | Correct and tested |
| Detector, OCR, Marian and llama.cpp adapters behind their Protocols | Swappable; the llama.cpp lifecycle is already done |
| JMdict importer (extended, not replaced) | Streaming, atomic, provenance |
| Renderer (`rendering/*`) | The best image code in the repo; kept as the English overlay mode |
| Test suites, CI, pinned-model / no-silent-download policy | Discipline worth keeping |

### 4.2 Redesign or replace

| Component | Change |
|---|---|
| Lexical lookup (`analysis.py` lexical part, `dictionary/*`) | Importer v2 (priorities, tags), ranking, function-word table, longest match, unit chunking, English conjugation labels, ~30 grammar patterns. **All rules and tables are stored as data**, with language-neutral golden tests. |
| Study popup content (`popup.ts`) | Sentence with furigana, ranked meaning units, grammar notes, folded alternatives, translation as a labelled section, OCR edit |
| Study OCR path (`analysis.analyze_image`) | Detect on the crop, then OCR per block |
| Translation engine selection | UI-selectable, measured default (Hy-MT2 / OPUS / Chrome Translator candidates) |
| Chapter control panel (`chapter/controls.ts` and siblings) | Small user panel: Select, Read page, English overlay, Stop. Everything else goes behind "Developer" |
| Backend URL and port | Configurable; never 8765 by default |
| Experimental engines/benchmarks | Move to `research/`, excluded from the wheel |
| *If the gate selects browser-first:* inference and lexical engine | Ported to the extension (ONNX Runtime Web, IndexedDB JMdict, JS tokenizer). The Python engine becomes an optional power mode. |

### 4.3 Postponed or removed

| Item | Decision |
|---|---|
| Side panel | Postponed until reading mode ships; reconsidered then |
| Preact migration of existing UI | Removed (new UI only) |
| Native-messaging launcher + token | Only if the gate keeps the backend mandatory |
| Model manager profiles | Postponed until after the gate |
| 150-pattern grammar table | Reduced to ~30, then grows |
| Local CBZ reader | **Removed** (owner Q3) |
| LLM "explain this sentence" | Postponed (hallucination risk; owner Q12 open) |
| Glossary UI, PT/ES targets, NLLB/Qwen/VNTL | Hidden or moved to `research/` |
| Deleting stage cache / diagnostics / progress code | Not done proactively; deleted only when dead |
| Improvements to the English renderer | None until usage data answers Q2 |

### 4.4 Expected effort (one experienced developer, focused weeks; estimates)

| Stage | Weeks |
|---|---:|
| 1 Quick wins + evaluation sets | 1.5–2 |
| 2 Distribution feasibility spike + gate | 2–3 |
| 3 Learning core (lexical + popup + translation choice) | 3–4 |
| 4 Reading mode (clickable Japanese, English toggle) | 2–3 |
| 5a *If browser-first:* port inference + lexical engine to the extension | 5–7 |
| 5b *If backend-mandatory:* Torch-free engine + installer + native host | 3–4 |
| 6 Capture (Anki, known words) + Web Store release prep | 2–3 |
| **Total to public beta** | **≈13.5–19 (backend path) / ≈15.5–22 (browser path)** |

The owner gets a much better personal tool after Stages 1 and 3, at about 6–9 weeks,
whichever way the gate goes.

### 4.5 Biggest technical risks

1. **In-browser OCR feasibility.** Model size, WASM CPU latency, and WebGPU
   availability. *Mitigation:* this is precisely what the gate measures, with
   predefined thresholds.
2. **Chrome Translator API availability and quality for ja→en.** Hardware, model
   download behaviour, extension-context access. *Mitigation:* measured in the spike
   against OPUS and Hy-MT2 on the same lines. It is one candidate, not an assumption.
3. **Web-reader fragility.** Sites change markup, and some move to canvas.
   *Mitigation:* selection-with-detection is the universal fallback.
4. **Store and legal exposure.** The raw manga that web readers serve is largely on
   unofficial aggregator sites. A public listing must stay generic: no site names, no
   bypassing of protections. The existing acquisition code already refuses bypasses.
   This is a policy risk, not a code risk, and it should get a deliberate decision before publishing.
5. **Scope creep** (the history is purely additive). *Mitigation:* every stage has an
   exit gate, and failed experiments move to `research/` within the same stage.

### 4.6 The resulting YomiScan experience

- **Install:** one Chrome Web Store install (browser path). The first use downloads the
  OCR model and dictionary (~150–500 MB), with a progress screen. Alternatively, on the
  backend path, the install is an extension plus a one-click companion installer. Power
  users can add the local engine for GPU speed and LLM translation in either case.
- **Any site:** press Ctrl+Shift+Y and drag over one bubble or a whole panel. Every text
  block in the selection is read. The popup shows the sentence with furigana, words
  grouped into meaning units with the *right* meaning first (は = topic particle),
  English labels for conjugations ("negative conditional, casual"), short grammar
  notes, an editable OCR line, and a labelled translation. One click saves to Anki.
- **Supported image readers:** click **Read this page**. Bubbles get faint outlines.
  Hover or click any bubble to get the same study card instantly, and J/K steps through
  bubbles. **English overlay** swaps in the existing typeset translation per page for
  readers who just want to get through it.
- **Privacy:** images and text stay on the machine. No accounts, no paid APIs.

---

## 5. Revised roadmap

### Stage 1 — Quick wins and measurement (1.5–2 weeks) — useful under any outcome
- Study path: detector on the selection, OCR per block, text joined in reading order.
- Configurable backend port (default not 8765); fix the Save button sizing; AU-01 navigation guard.
- Import JMdict priority tags; rank senses; hide homograph noise for particles (interim function-word list).
- ONNX INT8 detector as default (gate: recall parity on the corpus).
- Owner-only: CUDA-enabled Torch via a uv index for the local GPU.
- Build the **evaluation assets**: 40–60 pages across ≥6 series (local, gitignored,
  annotations only in Git), a ~150-sentence lexical golden set, and a ~150-line translation set.
- **Exit:** は/よ/た show their function-word meaning; a multi-bubble selection returns all text; baselines are recorded.

### Stage 2 — Distribution feasibility spike (2–3 weeks) — **the gate**
- Export manga-ocr (original weights) to ONNX; test quantized variants; run them in
  ONNX Runtime Web (WebGPU + WASM) in an extension offscreen document.
- Run the detector in the browser; JMdict in IndexedDB; a JS tokenizer comparison against UniDic on the golden set.
- Translation bake-off on the translation set: OPUS (Python and Transformers.js), Hy-MT2
  (llama.cpp), Chrome Translator API. Blind ratings.
- **Gate (proposed thresholds, to confirm before the spike):** browser OCR CER within
  +1 point of PyTorch on the corpus; ≤0.5 s/block on WebGPU and ≤2 s/block on WASM on a
  mid-range laptop; total first-run download ≤600 MB. **Pass → browser-first
  (Stage 5a). Fail → backend-mandatory (Stage 5b).**
- The spike's output is a decision record with measurements. No product code is merged.

### Stage 3 — Learning core (3–4 weeks)
- Lexical v2 as data-driven rules: longest match, unit chunking, ranking,
  function-word table, conjugation labels, ~30 grammar patterns, furigana alignment.
- Popup redesign with OCR edit → re-analysis.
- Translation engine selectable in the UI; default chosen from the Stage 2 ratings.
- User panel reduced to essentials; developer controls hidden; experiments moved to `research/`.
- **Exit:** ≥90% on the lexical golden set; a usability check of 20 bubbles across 3 sites.

### Stage 4 — Reading mode (2–3 weeks)
- "Read this page": chapter pipeline with `analyze-page` (no rendering), text outlines,
  hover/click → study card, J/K navigation, prefetch of the next pages.
- English overlay toggle per page, using the existing renderer unchanged.
- **Exit:** a reader studies 20+ bubbles without dragging on 3 supported sites. The first card appears ≤1 s after page OCR.

### Stage 5a — Browser-first engine (5–7 weeks) — if the gate passes
- Port detection/OCR/lexical to the extension (offscreen document, ONNX Runtime Web,
  IndexedDB). Reuse Stage 3's rule data and golden tests.
- English overlay in browser mode = HTML text boxes; the pixel renderer remains in the optional local engine.
- Optional "local engine" setting connects the existing Python backend for GPU/LLM.

### Stage 5b — Packaged local engine (3–4 weeks) — if the gate fails
- Torch-free engine (ONNX OCR/detector, CTranslate2 OPUS, llama.cpp Hy-MT2).
- Windows installer, frozen engine, native-messaging launcher, random port + token, idle shutdown.

### Stage 6 — Capture and public release (2–3 weeks)
- Save word/sentence; AnkiConnect export; CSV; known words → unknown-only furigana.
- Web Store listing, privacy policy, attribution (JMdict/KANJIDIC CC BY-SA), first-run onboarding, README rewrite.

---

## 6. Decisions needed from the owner before implementation starts

1. **Approve Option C with the distribution gate** (or choose another option).
2. **Confirm the gate thresholds** in Stage 2, or adjust them.
3. **Is a Chrome built-in translation model acceptable?** It is on-device and free, but
   not open source. If not, the bake-off covers only open models.
4. **Starting point:** Stage 1 on a new feature branch from `main`, as `AGENTS.md`
   requires. Nothing will be implemented until you approve.
