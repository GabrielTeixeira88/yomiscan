# Phase 6 rendering quality pass — 2026-10-02

This pass uses the same local `samples/page.png` (1115×1600). Copyrighted inputs and
derived images/JSON remain ignored. No Phase 7 code, new dependencies, detector model,
translation model, or browser changes were added.

## Reproduce and inspect

```powershell
uv run python scripts/render_page.py samples/page.png --device cpu --output samples/phase-6-quality.png --debug-dir samples/phase-6-quality-debug
```

Local baseline: `samples/phase-6-before-quality.png` and `.json`. Raw detection is
`01-detection.png`; grouped boxes/IDs are `01-grouped-blocks.png`. Raw and committed
glyph masks are separate from `06-layout-status.png`: green/red = rendered/skipped
source blocks, blue = inferred layout area, magenta = tight mask bounds. The cleaned
intermediate and final image show the actual edits, not just proposed geometry.

`metadata.json` maps every raw region to grouped block IDs or a filter reason. Per-block
diagnostics record OCR/translation completion, original OCR text, mask checks, inferred
layout kind and bounds, inpainting/typesetting outcomes, wrapping, font and skip reason.
An extreme vertical aspect ratio prompts OCR review. "OCR success" means the engine
returned text, **not** that transcription is correct. Normal API responses stay PNG with
existing count/time headers; they do not expose developer diagnostics.

## Audit of all detected regions

Use raw IDs below: grouped block IDs change after resolving the duplicate. The original
detector found 14 boxes; none were filtered by size or Japanese-script validation and
no OCR/translation call failed. The following omissions were principally renderer policy,
not detector recall. Detector thresholds were therefore left unchanged.

| Raw ID | Location / baseline issue | Quality-pass outcome |
| --- | --- | --- |
| 1 | Top-right narration; rendered at 36 px | Enclosed narration interior, balanced smaller type |
| 2 | Large right promotional column; `text_free` skip | Still preserved: connected border/artwork, open margin, severely incorrect OCR. It advertises the spin-off, rather than being story dialogue. Explicit diagnostics; no fabricated replacement |
| 3 | Gratitude narration; rendered at 36 px | Uses original narration interior and preferred-size text |
| 4 | Small sign on building; `text_free` skip | No safely separable glyph mask; artwork remains |
| 5 + 6 | Upper middle dialogue over artwork; nested predictions caused both to skip | One group retains both raw IDs and runs OCR once. Still skipped: glyphs/artwork cannot be separated safely and no enclosing bubble. OCR is also imperfect |
| 7 | Stylized white text over dark artwork; `text_free` skip | Dense/textured foreground remains unsafe; preserved without trying to classify it as SFX |
| 8 | Upper-right small dialogue bubble; mask grazed outline | Recovered using enclosed bubble interior; outline is not erased |
| 9 | "Eat more" bubble; mask grazed outline | Recovered using enclosed bubble interior |
| 10 | "Which one is my son" bubble; mask grazed outline | Recovered using enclosed bubble interior |
| 11 | Laughter/reaction bubble; rendered before | Remains rendered with preferred sizing; existing inappropriate English translation is not corrected by this pass |
| 12 | Tall "So even if…" narration | Uses full safe box width; four lines instead of six in the reviewed output. Original narration box itself is narrow |
| 13 | Lower narration | Wider balanced lines and preferred-size text |
| 14 | Bottom-right "Hmm?" bubble | Remains rendered; 18 px instead of 16 px. Available interior width genuinely limits the unbroken word |

The page number and tiny incidental marks inside the depicted phone were not detected;
they are not missing story bubbles. Visual review found no additional undetected normal
dialogue bubble on this page. This is a one-page observation, not a detector recall score.

## Geometry, masks and styling

`TextMask` stores glyph pixels in crop coordinates. `LayoutRegion` separately represents
an inferred bubble, narration interior or conservative fallback. Connected near-background
pixels plus provisional glyph holes identify enclosed areas. Components reaching the
search edge are rejected; area limits prevent unbounded expansion. Small paper specks
can be ignored only in the layout map. Erosion and an inscribed rectangle retain margins
and avoid outlines, unmasked artwork and neighboring blocks. No contour/bbox is filled
white. Only accepted glyph-mask pixels are cleaned.

For same-class block detections, complete containment with the outer prediction at
least as confident permits one group. Partial overlaps, nearby bubbles and different
classes are not merged. Both original regions remain inspectable.

Measured dynamic-programming wrapping compares line breaks and penalizes short orphan
lines. Preferred 26 px, minimum 14 px and maximum ceiling 30 px prevent oversized short
translations. A small reduction can eliminate an extra line. Ink is centered within
3 px font margins plus the estimated interior margin. No word truncation, arbitrary
word splitting, below-minimum shrinking, or artwork stretching is used.

## Visual results and limits

The real CPU pipeline improved from **6/14 rendered detections** to **9/13 rendered
logical blocks**, after grouping the duplicate. All nine ordinary bubble/narration
blocks now render. Four logical blocks remain intentionally preserved as explained above.
Original, raw/final masks, cleaned intermediate and final PNG were inspected.

Newly recovered bubbles retain their curved outlines. Previously conspicuous white
rectangles in narration are present in the original page; enlarging or reshaping those
boxes would alter the artwork. Cleaning does not paste white rectangles. Larger narration
now uses fewer, more balanced lines. Small narrow bubbles still require short lines;
"Hmm?" remains smaller than surrounding narration because it must fit on one line.

Existing OCR and translation mistakes remain, including "Oh, Shyful", the reaction
translation and the promotional-column transcription. Do not confuse better typography
with improved translation accuracy. Some paper texture/antialiasing remains. This pass
does not reconstruct detailed artwork or guarantee safety for disconnected decoration,
broken bubble boundaries, touching glyphs, colored paper or unusual page resolutions.
Test additional pages before claiming chapter-ready rendering.

## Validation

Synthetic tests cover mask/layout separation, ellipse/rectangle interiors, page-edge
fallback, unmasked obstacles, duplicate grouping, font limits and balanced wrapping,
misclassified enclosed bubbles, no rectangular erasure, stage diagnostics and isolated
OpenCV layout failures. Heavy models remain unnecessary for ordinary tests.

The real rendering CLI uses existing cached detector/OCR/translation resources. Study
Mode/API/dictionary regressions are covered by the full Python suite; the extension
has no implementation changes. Final validation: **146 Python tests passed** (including
36 rendering/quality tests), backend imports passed, **13 frontend tests passed**, and
extension build/typecheck passed. The first frontend attempt encountered sandbox access
denial in esbuild; the permitted retry passed. One existing Starlette TestClient
deprecation warning remains. No live Chrome interaction was claimed.

Final real CPU run: analysis ~5.55 s, rendering with diagnostics ~0.67 s, complete service
~6.70 s including lazy detector setup; initial OCR/translation loading is excluded.
These are single-machine observations. Models were already cached; GPU was not tested.
