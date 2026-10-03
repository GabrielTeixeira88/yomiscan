# Phase 7: Translate Chapter MVP

The user-facing unit is a chapter. The processing unit remains one page image sent to
the existing `POST /api/v1/render-page` endpoint. Phase 7 changes no Python models,
translation engines, dictionary services, rendering algorithms or backend endpoints.
There are no new package dependencies. The extension adds Chrome's `offscreen`
permission, retaining `activeTab`, `scripting` and the existing loopback host permission.
The acquisition correction adds optional image-host access and controlled scroll capture;
see [current acquisition behavior and real-reader results](phase-7-acquisition.md).

## Start and use

Complete the model/JMdict setup in the root README, then use two terminals:

```powershell
# Repository root
uv sync
uv run uvicorn yomiscan.api.main:app --host 127.0.0.1 --port 8765 --reload
```

```powershell
cd extension
npm.cmd ci
npm.cmd run build
# Optional development rebuilds:
npm.cmd run watch
```

Wait for backend application startup. Load `extension/dist` using Chrome's Developer
mode / Load unpacked. Rebuild, reload the extension and refresh the reader after changes.
Click YomiScan, then **Translate Chapter**. Large loaded reader images are processed
progressively. Close the controls with **×** to read; reopen with the extension action.

- **Original / English** reuses cached PNGs without another backend request.
- **Stop Translation** cancels future jobs and disconnects discovery observers. An
  already submitted page may finish; its result remains available.
- **Translate Chapter** resumes stopped queued work and discovery.
- **Retry Failed / Skipped** explicitly retries those pages. Ordinary failures do not
  cause automatic retry loops.
- **Clear Session** aborts client work, removes overlays and revokes cached URLs.
- **Select Text**, also available through Ctrl+Shift+Y, stops scheduling, waits for the
  current page, selects Original and opens the existing Study selection flow. It does
  not automatically resume chapter processing. Change shortcuts at
  `chrome://extensions/shortcuts`.

The status counts currently discovered pages, not a promised total chapter length.
Once known pages finish, the session keeps watching for lazy-loaded pages. A successful
page response can retain untranslated regions: “translated” counts returned page PNGs,
not perfect replacement of every Japanese block. Preserved-region counts are shown.

## Modules and page state

| Module | Responsibility |
| --- | --- |
| `chapter/discovery.ts` | Candidate decisions and replaceable `PageDiscoveryStrategy` |
| `chapter/model.ts` | Typed page records, serial queue, priority and resource ownership |
| `chapter/session.ts` | Discovery lifecycle, acquisition, health, results and cache |
| `chapter/acquisition.ts` | Loaded-image pixels and verified capture geometry |
| `chapter/transport.ts`, `wire.ts` | Bounded runtime-port image transfer |
| `offscreen.ts` | Local render requests and serialization across chapter tabs |
| `chapter/overlay.ts` | Reversible aligned images in isolated Shadow DOM |
| `chapter/controls.ts` | Compact Study/Reading controls and progress/errors |

Loaded eligible pages move through queued, processing, translated, failed or skipped.
Images not yet loaded remain unregistered, with rejection diagnostics, until they become
eligible. Each record has a stable generated ID, source element, selected source URL,
dimensions, state, attempts, error and optional rendered result. Element identity plus
`currentSrc`, dimensions and observed same-source reload revision prevents duplicate
work. Source changes invalidate only that element's result. Late results for an old
identity are discarded and their URLs revoked.

Discovery accepts natural sizes of at least 400×500 and displayed sizes of at least
240×300 CSS pixels, with aspect ratios between 0.15 and 2.2. It excludes hidden or
unloaded images and common navigation, ad, logo, avatar, recommendation and comment
contexts. It selects the dominant vertically stacked column of similarly sized images.
These are generic heuristics, not semantic manga classification. Developer diagnostics
log accepted/rejected images, reasons, dimensions, sources, IDs, states and attempts.

One request runs at a time per session. The offscreen transport also serializes chapter
requests across tabs, with at most eight connected chapter ports. Study requests retain
the backend's existing busy guard and can receive HTTP 429 when another tab is rendering.
Priority is recalculated before each job: visible, near below, near above, then distant
pages. It does not interrupt in-flight inference when the reader scrolls.

While active, a 150 ms debounced MutationObserver watches relevant source/layout
attributes and child changes, with load and resize events. It reads `currentSrc` for
`srcset`, and waits for a site's own lazy loader to populate the real image. It does not
fetch `data-src` itself. Only the explicit scroll-capture fallback moves the reader.
New eligible images enter the same queue.

## Image access and local transport

