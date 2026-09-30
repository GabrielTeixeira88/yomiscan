# YomiScan

An offline-first Japanese manga reading assistant that extracts and analyzes Japanese text from manga images using local OCR and NLP.

**Current status: Phase 3 — local manga OCR, Japanese morphological analysis,
local JMdict dictionary lookup, and local Japanese → English sentence translation
are implemented.** Real CPU inference and a complete crop-to-analysis run have been
verified. This does not establish accuracy across manga styles or dialogue contexts.
FastAPI, the Chrome extension, and all browser/UI/chapter workflows remain future work.

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
transformers, sentencepiece, and sacremoses; pytest is a dev dependency.
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
2. **Future:** Chrome extension, screenshot selection, FastAPI, and detailed study popup.
3. **Future:** Translate Chapter, manga page discovery, text detection, inpainting,
   typesetting, image overlays, and lazy-loaded page translation.

See [architecture](docs/architecture.md). No extension, selection UI, detailed popup,
HTTP API, chapter translation, JLPT grading, detection, inpainting, typesetting,
accounts, or cloud deployment is implemented.

## Limitations and licensing

Manually crop one text region; this is recognition, not full-page text detection.
There are no bounding boxes or confidence scores. Small, stylized, obscured, or long
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
