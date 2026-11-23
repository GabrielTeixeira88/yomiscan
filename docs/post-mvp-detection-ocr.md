# Post-MVP Detection and OCR experiments

Stage 2 covers P14–P17. Phases 1–7 remain historical MVP records. Stage 1 was merged
through PR #1 at `c651a3cf6f1a1bc68997f43b5d997dd439c6c104`; this work begins there.
The existing FastAPI/MV3 pipeline, original manga-ocr, PyTorch detector, 0.50/0.50
thresholds and OPUS translator remain the production defaults.

See [artifact provenance](research/stage2-model-provenance.md) and the
[measured results and decisions](research/stage2-detection-ocr-results.md).

## Optional setup and selection

Ordinary setup and CI still use `uv sync --frozen`. ONNX Runtime is an optional
`vision` extra; `benchmark` supplies optional process-memory observations.
The lockfile pins ONNX Runtime 1.32.0 and its small transitive dependencies. Windows
Python 3.13 CPU inference was tested. No CUDA provider or Android speed claim is made.
Runtime telemetry is disabled before creating CPU sessions.

```powershell
uv sync --frozen --extra vision --extra benchmark
# Explicit setup only. Original models may already be cached.
uv run --frozen --extra vision python scripts/setup_vision_models.py detector ocr-original ocr-2025 ocr-onnx
```

Setup downloads only the named, pinned files and verifies published weight/vocabulary
SHA-256 values. Models remain in the standard local Hugging Face cache, outside Git.
No experimental adapter downloads weights during construction. A missing artifact
produces setup instructions and preserves the underlying cause. After setup,
`HF_HUB_OFFLINE=1` and `TRANSFORMERS_OFFLINE=1` require cached inference.

Experimental backend selection is explicit:

```powershell
$env:YOMISCAN_DEVICE = 'cpu'
$env:YOMISCAN_DETECTOR = 'onnx-int8'   # default: current
$env:YOMISCAN_OCR = '2025-onnx'      # default: current
uv run --frozen --extra vision uvicorn yomiscan.api.main:app --host 127.0.0.1 --port 47615
```

Remove these two selection variables (or set each to `current`) before ordinary use.
`YOMISCAN_TRANSLATION_ENGINE` is independent and unchanged. Optional detector initialization
stays lazy on the existing worker. OCR is constructed once in the existing service
lifecycle; selected resources are closed on shutdown. No new UI or persistent cache exists.

The detector factory returns the existing `TextDetector` protocol. Direct callers can
set `ComicTextDetector(bubble_threshold=.25, free_threshold=.5)`; the legacy
`threshold=` argument remains valid. The ONNX adapter uses the same region/classes and
original-image coordinates. Its width/height target-size input is export-specific.
Its `v4-s` weights are not proven equivalent to the PyTorch checkpoint.

The OCR factory returns the existing `OCREngine` protocol:

| Selector | Weights / preprocessing / decoding |
|---|---|
| `current` | Original manga-ocr package, grayscale→RGB, existing published generation |
| `original-rgb` | Pinned original weights, RGB, published generation; preprocessing control |
| `2025` | Pinned 2025 source, RGB, published four-beam generation, maximum length 300 |
| `2025-greedy` | Same 2025 source, RGB, greedy, 128 new tokens, no repeat-ngram rule |
| `2025-onnx` | Precisely mapped 2025 export, matching RGB/greedy/128, per-crop KV reuse |
| `2025-onnx-no-cache` | Same export/control, recompute full prefix; benchmark control only |

The 2025 source has a smaller encoder. A gain over original manga-ocr cannot be
attributed to runtime alone. The matched 2025 greedy pair provides the runtime control;
the ONNX cache pair isolates KV reuse. ONNX start/stop IDs are resolved from the pinned
vocabulary and checked against the artifact's configuration. Tensor layouts come from
the actual graph. Cross-attention state belongs to one crop, and empty cached-branch
presents do not replace its first-step state. Explicit token-limit termination is an
error in the experimental adapters; it does not masquerade as complete text.

## Local corpus and annotations

Keep private pages, transcriptions, crops, manifests and raw outputs under ignored
`samples/`, `.cache/` or `reports/`. Do not commit manga pages or diagnostic ZIPs.
Raw benchmark JSON intentionally contains OCR/reference/translation text and may include
local error details; it is not a privacy-filtered Stage 1 export. Share aggregate
Markdown findings, or use the explicit Stage 1 export with its inclusion controls.

An annotation manifest uses this format (coordinates are original pixels, XYXY):

```json
{
  "schema_version": 1,
  "annotation_method": "Independent visual transcription, main text excluding ruby",
  "pages": [{
    "id": "synthetic-page",
    "image": "page.png",
    "sha256": "replace-with-the-image-byte-sha256",
    "split": "held_out",
    "annotations_complete": true,
    "regions": [{
      "id": "bubble-1", "bbox": [10, 20, 90, 120],
      "category": "dialogue", "text": "日本語",
      "tags": ["vertical", "small"]
    }]
  }]
}
```

Image paths resolve relative to the manifest. Hashes prevent scoring annotations against
replaced pixels. IDs must be unique; boxes must be valid and within image bounds.
Categories are `dialogue`, `narration`, `artwork`, `sfx`, `control`. Omit `text`/use null
when transcription is uncertain. An empty string is an intentionally blank reference.
Use `regions: null` when no geometry ground truth exists; missing labels never become
zero errors. Set `annotations_complete` only after annotating all relevant text; otherwise
unmatched predictions are reported without claiming a false-positive count.

Include normal vertical/horizontal dialogue, small text/ruby, interjections, long text,
mixed scripts, low contrast, unusual typography, art backgrounds and blank controls.
Keep tuning and held-out pages separate by source/chapter where possible. Derived crops
must stay in their source's split. Independently check references before reading model
outputs, record uncertainty and seek human adjudication before adoption decisions.

