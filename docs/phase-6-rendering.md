# Phase 6: conservative single-page rendering

The renderer consumes a Phase 5 `PageAnalysisResult`. It does not perform detection,
OCR, translation or dictionary lookup itself. `PageTranslationRenderService` runs
analysis once when needed and passes the result to a replaceable `PageRenderer`.
The existing application service retains this composition and its font cache across
requests on the existing single worker. There are no browser/chapter changes.

## Run locally

Complete the existing OCR/translation cache and JMdict setup, then:

```powershell
uv sync
uv run python scripts/create_text_mask.py samples/page.png --device cpu --output samples/text-mask.png
uv run python scripts/render_page.py samples/page.png --device cpu --output samples/translated.png --debug-dir samples/render-debug
uv run uvicorn yomiscan.api.main:app --host 127.0.0.1 --port 8765
curl.exe --fail-with-body -H "X-YomiScan-Client: study-extension-v1" -F "file=@samples/page.png" http://127.0.0.1:8765/api/v1/render-page -o samples/api-translated.png
```

The mask CLI needs detection only, no dictionary/OCR/translation. Its mask is a diagnostic
candidate mask; final rendering also checks layout, overlap, translations, and failures.
Render output must be PNG. Source and output/debug paths must differ. Use ignored
`samples/` for all copyrighted inputs and derived images. Normal rendering produces
only the requested image; normal HTTP rendering writes nothing to disk.

Optional debug directory:

| File | Meaning |
| --- | --- |
| `00-original.png` | Decoded, EXIF-oriented source |
| `01-detection.png` | Raw detector boxes/IDs (not reading-order block IDs) |
| `01-grouped-blocks.png` | Orange grouped boxes with original raw IDs |
| `02-raw-mask.png` | Candidate foreground before dilation, including later-rejected candidates |
| `03-mask.png` | Dilated masks actually committed by successful replacements |
| `04-inpainted.png` | Successful removal before English drawing |
| `05-final.png` | Final lossless translated page |
| `06-layout-status.png` | Green rendered/red skipped text boxes; blue layout interiors; magenta glyph-mask bounds |
| `metadata.json` | Raw-to-group mapping, filtered regions, OCR/translation completion, mask/layout/inpainting/typesetting status, reasons, wrapped text, font sizes and timings |

The mask-only CLI writes original/raw/final masks when debug is enabled. It does not
claim those masks will all be rendered. Its region IDs come directly from the detector.

## Architecture and API

`rendering/base.py` defines lightweight `PageRenderer` and `InpaintingEngine` Protocols,
result/status/timing dataclasses and contextual errors. `masks.py` owns geometry and
foreground segmentation. `layout_regions.py` estimates separate enclosed layout interiors.
`inpainting.py` owns local pixel reconstruction.
`typesetting.py` owns all wrapping, font fitting and English drawing; `renderer.py`
coordinates transactional block edits. `rendering/service.py` is the complete page
boundary; `rendering/cli.py` handles files and diagnostics.

Library entry points:

```python
# Reuse existing models and cached analysis:
result = service.translate_and_render_page(image, analysis=page_analysis)
# Or run analysis exactly once, followed by rendering:
result = service.translate_and_render_page(image)
# Rendering alone is separately replaceable/testable:
result = renderer.render(image, page_analysis)
```

`POST /api/v1/render-page` accepts multipart `file`, returns `image/png` and headers:
`X-YomiScan-Blocks-Rendered`, `X-YomiScan-Blocks-Skipped`, `X-YomiScan-Processing-Ms`.
These headers are exposed through the existing restricted CORS policy. No raw text,
tracebacks or filesystem paths are placed in headers. Detailed per-block metadata is
available through the library and debug CLI, not an additional stateful HTTP endpoint.
The response is `Cache-Control: no-store`. Partial/all-skipped rendering is HTTP 200
with counts; it may be identical to the source. The CLI prints every skip reason.

