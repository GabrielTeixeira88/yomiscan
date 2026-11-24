# Stage 2 results: browser feasibility

Applies the [Stage 2 gate](stage-2-feasibility-gate.md), including the owner's two recorded
decisions: the 23-page corpus and browser-first. Measured on 2026-11-24. Spike code and
reproduction steps are in [`research/stage-2/`](../../research/stage-2/README.md). No product
code was changed.

## Verdict

**Browser-first is feasible. Every hard requirement (G1, G2, G6, G7, G8) passes** on the
development PC. The reported targets (G3–G5) are met with a wide margin there. Stage 5a can
proceed as decided.

Laptop numbers are still missing: speed on an integrated GPU, CPU speed on a 4-core mobile
chip, and memory on an 8 GB machine. They set expectations for users but no longer decide
the outcome.

## Setup

- **Machine.** Development PC: i7-14700K (28 threads), 32 GB, RTX 4070 SUPER, Windows 11.
  Headless Chrome 157 with a fresh profile per run. ONNX Runtime Web 1.31.1 inside an MV3
  **offscreen document** that is cross-origin isolated (so WASM gets threads). Models are
  read from Cache Storage, which is how a shipped build keeps downloaded artifacts. The
  integrated UHD 770 is not exposed to Chrome's WebGPU on this machine, so integrated-GPU
  speed is unmeasured. CPU results use 8 threads and a 4-thread cap as a laptop approximation.
- **Reference arm.** Production detector crops (225 crops, 210 with references; grouping
  and 4 px padding as in production) read by PyTorch manga-ocr with its published decoding
  (beam 4, `no_repeat_ngram_size` 3, length penalty 2). Normalised CER **3.19%**.
- **Browser arms.** The original `kha-white/manga-ocr-base` weights exported to ONNX
  (encoder plus a 2-layer decoder without KV cache), plus fp16, int8 (dynamic) and q4
  (MatMulNBits) variants. Preprocessing and decoding were ported to JavaScript. The port
  reproduces PIL resizing to within 6e-8, and fp32 beam search was **identical to PyTorch on
  225/225 crops**.
- **Detector.** The production RT-DETR-v2 weights (`model.safetensors`) exported to ONNX
  (fp32 and fp16), with transformers' post-processing ported to JavaScript. In Node, the fp32 port
  reproduced 225/226 PyTorch boxes exactly.

## Gate criteria

| # | Criterion | Kind | Result | Status |
|---|---|---|---|---|
| G1 | Browser CER ≤ reference + 1.0 pp | hard | Every variant ≤ reference. Greedy decoding: **1.61–1.81%** (−1.4 to −1.6 pp). Beam: 3.09–3.19%. The held-out split agrees within 0.1 pp | **Pass** |
| G2 | New total failures ≤ 2% | hard | **0/225** for every variant and backend | **Pass** |
| G3 | WebGPU median ≤ 0.5 s, p95 ≤ 1.0 s | target | q4 greedy **85 ms / 165 ms** on a discrete GPU; integrated GPU unmeasured | Met (dGPU) |
| G4 | WASM median ≤ 2.0 s, p95 ≤ 4.0 s | target | int8 greedy **194 / 309 ms** (8 threads), **340 / 565 ms** (4 threads) | Met (desktop) |
| G5 | Load + first block ≤ 30 s | target | **1.2–3.4 s** for a new document reading from Cache Storage. A cold browser restart was not measured | Met |
| G6 | First-run transfer ≤ 600 MB (raised to 1 GB by the owner) | hard | **235–245 MB** gzip (OCR + detector + JMdict SQLite + UniDic tokenizer). About 425–435 MB with browser OPUS (fp16) | **Pass** |
| G7 | Recall ≥ PyTorch − 1/100 | hard | PyTorch 85.8%; browser fp32 **85.8%**, fp16 **86.2%**. Held-out 87.6% for both | **Pass** |
| G8 | Offscreen peak ≤ 1.5 GB (10 pages) | hard | Detector + OCR pipeline, 10 pages: **785–933 MiB** (extension process) | **Pass** |

