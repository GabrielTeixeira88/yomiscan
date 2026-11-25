# Stage 5b: packaged local engine (optional companion)

Status: **built**. Increments 1–5 are done. The installer is compiled and checked on CI's clean Windows runner; running it on the owner's machine waits for the owner's go-ahead (see increment 5). Started on the owner's go-ahead (2026-11-25)
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
| 3 | **Engine profile and freezing.** Default composition uses the Torch-free engines; Torch, transformers and manga-ocr move to an optional reference extra. A PyInstaller one-folder build with the API tests run against it; measured size and startup. | Done: Torch-free defaults, frozen engine 462 MiB (89 MiB compressed), ready in about 4 s (see increment 3). |
| 4 | **Launcher.** A native-messaging host that starts the frozen engine on a random loopback port with a per-launch token, hands both to the extension, and stops it after an idle period. The extension's engine choice gains the companion. | Done: real Chrome end to end, launch to first chapter in 12 s, idle exit and relaunch (see increment 4) |
| 5 | **Installer and release.** Per-user Windows installer (native-messaging registration in HKCU, uninstall cleanup), first-start model download with consent, docs, a clean-machine check in Windows Sandbox. | Done: NSIS installer built and checked on CI's clean Windows runner instead of Windows Sandbox; first start downloads 845 MB in 37 s after consent (see increment 5) |

## Gates

| Gate | Threshold |
|---|---|
| Vision parity | Torch-free detector boxes identical to the Torch path on ≥ 99% of regions; OCR text identical on ≥ 98% of blocks, end to end. GPU differences are reported, not hidden. |
| Translation parity | ≥ 95% of lines identical to transformers OPUS on the translation set; every difference listed. |
| Package size | Frozen engine without models ≤ 500 MB on disk. Owner decision 2026-11-25: raised from the proposed 400 MB after the measurement (462 MiB). |
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

**Size gate: passed after the owner raised it to 500 MB.** The folder is **462 MiB** without
models (201 files). That was over the originally proposed 400 MB; the owner then set the limit
to 500 MB (2026-11-25). A solid LZMA stream over it, roughly what an installer stores, is **89 MiB**.
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

## Increment 4: launcher

**Engine side.**
- `yomiscan/launcher.py` is the native-messaging host. Chrome starts `yomiscan-engine.exe
  chrome-extension://<id>/` for each `sendNativeMessage`, and the same frozen executable
  recognizes that argument. The host answers one message and exits:
  - `status`: version, whether the default models and the dictionary are installed, whether an
    engine runs.
  - `start`: reuses a running engine, or starts one detached (breaking away from Chrome's job
    object) on a free loopback port, with a fresh 43-character token passed through the
    environment, never the command line. It answers `{port, token}` once the engine serves
    readiness.
  - `stop`: ends the running engine.
- A lock file keeps two tabs from starting two engines. Port, token and process id are kept in
  `%LOCALAPPDATA%\YomiScan\engine-state.json`, and the engine logs to
  `%LOCALAPPDATA%\YomiScan\logs\engine.log`.
- **Token.** With `YOMISCAN_TOKEN` set, `LocalRequestGuard` requires `X-YomiScan-Token`
  (constant-time comparison) on every request, including `/health`. CORS allows the header. The
  developer server, which has no token, is unchanged.
- **Idle exit.** `--idle-exit SECONDS` (the launcher passes 900; `YOMISCAN_IDLE_SECONDS`
  overrides it for tests). An ASGI wrapper counts requests in flight, so a long page never
  counts as idle.
- **Registration.** `yomiscan-engine.exe --register --extension-id <id>` (or `--extension-path
  <unpacked folder>`, which computes the ID as Chrome does) writes the host manifest and the
  HKCU key `Software\Google\Chrome\NativeMessagingHosts\com.yomiscan.engine`, with no
  administrator rights. `--unregister` removes both.

**Extension side.**
- The manifest adds the `nativeMessaging` permission.
- `companion.ts` asks the host for `status` (cached 30 s, because each check starts the host) and
  `start`. It keeps port and token in `chrome.storage.session`: memory only, extension pages
  only. "Host not found" means not installed, and contexts without native messaging (content
  scripts, tests) see "not installed".
- `local.ts` is the single seam for local requests. "Local" means the companion when it is
  installed with its models, otherwise the developer backend on its configured port.
  - `localFetch` adds the headers. After a network error or a 401, it launches the engine again
    and retries once.
  - After a launch, it waits until readiness leaves `initializing`, because the engine answers
    at once but loads its models for a few seconds.
  - Request timeouts start only after that wait.
- Automatic resolves to the companion first (owner decision), then installed browser models,
  then a running developer backend. An explicit Browser choice never starts the companion.
- The chapter transport asks the service worker for the address (only for non-browser pages).
  The service worker hands the token to the offscreen document directly, so content scripts
  never see it; the offscreen document attaches it only for that exact origin.
- Advanced → Browser engine shows a line about the companion: not installed, installed with its
  models, or what it is missing and the `--prepare` command.

**Measurements** (development machine; native host driven like Chrome does):

| Step | Time |
|---|---:|
| `status` (host start, model check, answer) | 0.35 s |
| `start` with no engine running (launch until readiness answers) | 1.4 s |
| `start` with the engine running (reuse) | 0.36 s |

Without the token, or with a wrong one, the engine answered 401.

**End to end** (`extension/tests/companion-e2e.mjs`):
- **Setup:** real headless Chrome with a fresh profile, so no browser models; the developer
  backend stopped; three sample pages; Chrome started with `YOMISCAN_IDLE_SECONDS=20`.
- **ID:** Chrome assigned the unpacked extension the ID that `--extension-path` computed, and
  the host answered `status` from the service worker.
