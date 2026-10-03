# YomiScan

An offline-first Japanese manga reading assistant that extracts and analyzes Japanese text from manga images using local OCR and NLP.

**Current status: Phase 7 — Study Mode and Translate Chapter MVP implemented.** Local manga OCR, Japanese
morphological analysis, JMdict lookup, Japanese → English translation, localhost
FastAPI, and a Chrome extension with screenshot region selection and one comprehensive
study popup are available. The real extension flow was tested in isolated headless
Chrome with CPU inference. Translation quality remains limited on casual dialogue.
Single-page detection, cropping, OCR, initial ordering/grouping and block analysis are now
available through CLI/API. Single-page rendering now removes safely masked text and fits
English into suitable regions, preserving uncertain blocks. A real local page was visually
reviewed; broader detection/rendering accuracy still needs representative pages.
Translate Chapter progressively renders supported image-based readers, prioritizes visible
pages, discovers lazy-loaded images, and offers reversible Original/English overlays.
Generic discovery and cross-origin capture have limitations; universal site support is not claimed.

The purpose is to help Japanese learners study manga without paid APIs or per-request
costs. Sentence translation is separate from ordered tokens with readings, dictionary
forms, POS, conjugation information, and candidate English dictionary meanings.

## Setup (Windows / PowerShell)

