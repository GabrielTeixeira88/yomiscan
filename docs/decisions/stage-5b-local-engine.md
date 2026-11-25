# Stage 5b: packaged local engine (optional companion)

Status: **in progress**. Increment 1 (Torch-free vision) is done. Started on the owner's go-ahead (2026-11-25)
after Stage 5a merged.

## Why this stage exists now

The [strategy](../independent-assessment/07-STRATEGY_DECISION.md) planned Stage 5b as the
fallback if the Stage 2 gate failed. The gate passed and Stage 5a shipped the browser engine.
The owner had already asked for "an optional downloadable companion engine later", so this stage
builds that companion from the same plan: a Torch-free engine, frozen and installed with a
launcher, so that YomiScan's local engine no longer needs a developer's Python setup.

The browser engine stays the default for people who install only the extension. The companion
adds what the browser engine cannot do:
- GPU speed on any Windows GPU. The development machine has an RTX 4070 SUPER, but its backend
  runs Torch on CPU only, because the CUDA build of Torch is a large owner-only install.
- English pages typeset into the image (the pixel renderer), not only HTML text boxes.
- Hy-MT2 LLM translation (llama.cpp) and the pt-BR / es OPUS models.
- Work outside Chrome's memory: the extension renderer no longer needs about 2 GB.

## Goal

A Windows user installs one per-user companion (no Python, no administrator rights). The
extension starts it on demand, talks to it on a random loopback port with a per-launch token, and
it shuts itself down when idle. The developer backend (`uv run yomiscan-server`) keeps working
and stays the reference for parity.

## Increments

Each increment is merged only with its tests and a real-model measurement.

| # | Scope | Status |
|---|---|---|
| 1 | **Torch-free vision.** Python readers for pinned ONNX exports of the production detector and manga-ocr (same Hugging Face repository and commit as the browser bundle), an explicit verified download into a per-user folder, and an ONNX Runtime device choice (CPU, DirectML). Parity against the Torch path on the sample corpus, plus CPU and GPU timings. | Done: 99.1% identical text end to end, detection 7× faster on DirectML (see increment 1) |
| 2 | **Torch-free translation.** OPUS-MT ja→en (then pt-BR, es) without Torch: CTranslate2 and ONNX Runtime beam search compared with transformers on the Stage 3 translation set (identical lines, speed, memory). | Planned |
| 3 | **Engine profile and freezing.** Default composition uses the Torch-free engines; Torch, transformers and manga-ocr move to an optional reference extra. A PyInstaller one-folder build with the API tests run against it; measured size and startup. | Planned |
| 4 | **Launcher.** A native-messaging host that starts the frozen engine on a random loopback port with a per-launch token, hands both to the extension, and stops it after an idle period. The extension's engine choice gains the companion. | Planned |
| 5 | **Installer and release.** Per-user Windows installer (native-messaging registration in HKCU, uninstall cleanup), first-start model download with consent, docs, a clean-machine check in Windows Sandbox. | Planned |

## Gates

| Gate | Threshold |
|---|---|
| Vision parity | Torch-free detector boxes identical to the Torch path on ≥ 99% of regions; OCR text identical on ≥ 98% of blocks, end to end. GPU differences are reported, not hidden. |
| Translation parity | ≥ 95% of lines identical to transformers OPUS on the translation set; every difference listed. |
| Package size | Frozen engine without models ≤ 400 MB on disk. Measured, then confirmed with the owner. |
| Startup | Warm start to `/health` ≤ 10 s on the development machine. |
| No regressions | `uv run pytest`, the extension tests and the mocked Chrome fixture pass; the developer backend still runs unchanged. |

## Decisions the owner will be asked later (not blocking increment 1)

- **Code signing.** An unsigned installer shows a SmartScreen warning. Signing costs money every
  year, which the project has avoided so far. Default: ship unsigned and document the warning.
- **Automatic order when both engines are installed.** Default proposal: companion first when it
  is installed (GPU, pixel renderer), browser engine second, then setup.
- **Hy-MT2 in the installer or as a separate download.** Default proposal: separate, opt-in.

## Increment 1: Torch-free vision

**Design.** The browser bundle already holds verified ONNX exports of the production detector
and manga-ocr, so the local engine reuses that hosting: the same Hugging Face repository and
commit, with its own small manifest.

- `backend/yomiscan/resources/engine/local-manifest.json` pins the local engine's files:
  `detector-fp32` (new, 164 MiB) and `ocr-int8` (the browser bundle's CPU OCR, identical pins,
  checked by a test). `scripts/build_browser_artifacts.py` writes it next to the browser
  manifest; `scripts/publish_browser_artifacts.py` re-verifies both through the public URL and
  writes the same commit into `extension/src/engine/artifact-host.json` and
  `backend/yomiscan/resources/engine/local-host.json`. The browser manifest is unchanged.
