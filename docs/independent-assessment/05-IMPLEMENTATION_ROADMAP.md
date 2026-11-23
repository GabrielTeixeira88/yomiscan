# 05 — Implementation Roadmap

> **Superseded by [07-STRATEGY_DECISION.md](07-STRATEGY_DECISION.md)**, which revises this
> roadmap after the owner's answers (public Chrome extension, web readers only). It is
> kept for traceability.

This roadmap builds the product described in 04, starting from the existing repository.

## 0. Strategy: evolve, don't restart

I recommend **an incremental rebuild inside this repository, not a greenfield rewrite.**
About half the existing code is worth keeping: acquisition, discovery, the queue, the
security guard, the importer, the adapters, the renderer and the tests (02 §11, 04 §5).
The rewrite is concentrated where the product changes: the lexical engine, the study
UI, the result format, and the engine lifecycle.

Ground rules for the work:

- One descriptive feature branch per milestone, following the existing `AGENTS.md` convention.
- The `/api/v1` endpoints keep working until the v2 extension replaces them. Then
  remove v1 **and its code**.
- Every milestone ends with a **measured gate** on the evaluation set, not only passing tests.
- Experiments that don't pass a gate are moved out of the runtime package within the same milestone.

Effort figures are **rough estimates for one experienced developer**, expressed as
focused working weeks. They are planning aids, not commitments. AI-assisted development
may compress the coding, but it does not compress evaluation and content authoring.

---

## Milestone 0 — Decide and measure (≈1–1.5 weeks)

**Goal:** make the decisions in 06 and build the evaluation assets that every later gate depends on.

| Task | Output |
|---|---|
| Answer the blocking questions in 06 (users, reader sources, hardware, keep/demote chapter English) | Short decision record in `docs/decisions/` |
| **Evaluation corpus:** 40–60 pages from at least 6 series and genres (shōnen, shōjo, seinen, slice-of-life, a dense narration-heavy title, an SFX-heavy action title). Kept locally and gitignored; only annotations and hashes are versioned. | `eval/pages.json` (hashes, block boxes, reference text, reading order, kind) |
| **Lexical golden set:** ~150 sentences with expected meaning units, deinflection chains and the top sense for key tokens | `eval/lexical.jsonl`, run by pytest without models |
| **Translation set:** reuse the 53-line set, add ~100 real lines from the corpus, and use a blind A/B rating sheet | `eval/translation.jsonl` |
| Baseline measurements of the current system on the corpus | `eval/baseline.md`: detection recall, OCR CER, ordering accuracy, time per page CPU/GPU |

**Exit gate:** baseline numbers are recorded, and the decisions in 06 are made.

## Milestone 1 — Engine foundation (≈2–3 weeks)

**Goal:** a faster, Torch-optional, auto-started engine that returns structured page text.

| Task | Notes |
|---|---|
| Package split: `vision/`, `language/`, `translate/`, `store/`, `models/`, `api/v2` | Move existing modules; no behaviour change at first |
| Make the INT8 ONNX detector the default | **Gate:** recall ≥ PyTorch recall on the corpus (−1 block tolerance per 100) |
| Export the original manga-ocr weights to ONNX (encoder/decoder + KV) | **Gate:** identical text on ≥99% of corpus blocks; any differences reviewed by hand. If it fails, keep PyTorch OCR as an extra and proceed. |
| Enable a GPU execution provider when available (CUDA; DirectML/WinML to benchmark) | Measure time per page on CPU and GPU |
| `POST /v2/pages` → JSON blocks; text-only `cache.db` keyed by `(image SHA-256, pipeline version)` | Replaces the stage-cache lineage for v2 |
| Two-priority single-worker scheduler | Interactive requests preempt queued background pages |
| Native-messaging launcher: start-if-needed, random port, per-launch token, idle shutdown | Windows registry registration script first; Linux manifest next |
| Port OPUS to CTranslate2 int8; keep Hy-MT2 through the existing llama.cpp adapter | Translation stays out of the page path; on demand only |

**Exit gate:** the corpus is processed end-to-end through v2. Measured time per page is
reported. A clean machine starts the engine from the extension without a terminal.
The default install contains no Torch.

## Milestone 2 — Lexical engine v2 (≈3–4 weeks; the most important milestone)

**Goal:** the Study Card gives correct, ranked, meaning-unit analysis.

| Task | Notes |
|---|---|
| JMdict importer schema v2: forms with priority, `re_restr`, misc/field tags, "usually kana" | Keep streaming + atomic swap; bump schema version |
| Grammar-word table for particles, auxiliaries and copula (~80 items) | Replaces JMdict lookups for function words |
| Deinflection rule table (project-authored) | Each rule labelled for display (e.g., "negative conditional, colloquial") |
| Colloquial normaliser (~40 rules) | ねえ→ない, ちゃう→てしまう, てる→ている, … |
| Longest-match scanner over UniDic boundaries, plus ranking | POS/reading agreement → priority → usually-kana |
| Grammar-pattern matcher + first 50 patterns (N5–N4) | YAML: matcher, English one-liner, JLPT level, example |
| Furigana aligner | Kanji-span alignment with a whole-word fallback |
| `POST /v2/analyze` | Returns units, ranked senses, patterns, furigana |

**Exit gate:** ≥90% of the lexical golden set's expected meaning units and top senses
are correct. For example, は is a particle, 万年 is one unit, and しょうがねえ maps to
しょうがない. Each analysis takes under 50 ms on CPU.

