# Phase 4 validation — 2026-09-30

Scope: localhost API and Chrome Study Mode only. No reading-mode/chapter functionality.
Started on a clean `phase-4` branch at the merged Phase 3 commit `61a9378`.

## Setup and dependency changes

Python remains `>=3.13,<3.14`; verified Windows / Python 3.13.9. Added FastAPI, Pydantic,
Uvicorn, python-multipart, and explicit httpx test dependency. `uv.lock` records their
resolved versions: FastAPI 0.142.2, Pydantic 2.13.5, Uvicorn 0.54.0, python-multipart
0.0.32. Existing OCR/translation versions were retained. No global Python install.

Frontend development-only dependencies: TypeScript, esbuild, @types/chrome and
@types/node, locked in `extension/package-lock.json`. Tested Node 22.19.0 / npm 10.9.3.
No framework, frontend test runner dependency, or runtime external script/CDN.

```powershell
# Terminal 1, repository root
uv sync
uv run uvicorn yomiscan.api.main:app --host 127.0.0.1 --port 8765 --reload

# Terminal 2, repository root
cd extension
npm.cmd ci
npm.cmd run build
npm.cmd run watch
```

Load `C:\Users\T-GAMER\yomiscan\extension\dist` unpacked at `chrome://extensions`.
Use `npm` in non-Windows shells. Models and JMdict require the existing setup described
in README. The default backend port is 8765 and extension URL is fixed to that port.

## Automated tests

- `uv sync`: passed with Python 3.13 unchanged.
- `uv run pytest`: 82 passed, including the 63 Phase 1–3 tests. API tests inject fake
  neural engines and use a tiny synthetic dictionary. No weights are loaded/downloaded.
- API coverage includes health, repeated service reuse, actual light tokenizer/SQLite
  orchestration, nested response serialization, PNG/JPEG/WebP, malformed/empty/animated
  or unsupported input, upload and pixel limits, missing fields, safe errors, unavailable
  startup, CORS/client-header/Host checks, busy rejection and responsive health.
  Tests also cover EXIF orientation, streamed body limits without Content-Length,
  and retaining the busy slot until inference finishes after client cancellation.
- Resource creation, requests and teardown are asserted to share one owning thread.
- `npm.cmd run build`: strict TypeScript check and both bundles passed.
- `npm.cmd test`: 10 Node tests passed for geometry, zoom/DPR ratios, viewport stability,
  popup placement, nested response validation, fixed localhost uploads, malformed/error
  responses, network/timeout handling and manifest permissions.
- Imports checked separately; importing the API does not initialize neural models.

One upstream warning remains: Starlette's TestClient deprecates its httpx transport in
favor of httpx2. Tests pass; this does not affect the runtime API. The existing manga-ocr
Pillow image-processor fallback warning also remains and real OCR still runs.

## Real API inference

Started Uvicorn on `127.0.0.1:8765` with `YOMISCAN_DEVICE=cpu` and `HF_HUB_OFFLINE=1`.
Startup completed using the existing local JMdict database and cached model weights.

- `/health`: HTTP 200, `{"status":"ok"}`.
- Uploaded the existing ignored local manga crop through multipart HTTP twice: both
  HTTP 200, original Japanese, sentence translation, and 23 tokens with dictionary data.
- First request: OCR 511 ms, translation 556 ms, lexical analysis 6 ms, total 1,085 ms.
- Repeat request: OCR 501 ms, translation 588 ms, lexical analysis 4 ms, total 1,095 ms.
- Invalid-image request: HTTP 400.

Times exclude model initialization and HTTP transfer. They are development smoke
measurements, not controlled performance benchmarks. GPU execution was not tested.
Translation retains the Phase 3 casual-dialogue meaning error; Phase 4 changes delivery,
not model quality. No new OCR accuracy claim is made.

## Actual extension in isolated Chrome

The built extension was loaded into an isolated **headless Chrome 154.0.8037.92**
profile via Chrome's debugging protocol. A private localhost fixture displayed the
existing local crop. This was the real built Manifest V3 extension with real Chrome
capture APIs and the running Python API, not a mock popup or fabricated screenshot.
The user's normal Chrome profile was not used.