Extension-worker fetch is preferred for loaded HTTP(S) image sources after optional host
approval. Canvas remains a fallback when browser security permits. No cookies or remote
image URLs are sent to Python. Density-corrected
`naturalWidth`/`naturalHeight` can reduce pixel resolution for a high-density `srcset`
source; screenshot fallback also has viewport resolution rather than source resolution.

A tainted canvas can fall back to `captureVisibleTab` only when the entire image is
visible, unobscured at sampled points, aspect-correct and stable. Controls/English
overlays are hidden, two animation frames pass, and the worker verifies the active tab,
source and viewport before/after capture. Only the cropped page goes to Python. A
restricted image taller than the viewport can use opt-in scroll/capture/stitching, with
position restoration and cancellation. There is no requirement to zoom out for supported
fetch/stitch cases. Explicit Retry reruns acquisition and can request newly needed hosts.
See the acquisition document for geometry, occlusion and size limits. No access bypass.

Input is limited to 12 megapixels and 10 MiB; output to 32 MiB. Runtime messages use
192 KiB binary chunks encoded for Chrome 120's JSON messaging. An extension-origin
offscreen document performs the long localhost fetch with a five-minute deadline,
avoiding service-worker fetch lifetime limits. PNG type, count metadata, decoded image
dimensions and displayability are validated before overlaying. Invalid responses leave
the original visible. There is no web-accessible bridge or required all-sites host grant.

The backend remains `127.0.0.1:8765`, with the existing client header and CORS policy.
Health is checked before queueing. Network, HTTP, timeout and per-page capture errors are
reported; other pages can continue. Cancelling a browser request cannot guarantee that
Python inference stops. Wait for it to finish before retrying a busy server.

