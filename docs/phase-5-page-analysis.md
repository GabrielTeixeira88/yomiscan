# Phase 5: single-page detection and analysis

Implemented: replaceable detection, original-image coordinates, padded crops, reused
manga-ocr, conservative line grouping, initial reading order, batch sentence translation,
lexical/JMdict analysis, per-block failures, CLI diagnostics, and a local page API.
Study Mode and the extension are unchanged. No rendering or chapter orchestration exists.

## Detector decision

Default: `ogkalu/comic-text-and-bubble-detector`, RT-DETR-v2 R50vd, pinned revision
`16e8a622f91fabc6b5b65c96d32d1183f8843546`. The
[publisher's model card](https://huggingface.co/ogkalu/comic-text-and-bubble-detector)
describes comic training and three classes: bubble outline, text inside bubbles, and
text outside bubbles. YomiScan retains only the two text classes. Published license:
Apache-2.0. Original weights are 171,543,900 bytes (about 172 MB decimal / 164 MiB),
plus small configuration files. ONNX alternatives in the repository are not downloaded.

This is a practical initial default because it predicts text blocks, covers both
bubble and artwork text, and uses already installed PyTorch/Transformers/Pillow.
It does not need Ultralytics, Paddle, ONNX Runtime, torchvision, or custom remote code.
The PIL processor resizes to the published 640x640 input; official postprocessing maps
boxes back to original dimensions. [Transformers RT-DETR-v2 documentation](https://huggingface.co/docs/transformers/model_doc/rt_detr_v2).

This selection is provisional, based on integration fit and a real crop smoke test,
not a comparative accuracy benchmark across complete manga pages.

| Candidate | Manga considerations | Runtime, coordinates, size, license |
| --- | --- | --- |
| Selected comic RT-DETR-v2 | Block predictions suit multiline vertical/horizontal OCR input. Separate free-text class is useful for narration/artwork. Small text, furigana, stylized fonts and SFX remain unbenchmarked; 640px resizing can lose detail. | Actual Windows/Python 3.13 CPU run verified; CUDA supported in adapter but untested. Boxes and scores, about 172 MB weights, Apache-2.0 as published. Maintained Transformers integration. |
| [Comic Text Detector](https://github.com/dmMaze/comic-text-detector) | Manga-oriented block, line and segmentation outputs; promising for vertical dialogue and artwork. Would need extra postprocessing and an evaluation of furigana/SFX separation. | YOLOv5/DBNet-style stack; CPU/GPU routes possible. GPL-3.0 repository; third-party conversion labels are not sufficient license evidence. Artifact size depends on selected export; no artifact installed or measured. Older integration; Windows/Python 3.13 not verified here. |
| [PaddleOCR text detection](https://www.paddleocr.ai/latest/en/version3.x/module_usage/text_detection.html) | General multilingual detection; line polygons could suit horizontal narration and oriented text, but sentence grouping and Japanese manga coverage need evaluation. | Apache-2.0 project; mobile/server sizes vary. CPU/GPU inference and polygons/scores documented. Adds another runtime or export path; exact Windows/Python 3.13 wheel combination not tested. Actively maintained project. |
| [CRAFT](https://github.com/clovaai/CRAFT-pytorch) | Character affinities and polygon output are useful for irregular text. No demonstrated advantage here on vertical Japanese, furigana, or stylized manga/SFX. More character-to-block postprocessing. | MIT source; PyTorch/torchvision/OpenCV stack, CPU/CUDA possible. Legacy upstream requirements need compatibility work/verification. Weight size not measured; no Python 3.13 inference attempted. |

No candidate has been ranked for manga accuracy. For **each** candidate, evaluate white
bubbles, vertical columns, horizontal dialogue, narration boxes, text over artwork,
small text, furigana, stylized fonts and SFX using the same pages and annotations below.
Do not interpret model family capabilities as evidence of accuracy on those cases.

## Setup, cache and devices

`uv sync` is sufficient; no new package dependencies or Python requirement change.
Verified Windows Python 3.13.9, torch 2.14.0+cpu, transformers 5.17.0.
`auto` uses CUDA if PyTorch reports it available, otherwise CPU. Explicit unavailable
`cuda` fails usefully. GPU execution and VRAM have not been verified on this machine.
No automatic retry hides GPU inference failures.

First detector construction downloads the pinned safetensors/configuration to the
standard Hugging Face cache (Windows default `%USERPROFILE%/.cache/huggingface/hub`).
Set `HF_HOME` before launching to choose another cache. Later runs reuse cached files;
set `HF_HUB_OFFLINE=1` after setup to require no model network access. Windows without
symlinks can use extra cache disk space. Peak RAM/VRAM is not measured; weight size is
not total memory consumption. The full pipeline also holds OCR and translation models.

The API initializes detection lazily on its existing single analysis worker. A missing
detector does not prevent Study Mode startup. Its first page request includes detector
initialization/download latency; returned pipeline times exclude initialization.
Successful instances are reused across requests. Use one Uvicorn worker.

```powershell
uv sync
uv run python scripts/detect_text.py samples/page.png --device cpu --output samples/page-boxes.png
uv run python scripts/analyze_page.py samples/page.png --device cpu --debug-image samples/page-debug.png --json-output samples/page-analysis.json
uv run uvicorn yomiscan.api.main:app --host 127.0.0.1 --port 8765
```

Detection needs no JMdict/OCR/translation setup. Full analysis needs the existing
`data/jmdict.sqlite3`; override with `--dictionary`. The original image is never changed;
CLI output paths must differ from the input and each other. Save copyrighted inputs
and derived debug outputs in ignored `samples/`, not source directories.

`POST /api/v1/analyze-page` accepts multipart `file` with the same PNG/JPEG/WebP,
10 MiB / 12 megapixel limits and local-origin protections as Study Mode:

```powershell
curl.exe -H "X-YomiScan-Client: study-extension-v1" -F "file=@samples/page.png" http://127.0.0.1:8765/api/v1/analyze-page
```

The header name/value is retained for compatibility; no extension page-mode UI is added.
The response includes dimensions, region counts, ordered blocks (coordinates, source
region IDs, Japanese, translation, tokens, score, category, status/error), and timings.
400 invalid image, 413 oversized, 422 missing multipart field, 429 busy, 503 detector
initialization unavailable, 500 overall detector/unexpected failure. Individual OCR
and known translation/lexical failures produce `status: error` blocks with safe messages,
while other blocks continue. Detailed exceptions remain in server logs.

## Geometry, grouping, filtering and limitations

Rectangles use original decoded image pixels: left/top inclusive, right/bottom exclusive.
`TextRegion` also accepts optional polygons for future detectors. Default orientation
is unknown; box aspect ratio is not falsely presented as detected writing direction.
Category stays unknown: text outside a bubble is not reliably narration versus SFX.
Detection score is not OCR accuracy, language confidence, or calibrated probability.

Detector outputs are deterministic top/descending-right sorted before assigning IDs.
Reading order uses top-to-bottom bands anchored to each next topmost box, with tolerance
25% of its height clamped to 8–40 pixels; within a band, rightmost comes first.
This cannot understand panel borders, staggered bubbles, spreads, overlapping text,
or unusual narrative layouts. Raw region IDs and final block IDs are deliberately separate.

Only detectors explicitly emitting `granularity: line` and known matching orientations
enable grouping. Parallel lines must have >=80% long-axis overlap, <=60% short-axis
gap, and similar thickness (<=1.5 ratio). Every pair in a group must qualify, avoiding
transitive chains. This may undergroup more than two columns. The default model already
emits blocks; each prediction stays a block. No distant bubble merging, panel classifier,
or language-based reconstruction is attempted. Manga-ocr receives the grouped visual crop.

`PageConfig(padding=4, minimum_side=3)` controls cropping. Boxes are clipped before
validation; aspect ratio and vertical layout are preserved. Filters remove only invalid/
tiny geometry and OCR without a Japanese script character. Kana, half-width kana after
normalization, and CJK ideographs are recognized; ASCII mixed with Japanese is accepted.
Japanese punctuation is recognized by a separate helper but punctuation alone is not
sufficient evidence. Kanji-only Chinese can pass. OCR hallucinations can also pass.
SFX with Japanese script are retained without special translation/rendering rules.

Raw detections and geometry-filter reasons stay in domain diagnostics. OCR-filtered
blocks keep their OCR text and `filtered` status. CLI JSON adds raw regions; block
region IDs expose grouping. The normal API omits raw polygons/metadata. Debug images
number raw regions; compare IDs with JSON to inspect reading order and grouping.

OCR is sequential using one engine. Successful Japanese blocks use the existing
translator's genuine bounded batching; a known failed batch retries individually to
isolate bad blocks. NLP/JMdict uses the same analyzer/connection. No parallel GPU scheduler.
Page translation timing is wall time for batched analysis minus measured successful
lexical time, including orchestration/fallback overhead; shared per-item batch latency
is not summed. OCR timing includes failed attempts. Total includes filtering/grouping.

## Validation record and manual evaluation matrix

2026-09-30: only the existing `Screenshot 2026-09-29 154812.png` crop (245x297) was
available initially. It is **not a complete manga page**. The real CPU detection CLI
found one box `(6, 7, 232, 285)`, score 0.944, in 714 ms (an earlier smoke test: 846 ms).
The numbered overlay was visually inspected and encloses the visible vertical text.
One group/one reading-order position is trivial and does not validate multi-panel order.

Actual full pipeline on that crop:

> 自分らみたいな無職でも世間体を気にせずまったりできる夢の空間なんス！

English output:

> It's a dream space where people can't care about themselves even if they don't have a job like themselves!

The English is awkward and mistranslates the social-reputation nuance. OCR text visually
matches the crop aside from normalized spacing/punctuation; no accuracy percentage is
claimed. Detection 678 ms, OCR 546 ms, translation 610 ms, lexical analysis 34 ms, total
1,868 ms excluding model initialization/download. No observed missed text or false
positive in this single crop; full-page failure rates are **unknown**, not zero.

An additional **synthetic** 1000x1400 white canvas contained four pasted copies of that
same crop, not a real manga layout. A real offline API run detected four separate blocks;
all OCR texts matched the crop run, with no merges. Visual inspection confirmed order
top-right, top-left, lower-right, lower-left. Boxes included extra whitespace around the
pasted images. Total 4,029 ms: detection 689 ms, sequential OCR 2,422 ms, batch translation
898 ms, lexical work 20 ms. A blank 800x1000 page returned zero blocks (HTTP 200), and
Study Mode on the original crop still returned HTTP 200 (~1,276 ms) afterward using the
same resources. These used FastAPI TestClient with real models, **not a live browser**.
`HF_HUB_OFFLINE=1` was set. The first diagnostic runner hit Windows console encoding
while printing Japanese after successful inference; rerunning with UTF-8 completed.
Ignored artifacts: `samples/phase-5-*-api.json`, `phase-5-synthetic-debug.png`,
`phase-5-detection.png`, and `phase-5-page.json`.

Validation: `uv sync`, 110 Python tests, 13 frontend tests, TypeScript check and extension
build passed. No new packages or lockfile changes. Only an existing Starlette TestClient
deprecation warning remains; upstream OCR also reports a working Pillow processor fallback.

Ordinary tests use fakes, no model downloads. They cover coordinate clipping, stable
ordering, line grouping, Japanese validation, invalid/empty uploads, empty pages, DTOs,
OCR/detector failures, genuine batch invocation and individual fallback. Existing Study
Mode tests remain part of the full suite. See the final implementation report for counts.

Before calling detection reliable, privately test at least several pages per category:

| Case | Record for each page |
| --- | --- |
| Normal white bubbles / vertical dialogue | missed blocks, crop truncation, column order |
| Horizontal dialogue / narration boxes | fragmentation, mixed orientation |
| Text over artwork | missed low contrast text, artwork false positives |
| Small text / furigana | lost base text, duplicate furigana detections |
| Stylized fonts / large SFX | detection and OCR separately; no SFX rendering |
| Dense multi-panel / sparse pages | panel traversal, incorrect joins or splits |
| No dialogue | empty result versus hallucinated text |
| Mixed vertical and horizontal text | grouping and reading order corrections |

For each local file, record dimensions, annotated expected boxes/transcriptions/order,
threshold, device, cold/warm time, raw boxes, filtered reasons, group membership, OCR,
translation errors, false positives, misses, and manual order corrections. Keep numbered
overlays and JSON alongside ignored samples. Run multiple pages through a reused service
for meaningful warm latency. CPU/GPU and detector comparisons require identical inputs.

Recommended Phase 6: use this corpus to review/correct regions and reading order, improve
detection where measured failures justify it, then scope rendering separately. No Phase 6
functionality is implemented here.
