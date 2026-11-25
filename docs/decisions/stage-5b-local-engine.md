# Stage 5b: packaged local engine (optional companion)

Status: **in progress**. Increments 1 (vision), 2 (translation) and 3 (engine profile and freezing) are done. Started on the owner's go-ahead (2026-11-25)
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
| 2 | **Torch-free translation.** OPUS-MT ja→en (then pt-BR, es) without Torch: CTranslate2 and ONNX Runtime beam search compared with transformers on the Stage 3 translation set (identical lines, speed, memory). | Done for ja→en: 153/153 identical lines (see increment 2). The experimental pt-BR / es models stay Torch-only for now. |
| 3 | **Engine profile and freezing.** Default composition uses the Torch-free engines; Torch, transformers and manga-ocr move to an optional reference extra. A PyInstaller one-folder build with the API tests run against it; measured size and startup. | Done: Torch-free defaults, frozen engine 462 MiB (89 MiB compressed), ready in about 4 s (see increment 3). The size gate is missed by the UniDic dictionary. |
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

## Owner decisions (2026-11-25: "do as you think is best", so the proposals below apply)

- **Code signing: unsigned.** An unsigned installer shows a SmartScreen warning; signing costs
  money every year, which the project has avoided. The warning is documented.
- **Automatic order when both engines are installed: companion first** (GPU, pixel renderer),
  browser engine second, then setup.
- **Hy-MT2: a separate, opt-in download**, not part of the installer.

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

## Increment 2: Torch-free translation

**Candidates.** Each line of the translation set was translated alone by the current
`MarianTranslationEngine` (transformers, CPU) and by each candidate. The set is
`benchmarks/manga-dialogue.jsonl` (53 lines) plus the local-only Stage 2 set (100 real corpus
lines), 153 lines in all. Both candidates used a new transformers-free tokenizer
(`sentencepiece` plus `vocab.json`, as `MarianTokenizer` does), which produced identical ids on
all 153 lines.

| Candidate | Identical lines | Median per line | Load | Files |
|---|---:|---:|---:|---:|
| Torch (reference) | — | 201 ms | — | — |
| **ONNX Runtime fp32 + ported beam search** | **153 / 153** | **196 ms** | 1.4 s | 411 MiB |
| ONNX Runtime fp16 (browser file) | 152 / 153 | 447 ms | 0.9 s | 210 MiB |
| ONNX Runtime quantized (Xenova) | 62 / 153 | 373 ms | 0.7 s | 104 MiB |
| CTranslate2 float32 | 121 / 153 | 109 ms | 0.4 s | 289 MiB |
| CTranslate2 int8 | 85 / 153 | 38 ms | 0.1 s | 75 MiB |

CTranslate2 is the fastest, but its beam search finishes hypotheses differently from
transformers: even at full precision one line in five changed, which fails the 95% gate.
ONNX Runtime with the ported beam search is exact, at the speed of Torch.

**Design.**
- `translation/beam.py`: transformers' beam search for one input in NumPy. It is ported from the
  browser engine's port, including the separate penalties and the stopping heuristic.
- `translation/marian_sentencepiece.py`: the tokenizer. Like `MarianTokenizer`, decoding skips
  `</s>`, `<unk>` and `<pad>` and turns any leftover `▁` into a space.
- `translation/opus_onnx.py`: `PinnedOpusTranslationEngine`, with the backend's contract:
  - whitespace collapsed;
  - more than 512 tokens is an error;
  - 4 beams, pad banned with renormalized logits, at most 511 new tokens;
  - an unfinished or empty output is an error.

  The merged decoder reuses its key/value cache, and each beam's cache follows its parent. It
  runs on the CPU.
- Selected with `YOMISCAN_TRANSLATION_ENGINE=opus-pinned`, or at run time in the Setup panel
  ("Translation engine → Use"). Readiness lists it with its setup command.
- Files: the `translation-opus-ja-en-fp32` component in `local-manifest.json`. It holds the
  Xenova fp32 export plus the Marian SentencePiece files, published as commit `26da07d`. The
  publish script re-verified all 1,238 MiB, the extension's pin moved with it, and the browser
  files are unchanged. The Hugging Face download (411 MiB) took 18 s.
- Tests without weights: on six random tiny `MarianMTModel`s, the ported beam search picks
  exactly the tokens of `model.generate()`. The tokenizer matches `MarianTokenizer` when its
  files are cached. The engine contract (cache reuse, errors) runs against scripted sessions.

**Result** (`scripts/compare_torch_free_translation.py`, production engine, 153 lines):

| | Torch | Torch-free |
|---|---:|---:|
| Identical lines | — | **153 / 153** |
| Median / p95 per line | 197 / 428 ms | 183 / 392 ms |
| Load | 9.9 s | 2.1 s |
| Peak working set (process, 30 lines) | 659 MiB | 1,071 MiB |

**Memory.** The ONNX export stores the 60,716-entry embedding three times (encoder input,
decoder input, output projection; about 124 MB each), where Torch ties them into one copy.
Graph optimization level and the CPU memory arena changed nothing. Disabling weight prepacking
(`session.disable_prepacking`) lowered the peak working set to 868 MiB but made translation
26% slower, so the default is kept. Increment 3 measures the whole frozen engine and can
revisit this.

**Not done.** The experimental pt-BR and es OPUS models still need Torch; neither has a
pinned ONNX export yet. They stay available in the developer backend.

## Increment 3: engine profile and freezing

