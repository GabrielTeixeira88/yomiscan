# Phase 7 image acquisition correction

## Root cause and boundary

The initial chapter MVP started with `drawImage` on a content-script canvas. CDN images
without CORS tainted that canvas. Its only fallback required the entire image to fit in
the viewport, so tall reader pages were skipped despite successful discovery. The
manifest also allowed network access only to localhost.

`PageImageAcquirer` now owns acquisition independently of discovery, the queue, overlays
and the unchanged Python page renderer. It returns pixels, dimensions, the successful
method and ordered attempts. Developer diagnostics retain each failed method/reason,
including HTTP 401/403, even when a later method succeeds. Normal UI shows a concise
final failure only after the chain is exhausted.

1. **direct-extension-fetch:** selected HTTP(S) source in the extension worker.
2. **canvas:** same-origin/CORS-permitted loaded pixels, including data/blob sources.
3. **viewport-capture:** unobscured whole image in the current viewport.
4. **stitched-capture:** opt-in controlled scroll/crop/stitch for taller/offscreen pages.

Data/blob sources do not enter network fetching. Page-owned blobs remain in their owning
page context. If canvas access fails, the screenshot methods remain available. Failed
acquisition does not send an empty image to Python. Retry runs the full chain again and
checks current permissions anew.

## Permissions and source fetch

The production manifest retains required `activeTab`, `scripting`, `offscreen` and
loopback access. `optional_host_permissions` declares HTTP/HTTPS patterns so specific
image hosts can be requested at runtime. Broad access is not granted at installation.
The CSP permits HTTP(S) connections; Chrome host permissions still gate image fetching.

Translate Chapter / Retry checks the discovered hosts. Missing access opens a small
extension-owned window listing those exact hosts. **Allow image host access** calls
`chrome.permissions.request` from its own click handler, then Chrome asks for approval.
This extra window is necessary: relaying a content-script click to the worker did not
preserve the user gesture required by Chrome in real-reader testing. **Use capture
fallbacks** continues without granting hosts. Stop/Clear invalidates a pending window's
resume ticket. Closing the window leaves the session waiting; activate again to retry.

Grant access to the listed image CDN hosts, not every website. New lazy-loaded image
hosts can require another explicit Retry. Chrome permissions cover every path/port on
the requested scheme/hostname. Revoke them in Chrome's extension settings when desired.

The worker accepts an acquisition nonce, not an arbitrary remote URL. The isolated
content script resolves it only to the currently acquiring, connected, fully loaded
image's `currentSrc`. The source is rechecked after fetching. No page script bridge,
backend internet proxy, cookies API, request-header rewriting or security bypass exists.

Source requests use `credentials: include`: Chrome decides which cookies may be sent.
This cannot promise access to partitioned/session-bound CDN cookies or hotlink policies.
No cookies or source URLs are sent to Python. HTTP failures are retained in diagnostics.
Redirects are rejected rather than following unverified hosts; canvas/capture can still
read already-visible pixels. PNG, JPEG and WebP bytes and MIME are preserved. Other
types use the fallback chain. Browser-decoded dimensions and existing 10 MiB / 12 MP
limits are checked. A bounded 25-second source request aborts on disconnect/cancellation.

## Capture and stitching

The visible-page method hides YomiScan controls/English overlays, waits for repaint,
checks occlusion at sampled points, and verifies source, geometry and active tab before
and after capture. Only the image crop is transferred. Actual screenshot-to-CSS ratios
account for DPR and ordinary browser zoom, without multiplying DPR twice.

**Allow scroll capture** is off by default because it temporarily moves the reader.
When enabled and earlier methods fail, the stitcher records the original scroll position,
estimates top/bottom obstruction by fixed/sticky elements, plans adjacent vertical slices,
scrolls each slice into view, crops and composites into one PNG. Shared rounded pixel
boundaries avoid duplicate destination rows; fractional crop offsets exclude screenshot
rounding margins. It does not erase/hide website headers or alter the source image.

All screenshot requests, including Study Mode and other chapter tabs, share a serial
650 ms start-spacing throttle, below Chrome's two-captures-per-second limit. A maximum
of 40 segments and the existing pixel/upload limits bound work. Buffers are released.
Scroll restoration runs in `finally` after success, errors or cancellation. Escape,
wheel/touch/pointer/keyboard input, Stop, source replacement, resizing and geometry
changes interrupt capture. Backend inference already submitted may still finish.

