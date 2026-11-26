# YomiScan Chrome Study and Chapter Modes

Manifest V3 extension using plain TypeScript/DOM and esbuild. No React, runtime CDN,
analytics, third-party inference requests, or automatic screenshot storage. Explicit
diagnostic downloads can include text/images chosen by the user.

## Build and load

Install Node.js 22+ and run from `extension/`:

```powershell
npm.cmd ci
npm.cmd run build
npm.cmd test
npm.cmd run watch
```

On macOS/Linux use `npm`. On Windows `npm.cmd` avoids PowerShell script-policy errors.
Build includes TypeScript checking. Watch rebuilds code only; run `npm.cmd run typecheck`
separately. Restart watch after manifest changes. Bundles/source maps are generated in
ignored `dist/`; they are not repository source.

Open `chrome://extensions` → Developer mode → Load unpacked → choose `extension/dist`
(here `C:\Users\T-GAMER\yomiscan\extension\dist`). Reload the extension and refresh the
webpage after rebuilding to replace injected code. Chrome 120+ is required.

In another terminal at the repository root:

```powershell
uv sync
uv run uvicorn yomiscan.api.main:app --host 127.0.0.1 --port 47615 --reload
```

Import JMdict using the root README first; wait for application startup and model
downloads. No installer, automatic startup, native messaging or bundled Python exists.

## Use

Click the action to open **Select Text / Read Chapter / Translate Chapter** controls. Ctrl+Shift+Y
(Command+Shift+Y on macOS) activates Select Text directly. Assign a shortcut at
`chrome://extensions/shortcuts` if the suggestion conflicts. Drag in any direction
around a visible bubble and release. Escape cancels selection. Loading is followed by
one study popup with original Japanese, translation, readings, lemmas, dictionary forms,
POS, conjugation and dictionary senses. Extra senses expand inside it. Close with ×
or Escape. **Edit text** corrects the recognized Japanese and re-analyzes it locally without new OCR.
**Copy Japanese** / **Copy English** copy the displayed sentence with keyboard-accessible
controls and brief success/failure feedback. Browser clipboard restrictions leave text
selection/manual copying available; no permission was added.

Drag the title bar to move the popup. Its right edge, bottom edge, and bottom-right
grip resize it. The close button and selectable body text do not start dragging.
Minimum size is 320×220 CSS pixels, relaxed for smaller viewports; the viewport is
the maximum. Manual placement/size stays in effect for the current popup, including
when results arrive or extra senses expand. A new selection starts with automatic
placement and the default size. No settings are persisted.

Original and Translation remain full-width. Word Breakdown uses a responsive grid:
one column at normal widths, then additional columns as space permits (260px minimum
card width). The header stays visible above one scrolling content area.

The popup uses closed Shadow DOM, bounded dimensions and internal scrolling. Untrusted
OCR/translation/dictionary strings use `textContent`, never HTML. Dictionary senses
remain candidates, not meanings selected for the sentence's context.

## Read Chapter (reading mode)

**Read Chapter** reads every page in the background without changing it: visible pages
first, then the next ones. Each detected bubble gets a faint outline that strengthens on
hover. Click a bubble to open its study card from the retained page analysis, with no
dragging, screenshot or new OCR. **J** / **K** open the next / previous bubble in reading
order across pages and scroll it into view. They do nothing while you type in a field. A
page that is still being read stops J / K with a message instead of being skipped. The
**English** button at each page's top-right corner renders that page in English on
demand, reusing the backend's cached OCR and translation; **Japanese** switches back.
Bubbles stay clickable over the English image. **Stop**, **Retry**, **Retranslate Page**
and **Clear Session** work as in Translate Chapter. Choosing the other mode starts a new
session.

## Engines and first-run setup

YomiScan's engine choice is **Automatic** by default:
1. the **local engine companion** (`yomiscan-engine.exe`, Stage 5b) when it is installed with its
   models: Chrome starts it through native messaging on a random local port with a one-time
   token, and it exits after 15 idle minutes. When it is installed without its models, the panel
   offers them first (845 MB, explicit Download);
