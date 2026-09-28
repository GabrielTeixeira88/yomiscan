# YomiScan

An offline-first Japanese manga reading assistant that extracts and analyzes Japanese text from manga images using local OCR and NLP.

**Current status: Phase 1 — OCR validation only.** Local OCR code and a CLI are implemented.
NLP and all other study features are planned. Accuracy on real manga screenshots has not
yet been established; unit tests are not evidence of recognition quality.

The purpose is to help Japanese learners study manga without paid APIs or per-request
costs. The first question is whether local OCR can reliably read real, manually cropped
manga text regions.

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
Model weights and real-image inference have not been tested yet.

## Design and validation

`OCRResult` and the typed `OCREngine` protocol form the engine-independent boundary.
`MangaOCREngine` implements it and loads one model per instance. Importing the public
interface does not load the network. Unit tests substitute a fake upstream model.
The CLI logic lives in the package so the script stays small and tests can import it.

Direct runtime dependencies are manga-ocr and Pillow; pytest is a dev dependency.
manga-ocr may bring Japanese tokenizer libraries such as fugashi transitively for its
own model. YomiScan does not implement a morphological analysis or NLP pipeline.

See [sample testing instructions](samples/README.md) for a manual evaluation matrix.
Do not commit copyrighted screenshots. Compare actual OCR with a manually verified
transcription before describing recognition as reliable.

## Roadmap and eventual architecture

1. **Current:** validate local OCR on cropped manga screenshots, recording accuracy and latency.
2. **Future:** Chrome region selection → local FastAPI → OCR → Japanese morphological
   analysis → local JMdict lookup → local sentence translation → one detailed study popup.
3. **Future:** full-page detection, OCR, sentence reconstruction, translation, masking,
   inpainting, and typesetting.

See [architecture](docs/architecture.md). No extension, HTTP API, NLP, dictionary,
translation, detection, inpainting, accounts, or cloud deployment is implemented.

## Limitations and licensing

Manually crop one text region; this is recognition, not full-page text detection.
There are no bounding boxes or confidence scores. Small, stylized, obscured, or long
text can be misread. The generative OCR model can invent text on images without text.
Furigana is not exposed as separate readings. Punctuation and spacing may be normalized
by the upstream engine. Each CLI invocation loads a new engine, so wall-clock runtime
includes startup even though the displayed inference time does not.

YomiScan's original source code uses the [MIT License](LICENSE). Third-party libraries,
models, and datasets retain their own licenses; YomiScan's license does not relicense them.