**ONNX Runtime package.** Windows needs `onnxruntime-directml` for the GPU, and its newest
release is 1.24.4. The same Torch-free workload under three packages (6 pages, 61 crops, 153
translation lines; development machine, 4 threads):

| Package | Detector / page | OCR / block | Translation / line | Translation identical |
|---|---:|---:|---:|---:|
| onnxruntime 1.32.0 (CPU) | 1,413 ms | 275 ms | 210 ms | 153 / 153 |
| onnxruntime-directml 1.24.4 (CPU path) | 1,553 ms | **181 ms** | 248 ms | 153 / 153 |
| onnxruntime 1.24.4 (CPU) | 1,596 ms | 184 ms | 214 ms | 153 / 153 |

1.24.4 has the faster int8 OCR kernels. Its OCR text differs slightly from 1.32's on the
crops, but both read 223/225 blocks identically to PyTorch in increment 1, so neither is less
accurate. The project now pins **1.24.4 on every platform**: `onnxruntime-directml` on Windows
and `onnxruntime` elsewhere. Every platform therefore runs the same CPU kernels. The earlier
`>=1.32` pin had no recorded reason beyond being the newest release.

**Dependencies.**
- The package's dependencies are Torch-free: ONNX Runtime, sentencepiece, jaconv, fugashi and
  unidic-lite, OpenCV, FastAPI.
- PyTorch, transformers, manga-ocr and sacremoses form the `reference` dependency group.
  `uv sync` installs it by default (`[tool.uv] default-groups`), so development, the parity
  scripts and CUDA keep working; the wheel and the frozen engine never include it.
- 44 tests of the PyTorch adapters carry the `reference` marker and are skipped, with a reason,
  in a Torch-free install. CI runs the suite both ways.

**Defaults.**
- The default engines are `pinned` (detector), `pinned` (OCR) and `opus-pinned` (translation).
  The PyTorch engines remain selectable as `current`.
- `YOMISCAN_ONNX_DEVICE` defaults to `auto`: DirectML when the runtime offers it, else the CPU.
- `yomiscan-prepare-defaults` downloads the default models plus the dictionary (805 MiB,
  SHA-256 checked); `--reference` keeps the old PyTorch downloads.
- The local bundle gains the `dictionary` component, the browser bundle's JMdict file. An
  imported `data/jmdict.sqlite3` still takes precedence.
- Readiness lists the default engines first and declares each PyTorch model's dependency.
- Hugging Face cache lookups are skipped when `huggingface_hub` is absent.

**Frozen engine.**
- `yomiscan/engine_main.py` (`yomiscan-engine`) is the packaged entry point. It never reads the
  working directory: models and the dictionary come from `%LOCALAPPDATA%\YomiScan\models`, and
  the processing cache and glossaries live under `%LOCALAPPDATA%\YomiScan`.
- `--prepare [--component ...]` downloads the models explicitly. Readiness then reports
  `yomiscan-engine --prepare` as the setup command.
- `scripts/build_engine.py` syncs its own environment without the `reference` group, then runs
  `packaging/engine/yomiscan-engine.spec`. The spec excludes the PyTorch packages and fails
  the build if any reached the bundle.
- YomiScan's own `.py` files ship next to their bytecode (`module_collection_mode
  "pyz+py"`), because the processing cache keys results by a hash of the analysis sources.
- OpenCV's FFmpeg video plugin (30 MB) is removed.
- `scripts/validate_engine_build.py` runs the `.exe` with a fresh per-user folder: with no
  models, readiness must report the setup; with models, it checks readiness, text and a page.

**Measurements** (development machine; cold start; page `008.jpg`, 11 blocks):

| | Developer backend, PyTorch (CPU) | Frozen engine, CPU | Frozen engine, detector on DirectML |
|---|---:|---:|---:|
| Ready to serve | 19.1 s | **4.3 s** | **4.1 s** |
| First page (models load on first use) | 10.4 s | 9.4 s | 8.4 s |
| Working set, ready / after the page | 1,132 / 1,448 MiB | 913 / **1,222 MiB** | 912 / 1,469 MiB |
| Private bytes after the page | 2,553 MiB | 2,013 MiB | 2,894 MiB |

- Text analysis took 207–261 ms, and every block on the page was translated.
- The frozen `.exe` downloaded the dictionary itself from Hugging Face (119 MiB in 6 s).
- With no models, it answered readiness 1.1 s after launch, listing exactly the missing
  defaults and their `--prepare` commands.
- DirectML commits extra private memory, but its working set stays close to the CPU path's.

**Size gate: missed and explained.** The folder is **462 MiB** without models (201 files), over
the 400 MB target. A solid LZMA stream over it, roughly what an installer stores, is **89 MiB**.
The largest parts:
- unidic-lite: 248 MiB, the dictionary the fugashi tokenizer memory-maps. Every Python install
  of YomiScan already carries it.
- OpenCV: 70 MiB after the FFmpeg plugin is removed; the page renderer needs it.
- ONNX Runtime: 63 MiB.

Shrinking further means replacing the tokenizer's dictionary, which would change the lexical
analysis that the golden set measures. That is not worth it for disk space, and the download is
what users notice. Increment 5 measures the real installer.

**Startup gate: passed.** About 4 s to ready (gate ≤ 10 s).

**CI.** Two new jobs:
- "Python 3.13 without PyTorch": the suite in a Torch-free environment.
- "Frozen local engine / Windows": builds the engine and runs the no-model check.

The distribution check installs the wheel without the `reference` group and expects the
default engines to report their missing models.