2. otherwise the **browser engine** once its models are installed;
3. otherwise the **local backend**, if it is running;
4. otherwise the panel shows **Download the reading models**.

The setup card gives the size for this computer (about 580 MB with a GPU, 600 MB on CPU), the
host (Hugging Face) and the licenses. Nothing downloads until you click **Download**. Each file
is checked against a SHA-256 built into the extension and stored by Chrome for this extension
only. A download that cannot fit is refused, with how much space to free. If Chrome later
removes the models, the card offers them again. **Advanced → Browser engine** can force Local
or Browser, show sizes and storage, and remove the models. The browser engine is English only
and needs about 2 GB of memory with every model loaded.

## Translate Chapter

Post-MVP page actions: choose a page (or **Nearest viewport**) and **Retranslate Page**
to refresh only its result, retaining the previous translation on failure/cancellation.
The panel keeps reading controls visible. Maintenance tools (page reports, region
inspector, processing cache, Setup & readiness, processing details, developer diagnostics)
are folded under **Advanced**. **Export Page Report** downloads a metadata-only ZIP by default; optional OCR/translation
text and original/translated pixels require explicit checkboxes. No upload/inference is
performed during export. Recent originals and diagnostics live in bounded session memory;
Clear/navigation releases them. See [report details and model-free browser validation](../docs/post-mvp-reliability-qol.md).

Open a standard image-based reader and choose **Translate Chapter**. Backend health is
checked before discovery. Large, loaded images in the dominant reader column are queued
one at a time, visible first, then immediately below/above, then distant pages. Status
reports known pages; observers remain active for appended/lazy-loaded images.

- **Original / English:** immediate view change using cached translated PNGs.
- **Stop:** disconnect discovery observers, cancel queued work and acquisition;
  backend rendering already submitted may finish. Translated pages remain available.
- **Retry Failed / Skipped:** explicit retry; no unlimited automatic failure loops.
- **Clear Session:** remove overlays, revoke result URLs, abort client work and clear state.
- **Select Text:** stop scheduling, wait for the current page, switch to Original, then
  use the unchanged Japanese screenshot-analysis popup. Chapter mode does not auto-resume.
- **×:** hide controls while processing continues; click the extension to reopen.

Navigation/page unload destroys session results. Generic SPA URL changes are detected
within one second, including hash changes. Use Clear Session for a reader that changes
chapters without changing its URL or source images. Refresh after extension updates.

See [Phase 7 details and test matrix](../docs/phase-7-chapter.md).

## Capture, privacy and permissions

`activeTab` and `scripting` permit on-demand injection after explicit activation. There
is no all-sites content script or `<all_urls>` permission. The service worker captures
with `chrome.tabs.captureVisibleTab`, verifies tab/viewport stability, crops through
`OffscreenCanvas`, then posts PNG to `http://127.0.0.1:<port>/api/v1/analyze-image` (default port 47615).
Only the crop is sent; the full screenshot stays transiently in extension memory and
is never returned to webpage code. No screenshot is stored. Text and analysis are stored only
when you click **Save word** or **Save sentence**, in the extension's own IndexedDB; the Saved
page (YomiScan → Open Saved) shows, exports and deletes them. **Mark known** and Import list
store known words (dictionary forms only) in the same database; the furigana setting is kept in
`chrome.storage.local`.

The additional `offscreen` permission provides an extension-origin Blob transport for
long page-render requests. It calls only the fixed localhost render URL. Already-loaded
image pixels pass through bounded JSON/base64 chunks (Chrome 120 compatibility); only
compressed Blob URLs are cached per session. No web-accessible bridge, remote chapter
storage or third-party inference is added. Image acquisition uses the separate optional
host access described below.