Install Git, Python **3.13.9**, and [uv](https://docs.astral.sh/uv/getting-started/installation/).
From the repository root:

```powershell
py -3.13 --version
uv --version
uv sync
uv run pytest
```

`uv sync` creates a local `.venv`, installs the `yomiscan` package from `backend/`,
and includes the dev dependency group. Python is constrained to `>=3.13,<3.14`.
The generated `uv.lock` records resolved versions; direct dependencies live in
`pyproject.toml`. No global Python configuration changes are needed.

## Single-page analysis (Phase 5)

```powershell
uv run python scripts/detect_text.py samples/page.png --device cpu --output samples/page-boxes.png
uv run python scripts/analyze_page.py samples/page.png --device cpu --debug-image samples/page-debug.png --json-output samples/page-analysis.json
```

The existing local server also exposes `POST /api/v1/analyze-page` (multipart `file`,
`X-YomiScan-Client: study-extension-v1`). Study Mode's `/api/v1/analyze-image` is unchanged.
Detection uses a pinned comic-trained RT-DETR-v2 model (about 172 MB, publisher license
Apache-2.0), loaded once on the first page request. Models run locally and reuse the
Hugging Face cache. No new dependencies. Full analysis needs the existing JMdict setup.

See [detector decision, commands, cache, limitations and evaluation](docs/phase-5-page-analysis.md).
Keep page images and debug outputs under ignored `samples/`. Browser chapter orchestration
reuses this single-page pipeline; there is no chapter archive/backend batch endpoint.

## Translate Chapter (Phase 7)

Start the configured backend and build the extension:

```powershell
# Terminal 1, repository root (after model/JMdict setup)
uv run uvicorn yomiscan.api.main:app --host 127.0.0.1 --port 8765 --reload
# Terminal 2
cd extension
npm.cmd ci
npm.cmd run build
```

Load `extension/dist` at `chrome://extensions` → Developer mode → Load unpacked.
Open an image-based chapter and click YomiScan → **Translate Chapter**. Visible pages
process first, one at a time. **Original / English** switches cached results immediately;
close the controls with × to read unobstructed. **Stop Translation** stops future work
while the current page may finish. **Retry Failed / Skipped** retries explicitly.
**Clear Session** removes all translated overlays and releases cached images.

**Select Text** (or Ctrl+Shift+Y) remains Study Mode. It stops chapter scheduling,
waits for the current page, and switches to Original before screenshot selection.
Chapter translation resumes only when explicitly started again.

For HTTP(S) images, the extension first fetches the selected source with permission for
its image host. A small YomiScan access window lists the required hosts; approve Chrome's
permission prompt or choose capture fallbacks. It then tries safe canvas extraction and
visible-tab cropping. **Allow scroll capture** enables a final tall-page stitching fallback;
it temporarily scrolls, restores position, and cancels on Escape/user input. No manual
zooming is needed for direct fetching or supported stitched captures. No access bypass.
Canvas/WebGL readers, frames, unusual layouts and restrictive content policies may not work.
See [chapter architecture, validation and limitations](docs/phase-7-chapter.md).
See [image acquisition, permissions and real-reader validation](docs/phase-7-acquisition.md).

## Single-page rendering (Phase 6)

```powershell
uv sync
uv run python scripts/create_text_mask.py samples/page.png --output samples/text-mask.png
uv run python scripts/render_page.py samples/page.png --device cpu --output samples/translated.png --debug-dir samples/render-debug
```

Rendering runs page analysis once, generates tight foreground masks, reconstructs safe
backgrounds using uniform fill/OpenCV inpainting, then fits and typesets English with
Pillow's bundled Aileron font. It preserves original pixels when a block is uncertain,
overlaps another detection, fails processing, or cannot fit readable English.
Complex artwork and unclassified free text are normally skipped. The source is not changed.
The quality pass separates tight glyph masks from enclosed bubble/narration interiors,
uses balanced measured wrapping and a preferred font size, and groups contained duplicate
predictions. See the [real-page skip audit and before/after observations](docs/phase-6-quality.md).

The existing server exposes `POST /api/v1/render-page`, multipart `file`, with the same
`X-YomiScan-Client: study-extension-v1` header. It returns PNG and rendered/skipped counts
in response headers. The Chrome extension remains Study Mode only.

No additional model weights or font installation is needed; `uv sync` installs OpenCV
headless and NumPy. Rendering uses CPU; `--device` controls analysis. Debug output includes
original, detection, raw/final masks, cleaned and final pages, plus metadata.
See [Phase 6 design, licensing, validation and limitations](docs/phase-6-rendering.md).
See the [targeted coverage pass](docs/phase-7-coverage.md) for dense-bubble fixes,
conservative artwork-text recovery, per-block reasons and real before/after results.

## Study mode: two-terminal development

Complete the [JMdict import](#set-up-the-local-jmdict-dictionary) below first. Install
Node.js 22+ for extension tooling. The backend runs on your machine and must be started
manually for this MVP.

Terminal 1, from the repository root:

```powershell
uv sync
uv run uvicorn yomiscan.api.main:app --host 127.0.0.1 --port 8765 --reload
```

Wait for `Application startup complete`. First startup may download OCR/translation
weights; subsequent requests reuse the initialized models. Set
`$env:YOMISCAN_DEVICE = "cpu"` before startup to force CPU (default `auto`).
`YOMISCAN_DICTIONARY` overrides `data/jmdict.sqlite3`. Once models are cached, set
`$env:HF_HUB_OFFLINE = "1"` to require offline model use.

Terminal 2, from the repository root:

```powershell
cd extension
npm.cmd ci
npm.cmd run build
npm.cmd run watch
```

Use `npm` on macOS/Linux. `npm.cmd` avoids Windows PowerShell's `npm.ps1` execution
policy error; changing execution policy is unnecessary.

1. Open `chrome://extensions`, enable **Developer mode**, and choose **Load unpacked**.
2. Select `extension/dist` (here **`C:\Users\T-GAMER\yomiscan\extension\dist`**).
3. Open a normal manga webpage, click YomiScan's extension action → **Select Text**, and drag around a
   Japanese speech bubble. Only that viewport crop is sent to the local backend.
4. Read the original, translation, readings, lemmas, POS, conjugations, and dictionary
   meanings in one scrollable popup. Extra senses expand inside it.
5. Close with **×** or **Escape**. Escape also cancels selection or dismisses pending work.

The suggested shortcut is **Ctrl+Shift+Y** (**Command+Shift+Y** on macOS). Conflicts
can leave it unassigned; change the binding at `chrome://extensions/shortcuts`.
Reload the extension and refresh the manga tab after rebuilding. Watch rebuilds code
but does not reload Chrome or type-check changes; run `npm.cmd run typecheck` separately.

Selected screenshots are sent only to the local YomiScan backend at `127.0.0.1:8765`.
Initial model/dictionary/dependency downloads are separate from local image analysis.
The full visible-tab screenshot is transient in extension memory; only the selected
crop is uploaded. Images/results are not saved by the application. There is no analytics,
cloud upload, paid API, or third-party inference. The attribution link opens externally
only if clicked.

## Local API

- `GET /health` → `{"status":"ok"}` when resources are ready; 503 after initialization
  failure. Fix setup and restart; see terminal diagnostics.
- `POST /api/v1/analyze-image`: multipart upload named **`file`**, plus header
  **`X-YomiScan-Client: study-extension-v1`**. Supports still PNG, JPEG and WebP.
- API schema: `http://127.0.0.1:8765/docs`. POST clients must supply the client header;
  the curl example is the simplest manual request.

```powershell
curl.exe http://127.0.0.1:8765/health
curl.exe -H "X-YomiScan-Client: study-extension-v1" -F "file=@samples/test.png" http://127.0.0.1:8765/api/v1/analyze-image
```

JSON contains `original_text`, separate `translation`, `processing` times, and ordered
`tokens` with readings, lemmas, dictionary forms, POS, conjugation, and grouped senses
with restrictions. The extension never needs to know which translation model is used.
Limits: **10 MiB image**, **12 megapixels**, one analysis at a time. Overlapping requests
return 429. The extension times out after 25 seconds. Client cancellation does not
interrupt ongoing model inference; wait before selecting again.

Bind to loopback, not `0.0.0.0`. Development CORS permits valid `chrome-extension://`
origins only, never `*` or arbitrary manga-site origins. To allow only your extension,
find its ID on `chrome://extensions` and set this before startup:

```powershell
$env:YOMISCAN_EXTENSION_ORIGINS = "chrome-extension://YOUR_EXTENSION_ID"
```

The custom header requires preflight for webpage requests; unapproved Origin/Host
headers are rejected. This is a local development boundary, not authentication against
other programs on your machine. The extension's fixed backend request URL sends analysis
to loopback port 8765; optional source-image host access is separate. Keep that port unless you
rebuild the extension with matching changes. Use one Uvicorn worker to avoid duplicating
model memory. See [extension instructions](extension/README.md) and
[Phase 4 validation/checklist](docs/phase-4-validation.md).

## Run OCR

Put your own cropped screenshot at `samples/test.png` (ignored by Git), then run:

```powershell
uv run python scripts/ocr_image.py samples/test.png
```

Quote paths containing spaces. To force CPU execution:

```powershell
uv run python scripts/ocr_image.py samples/test.png --cpu
```

The CLI prints the engine, inference time in milliseconds, and Japanese text.
Model initialization and download time are excluded from the reported inference time.
Upstream initialization logs and download progress may also appear on stderr.
Exit codes: `0` success, `2` invalid arguments/image, `3` model initialization failure,
`4` recognition failure.

The first valid-image run downloads model files from Hugging Face and initializes the
model, including an upstream warm-up. This needs internet access, disk space, and time.
Dependencies also require an initial download. After caching the model, inference runs
locally with no cloud OCR calls. The upstream guide estimates a roughly 400 MB model
download; Python dependencies require additional space. See the
[manga-ocr documentation](https://github.com/kha-white/manga-ocr).

Hugging Face normally stores weights in the user's cache. To keep model downloads
inside the ignored project cache, set this before the first OCR run:

```powershell
$env:HF_HOME = "$PWD/.cache/huggingface"
```

After a successful download, test offline operation using the same cache:

```powershell
$env:HF_HUB_OFFLINE = "1"
uv run python scripts/ocr_image.py samples/test.png --cpu
```

Unset offline mode with `Remove-Item Env:HF_HUB_OFFLINE` if files still need downloading.
Missing or incomplete weights produce an initialization error.

## CPU and GPU

CPU inference is supported. A compatible NVIDIA GPU can be selected automatically
by manga-ocr when the installed PyTorch build supports CUDA. Having an NVIDIA GPU
alone does not guarantee acceleration. Check the environment with:

```powershell
uv run python -c "import torch; print(torch.__version__); print(torch.cuda.is_available())"
```

GPU-specific package configuration is deferred until hardware is verified; use the
[official PyTorch installation guide](https://pytorch.org/get-started/locally/) when
selecting a compatible build. CPU remains the baseline.

Initial Windows validation passed dependency installation, package/upstream imports,
and 13 unit tests on Python 3.13.9. The installed PyTorch build was CPU-only and CUDA
was unavailable. Transformers emitted a warning that its image processor falls back
to the Pillow implementation because torchvision is absent; the import succeeded.
No Python version change or additional image-processing dependency was necessary.
Subsequent Phase 1 runs successfully recognized three local screenshots on CPU.

## Set up the local JMdict dictionary

From the repository root, download the official English JMdict source and import it:

```powershell
New-Item -ItemType Directory -Force data | Out-Null
Invoke-WebRequest -Uri "https://www.edrdg.org/pub/Nihongo/JMdict_e.gz" -OutFile "data/JMdict_e.gz"
uv run python scripts/import_jmdict.py data/JMdict_e.gz
```

This builds `data/jmdict.sqlite3`. Both raw XML and the generated database stay local
and are ignored by Git. Plain XML is also accepted. Use only official/trusted JMdict
sources; this importer is not a general-purpose XML ingestion service. The import
streams entries, stores English senses and metadata, and indexes exact spellings and
readings. It never parses XML during a lookup. Leave room for the compressed source,
database, and a temporary database during rebuilds.

Download and repeat the same import command to update the data. A failed build keeps
the previous database intact. Close running dictionary readers before replacing the
database on Windows. The database records source filename, SHA-256, import timestamp,
source/license URLs, and transformation details. Initial setup needs network access;
all subsequent tokenization and dictionary queries are fully local. No dictionary API
or Jisho requests are used.

## Analyze text or images

```powershell
uv run python scripts/analyze_text.py "でも大丈夫"
uv run python scripts/analyze_text.py "食べました"
uv run python scripts/analyze_text.py "高かった。猫とYomiScan！"
uv run python scripts/analyze_text.py "でも大丈夫" --translate --device cpu
uv run python scripts/analyze_image.py samples/test.png --cpu
```

Both analysis commands accept `--dictionary path/to/jmdict.sqlite3`. Paths default to
the current working directory; run examples from the repository root. Keep using
`scripts/ocr_image.py` for OCR-only output. Image analysis needs the same OCR weights
as Phase 1; text analysis never initializes the OCR model. Text analysis remains
lexical-only unless `--translate` is supplied. Image analysis includes sentence
translation by default; `--no-translation` retains the Phase 2 lexical-only workflow.
`--device auto|cpu|cuda` selects the translation device. Image `--cpu` forces both
OCR and translation onto CPU and cannot be combined with `--device cuda`.

The tokenizer is **fugashi + UniDic-lite** (a packaged UniDic 2.1.2 dictionary), chosen
as a small, reproducible baseline already compatible with Windows/Python 3.13. It is
explicitly selected rather than relying on whichever system MeCab dictionary exists.
Full UniDic is a potential future benchmark; no separate dictionary download is needed
for this tokenizer. UniDic is morphological data; JMdict supplies English meanings.

Output preserves UniDic segmentation: `でも大丈夫` currently becomes `で / も / 大丈夫`,
not a hardcoded two-word split. `大丈夫` has reading `だいじょうぶ`; `食べ` in `食べました`
looks up `食べる`, and `高かっ` looks up `高い`. Auxiliaries remain separate tokens.
Readings use UniDic's written kana fields, converted to hiragana; they are not a
phonetic transcription (for example, particle は retains the written reading は).

Each token reports candidate JMdict entries with their readings, English senses,
POS labels, and any retained restrictions/notes. Homonyms and archaic senses may
appear. These are dictionary candidates, **not context-selected meanings or sentence
translations**. Punctuation stays in the token list but is not looked up; unknown
words retain their surfaces and may have no lemma, reading, or dictionary match.
Empty text produces an empty token list. Whitespace is retained in `original_text`,
but UniDic does not emit it as tokens.

Analysis exit codes: `0` success, `2` invalid arguments/image, `3` missing/invalid
dictionary, tokenizer, OCR, or translation initialization error, `4` OCR or translation failure.
The dictionary importer returns `1` on import failure.

## Local sentence translation

```powershell
uv sync
uv run python scripts/translate_text.py "でも大丈夫"
uv run python scripts/translate_text.py "今日は学校に行かなかった。" "何をしているんだ？" --device cpu
uv run python scripts/benchmark_translation.py --device cpu
```

The default is **Helsinki-NLP/opus-mt-ja-en**, a small Marian model at a pinned
revision. It runs locally using Transformers/PyTorch, with no paid API or translation
service. The first invocation downloads approximately **306 MB** of model/tokenizer
files; Python dependencies use additional space. The model is loaded once per engine
instance and reused across sentences and real padded batches (up to eight by default).
Separate CLI invocations each initialize their own engine.

The default Hugging Face cache is `~/.cache/huggingface/hub` (normally
`C:\Users\<user>\.cache\huggingface\hub` on Windows). Set `HF_HOME` before setup to use
another directory, as shown above. Later runs reuse cached weights. After the first
successful run, verify offline use with:

```powershell
$env:HF_HUB_OFFLINE = "1"
uv run python scripts/translate_text.py "本当に大丈夫なの？" --device cpu
```

Use the same cache for setup and offline runs. An incomplete cache produces an
initialization error; unset `HF_HUB_OFFLINE` to finish downloading. Windows can cache
without symlinks; the upstream warning about extra disk usage is not a failure.

`auto` selects CUDA when available, otherwise CPU. Explicit `cuda` fails with an
actionable error when unavailable. CPU and Python 3.13.9 were verified; actual GPU
inference was **not** verified. Short synthetic examples took roughly 140–260 ms each
on the development CPU, excluding initialization. Other PCs and longer text will vary.
FP32 weights alone occupy about 303 MB; total RAM/VRAM includes runtime, activations,
and batch/beam buffers. Peak RAM/VRAM has not been measured; budget extra memory,
especially when OCR is loaded too.

Translation output includes source, English translation, engine, model, device, and
elapsed time. For batched inputs, each result reports its entire batch's elapsed time,
not individual latency; do not sum repeated batch times. Downloads and initialization
are excluded. Empty/whitespace-only CLI input is rejected before model loading;
exit codes are `0` success, `2` invalid input, `3` initialization failure, `4` inference
failure. Inputs over 512 model tokens and unfinished output fail rather than silently
losing text. Analyze-text preserves Phase 2's empty result and skips translation.

The observed translation of `でも大丈夫` is **“But I'm fine.”**, not a fixed expected
string. Omitted subjects are ambiguous. Slang, tone, and longer casual dialogue can be
mistranslated; the real crop run exposed a substantial meaning error. This is a usable
local baseline, not a validated manga localization system. See
[model comparison, licensing, and manual evaluation](docs/phase-3-translation.md).

## Design and validation

`OCRResult` and the typed `OCREngine` protocol form the engine-independent boundary.
`MangaOCREngine` implements it and loads one model per instance. Importing the public
interface does not load the network. Unit tests substitute a fake upstream model.
The CLI logic lives in the package so the script stays small and tests can import it.

Direct runtime dependencies are manga-ocr, Pillow, fugashi, UniDic-lite, torch,
transformers, sentencepiece, sacremoses, FastAPI, Pydantic, Uvicorn, and python-multipart;
pytest and httpx are dev dependencies.
SQLite and the XML importer use Python's standard library.
`JapaneseTokenizer` isolates the tokenizer, while `TextAnalyzer` composes it with the
dictionary. Each analyzer reuses its tokenizer and dictionary connection. Shared
entries are stored once per result and referenced by JMdict ID from tokens.

Run `uv run pytest` for tests covering real lightweight tokenization, synthetic JMdict
imports (including gzip and failed rebuilds), normalized lookup, CLI errors, and a
mocked OCR/translation-to-analysis pipeline. Tests need no network or neural weights. The full
downloaded JMdict database is not required for tests. See
[Phase 2 validation](docs/phase-2-validation.md) for actual execution results.

See [sample testing instructions](samples/README.md) for a manual evaluation matrix.
Do not commit copyrighted screenshots. Compare actual OCR with a manually verified
transcription before describing recognition as reliable.

## Roadmap and eventual architecture

1. **Implemented:** local OCR → sentence translation + morphological analysis / JMdict lookup.
2. **Implemented:** Chrome screenshot selection → localhost FastAPI → one study popup.
3. **Implemented:** single-page text detection, region cropping, initial reading order/grouping,
   OCR and translation/lexical analysis per block.
4. **Implemented:** conservative masks, text removal/inpainting, English font fitting,
   typesetting and single-page translated PNG output through CLI/API.
5. **Implemented:** generic chapter-image discovery, progressive serial processing,
   viewport priority, lazy-image observation, Original/English overlays, session cache,
   page states, Stop/Retry and cleanup.
6. **Future:** OCR correction, translation engine improvements/benchmarking,
   manga-context-aware translation, vocabulary saving/export,
   improved artwork reconstruction, broader site adapters/acquisition support,
   persistent caching, and packaging/automatic local backend startup.

See [architecture](docs/architecture.md). JLPT grading, accounts, vocabulary export,
model fine-tuning, and cloud deployment are not implemented.

## Limitations and licensing

Study Mode accepts one selected crop. Page analysis accepts a complete page and returns
text boxes and detector scores; the OCR engine itself has no confidence score. Small, stylized, obscured, or long
text can be misread. The generative OCR model can invent text on images without text.
Furigana is not exposed as separate readings. Punctuation and spacing may be normalized
by the upstream engine. Each CLI invocation loads a new engine, so wall-clock runtime
includes startup even though the displayed inference time does not.

UniDic-lite is an older dictionary and can split expressions differently from JMdict.
There is no multi-token phrase reconstruction, grammar explanation, word-sense
disambiguation, or tokenizer comparison yet. Kana normalization can merge homophones;
candidate lists can be verbose. Reading and sense restrictions are preserved and
displayed, not used to claim a context-specific sense. OCR errors propagate into NLP.

YomiScan's original source code uses the [MIT License](LICENSE). Third-party libraries,
models, and datasets retain their own licenses; YomiScan's license does not relicense them.
YomiScan uses JMdict from the Electronic Dictionary Research and Development Group
(EDRDG), under CC BY-SA 4.0. The generated database is derived dictionary data, not
MIT-licensed source code. UniDic-lite includes UniDic Consortium data under BSD terms.
See [third-party attribution and redistribution notes](docs/third-party-licenses.md).