Supported stitching assumes a stable, axis-aligned image in the window scroller.
Nested scroll containers, horizontal clipping, pinch zoom, overlays covering sampled
image points and changing layouts fail with a reason. Occlusion sampling cannot prove
that every source pixel is unobstructed; direct source fetching remains preferred.
Animated images and complex transforms are not promised. No source-resolution claim is
made for screenshot/canvas fallback; direct fetch retains actual selected-file resolution.

## Validation

Ordinary tests mock network/Chrome boundaries and do not load models. They cover fallback
ordering, source MIME/credentials, missing/granted permission retry, authentication
failures, canvas security errors, data/blob handling, bounded sizes, slice/DPR rounding,
scroll restoration and capture throttling. Existing Study geometry and discovery tests
cover `currentSrc`, zoom and viewport coordinate conversion.

The opt-in browser fixture additionally exercises a real cross-origin PNG endpoint with
cookies and no CORS, an SVG source that must use capture, tall stitching without zooming,
Escape restoration, and unchanged Study/toggle/lazy-load/error/cleanup behavior. Neural
rendering runs on the local CPU backend; the 24-page queue stress case remains mocked.

Real-reader validation uses the two URLs supplied by the user. In isolated headless
Chrome, native optional-permission approval cannot be clicked by the page CDP harness.
For the granted-access tests only, an ignored copy of the built extension pre-grants
`https://kuma.kyut.dev/*` and `https://ihlv1.xyz/*` through normal manifest host permissions.
Application code is identical; production permissions remain optional. The production
access window was tested up to Chrome's native approval prompt. No CORS/security flag,
authentication bypass or proprietary/copyrighted sample is added to the repository.

Results on Windows / Python 3.13.9 / Chrome 154.0.8037.93, local CPU inference:

| Supplied chapter | Discovered | Acquired | Rendered pages | Acquisition / page failures |
| --- | ---: | ---: | ---: | --- |
| [Rawkuma, Fairy Tail chapter 220](https://rawkuma.net/manga/fairy-tail-100-years-quest/chapter-220.413422/) | 20 | 20 | 20 | All `direct-extension-fetch`; 0 failed, 0 skipped |
| [Nihonkuni, Kinki chapter 4](https://nihonkuni.com/manga/kinki-spiritual-affairs-bureau-7804/chapter-4.306159.html) | 38 | 38 | 38 | All `direct-extension-fetch`; 0 failed, 0 skipped |

Nihonkuni initially had only three loaded page images. Scrolling through the existing
reader triggered its own lazy loading before the complete 38-page run. There was no
manual zoom-out or screenshot stitching in either granted-access reader test. Nihonkuni's
38-page acquisition/render loop took about 201 seconds on this CPU environment, excluding
initial model setup and the preliminary reader-loading scroll. This is one chapter, not
a general benchmark. Rawkuma timing is omitted because the temporary reporting harness
continued polling after completion. Per-page diagnostics verified all 58 direct fetches.

“Rendered” means a valid PNG response was displayed, not every Japanese glyph replaced.
The existing renderer reported preserved regions on 8 Rawkuma pages and 34 Nihonkuni
pages. No translation/masking/typesetting quality changes are part of this acquisition fix.
Reports remain in ignored `.cache/`; manga pixels are not added to Git.

The backend regression suite passes 146 tests (one existing Starlette/httpx deprecation
warning). The extension suite passes 36 tests and the strict TypeScript/esbuild build.
The final browser fixture passes all 19 scenarios, including direct cross-origin source
fetching with cookies, viewport capture, stitching at fractional DPR (1.25),
cancellation/restoration, Study OCR on original Japanese, toggles, lazy discovery,
failed-page retry and cleanup. The missing-host window lists the specific host and its
capture-fallback choice successfully resumes the reader. Native permission approval
still requires the user's Chrome interaction; that approval is not automated.
Source timeouts, native permission-gesture
rejection and an outdated zoom-based fixture expectation surfaced during intermediate
runs; the permission flow and fixture were corrected before final validation.

Primary references: [extension cross-origin requests](https://developer.chrome.com/docs/extensions/develop/concepts/network-requests),
[optional permissions and user gestures](https://developer.chrome.com/docs/extensions/reference/api/permissions),
[captureVisibleTab and rate limits](https://developer.chrome.com/docs/extensions/reference/api/tabs).
