# Stage 5a: browser-first engine

Status: **in progress**. Increment 1 of 5 is done. Follows the [Stage 2 results](stage-2-results.md),
where every hard gate passed and the owner chose browser-first even when it is slower or
CPU-only. The Python backend stays available as the optional "local engine" (GPU, Hy-MT2).

## Goal

A Chrome user installs the extension, explicitly downloads pinned models once, and can
study and read manga with no Python, no server and no account. Everything runs on the
device: WebGPU when available, multi-threaded WASM otherwise.

## Increments

Each increment is merged only with its tests and a real-model measurement.

| # | Scope | Status |
|---|---|---|
| 1 | **Engine foundation and vision.** Cross-origin isolated offscreen document running ONNX Runtime Web 1.31.1. Pinned artifact manifest, verified install into Cache Storage, a Setup section. Detector, production grouping/ordering and greedy manga-ocr ported to TypeScript, plus a parity harness against the backend. | Done (see measurements) |
| 2 | **Lexical engine.** lindera-wasm-unidic tokenizer and JMdict SQLite (sqlite-wasm, OPFS). TypeScript ports of the ranking rules plus the Stage 3 data files (`units.json`, `grammar.json`, `inflections.json`). The lexical golden set is run against the browser engine (target: the Python 96.7%). | Next |
| 3 | **Translation.** OPUS-MT fp16 with transformers-exact beam search (Stage 2: 99/100 lines identical to Python). The Chrome Translator stays optional and experimental. | Planned |
| 4 | **Integration.** An engine setting (Browser / Local backend). Study selection, Read Chapter and the edit-text re-analysis run through the browser engine. English in browser mode is HTML text boxes over the page; the pixel renderer stays in the local engine. | Planned |
| 5 | **Release readiness.** First-run onboarding with sizes and consent, storage-pressure handling, laptop measurements (integrated GPU, 4-core CPU, 8 GB), and docs. | Planned |

## Architecture (increment 1)

- **Runtime.** The offscreen document hosts `BrowserEngine` (`extension/src/engine/`). The
  extension is cross-origin isolated (`cross_origin_embedder_policy: require-corp`,
  `cross_origin_opener_policy: same-origin`), so WASM can use threads. The CSP adds only
  `'wasm-unsafe-eval'`. The ONNX Runtime bundles ship in `dist/ort/`, about 42 MB: the
  plain threaded build for CPU and the asyncify build for WebGPU. They are imported at
  runtime and only when the engine is used.
- **Device path.** WebGPU uses q4 OCR, CPU uses int8 OCR (int8 is 10× slower on WebGPU),
  and both use the fp16 detector. One OCR variant is downloaded per device. The detector
  is 82 MiB; q4 OCR is 88 MiB and int8 OCR is 111 MiB.
- **Artifacts.** `scripts/build_browser_artifacts.py` packages the Stage 2 exports and writes
  `extension/src/engine/artifact-manifest.json` (path, size and SHA-256 per file), which
  is committed. Installation is an explicit click. Each file is streamed, its size and
  SHA-256 are checked, and it is stored in Cache Storage under its hash, never its URL, so
  a host can move files but cannot swap them. `unlimitedStorage` keeps them from being
  evicted. Removal is one click.
- **Vision.** `engine/geometry.ts` is a line-for-line port of `page_layout.py`,
  `PageAnalysisService._detect` and the "bands" page order. `engine/vision-models.ts`
  holds the validated Stage 2 ports: PIL-exact resizing, RT-DETR post-processing, and
  greedy manga-ocr with its post-processing. `engine/vision.ts` crops each block with 4 px
  padding and applies the backend's Japanese-script filter.
- **Boundary.** Only the extension's own service worker can drive the engine. Content
  scripts can ask for status, install, cancel and remove; they cannot run recognition yet.

## Increment 1 measurements (2026-11-24)

These come from `extension/tests/browser-engine.mjs`: the real extension build, models
installed through the verified store from the local artifact server, and 10 owner-supplied
sample pages (94 text blocks). Each page is compared with the running Python backend's
`analyze-page` (PyTorch detector fp32, manga-ocr greedy). Development PC (i7-14700K,
RTX 4070 SUPER), headed Chrome 157. Laptop numbers are still missing.

| Path | Blocks matched (IoU ≥ 0.5) | Same order | Identical text | CER vs Python | Median page (after first) | First page incl. model load |
|---|---|---|---|---:|---:|---:|
| WebGPU (q4 OCR, fp16 detector) | 94 / 94 | 10 / 10 pages | 88 / 94 | 0.82% | 1.4 s | 7.2 s |
| CPU, WASM ×8 (int8 OCR, fp16 detector) | 94 / 94 | 10 / 10 pages | **94 / 94** | **0.00%** | 2.3 s | 3.9 s |

The CER column is the difference from the backend's output, not accuracy against ground
truth. q4's small drift matches Stage 2, where q4 measured 1.81% CER against ground truth
and fp32 1.61%. Install from loopback took 0.5–1.2 s. Cross-origin isolation was
confirmed (`crossOriginIsolated`, 8 threads). With isolation on, the mocked reader fixture
still passed its cross-origin, cookie-bearing image acquisition. Its intermittent failures
are in report downloads and also occur on `main`.

The real run also caught one bug that the unit tests could not: the default `fetch` was
stored as a method, which Chrome rejects ("Illegal invocation").

## Owner decision needed (not blocking development)

**Where the public model files are hosted.** Local development serves them from
`scripts/serve_browser_artifacts.py`. A public release needs a stable public URL. A
Hugging Face model repository under the owner's account fits best: free and versioned,
with the licenses already Apache-2.0 for the vision models, CC-BY-4.0 for OPUS-MT and
CC BY-SA for JMdict with attribution. Because the extension verifies pinned hashes, the
host needs no trust, only availability. Publishing requires the owner's account and
consent.

## Development commands

```powershell
uv run python scripts/build_browser_artifacts.py      # package exports and pin hashes
uv run python scripts/serve_browser_artifacts.py      # http://127.0.0.1:47620/
# Chrome (test profile) with --remote-debugging-port=9231 --enable-unsafe-extension-debugging
node extension/tests/browser-engine.mjs samples/vision/008.jpg samples/vision/1.jpg
```