Existing `/api/v1/analyze-image` and `/api/v1/analyze-page` responses are unchanged.
Uploads retain existing origin/header guards, format checks, 10 MiB / 12 MP limits,
400/413/422 validation errors, shared 429 busy guard, and cancellation behavior.
Unavailable detection gives 503; unexpected overall errors give safe 500 responses.
Mask/inpaint/typesetting boundary errors are logged and isolated to individual blocks.
Programming errors are not silently treated as successful rendering.

## Mask and safe-area strategy

The Phase 5 detector supplies boxes, not glyph masks. Filling entire boxes would erase
artwork. The default uses local RGB contrast and connected components:

1. Clip the text box; use 4 px text padding and 12 px context padding.
2. Estimate the dominant background in 8-level grayscale bins, then its median RGB.
3. Threshold color distance >=25 to find foreground components. Reject components
   crossing target/context boundaries or covering most of the region in both axes.
4. Keep separable components, then dilate by 1 px. Dilation cannot extend beyond the
   target area or onto rejected structural components.
5. Require >=65% background, no rejected structure inside the original text box, and
   low remaining background variation. Ambiguous midtones (76–179) are skipped.

Constants live in `MaskConfig`, not scattered through orchestration. Mask pixels are
crop-local with an explicit original-coordinate `crop_box`; debug masks are full-page
L-mode images. Vertical and horizontal text use the same geometry. White foreground
on dark uniform backgrounds works; white background is not assumed.

The renderer also skips unsuccessful/missing translations, known `sfx`/`possible_sfx`,
overlapping boxes, padding that intrudes on another text box, and unclassified
`text_free` detections without a verified enclosed interior. It does not infer SFX from a short Japanese word. Explicit
dialogue/narration outside bubbles may proceed only if the pixel safety tests pass.

English layout is separate from the glyph erasure mask. A bounded connected-background
search provisionally fills only masked glyph holes, then seeks an enclosed uniform
interior. Open/page-margin components fall back to the original 12 px strip expansion.
The search uses 128–256 px context, rejects interiors over 20 times the text-box area,
and requires at least 98% of masked pixels to belong to one component. Tiny enclosed
paper specks may be ignored for layout only. A 2 px erosion protects outlines; a largest
inscribed rectangle (with a width preference for curved bubbles) determines the usable
area. Nearly rectangular interiors are labeled narration boxes. Neighboring padded
boxes and reserved English areas remain obstacles. Typesetting adds 3 px margins.
An enclosed interior can certify rejected connected pixels as boundary structure;
those pixels remain excluded from the erasure mask. No interior is painted white.

Contained lower-confidence same-class block predictions are grouped into one OCR crop;
both raw IDs remain available. Partial overlaps and different-class predictions are
not merged. Detector confidence thresholds and minimum-size filters are unchanged.

These are heuristics, not accurate learned segmentation. Disconnected decorative art
inside a mistakenly detected bubble can look like glyphs; antialiased halos, tiny
furigana, faint gray marks and very tight crops can be missed or cause skips. Texture
and connected border tests deliberately reject some valid bubbles. Never infer broad
artwork safety from a single successful page.

## Inpainting decision and alternatives

Default: `OpenCVInpaintingEngine`, an understandable hybrid. If 98% of a 3 px ring
around the mask differs from its median background by at most 12 channel levels, fill
only masked pixels with that median. Otherwise use OpenCV Telea (radius 3) on the crop.
Pixels outside the mask are restored exactly even if another engine modifies them.
This avoids Telea smudges on thick text in uniform white/black bubbles while retaining
local reconstruction for slight background variation. Complex artwork is rejected by
the mask policy before inpainting; there is no speculative model-based repair.