- `yomiscan/engine_models.py`: the explicit, verified download (`uv run yomiscan-prepare-engine
  detector-fp32 ocr-int8`) into `%LOCALAPPDATA%\YomiScan\models\<bundle>` (or
  `YOMISCAN_ENGINE_MODELS`). Finished files are kept; a file that does not match is never kept.
  Inference verifies the SHA-256 at load and never downloads.
- `yomiscan/onnx_runtime.py`: one session factory with a device choice. `YOMISCAN_ONNX_DEVICE`
  is `cpu` (default) or `directml`; DirectML needs the separate `onnxruntime-directml` package.
- `yomiscan/detection/pinned.py` (`YOMISCAN_DETECTOR=pinned`) and `yomiscan/ocr/pinned.py`
  (`YOMISCAN_OCR=pinned`): the readers. Python needs no hand-ported resizing; Pillow is the
  reference the browser port copies. The detector runs on the chosen device; OCR always runs on
  the CPU (see below). Readiness lists both with their setup commands. The Torch path stays the
  default in this increment.
- `scripts/compare_torch_free.py`: both paths through `PageAnalysisService.extract` on real
  pages. It reports region parity, OCR parity on the Torch path's own blocks, and end-to-end
  text parity (each path OCRs its own blocks), plus timings.

**Choosing the exports** (23-page Stage 2 corpus, 226 Torch regions, 225 blocks; development
machine: 4 threads, RTX 4070 SUPER; each variant against the Torch path on the same input):

| Export | Device | Identical to Torch | Median |
|---|---|---:|---:|
| Detector fp32 | CPU | 225 / 226 boxes (226 within 2 px) | 1,822 ms / page |
| Detector fp16 (browser) | CPU | 136 / 226 boxes (224 within 2 px) | 942 ms / page |
| Detector fp32 | DirectML | **226 / 226** boxes | 57 ms / page |
| Detector fp16 (browser) | DirectML | 35 / 226 boxes (214 within 2 px) | 38 ms / page |
| OCR fp32 | CPU / DirectML | 225 / 225 blocks | 473 / 332 ms / block |
| OCR fp16 | CPU / DirectML | 224 / 223 | 505 / 357 ms |
| OCR int8 (browser CPU file) | CPU / DirectML | 223 / 223 | **363** / 625 ms |
| OCR q4 (browser WebGPU file) | CPU / DirectML | 219 / 219 | 479 / 484 ms |

The browser's fp16 detector moves most box edges by a pixel. With it, OCR on the shifted crops
gave 218/225 identical blocks end to end on CPU and 211/225 on DirectML: below the 98% gate.
fp32 restores the Torch boxes. For OCR, int8 on the CPU is as accurate as fp16 and faster than
any GPU variant: this export has no KV cache, so every token re-reads the whole sequence and the
GPU gains little per step. A cached decoder export is a possible later speed-up.

**Result: chosen configuration** (`scripts/compare_torch_free.py`, all 23 pages):

| | Torch (CPU, reference) | Torch-free, CPU | Torch-free, detector on DirectML |
|---|---:|---:|---:|
| Regions identical | — | 225 / 226 (226 within 2 px) | **226 / 226** |
| OCR identical on Torch's blocks | — | 223 / 225 | 223 / 225 |
| Pages with the same blocks | — | 23 / 23 | 23 / 23 |
| Text identical end to end | — | **223 / 225 (99.1%)** | **223 / 225 (99.1%)** |
| Detection, median per page | 1,003–1,059 ms | 1,470 ms | **143 ms** |
| OCR, median per block | 301–317 ms | 304 ms | 161 ms |
| Load | 9.5–12.9 s | 2.2 s | 3.3 s |

Both configurations pass the vision parity gate. The two differing blocks are the same in every
run: one punctuation run (`！！？` read as `！？`) and one block of English lettering that the
page pipeline filters out as non-Japanese.

Observations for later increments:
- On CPU the fp32 detector is about 1.4× slower than Torch. CPU-only users already have the
  browser engine; the companion's main case is the GPU.
- The DirectML run's CPU OCR used onnxruntime-directml 1.24.4 and took 161 ms per block; the
  CPU run used onnxruntime 1.32 and took 304 ms for the same int8 files. The cause is not
  investigated yet. Increment 3 chooses the runtime package to freeze and must measure this.
- `onnxruntime-directml` is a separate package that conflicts with `onnxruntime`, and its
  latest release (1.24.4) is older than the project's `onnxruntime>=1.32` pin. DirectML is in
  maintenance; Windows ML is its successor. Increment 3 decides the GPU runtime.
- The Hugging Face download of the local bundle (275 MiB) took 14 s here.