HTTP(S) image acquisition prefers extension-worker fetch of a verified loaded `currentSrc`.
Optional HTTP(S) host permissions are requested only for discovered image hosts through
an extension-owned access window, where an explicit click supplies Chrome's user gesture.
Analysis still goes only to localhost. Source requests include eligible cookies and retain
PNG/JPEG/WebP bytes/MIME. Redirects and HTTP authentication failures are reported, not bypassed.
Data/blob sources stay in page context and use canvas, then screenshot fallbacks.

Fallback order is canvas, visible-page screenshot, then optional **Allow scroll capture**.
Stitching handles supported window-scrolling readers, restores scroll on all exits and
aborts on Escape, user input, Stop or layout changes. Capture calls share a 650 ms throttle
with Study Mode. No manual zoom-out is required. Nested scrollers, occlusion and image
limits can still prevent capture. See [acquisition details](../docs/phase-7-acquisition.md).

Selection uses viewport CSS coordinates. After removing the overlay, two animation
frames pass before capture. Conversion measures screenshot/viewport width and height,
accounting for ordinary zoom and OS scaling without multiplying DPR twice. No document
scroll offset is added. Scroll, resize, hidden tabs and stale selection IDs invalidate
pending capture. Pinch zoom is unsupported; reset it first. Animated page content can
still change between selection and capture.

The localhost host permission covers ports. Backend requests use loopback with the port saved in Setup & readiness (default 47615; never AnkiConnect's 8765). The offscreen document accepts only a validated `http://127.0.0.1:<port>` origin from the content script.
The extension CSP also permits HTTP(S) source-image fetches, gated by Chrome host access.
The worker resolves an active image ticket through the isolated content script; it does
not accept an arbitrary message-supplied URL. The EDRDG
attribution link is an explicit user navigation. Backend CORS permits Chrome extension
origins only; optionally set `YOMISCAN_EXTENSION_ORIGINS` to your exact extension origin.
These are local development protections, not authentication against other local apps.

## Failures and limitations

- Missing models/dictionary require setup and backend restart. Initial downloads need
  internet; inference is local and can run with `HF_HUB_OFFLINE=1` after setup.
- Study timeout is 25 seconds, below Chrome's service-worker fetch-response lifetime limit.
  Model startup occurs before serving requests. A cancelled/timed-out crop may keep
  running on the backend; new requests receive 429 until it finishes.
- Chrome internal pages, Web Store, restricted viewers and unpermitted file URLs may
  reject injection. The action shows `!` and an explanatory tooltip. Use a normal page.
- Chapter requests use an offscreen extension document with a five-minute deadline.
  Backend inference may continue after timeout/cancellation; retry once it finishes.
- Selection covers the visible viewport only. Website fullscreen/top-layer elements,
  sticky headers and unusual stacking/clipping layouts may obscure or overlap overlays.
- Generic discovery can miss unusual readers or select a large unrelated image. It
  excludes common logo/ad/avatar/navigation contexts but cannot guarantee content identity.
- Image limits: 12 MP / 10 MiB input, 32 MiB output, 128 MiB compressed result cache per
  session. Distant overlays release their decoded image source, retaining cached Blob URLs.
- Canvas/WebGL readers, shadow-root/iframe readers, transformed/padded/bordered image
  elements, CSS background images and sites disallowing blob images are unsupported.
- OCR/translation errors, ambiguous dictionary entries, and missing context remain.
  No correction, vocabulary storage/export, or grammar explanation is added.

Tests use Node's built-in runner, mocked fetch and pure geometry/response logic; no
frontend test framework or browser download is required for ordinary tests. See
[Phase 4 validation](../docs/phase-4-validation.md) for actual Chrome checks and the
remaining manual matrix, including physical HiDPI and diverse manga websites.

Primary references: [captureVisibleTab](https://developer.chrome.com/docs/extensions/reference/api/tabs#method-captureVisibleTab),
[activeTab](https://developer.chrome.com/docs/extensions/develop/concepts/activeTab),
[commands](https://developer.chrome.com/docs/extensions/reference/api/commands), and
[service-worker lifetime](https://developer.chrome.com/docs/extensions/develop/concepts/service-workers/lifecycle).