Verified with browser automation:

1. Trigger extension action, enter selection mode, cancel with Escape; overlay removed.
2. Activate again, dispatch a drag over the displayed crop, remove overlay and capture.
3. Observe actual full screenshot dimensions 1000×800 and uploaded PNG dimensions
   **245×297** (61,677 bytes). Only the selected region reached the analysis request.
4. Receive real OCR/translation and render original, translation, readings, lemmas, POS,
   conjugation and dictionary meanings inside one popup. Visually inspected its actual
   screenshot; popup had internal scrolling and stayed within the viewport.
5. Escape closes the popup. Repeated action does not duplicate injection/listeners.
6. Scroll the page, emulate DPR 2, select again, receive another complete result.
   Chrome's capture API still emitted a 1000×800 screenshot under this emulation;
   the correct crop therefore stayed 245×297. This confirms using actual screenshot
   ratios instead of blindly multiplying the emulated DPR. It is not a physical HiDPI test.
7. Close button removes the popup.
8. Block the backend URL in Chrome's network layer and select again: the popup explains
   that the local server must be started. Restore network access and dismiss it.

The action, capture, HTTP pipeline and UI were tested automatically, not manually by a
human dragging a mouse. Network blocking simulated an unreachable backend; separate
unit tests cover timeout and model failures. Diagnostic screenshots, fixture code,
full OCR output, and the source manga crop stay inside ignored local caches/samples.
No copyrighted screenshots/transcripts were added to documentation.

## Manual validation still recommended

Use the setup commands above and your own manga webpage:

- Activate via the toolbar and assigned keyboard shortcut; confirm shortcut conflicts
  at `chrome://extensions/shortcuts` and choose another key if needed.
- Drag a bubble in each direction; check the resulting text and translation, then repeat
  on a different region. Compare against the Japanese manually, not just fluent English.
- Test selection near all viewport edges and long word breakdowns; scroll inside the
  popup, expand additional senses, close with × and Escape, and check page layout.
- Test Escape mid-drag and during processing, scrolling/resizing during selection,
  switching tabs during capture, and reactivating after closing.
- Test real browser zoom at 80/100/125/150%, Windows display scaling/physical HiDPI,
  small browser windows and reader pages with their own CSS/keyboard/scroll handlers.
- Stop the backend and select again; restart it, wait for startup, and retry. Check a
  missing dictionary/model-cache setup and recovery by fixing it and restarting.
- Try a Chrome restricted page; injection failure should show an action badge/tooltip.

Normal headed Chrome interaction, actual keyboard-shortcut assignment, physical
HiDPI/multi-monitor behavior, and broad third-party manga-site compatibility have not
been manually verified. Website fullscreen/top-layer elements, animations and changing
content remain limitations. Pinch zoom and offscreen selection are unsupported.

## Review and next milestone

### Popup UX follow-up

Added header-only Pointer Events dragging and right/bottom/corner resizing, with a
320×220 minimum relaxed for small viewports. Manual placement survives result updates
and sense expansion; new selections reset placement. Word cards reflow through CSS
Grid while Original/Translation stay full-width. No backend or analysis changes.

Frontend build/type-check and 13 Node tests passed (three additional geometry tests).
An isolated Chrome 154 run using fixture API responses verified initial placement,
no-jump header dragging, close-button exclusion, body text interaction without dragging,
right-edge enlargement to two/three columns, minimum-size shrinking to one column,
bottom and corner resizing, long-content scrolling with a stationary header, all-edge
viewport clamping, a 300×180 viewport, close button, Escape during a drag, and automatic
placement on a new selection. These are UI tests, not additional inference evaluation.

Models remain cached outside source control. New model formats, generated frontend
bundles, node_modules, Python caches, local dictionaries and manga samples are ignored.
No commit/push is performed as part of implementation. See final git status for changes.

Recommended Phase 5: OCR correction/reanalysis and a reviewed dialogue-quality benchmark,
after the headed-browser compatibility checks. Context-aware translation and alternative
engines can remain behind the service/translation boundary. No Phase 5 work, chapter
discovery, text detection, inpainting, typesetting, storage/export, installers, accounts,
or cloud service was implemented.