G8 method: Windows `PrivatePageCount` of the extension renderer process (which also holds
the service worker), sampled every 500 ms, with one fresh Chrome per configuration. The GPU
process is reported separately (up to 917 MiB with WebGPU). fp32 OCR alone peaked at
1.55–1.6 GiB, so **fp32 is excluded**.

## OCR variants in the browser (225 crops)

| Variant | Backend | Decoding | CER | Median / p95 per block | Load + first block | Peak extension / GPU |
|---|---|---|---:|---:|---:|---:|
| q4 | WebGPU | greedy | 1.81% | 85 / 165 ms | 1.6 s | 595 / 627 MiB |
| q4 | WebGPU | beam | 3.19% | 105 / 219 ms | 1.5 s | 601 / 653 MiB |
| fp16 | WebGPU | greedy | 1.68% | 113 / 228 ms | 2.7 s | 1098 / 799 MiB |
| fp16 | WebGPU | beam | 3.09% | 168 / 350 ms | 2.6 s | 951 / 797 MiB |
| fp32 | WebGPU | greedy | 1.61% | 121 / 252 ms | 3.4 s | 1599 / 1104 MiB |
| int8 | WebGPU | greedy | 1.64% | 1123 / 2088 ms | 2.9 s | 671 / 424 MiB |
| int8 | WASM ×8 | greedy | 1.64% | 194 / 309 ms | 1.4 s | 478 MiB |
| int8 | WASM ×8 | beam | 3.09% | 390 / 857 ms | 1.6 s | 653 MiB |
| int8 | WASM ×4 | greedy | 1.64% | 340 / 565 ms | 1.5 s | 443 MiB |
| q4 | WASM ×8 | greedy | 1.81% | 545 / 971 ms | 1.7 s | 430 MiB |
| q4 | WASM ×4 | greedy | 1.81% | 857 / 1440 ms | 2.0 s | 406 MiB |
| fp16 | WASM ×8 | greedy | 1.61% | 422 / 706 ms | 1.9 s | 1276 MiB |
| fp32 | WASM ×8 | greedy | 1.61% | 318 / 563 ms | 1.2 s | 1550 MiB |

Full pages (detector + OCR on raw detected boxes, 10 pages, 94 blocks): median **2.0 s per
page** on WebGPU (q4 + fp16 detector), **3.0 s** on WASM ×8 and **5.5–5.7 s** on WASM ×4
(int8). A laptop CPU is probably 2–3× slower than this desktop's.

## Recommended Stage 5a configuration

- **WebGPU available** (including integrated GPUs): q4 OCR + fp16 detector, greedy decoding.
- **CPU fallback:** int8 OCR + fp16 detector, greedy decoding, threads = available cores.
  int8 must not run on WebGPU: ONNX Runtime Web has no fast int8 path on WebGPU (10× slower).
- Download the one OCR variant that fits the device (about 83–92 MB), not both.
- **Dictionary:** the existing JMdict SQLite through `@sqlite.org/sqlite-wasm` (opens in
  0.9 s from storage, 0.07 ms per lookup). Persist it in OPFS from a worker.
- **Tokenizer:** `lindera-wasm-unidic` 2.1.0 (UniDic, 50 MB). It scored identically to
  fugashi + UniDic-lite on the lexical golden set (137/138, the same single failure).
- **Translation:** browser OPUS **fp16 with beam search on WASM** (189 MB gzip). The
  transformers-exact beam search (`browser/beam.mjs`, shared with the OCR port; KV cache
  reordered per beam) reproduces the Python backend's OPUS (beam 4) on **99/100** real
  lines. It takes **710 ms per line** median (p95 1.4 s) with 8 threads and 886 ms with 4.
  WebGPU is slower for this small decoder (971 ms) and drifts more (93/100). The q8 weights
  diverge (30/100 even with beam search), so they are not used. Transformers.js supplies only
  the Marian tokenizer. Chrome's built-in Translator
  stays **optional and experimental**. It needs a user click to download its language pack
  (18.5 s first time), then translates in about 7 ms per line. Hy-MT2 belongs to the companion engine.

