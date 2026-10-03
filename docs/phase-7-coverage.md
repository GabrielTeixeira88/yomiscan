# Rendering coverage correction

This pass changes mask/layout decisions and diagnostics, not chapter acquisition,
queueing, OCR models, translation models or dictionary analysis.

## Reproduced failures and changes

The user supplied Rawkuma's Jujutsu Kaisen chapter 40. Pages 1–3 were downloaded from
the actual loaded reader sources to ignored `samples/coverage-jjk-{1,2,3}.png`.
One real CPU analysis per page was reused for before/after rendering, so differences
are renderer changes rather than stochastic OCR or translation differences.

Page 1's first (upper-right) bubble was detected and correctly OCR'd as `真希？`.
Translation succeeded, but bold glyphs exceeded the mask's density limit. Dense text
is now accepted inside a verified enclosure only if glyphs are completely separated
and the remaining background is uniform. Density restrictions remain for artwork.

The connected balloon's `万年４級` had the same mask issue. Its small text bbox also
made the old interior search too narrow to see the entire enclosing balloon. The
bounded search now reaches farther, keeps neighbors as obstacles, and rejects an
inferred rectangle that is much smaller than the existing conservative fallback.
After those fixes, the generated `Four-year-olds.` still overflowed as a single
unbreakable token. Wrapping now permits breaks at existing word-internal hyphens,
preserving spaces around standalone dashes and the minimum readable font size.
The translation itself is incorrect; this pass does not fix that model's wording.

Unboxed text is no longer rejected solely because the detector called it `text_free`.
It still needs a safe mask and a readable layout. A narrow fallback detects dark
components surrounded by light edging, excluding other glyph strokes from background
measurements. It requires isolated, contained components and rejects significant
unseparated ink. It includes gray antialiased/furigana strokes, not just pure black.
Only the glyph mask is passed to existing crop-based inpainting. It does not paint
the bbox white, remove surrounding halos, or attempt general artwork reconstruction.

Detection thresholds, Japanese filtering and grouping were **not relaxed**: all
reported normal bubbles on page 1 already reached the renderer. No evidence from
these pages justified a global detector-threshold change.

## Real before/after observations

| Chapter page | Detected blocks | Rendered before | Rendered after | Preserved after |
| --- | ---: | ---: | ---: | ---: |
| 1 | 13 | 7 | 9 | 4 |
| 2 | 2 | 0 | 1 | 1 |
| 3 | 5 | 1 | 2 | 3 |
| Total | 20 | 8 | 12 | 8 |

All nine normal dialogue bubbles on page 1 now render. The bubble outlines and
neighboring artwork remain intact in the inspected output. Page 2's short thought
over the face and page 3's lower-right narration now render with tight masks.
Page 3's long English is still small/narrow; the preserved white edging remains
visible against screentones. Small gray inpainting specks remain on some bold text.
These results do not establish reliable general artwork segmentation or translation
accuracy. Real translations include incorrect names and meanings; no claims of
translation-quality improvement are made.

Every remaining detected block was OCR'd and translated. Exact renderer outcomes:

| Page / block | Location | Reason |
| --- | --- | --- |
| 1 / 1 | Small top caption | Dense/textured foreground; no complete light-edged separation |
| 1 / 10 | Series logo | Dense/textured foreground; no complete light-edged separation |
| 1 / 12 | Chapter subtitle | Dense/textured foreground; no complete light-edged separation |
| 1 / 13 | Author credit | Dense/textured foreground; no complete light-edged separation |
| 2 / 2 | Large outlined vertical thought over clothing | Dense/textured foreground; cannot separate all text safely |
| 3 / 1 | Upper-right thought over trees | Dense/textured foreground; connected artwork remains |
| 3 / 3 | Middle-left thought beside weapon/hand | Mask intersects connected artwork; preserve original |
| 3 / 5 | Lower-left thought over screentones | Dense/textured foreground; no complete light-edged separation |

The two large stylized SFX on page 3 were **not detected**. They never reached the
renderer and are not counted as renderer-preserved SFX. They remain unchanged.
No detected regions were dropped by size/Japanese filtering or lost in grouping
on these three pages. An automatic count of undetected text is unavailable; the
metric is `null`, not a misleading zero. The remaining 16 chapter pages were not
visually audited in this pass.

Before/after images and per-block JSON remain locally in
`samples/coverage-jjk-N-before/` and `samples/coverage-jjk-N-after/`. Those directories,
source images and analysis caches are ignored and must not be committed.

## Categories, diagnostics and UI

`rendering/coverage.py` assigns rendering categories using explicit categories,
enclosure geometry, detector labels and a small explicit SFX pattern list:
`bubble`, `narration`, `artwork_text`, `sfx`, `unknown`. These are practical hints,
not a semantic classifier: an enclosed plain panel background can resemble a bubble.
Explicit SFX are preserved. Short dialogue is not classified as SFX just by length;
the sound-pattern heuristic is restricted to free-text detections. Titles and
credits can remain `artwork_text` rather than being falsely called SFX.

Per-block debug metadata contains raw region IDs, bbox, category/reason, OCR text,
translation, analysis state, mask method/recovery, layout bbox, font size, render
state and exact reason. Stage codes distinguish OCR/filter/analysis failure,
geometry conflicts, mask failure, inseparable mask, unsafe background, layout
failure, overflow, inpainting failure, typesetting failure and likely SFX.
Raw detection IDs and filter/group mappings are retained even without debug images.
Skipped-block reasons are also logged at INFO level without text/stack traces.

`metadata.json` includes per-category detected/rendered/preserved counts,
pre-group filtering count, skip-code counts and unavailable undetected estimate.
The additive `X-YomiScan-Coverage` response header carries aggregate metrics only;
normal image responses do not contain OCR text or per-block debug objects.
Chapter controls summarize preserved dialogue/artwork, likely SFX and unknown
counts across completed pages. Developer console tables expose per-page category
counts; use the CLI for full block-level reasons and source geometry.
Older backends without this header remain supported as unknown preservation counts.

```powershell
uv run python scripts/render_page.py samples/coverage-jjk-1.png --output samples/coverage-check.png --debug-dir samples/coverage-check --device cpu
```

`06-layout-status.png` labels blocks and reason codes: red for preserved
bubble/narration, orange for artwork text, purple for SFX, gray for unknown and
green for rendered blocks. Blue marks placement areas; magenta marks glyph bounds.
The other images show detection, grouped blocks, masks, cleaned pixels and final output.

## Validation

- `uv run pytest -q`: 153 passed, one existing Starlette/httpx deprecation warning.
- Package/API/new-module import checks passed on Python 3.13.9.
- `npm test`: 38 passed; `npm run build`: strict TypeScript and esbuild passed.
- Isolated Chrome fixture: all 19 scenarios passed, including actual Study OCR,
  discovery, cross-origin acquisition, stitching, retry, lazy loading, toggles,
  cancellation and cleanup. The 24-page stress case uses mocked rendering.
- The user's server on 8765 was left running. Integration used a separate updated
  backend on 8766 and an ignored test-build copy with only its loopback port changed.
- Real-page masks, final images and status overlays were inspected for all three
  supplied chapter pages; no GPU execution was tested or required.

Restart the local backend, reload the extension and refresh/clear the chapter session
to use the new renderer rather than old cached page overlays.