## Milestone 3 — Reading & Study UI (≈3–4 weeks)

**Goal:** the core loop from 04 §2.1 works on supported image readers.

| Task | Notes |
|---|---|
| Extension restructure: Preact side panel, page-layer content script, background router | Discovery, acquisition and queue reused with JSON results |
| Text layer: positioned, selectable Japanese per block; hover outline; click → panel | Check that **Yomitan can scan it** (light DOM or open shadow root; see 06 Q9) |
| Study Card: sentence + furigana toggle, meaning units, grammar notes, collapsed translation, other entries | Keyboard: J/K, T, E, S, Esc |
| OCR edit → `/v2/corrections` → re-analysis; corrections persisted | |
| Region select runs detection on the crop and returns several blocks | Add a navigation generation to the selection ticket (fixes AU-01) |
| Per-site enable, setup/readiness page in the side panel | Replaces the 30-button floating panel |
| Remove the v1 chapter-rendering path from the extension | The renderer stays in the backend for Glance |

**Exit gate:** a blind user session on 3 different sites. A learner reads 10 pages and
studies at least 20 bubbles without touching a terminal or a drag-selection on supported
readers. Time-to-first-card on a visible page is ≤1 s after background OCR completes.

**➜ End of MVP (≈9–12.5 weeks cumulative).**

## Milestone 4 — Capture & personalisation (≈2–3 weeks)

| Task | Notes |
|---|---|
| `user.db`: deck entries, known words, settings; export/backup | Migrate optional history from `chrome.storage` |
| Save word / sentence card (with optional bubble crop) | URL saving off by default |
| AnkiConnect push with configurable note type and field mapping; CSV export | The engine and AnkiConnect no longer collide on ports |
| Known words → unknown-only furigana and new-word highlighting | Optional JLPT-threshold seeding (licence permitting, 06 Q7) |
| KANJIDIC2 importer + kanji panel | CC BY-SA attribution |
| Grammar patterns expanded to ~150 (N3–N2) | Content work; can run in parallel |

**Exit gate:** saved cards appear correctly in Anki. Known-word marking measurably
reduces furigana on a re-read page.

## Milestone 5 — Translation tiers & distribution (≈2–3 weeks)

| Task | Notes |
|---|---|
| Blind A/B rating of OPUS-CT2 vs Hy-MT2 (and any newer small model) on the translation set | Choose defaults per profile from the ratings, not from impressions |
| Model manager: manifest, Light/Standard profiles, GPU detection, verified resumable downloads | Replaces `readiness.py`, `vision_models.py`, `setup_models.py` |
| Windows installer: frozen engine + native host registration + first-run setup page | Decide signing per 06 Q10 |
| Linux packaging (AppImage or a `uv tool` based install) | macOS only if 06 Q4 says so |
| Docs reset: 1-page README, architecture, decision records; history moved to `docs/history/` | |

**Exit gate:** clean Windows VM → installer → first card in under 10 minutes, excluding
download time. The translation default is justified by the ratings.

## Milestone 6+ — Optional (ordered by expected value)

1. **Glance mode**: wire the existing renderer to a per-page toggle and return a PNG on
   request only. About 1 week, because the renderer already exists.
2. Local CBZ/folder reader page (about 2 weeks).
3. Opt-in "Explain this sentence" with a local instruct LLM, clearly labelled, and
   evaluated on the golden set for hallucinated grammar (about 2 weeks + evaluation).
4. In-browser ONNX detection for instant outlines (about 1–2 weeks).
5. Source-furigana capture, Firefox port, extra gloss languages.

---

## Risk register

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| manga-ocr ONNX export doesn't match PyTorch output | Medium | Medium | Keep PyTorch OCR as an optional extra; Torch-free becomes "Light without OCR parity" |
| The ONNX detector underperforms on the wider corpus | Low–Medium | Medium | The PyTorch detector remains selectable; decide from data |
| The text layer conflicts with site CSS/JS or Yomitan can't scan it | Medium | High (core UX) | Prototype in week 1 of Milestone 3 on 3 sites; the side-panel click flow works even if Yomitan doesn't |
| Grammar/deinflection authoring takes longer than planned | High | Medium | Ship 50 patterns at MVP; expand iteratively from logged "unexplained" chains |
| Reader sites change markup or move to canvas | Medium | Medium | Region select with detection is the universal fallback; a local reader is the long-term hedge |
| Native messaging install friction on Linux/macOS | Medium | Low | Fallback: a manual "start engine" command with a pairing code |
| Scope creep (re-adding the experiment zoo) | High (given the history) | High | Each milestone's exit gate; "move or delete" rule for failed experiments |

## Migration and removal checklist

- [ ] v2 endpoints live → extension switched → **delete** `/api/v1/render-page`
      orchestration, `progress.py`, stage lineage caching, the diagnostics ZIP and
      `chapter/zip.ts`, the glossary endpoints and UI, region-inspector leases.
- [ ] Move `translation/manga.py` (except the llama.cpp lifecycle), `nmt.py`,
      `experiments.py`, `structured.py`, `benchmark.py` and `vision_benchmark/` into
      `research/`. It is excluded from the wheel.
- [ ] Re-import JMdict (schema v2). Document the step for existing users.
- [ ] Remove the hard-coded `127.0.0.1:8765` everywhere.
- [ ] README rewritten to describe current behaviour only; phase history moved under `docs/history/`.