| Candidate | Background/line-art tradeoffs | Deployment and decision |
| --- | --- | --- |
| Uniform fill + OpenCV Telea (selected) | Strong fit for white/black uniform bubbles and plain narration; supports RGB/grayscale. Telea may smear line art and screentones, so those regions are skipped. A real thick-glyph gray smudge motivated the flat-fill check. | CPU; no weights/download, low crop memory. OpenCV 4.x Apache-2.0, NumPy BSD-3-Clause. Windows/Python 3.13 actually tested. |
| OpenCV Navier–Stokes | Also local diffusion; could preserve some edge directions, but does not understand manga strokes or periodic screentones. No reason demonstrated to favor it for the tested uniform regions. | Same CPU dependency and no weights. Considered from documentation, not benchmarked here. |
| LaMa / OpenCV Zoo LaMa | Learned repair is a candidate for larger artwork holes; line continuity, grayscale detail and screentone phase still need manga-specific comparisons. Unnecessary for flat bubbles. | OpenCV's published ONNX artifact is about 92.6 MB, Apache-2.0 as published. CPU/GPU routes depend on runtime. Not installed or benchmarked; Python 3.13 runtime compatibility not claimed. |
| Manga-oriented learned inpainters | Promising for manga textures but need exact weight provenance and representative line-art evaluation. A full translator framework adds unrelated dependencies. | `manga-image-translator` is GPL-3.0 source; individual models retain their own terms/sizes. Not imported, copied or benchmarked. |

