# Stage 2 distribution feasibility spike

Measurement code for the [Stage 2 gate](../../docs/decisions/stage-2-feasibility-gate.md).
None of this is product code. It is kept so the decision record can be reproduced. All
artifacts, pages, crops, outputs and browser profiles stay under ignored `.cache/stage2/`
and `reports/`. Export tools run ephemerally with `uv run --with ...` and do not change `uv.lock`.

## Pipeline

Run from the repository root unless noted. Steps 1–3 reuse the Stage 1 corpus tooling.

```powershell
# 1. Reference arm: production detector crops (grouping, 4 px padding) + PyTorch manga-ocr.
uv run --frozen --extra vision --extra benchmark python scripts/benchmark_detection.py samples/vision/pages.json --engine current --pipeline --repeats 1 --output reports/stage2-detect-current-pipeline.json
uv run --frozen --extra vision --extra benchmark python scripts/benchmark_ocr.py samples/vision/pages.json --detector-results reports/stage2-detect-current-pipeline.json --engine current --output reports/stage2-ocr-reference.json

# 2. Export the original manga-ocr weights and the production detector weights to ONNX; quantize.
uv run --frozen --extra vision --with onnx --with onnxscript python research/stage-2/export_manga_ocr.py
uv run --frozen --extra vision --with onnx --with onnxconverter-common --with onnx-ir python research/stage-2/quantize_manga_ocr.py
uv run --frozen --extra vision --with onnx --with onnxscript --with onnx-ir --with sympy python research/stage-2/export_detector.py

# 3. Inputs for JavaScript: the reference crops, Pillow-decoded pages, reference pixels.
uv run --frozen --extra vision python research/stage-2/dump_crops.py samples/vision/pages.json reports/stage2-detect-current-pipeline.json reports/stage2-ocr-reference.json
uv run --frozen --extra vision python research/stage-2/dump_pages.py samples/vision/pages.json
uv run --frozen --extra vision python research/stage-2/dump_pixels.py 20

# 4. JavaScript port, validated in Node, then measured in Chrome (from research/stage-2/browser).
npm ci
node validate-node.mjs fp32 beam          # preprocessing parity + identical-to-PyTorch count
node validate-detector-node.mjs detector.onnx
node run-browser.mjs --configs q4:webgpu:greedy,int8:wasm:greedy:t4 --out example
powershell -NoProfile -File run-matrix.ps1  # every OCR variant, one fresh Chrome each

# 5. Scoring with the project's own metrics.
uv run --frozen python research/stage-2/score_ocr.py reports/stage2-ocr-reference.json .cache/stage2/ocr-*.json
```

## Files

| File | Purpose |
|---|---|
| `export_manga_ocr.py`, `quantize_manga_ocr.py` | ONNX encoder + decoder (no KV cache) for `kha-white/manga-ocr-base`, with fp16/int8/q4 variants |
| `export_detector.py` | ONNX export of the production RT-DETR-v2 weights (fp32, fp16) |
| `browser/ocr.mjs` | JS manga-ocr: PIL-exact preprocessing, transformers-exact beam search, greedy decoding, post-processing |
| `browser/detector.mjs` | JS detector pre- and post-processing, matching `RTDetrImageProcessorPil` and `decode_regions` |
| `browser/extension/` | Spike-only MV3 extension. The offscreen document runs ONNX Runtime Web (WebGPU or WASM) |
| `browser/run-browser.mjs` | Launches Chrome with a fresh profile over CDP, loads the extension, primes Cache Storage, runs configs, samples process memory |
| `score_ocr.py` | G1/G2 against the reference arm, using `vision_benchmark` normalization and metrics |
| `artifact_sizes.py` | G6 raw and gzip transfer sizes |
| `evaluate_js_tokenizer.py`, `browser/tokenize-golden.mjs` | Informational: lindera-wasm-unidic on the lexical golden set |
| `build_translation_set.py` | Informational: 100 real corpus lines for the translation bake-off (local only) |

Config syntax for `run-browser.mjs`: `variant:backend:decoding[:low-power|high-performance][:tN]`.
Variants are `fp32|fp16|int8|q4`, backends `webgpu|wasm`, decodings `beam|greedy`, and `tN`
caps WASM threads. Detector configs are `detector[-fp16]:backend:png|original`.
