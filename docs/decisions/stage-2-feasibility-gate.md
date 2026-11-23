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
