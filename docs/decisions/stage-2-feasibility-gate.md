# Stage 2 distribution feasibility gate

Accepted by the owner on 2026-11-23, as proposed by the independent assessment
([07-STRATEGY_DECISION.md](../independent-assessment/07-STRATEGY_DECISION.md) §5 and
[README](../independent-assessment/README.md) "Proposed pass/fail thresholds").
It resolves the ambiguities listed there. Stage 2 is a measurement spike. Its only
deliverable is a results record that applies this gate. No product code is merged from the spike.

## Question decided by the gate

Can YomiScan's public build run text detection and OCR **inside the Chrome extension**
(browser-first, local Python engine optional), or must the local engine remain
**mandatory** (packaged installer)?

## Inputs fixed before measuring

- **Corpus.** The Stage 1 page corpus: at least 40 pages from at least 6 series, with
  reviewed reference transcriptions, kept locally and never committed (see
  `docs/evaluation/README.md`). The gate is not applied to a smaller corpus.
- **Crops.** Both OCR arms read the *same* detector crops: production grouping, 4 px
  padding. Detection is measured separately.
- **Reference arm.** The current production stack: PyTorch manga-ocr with the original
  weights, published decoding, CPU.
- **Browser arms.** The original manga-ocr weights exported to ONNX (fp32 and every
  quantized variant tried), run in ONNX Runtime Web inside an extension offscreen
  document, once with WebGPU and once with WASM. The browser OCR result is the
  **single variant** that best meets the latency criteria. All variants are reported.
- **Reference machine.** A mid-range laptop: a 4-core/8-thread mobile CPU of the
  2021–2023 generation (Intel i5-1135G7/1235U or AMD Ryzen 5 5500U/7530U class),
  16 GB RAM, integrated GPU, Windows 11, current stable Chrome. The development PC
  (i7-14700K / RTX 4070 SUPER) may be used for iteration only. If no reference laptop
  is available, the gate is **not applied**, and the owner decides whether a
  substitute machine is acceptable.

## Owner deviation recorded before measuring (2026-11-24)

The owner chose to apply the gate to the **23-page, 10-series Stage 1 corpus**
(253 regions; 105 in the 9-page `held_out` split) instead of waiting for 40 pages. The owner
accepted the draft annotations as they are; they were not checked line by line, and
`annotations_complete` remains `false`. This replaces the corpus input above for this run
only. Consequences fixed now, before any measurement:

- **Resolution.** On the held-out split, one region is about 1 point. A G1 or G7
  difference within **±2 points** of its threshold is reported as **inconclusive**, not
  as a pass or fail. An inconclusive G1 or G7 becomes a fresh owner decision, the same way as
  CONDITIONAL.
- **Same references for both arms.** Reference errors affect both OCR arms equally, so
  G1's *difference* stays meaningful even though absolute CER is a draft value.
- **Scope.** G1, G2 and G7 are computed over all 23 pages and over held-out alone. Both
  are reported, and the gate uses all 23 pages. G3–G6 and G8 do not depend on corpus size.

## Owner decision: browser-first (2026-11-24, during measurement)

The owner chose **browser-first (Stage 5a)** before the gate result. The reason is that a
Chrome Web Store extension that works on any computer's CPU is worth more than the speed
the gate protects. A downloadable, all-dependencies engine will follow as an **optional
companion** for GPU speed and stronger translation (it replaces Stage 5b as a mandatory
installer). This is recorded as an owner decision, not as a change of thresholds after
measurement started. The criteria are applied as follows:

- **Hard requirements (must pass before Stage 5a ships):** G1 OCR accuracy, G2 OCR
  robustness, G7 detection recall, G8 memory, and G6 download size. Wrong text or crashed
  tabs would make the extension unusable.
- **Reported targets, not pass/fail:** G3 WebGPU latency, G4 WASM latency and G5 cold
  start. They set user expectations and optimization priorities. WebGPU is used when
  Chrome offers an adapter (including integrated GPUs), and WASM on the CPU is the universal fallback.
- **Reference laptop:** still wanted for realistic expectations, no longer decisive.
- **Translation:** the browser build uses a model that runs on the CPU (OPUS). The
  Chrome built-in Translator stays optional and experimental. Hy-MT2 and other GPU-class
  models belong to the companion engine.

## Criteria

| # | Criterion | Threshold | Measurement |
|---|---|---|---|
| G1 | OCR accuracy | Browser **normalized** CER ≤ reference normalized CER **+ 1.0 percentage point** (absolute) over all scored corpus blocks | `vision_benchmark` normalization and metrics, same references for both arms |
| G2 | OCR robustness | New total failures (empty, non-Japanese or truncated output where the reference arm succeeded) ≤ **2% of blocks** | Per-block comparison of both arms |
| G3 | WebGPU latency | Warm per-block **median ≤ 0.5 s** and **p95 ≤ 1.0 s** | Preprocessing + encoder + decoding, excluding detection; at least one warm-up block discarded |
| G4 | WASM latency | Warm per-block **median ≤ 2.0 s** and **p95 ≤ 4.0 s** | Same as G3, CPU only, with the thread count actually available to the extension recorded |
| G5 | Cold start | Model load + first block **≤ 30 s** on each backend | Fresh browser profile with the artifacts already downloaded |
| G6 | Download size | YomiScan-managed first-run transfer (OCR, detector, dictionary build, tokenizer dictionary) **≤ 600 MB compressed** | Sum of artifact transfer sizes. Installed size is reported, not gated. Chrome-managed models (e.g., the built-in Translator) are excluded. |
| G7 | Detection recall | Browser detector recall ≥ PyTorch detector recall **− 1 block per 100** annotated blocks | Existing `vision_benchmark` matching on the corpus |
| G8 | Memory | Peak private memory of the offscreen document during a 10-page run **≤ 1.5 GB** | Chrome task manager / process memory sampling, method recorded |

**Informational only** (reported, not gated): a JavaScript tokenizer compared with
UniDic on the lexical golden set; translation-engine ratings, including the Chrome
built-in Translator; installed size.

## Outcomes

| Outcome | Condition | Next stage |
|---|---|---|
| **PASS** | G1, G2, G5–G8 pass, and G3 and G4 both pass | Stage 5a: browser-first; the Python engine becomes an optional companion |
| **CONDITIONAL** | Everything passes except G4 (WASM latency) | Stage 5a for WebGPU-capable browsers, with the companion engine required where WebGPU is unavailable. **Requires a fresh owner decision before Stage 5a starts.** |
| **FAIL** | Any of G1, G2, G3, G5, G6, G7 or G8 fails | Stage 5b: packaged, mandatory local engine |

A failed criterion can be re-measured once after a documented fix (e.g., another
quantization) within the spike's time box. Thresholds do not change after
measurement starts.

## Chrome built-in Translator

It is included in the translation bake-off **as an optional experimental provider
only**. It must never become a mandatory dependency, the default engine, or a
replacement for the local translation engines. Its proprietary nature is accepted
for evaluation. Its results are informational for this gate.