## Independent benchmark commands

```powershell
uv run --frozen --extra vision --extra benchmark python scripts/benchmark_detection.py samples/vision/pages.json --engine current --bubble-threshold .5 --pipeline --output reports/detect-a.json
uv run --frozen --extra vision --extra benchmark python scripts/benchmark_detection.py samples/vision/pages.json --engine current --bubble-threshold .25 --pipeline --output reports/detect-b.json
uv run --frozen --extra vision --extra benchmark python scripts/benchmark_detection.py samples/vision/pages.json --engine onnx-int8 --bubble-threshold .5 --pipeline --output reports/detect-c.json
uv run --frozen --extra vision --extra benchmark python scripts/benchmark_detection.py samples/vision/pages.json --engine onnx-int8 --bubble-threshold .25 --pipeline --output reports/detect-d.json
# Optional independent same-class overlap/containment policy, isolated from production:
uv run --frozen --extra vision --extra benchmark python scripts/benchmark_detection.py samples/vision/pages.json --engine current --suppression coverage --pipeline --output reports/detect-e.json
uv run --frozen --extra vision --extra benchmark python scripts/benchmark_ocr.py samples/vision/ocr.json --engine current --output reports/ocr-current.json
uv run --frozen --extra vision --extra benchmark python scripts/benchmark_ocr.py samples/vision/ocr.json --engine original-rgb --output reports/ocr-rgb.json
uv run --frozen --extra vision --extra benchmark python scripts/benchmark_ocr.py samples/vision/ocr.json --engine 2025 --output reports/ocr-2025.json
uv run --frozen --extra vision --extra benchmark python scripts/benchmark_ocr.py samples/vision/ocr.json --engine 2025-greedy --output reports/ocr-greedy.json
uv run --frozen --extra vision --extra benchmark python scripts/benchmark_ocr.py samples/vision/ocr.json --engine 2025-onnx --output reports/ocr-onnx.json
uv run --frozen --extra vision --extra benchmark python scripts/benchmark_ocr.py samples/vision/ocr.json --engine 2025-onnx-no-cache --output reports/ocr-no-cache.json
# Identical production crops, grouped/padded exactly as the existing pipeline:
uv run --frozen --extra vision --extra benchmark python scripts/benchmark_ocr.py samples/vision/pages.json --detector-results reports/detect-a.json --engine 2025-onnx --output reports/ocr-production.json
uv run --frozen python scripts/summarize_vision_results.py "reports/*.json" --output reports/summary.md
```

Use a fresh process per arm and run arms sequentially. Defaults are CPU, four requested
threads, one unmeasured warmup and three measured repetitions **per image/crop**.
`--split` selects `tune`, `held_out` or `control`. `--pipeline` requires the configured
local JMdict database and cached original OCR/OPUS; it runs downstream processing once
using the exact saved detections, not an extra detector inference. It captures Stage 1
snapshots and labels undetected, incorrectly grouped, OCR/translation failures and
translated-but-renderer-preserved dialogue separately.

Detection matching requires at least 50% of an annotated rectangle covered by one raw
prediction. A predicted box covering two dialogue units is a merge. Repeated assignments
identify duplicates. Grouped crops receive the unchanged four-pixel padding; at least
95% coverage counts as a complete annotation rectangle. These are **geometry proxies**,
not proof that every glyph is present. Inspect source/crop pixels before calling a crop
truncated. Split candidates are partial multiple overlaps requiring adjudication.
The benchmark-only suppression arm keeps larger same-class boxes for >=90% containment
or >=80% IoU, never joins neighbors, and does not suppress unknown classes.

OCR reports literal CER/exact match and a separate NFKC/whitespace-normalized comparison.
Character insertions, deletions and substitutions are separately aligned. Failed reads
score as empty output against known references; missing truth remains unscored. A blank
reference's inserted characters are recorded separately. Production crops are scored
only with a unique, sufficiently covered reference; incomplete/merged crops remain
explicitly unscored. CER does not establish translation quality.

Warm median/p95 use successful measured reads; p95 uses nearest rank. Initialization
includes the implementation's imports/cache verification/model construction and the
original package's built-in example warmup. It excludes model downloads and does not
represent an OS cold disk cache. RSS is for the whole process; 10 ms sampled peaks are
lower bounds, and Windows OS peaks are process-lifetime high-water marks. Memory after
the detector load is distinct from end-to-end memory including OCR/OPUS. CUDA/GPU memory
is unmeasured. Record artifact hashes/sizes, versions, hardware and sample counts with results.

## OCR confidence and diagnostics

`OCRResult` keeps its text, engine, timing and optional metadata contract. Greedy
experimental adapters populate `confidence` and `confidence_method` with the mean
selected-token probability **including EOS**, plus model/revision, preprocessing,
decoding, termination, token count and `uncertainty: uncalibrated`. Original manga-ocr
does not expose scores; they remain unavailable. Published beam-mode confidence is
also unavailable rather than guessed from beam scores.

Scores are diagnostic metadata only. They do not represent the probability a transcript
is correct. There is no 0.85 preservation/retry gate or automatic low-confidence rejection.
Stage 1 page reports now allowlist the optional OCR metadata separately from detector
confidence. Unknown original confidence and termination remain unknown; summary counts
of observed token-limit errors are not evidence of zero truncation in an opaque engine.

The summary records confidence/CER correlation, high-confidence errors, correct
low-confidence reads and exploratory threshold precision/recall, including short and
mixed-script subsets. A useful warning/retry gate needs an independent representative
calibration and held-out validation set. Stage 2 adopts no such gate.