Primary Chrome references: [offscreen documents](https://developer.chrome.com/docs/extensions/reference/api/offscreen),
[messaging serialization](https://developer.chrome.com/docs/extensions/develop/concepts/messaging),
[service-worker lifetime](https://developer.chrome.com/docs/extensions/develop/concepts/service-workers/lifecycle),
and [visible-tab capture](https://developer.chrome.com/docs/extensions/reference/api/tabs#method-captureVisibleTab).

## Overlays, cleanup and memory

Pointer-transparent fixed overlays live in closed Shadow DOM, leaving site images,
`srcset` and layout unchanged. Bounds, object fitting and ancestor clipping follow the
source on scrolling and resizing. Original hides overlays immediately; untranslated
and failed pages always retain their originals. Ordinary scrolling/navigation controls
remain usable. The controls have separate isolated styling.

Compressed results use object URLs, capped at 128 MiB per session. Distant overlays and
Original mode release decoded image sources while retaining cached compressed results.
Canvas buffers, response chunks and decode probes are released after use. Replacement,
removal and session destruction revoke result URLs. Clear/unload aborts client requests,
disconnects observers/listeners, cancels animation frames and drops late responses.
URL changes in SPAs, including hash changes, destroy the session within one second.
The small offscreen extension document may remain idle after requests finish; it does
not retain completed page images or poll the backend.

Stop intentionally retains display listeners/cache for scrolling and toggles. Clear or
navigation performs full session cleanup. Use Clear when a reader changes chapters
without changing URLs or image sources, or reloads changed bytes at the same URL while
discovery is stopped. No persistent settings/history, analytics or remote storage exist.

## Validation and development fixture

Ordinary checks, without loading neural weights:

```powershell
uv run pytest
uv run python -c "import yomiscan.api.main, yomiscan.page, yomiscan.rendering"
cd extension
npm.cmd test
npm.cmd run build
```

The fixture generates original synthetic panels, bubbles and Japanese text in browser
canvas. No copyrighted images are included. Serve it from the repository root:

```powershell
uv run python -m http.server 8772 --bind 127.0.0.1 --directory extension/fixtures
```

Open `http://127.0.0.1:8772/reader.html` (`?single=1` for one page). Buttons load a
`data-src` page, append another page, replace an image source and simulate SPA navigation.

The opt-in `node extension/tests/browser-chapter.mjs` uses an already running backend
and isolated Chrome at debugging port 9231. It starts its own fixture servers on
8772/8773, so stop the manual fixture server first. It loads the built extension and
uses Chrome DevTools only as a development test harness; product operation requires
no external browser automation. One way to start the dedicated test Chrome on Windows:

```powershell
Start-Process -FilePath 'C:\Program Files\Google\Chrome\Application\chrome.exe' -WindowStyle Hidden -ArgumentList '--headless=new','--remote-debugging-port=9231','--enable-unsafe-extension-debugging','--no-first-run','--no-default-browser-check',"--user-data-dir=$PWD\.cache\phase-7-chrome",'about:blank'
node extension/tests/browser-chapter.mjs
```

Use that isolated development profile, not an everyday Chrome profile: the harness
reloads YomiScan there. Generated reports/screenshots stay under ignored `.cache/`.
Real inference checks require existing cached models and JMdict. The long-queue test
uses mocked render responses and is not a neural-model quality benchmark.

Validation on Windows, Python 3.13.9 and isolated headless Chrome 154.0.8037.93:

| Check | Observed result |
| --- | --- |
| `uv sync`; backend imports | Passed |
| Full Python suite, including Study/page/render APIs | 146 passed; one existing Starlette/httpx deprecation warning |
| Extension unit tests | 23 passed, including queue, discovery, lifecycle and Study geometry/API cases |
| Extension build | Passed strict TypeScript checking and esbuild |
| Five stacked pages, then seven with lazy/appended images | Real local CPU render responses displayed progressively |
| Visible-page priority | Page 3 submitted before pages 1/2 |
| Stop, scroll and resume | Queued pages stopped; scrolling during inference worked; result retained; resume processed remaining pages |
| Failure isolation and retry | Injected page-2 HTTP 500 did not stop other pages; explicit retry succeeded |
| Original/English | Computed overlay visibility changed; repeated toggles made no additional requests |
| `srcset` and source replacement | Selected source used; replacing page 1 invalidated only its result and submitted one new job |
| Responsive resize/scroll | Overlay bounds matched source within 0.6 CSS pixels |
| Study after English | Original restored, Escape cancelled, actual selected Japanese produced OCR/translation/dictionary popup |
| SPA navigation / Clear | Session overlays removed and state cleared; URL-release ownership also covered by unit tests |
| Offline backend | Blocked health request produced startup guidance before render queueing |
| One cross-origin image without canvas access | Fully visible screenshot fallback rendered successfully |
| Restricted image taller than viewport | Stayed original with skip reason, then retried when fully visible |
| Long synthetic chapter | 24 pages completed in 1,999 ms and cleared with mocked PNG responses; not real inference timing |

The browser harness covers 16 scenarios; HTTP failure/offline conditions are deliberately
injected. Ordinary backend tests use fakes; real model inference is separate and used
existing caches with `HF_HUB_OFFLINE=1` and CPU selected. No GPU execution was tested.
The full integration report is generated at `.cache/phase-7-browser.json`.

The generated browser screenshot was visually inspected: English “But I'm fine.” sits
inside the synthetic bubble and the overlay aligns with the original page after resize.
The renderer preserves the separate Japanese text outside that bubble, and the controls
report preserved regions. The controls cover part of the right side while open; × hides
them. This demonstrates integration, not broad manga translation/rendering quality.
No public sites or copyrighted chapter fixtures were used. Long-chapter inference time,
peak memory and multi-tab fairness were not benchmarked.

An intermediate integration rerun hit a 60-second test deadline at 18/24 mocked pages
with no failed/skipped pages. Its progress polling repeatedly serialized the entire DOM,
including every fixture data URL. The harness now retains a reference to the controls
and reads only their status. The final full rerun passed all 16 scenarios; the roughly
two-second mocked queue result above measures transport/orchestration on this fixture,
not neural rendering or a general performance guarantee.

## Supported scope and remaining work

Works with standard image-based readers using supported page layouts. No public manga
website compatibility is claimed from the local fixture. Generic discovery can miss
unusual columns or include a large unrelated image. Canvas/WebGL readers, iframe or
shadow-root readers, CSS backgrounds, transformed/padded/bordered image elements and
content policies blocking Blob images are unsupported. Ancestor transforms, fullscreen
or top-layer content and unusual clipping/stacking may misalign or obscure overlays.
Pinch zoom remains unsupported; tall restricted images use the optional stitcher. Physical
HiDPI, many simultaneous tabs and diverse real-site layouts need broader testing.

CPU rendering remains sequential and can be slow on long chapters; no GPU performance
claim is made. First page use may initialize the detector. The renderer can preserve
uncertain blocks, artwork and SFX; detector misses, narrow layouts and imperfect
inpainting/typesetting remain Phase 6 limits. Local translation still lacks chapter
dialogue context and can mishandle slang or omitted subjects. Phase 7 changes none of
those quality tradeoffs.

Recommended post-MVP work: representative authorized reader testing and targeted
discovery/acquisition adapters, followed by translation/rendering benchmarks and OCR
correction. Persistent caching, packaging and additional study features remain future
work; they are not implemented here.