## Findings outside the gate

1. **The published manga-ocr decoding damages repeated text.** `no_repeat_ngram_size=3`
   forbids any repeated 3-token sequence, so doubled words and laughter lose or change a
   character. Greedy decoding halves CER on this corpus (3.19% → 1.61%); the JS port decodes about 2× faster.
   **Fixed in the Python backend** (branch `fix/ocr-greedy-decoding`): measured on the same
   crops, CER fell from 3.19% to 1.61% and the CPU median from 415 to 310 ms per block.
2. fp16 conversion must use ONNX Runtime's converter. `onnxconverter-common` mistypes `Cast`
   nodes in both graphs, and the sessions fail to load.
3. Transformers.js 4.3.2's local-model loader never requested tokenizer files from an
   extension page. Its remote loader, pointed at a self-hosted URL, works.
4. The third-party int8 detector export used by the current experimental ONNX engine is
   not weight-equivalent. Our own export of the production weights keeps recall exactly.

## Translation bake-off (informational, pending owner ratings)

100 real corpus lines (local only) were translated by Python OPUS (beam 4), browser OPUS
(q8, greedy; the first browser attempt), Hy-MT2 manga v5 (llama.cpp, GPU) and the Chrome Translator. A blind sheet
(`.cache/stage2/blind-ratings.csv`, four shuffled candidates per line) awaits optional owner
ratings. `research/stage-2/blind_ratings.py unblind` and `scripts/summarize_translation_ratings.py`
then summarize the ratings. No winner is chosen without ratings.

### Against official English (42 lines, 9 pages, 4 series)

The owner supplied official English pages for 9 corpus pages. Their lines were transcribed
per region and kept local. They appear as an `official` column in the rating sheet, and
`research/stage-2/score_official.py` scores them. Official localizations rephrase freely,
so chrF/BLEU are rough signals. Meaning errors (flipped negation, wrong person, invented or
missing key content, gibberish) were marked by the AI assistant, not blind and not the
owner.

| Engine | chrF++ | BLEU | Lines with a major meaning error | Offensive hallucinations |
|---|---:|---:|---:|---:|
| Hy-MT2 manga v5 (GPU, companion) | 31.9 | 13.8 | 14 / 42 | 2 |
| Chrome built-in Translator (optional) | 29.2 | 9.1 | **11 / 42** | 0 |
| OPUS, Python (beam 4, current backend) | 24.2 | 6.6 | 19 / 42 | 0 |
| OPUS, browser (fp16, beam 4), recommended | 24.1 | 6.6 | 19 / 42 | 0 |
| OPUS, browser (q8, greedy), first attempt | 22.5 | 5.6 | 28 / 42 | 1 |

Findings:
- **Beam search closes the browser gap.** The first browser attempt (q8, greedy) added 9
  meaning errors. With fp16 weights and beam search, browser OPUS differs from Python on
  one of these 42 lines (both versions are wrong there), so it has the same 19 errors and
  the same scores. The blind sheet's browser candidate is the earlier greedy run. Python OPUS
  ratings stand for the recommended browser OPUS.
- **Every engine fails the same hard cases:** katakana robot speech, all-hiragana child
  speech, implied subjects that only context supplies (Japanese often omits who is
  speaking or acting), and puns. These lines need context-aware translation (future work)
  more than a different model.
- **Name handling is poor everywhere.** The Stage 3/4 glossary work matters for every engine.
- **The Chrome Translator made the fewest meaning errors on this sample.** It remains
  optional and experimental by owner decision; whether its role should change is the
  owner's call.
- **Hy-MT2 scored best on overlap but produced two offensive misreadings** of
  child speech. Its use in the companion engine needs a safety review.

## Limitations

- 23-page draft corpus (see the gate deviation). G1/G7 differences of 2 points or less would have been
  inconclusive; none was near a threshold.
- Development PC only, headless Chrome. No integrated-GPU or mobile-CPU measurement.
- Cold start reopened the document inside a running browser, not a full browser restart.
- The full-page pipeline used raw detected boxes; production grouping is not ported yet.