- **Read Chapter**, Automatic: started the companion and read the 3 pages in **12.0 s**,
  including the launch and model load. The engine kept running after the host exited.
- **Translate Chapter:** rendered the 3 pages with the pixel renderer in 12.3 s (OCR and
  translation came from the processing cache).
- **Idle exit and relaunch:** the engine exited by itself 20 s after the last request. The next
  Read Chapter launched a new engine and finished in 20.9 s.

Two bugs were found by this run and fixed before merging:
- The first request after a launch arrived while the models were loading (503).
- A request timeout created before the launch wait expired during it.

**Not covered yet:**
- First-start model download from the extension (the panel names the `--prepare` command).
- An installer, and running the engine from a stable install location; registration now points
  at the build folder.
- A console window may flash when Chrome starts the host in a visible (non-headless) Chrome.

All three belong to increment 5.

## Increment 5: installer and first start

**First start, with consent.**
- The native host gains `prepare`. It starts the explicit download (`yomiscan-engine --prepare
  --progress <file>`) as a detached process and answers at once.
- `status` reports what is missing, how many bytes, the source
  (`huggingface.co/<repository>`) and the download's progress.
- A download whose process is gone is reported as failed, with the path of its log. A second
  `prepare` while one runs does nothing.
- In the extension, `chapter/companion-setup.ts` is a card shown when the local engine is
  installed without its models:
  - It shows the size (845 MB), where the files come from and the fingerprint check.
  - It has **Download** and **Not now**, and shows progress.
  - While it is shown, the browser models' card stays hidden.
- Advanced → Browser engine shows the extension's ID when the engine is not installed, because
  the installer asks for it.

**Windowless executables.** The bundle now has two executables. `yomiscan-engine.exe` is the
console one for commands. `yomiscan-engine-host.exe` is windowless: Chrome starts it as the
native host, and it runs the detached engine and the download.
- No console window can appear. The program reattaches the standard handles Windows passed it:
  Chrome's pipes, or the log file.
- `disable_windowed_traceback` is set. Without it, an unhandled error made PyInstaller's
  windowed bootloader open a dialog and wait for a click that nobody can give; a crashed
  download process (see below) hung that way.

**Installer** (`packaging/engine/installer.nsi`, NSIS 3, zlib license; built by
`scripts/build_installer.py`):
- Per user, no administrator rights: `%LOCALAPPDATA%\Programs\YomiScan Engine`, HKCU only,
  solid LZMA compression.
- Pages: welcome, license (YomiScan's MIT license plus a pointer to the bundled third-party
  notices), then "Connect to Chrome", which asks for the extension ID. Silent installs use
  `/S /EXTENSIONID=<id>`.
- Install stops a running engine of an earlier install, copies the files, and registers the
  native host for that extension. An invalid ID aborts the install (exit code 2). It also writes
  the Add/Remove Programs entry.
- The uninstaller stops the engine, removes the registration, the files and the entry, then asks
  whether to remove downloaded models and data. Silent uninstalls keep them unless `/PURGE`.
- The engine build adds `LICENSE.txt` and `licenses/<package>/` with the license files of all 35
  bundled packages, indexed in `licenses/THIRD-PARTY-NOTICES.txt`. The bundle is 472 MiB.
- The installer is unsigned (owner decision), so SmartScreen can warn. Until the extension is in
  the Chrome Web Store, the user pastes the extension ID shown in Advanced; `--extension-id`
  pre-fills it with the store ID later.

**Clean-machine check.** Windows Sandbox needs administrator rights to enable, and a reboot. The
"Frozen local engine and installer / Windows" CI job uses a GitHub-hosted runner instead, which
is a fresh Windows VM on every run. `scripts/validate_installer.py`:
- refuses an invalid extension ID;
- runs a silent install;
- checks the files, the native-messaging key and manifest (the windowless host, the allowed
  extension) and the uninstall entry;
- asks the installed host for `status` the way Chrome does;
- runs a silent uninstall and checks that everything but user data is removed.

The job uploads the installer as an artifact. Running a freshly downloaded NSIS compiler on the
development machine was refused by the permission system, so the installer is compiled on CI.

First CI run (NSIS 3.13 from Chocolatey, GitHub `windows-latest`):

| Check | Result |
|---|---|
| Installer | **85.3 MiB** (installs 473.6 MiB) |
| Invalid extension ID | Refused, exit code 2, nothing registered |
| Silent install | 13.8 s; files, native-messaging key and manifest (windowless host, allowed extension), uninstall entry |
| Installed host `status`, Chrome framing | Answers; 805 MiB of models still to download |
| Silent uninstall | 1.0 s; files, registration and entry removed, user data kept |

**End to end, first start** (`YOMISCAN_E2E_FIRST_START=1 node extension/tests/companion-e2e.mjs`:
real Chrome; the engine's data folder empty through `YOMISCAN_DATA`; developer backend stopped):

| Step | Result |
|---|---|
| Status before consent | Models missing: 845 MB |
| Panel | Offered the local engine's models (845 MB, from Hugging Face); nothing downloaded before the click |
| Download, verify, store | **37.1 s**, then the card closed |
| Automatic → Read Chapter, 3 pages | 20.9 s, including the engine start and model load |
| Translate Chapter, 3 pages, pixel renderer | 14.6 s |
| Idle exit (20 s test setting), next Read Chapter | Exited after 24 s; a new engine served the next Read Chapter in 22.0 s |

The first run of this test found a missing import in `--prepare --progress`. The download
process crashed, and because of the windowed traceback dialog it hung instead of exiting. Both
are fixed and covered by tests.

**Not done.**
- The installer has not run on the owner's machine.
- Code signing (owner decision: unsigned).
- A Chrome Web Store listing, so no extension ID needs pasting (Stage 6).

