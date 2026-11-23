# Independent assessment — summary and status

This directory holds an independent product and engineering assessment of YomiScan.
It was produced in a separate, read-only reference clone (`YomiScan-Independent`,
cloned at `178e506`) and copied here unchanged on 2026-11-23. The documents are
**proposals and evidence, not current behaviour**. The application's current
behaviour is still described by the root `README.md` and `docs/architecture.md`.

**Status labels in this summary**

| Label | Meaning |
|---|---|
| **Verified** | The assessing agent ran or measured it, or read the code path, at baseline `178e506` |
| **Recommendation** | The agent's proposal; not adopted until approved |
| **Hypothesis** | Plausible but untested; needs the Stage 2 spike or another measurement |
| **Owner decision** | Decided by the owner (listed with its scope) |
| **Pending approval** | Needs an owner decision before work starts |

## Why the assessment was done

An agent with no prior involvement was asked to inventory what actually works,
audit the implementation, evaluate the product for Japanese learners, and propose how
it would build YomiScan from scratch. It then compared that against improving the
existing code. The aim was a second opinion that neither defends nor discards the
existing decisions.

## Documents

| File | Phase | Contents |
|---|---|---|
| [01-PROJECT_UNDERSTANDING.md](01-PROJECT_UNDERSTANDING.md) | Initial assessment | Purpose, history, **feature inventory with status and evidence**, what was and wasn't verified |
| [02-IMPLEMENTATION_AUDIT.md](02-IMPLEMENTATION_AUDIT.md) | Initial assessment | Architecture, strengths, defects D1–D9, overcomplication, docs-vs-code contradictions |
| [03-PRODUCT_ASSESSMENT.md](03-PRODUCT_ASSESSMENT.md) | Initial assessment | UX, learning experience, OCR/translation quality |
| [04-INDEPENDENT_VISION.md](04-INDEPENDENT_VISION.md) | Initial assessment | From-scratch vision, architecture, feature tiers, comparison table. Parts are **revised by 07**. |
| [05-IMPLEMENTATION_ROADMAP.md](05-IMPLEMENTATION_ROADMAP.md) | Initial assessment | First roadmap. **Superseded by 07** (banner added at the top). |
| [06-OPEN_QUESTIONS.md](06-OPEN_QUESTIONS.md) | Initial assessment | Questions Q1–Q21, assumptions, unverified areas |
| [07-STRATEGY_DECISION.md](07-STRATEGY_DECISION.md) | **Revised recommendation** (after owner's answers to Q1–Q3) | Options A/B/C compared, self-critique of 04/05, **Option C with a Stage 2 gate**, revised roadmap |

There is one version of each file. Where 07 contradicts 04 or 05, **07 is the current
recommendation**.

## Most important findings (Verified at `178e506`)

- **Tests pass:** backend 316 passed / 1 skipped; extension 68 passed; typecheck clean.
  The tests are model-free, so they do not measure learner-facing quality.
- **The dictionary output misleads learners.** Lookup is per token, unranked, and
  matches every kana homograph. With the real JMdict, particle は shows "feather / tooth /
  blade" first, and しょう returns 41 entries. Expressions that exist in JMdict (万年,
  しょうがない, なきゃいけない) are never found. Priority tags are discarded at import.
  (02 §3.1, 03 §3.2)
- **Study selection silently drops text.** The whole selection is OCR'd as one block.
  A selection containing 2 detected blocks returned only one. (02 §3.2)
- **The default translation (OPUS-MT) makes meaning errors on manga dialogue**, for
  example a wrong character name and 万年４級 → "Four-year-olds". (01 §4.1)
- **The renderer is the strongest image code in the repo**, and its visual cleaning is
  good. Text "outside bubbles" is mostly *preserved by the renderer* rather than
  *missed by the detector*. (02 §2, 03 §3.3)
- **The GPU is unused.** The lockfile resolves `torch+cpu`. Startup takes about 20 s,
  and a page takes 4–8 s on CPU. (02 §6)
- **The backend port 8765 is hard-coded in 7 places and clashes with AnkiConnect's
  default.** (02 §3.5)
- **The UI is overloaded:** about 30 controls, developer diagnostics included, in the
  end-user panel. The history is purely additive, with no experiments removed. (02 §4–5)
- The evaluation corpus behind every model decision is 3 pages from one series. (01 §5)

The audit commit `ecb51ca` (AU-01…AU-10), unmerged when the assessment was written and
merged as PR #6 on 2026-11-23, is cited as supporting evidence. The
agent agreed with it from the source but did not re-run its probes.

## Recommended strategy: Option C — staged hybrid with a distribution gate

**Owner decision: approved**, as a strategy. It is not authorisation to implement.

- **Preserve** (Recommendation): extension acquisition, discovery, queue, overlay and
  selection code; backend worker model, security guard and image validation; the
  engine adapters; the JMdict importer (extended); the renderer as an "English overlay"
  toggle; the tests, CI and pinned-model policy.
- **Redesign** (Recommendation): lexical lookup, as data-driven targeted fixes rather
  than a rewrite; Study popup content; Study OCR (detect first); a UI-selectable
  translation engine; a reduced control panel; a configurable port; experiments moved to `research/`.
- **Postpone or remove** (Recommendation): side panel, Preact migration, model
  profiles, a large grammar table, the local CBZ reader (removed per the owner's Q3
  answer), LLM explanations, new renderer work.
- **Problem classification** (07 §2): every identified problem except *public
  distribution* can be fixed with targeted changes. The only genuinely architectural
  question is where inference runs for public users.

## Browser-first architecture with an optional local engine (Hypothesis)

The owner plans a **public Chrome extension** and reads from **web readers**. A
mandatory Python backend plus about 2.8 GB of downloads and a background server is
therefore the biggest adoption risk. The proposal, **conditional on the Stage 2 gate**:

- **If the gate passes:** detection, OCR, tokenization and JMdict run *inside the
  extension* (ONNX Runtime Web with WebGPU/WASM in an offscreen document; JMdict in
  IndexedDB; a JS tokenizer). The existing Python backend becomes an **optional local
  companion engine** for GPU speed, local LLM translation and the pixel renderer.
- **If the gate fails:** the backend stays mandatory and is packaged: Torch-free
  runtime, Windows installer, native-messaging launcher, random port plus token.

Nothing about the browser-first path has been tested yet.

## Stage 2 feasibility tests and gate

Stage 2 is a 2–3 week spike. Its output is a measured decision record; no product code
is merged. It includes:

1. Export manga-ocr's original weights to ONNX, test quantized variants, and run them
   in ONNX Runtime Web (WebGPU and WASM).
2. Run the detector in the browser; JMdict in IndexedDB; compare a JS tokenizer with UniDic on the lexical golden set.
3. A translation bake-off with blind ratings: OPUS (Python and Transformers.js),
   Hy-MT2 (llama.cpp), and the **Chrome built-in Translator API**.

**Owner decision on the Chrome Translator:** approved **for evaluation only**, as an
optional experimental provider. It must not become a mandatory dependency or replace
the local translation engines. Its proprietary nature is acceptable for testing.
*Conflict to note:* 07 §4.2 and Stage 3 say the default engine is "chosen from the
Stage 2 ratings", with Chrome Translator among the candidates. Under the owner's
decision, it can be offered but **cannot be the default or the only engine**.

### Proposed pass/fail thresholds — **Owner decision: approved as resolved**

On 2026-11-23 the owner accepted the resolution of every ambiguity below. The binding
version is [docs/decisions/stage-2-feasibility-gate.md](../decisions/stage-2-feasibility-gate.md)
(criteria G1–G8 and PASS / CONDITIONAL / FAIL outcomes). The table is kept as the
record of what was ambiguous.

Quoted from 07 §5 (Stage 2): *"browser OCR CER within +1 point of PyTorch on the
corpus; ≤0.5 s/block on WebGPU and ≤2 s/block on WASM on a mid-range laptop; total
first-run download ≤600 MB. Pass → browser-first (Stage 5a). Fail → backend-mandatory (Stage 5b)."*

| Threshold | How it would be measured | Ambiguities to settle before the spike |
|---|---|---|
| OCR CER within +1 point of PyTorch | Run PyTorch manga-ocr and the browser ONNX model on the same detector crops from the Stage 1 corpus. Compute character error rate against hand-checked references, using the same normalisation as `vision_benchmark/metrics.py`. | **Strict or normalized CER?** (The repo reports both.) **Absolute percentage points or relative?** Which quantized variant counts? The corpus and references don't exist yet (Stage 1 builds them) and have no independent review. Is any regression on specific failure types (e.g., names) a fail even within +1 point? |
| ≤0.5 s/block WebGPU | Warm per-block OCR latency in an extension offscreen document, including preprocessing, over all corpus blocks | **Median or p95?** Is cold start (first block, model compile) included? Which GPU class? Large blocks vary a lot. |
| ≤2 s/block WASM | Same as above with the WASM backend, CPU only | Thread count (cross-origin isolation in extensions affects WASM threads). Median or p95? |
| "Mid-range laptop" | One named reference machine | **Undefined.** It needs a concrete CPU, GPU and RAM spec. The development PC (i7-14700K / RTX 4070 SUPER) is high-end and does not qualify. |
| ≤600 MB first-run download | Sum of the browser-path artifacts: OCR, detector, JMdict build, tokenizer dictionary | Does the Chrome-managed Translator model count? (It is downloaded by Chrome, not YomiScan.) Compressed or installed size? |
| Pass/fail logic | — | **Undefined partial outcomes:** e.g., WebGPU passes and WASM fails. Users without WebGPU would then need the backend, so a "browser-first where WebGPU, backend otherwise" result is possible and has no defined decision. |
| Missing criteria | — | The gate does not include **detection recall** in-browser, **memory use** (tab/offscreen RAM), **JS-tokenizer parity**, or **translation quality**. Decide whether these are gate criteria or informational only. |

## Major unresolved decisions

| # | Decision | Status |
|---|---|---|
| 1 | Stage 2 thresholds, including the ambiguities above | **Owner decision (2026-11-23):** approved; see `docs/decisions/stage-2-feasibility-gate.md` |
| 2 | Keep automatic English typesetting as a main feature? (Q2: owner "not sure") | Open. The recommendation is to keep it unchanged as a toggle and decide from usage. |
| 3 | Which branch receives this documentation and the Stage 1 work | **Owner decision (2026-11-23):** first commit on `feat/stage-1-foundation`, created from `main` after PR #6 was merged |
| 4 | Store and legal positioning for a public listing, given that raw manga mostly comes from unofficial aggregator sites (07 §4.5) | Open |
| 5 | Distribution and signing (unsigned vs signed installer; Web Store listing) (06 Q10) | Open |
| 6 | LLM "explain this sentence" (06 Q12); default-on text cache (06 Q13); Anki/Yomitan priority (06 Q6) | Open |
| 7 | Start Stage 1 | **Owner decision (2026-11-23):** authorised on `feat/stage-1-foundation` |

## Repository state at handoff

- These documents were first copied into the original repository while it was on
  `audit/post-mvp-full-review`. That audit was then merged into `main` as PR #6
  (`cb446ab`). The documents are committed as the first commit of `feat/stage-1-foundation`.
- The independent clone is a read-only reference. It is not a development branch,
  and none of its branches were merged.