Primary sources: [OpenCV algorithms](https://docs.opencv.org/4.x/df/d3d/tutorial_py_inpainting.html),
[OpenCV license](https://opencv.org/license/),
[original LaMa](https://github.com/advimman/lama),
[OpenCV LaMa artifact/license](https://huggingface.co/opencv/inpainting_lama),
[manga-image-translator](https://github.com/zyddnys/manga-image-translator).
This is an engineering comparison, not a claimed comparative quality benchmark.
There are no artificial fast/quality switches.

## Font, fitting, and rollback

Use **Aileron Regular**, the scalable subset embedded in Pillow's `load_default(size)`.
It is a neutral sans-serif font available with Pillow, independent of Windows fonts.
The author's terms are **No Rights Reserved**, permitting modification/redistribution;
Pillow itself is MIT-CMU. No proprietary font or additional font file is committed or
downloaded. [Author's terms](https://dotcolon.net/fonts/aileron/),
[Pillow font API](https://pillow.readthedocs.io/en/stable/reference/ImageFont.html).

Normalize common English typographic punctuation, then compare measured word-boundary
wraps using dynamic programming. Prefer fewer, balanced lines, including the last line,
instead of greedy wrapping with a tiny orphan. Measure Pillow's actual multiline ink
bounds. Defaults: preferred 26 px, minimum 14 px, maximum ceiling 30 px; short translations
do not grow beyond the preferred size. Compare fitting sizes down to the minimum,
allowing a small reduction when it avoids another line. Use 18% line spacing (at least
2 px) and center measured ink inside 3 px margins.
Fonts are cached per typesetter instance. Unknown categories use centered layout; no
unreliable dialogue/narration style classifier is added. English stays horizontal.

If words/lines cannot fit at 14 px, or a glyph is unsupported, skip the block before
erasing anything. Do not silently truncate, invent a shorter translation, split words
arbitrarily, stretch bubbles, or shrink below the configured minimum. Layout is chosen
before inpainting. Inpainting and drawing occur on an isolated crop; only after both
succeed are mask pixels and new text ink composited. Failed blocks keep original pixels.
Context crop overlap never pastes whole original crops over already-rendered neighbors.

Internal images use lossless arrays/Pillow objects; dimensions stay unchanged. Library
rendering preserves L mode and RGBA alpha. Other modes normalize to RGB; the existing
HTTP decoder still returns RGB. EXIF orientation is applied by the CLI/API. ICC/DPI/other
file metadata is not promised to round-trip. Final and debug output is PNG.

## Initial compatibility, performance and validation (2026-10-01)

Added `opencv-python-headless>=4.13,<5` and direct `numpy>=2,<3` declarations via uv.
OpenCV 4.14.0.94 installed on Windows/Python 3.13.9. NumPy was already transitive.
No Python requirement change; no GPU requirement. Masking/inpainting/typesetting use
CPU even when analysis uses CUDA. CUDA execution was not tested. No rendering model
weights exist; existing detection/OCR/translation cache behavior remains unchanged.

One real local page, `samples/page.png` (1115x1600), was run through detection, analysis,
mask and render CLIs. It contains vertical dialogue, narration, white bubbles, artwork,
screentones, close blocks and detection mistakes. All images remain ignored by Git.

The page produced 14 analyzed blocks. Rendering replaced **6** (IDs 1, 3, 10, 12, 13,
14), preserved **8**. Skips included two overlapping detections, three border/connected
artwork cases, and three unclassified free-text cases. The source promotional sidebar
has bad OCR; it remains unchanged. Translation errors such as the inappropriate
"Oh, my God." remain a Phase 3 limitation, not corrected by typesetting.

Actual stages inspected: original, raw/final masks, cleaned page, final English page,
and an enlarged narration detail. Masks followed glyphs rather than whole boxes; panel
and narration borders remained intact in the reviewed output. The initial Telea-only
prototype left a faint gray smudge; flat-background fill removed that visible artifact.
Final output had readable, centered English without observed clipping in replaced blocks.
Narrow narration boxes produce tall, sometimes awkward wrapping; the short bottom-right
utterance used an 18 px font initially and 16 px after reserving neighboring padded areas.
Some faint paper texture remains. Unmodified detailed
artwork/screentones were preserved, **not reconstructed successfully**.

Final measured CLI rendering: ~152 ms (mask ~48 ms, inpainting ~11 ms, layout/drawing ~76 ms),
analysis ~6.77 s, complete page service ~7.49 s including lazy detector setup. Times are
single-machine observations, not throughput promises; cold OCR/translation startup and
file encoding are outside renderer timings. Detector resources and fonts are reused.

Real offline FastAPI TestClient run (`HF_HUB_OFFLINE=1`) returned HTTP 200, PNG 1115x1600,
6 rendered / 8 skipped, ~7.29 s. Blank input image returned PNG with 0/0 counts. This
was the real API/model path in-process, not a Chrome page replacement test. Final cached-
analysis rendering after the adjacent-layout and background-tolerance fixes still replaced 6/14, taking
~95 ms in that run. Unit/API tests use synthetic images and fake engines and need no
neural weights. `uv sync`, 137 Python tests (including 27 rendering tests), backend imports,
13 frontend tests and the extension build/typecheck passed. An existing Starlette
TestClient deprecation warning remains; upstream OCR uses its working Pillow fallback.

## Manual evaluation matrix and known gaps

| Case | Current evidence / next check |
| --- | --- |
| White bubbles, narration, vertical Japanese | Real page inspected; six replacements |
| Black bubbles / horizontal source | Synthetic dark-bubble fixture rendered and visually inspected; real black manga bubbles still needed |
| Small text / short translation | Real bottom-right utterance; minimum-size and unsupported-glyph tests |
| Long English | Real tall narration wrapping; synthetic overflow preserves original |
| Artwork / detailed line art / screentones | Present in real page; difficult text skipped, surrounding artwork inspected |
| Close blocks / borders | Real skips; synthetic overlap/expansion tests |
| Stylized SFX | Difficult free text preserved; explicit SFX skip unit test, no special reconstruction |
| Detection mistakes | Duplicate/overlapping predictions preserved; missed detections necessarily stay Japanese |

For more pages record detection/translation errors separately from masking, edge halos,
border damage, blur, screentone corruption, clipping, centering, margins and font size.
Test grayscale/color pages and several resolutions. Keep local annotated references and
debug images out of Git. Sparse disconnected art can evade the heuristic; safe skipping
is not a guarantee of universal segmentation correctness.

Recommended Phase 7: browser image discovery and lifecycle/orchestration should call
the complete page service and consume its PNG/counts, with Original/English switching,
visible-page priority, cancellation, cache/session management and lazy-load handling.
None of those browser/chapter features are implemented in Phase 6. Continue expanding
the rendering evaluation corpus before enabling broad automatic replacement.
