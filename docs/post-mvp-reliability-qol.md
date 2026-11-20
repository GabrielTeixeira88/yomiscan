# Post-MVP Reliability & Quality of Life

Phases 1–7 remain the historical MVP. This increment implements P01–P05 from the
[repository comparison](yomiscan-vs-yomu-research.md) on a descriptive feature branch.
OPUS, detector/OCR selection, rendering safety and the Python/FastAPI/MV3 boundaries
remain the baseline. Detection experiments, persistent caching and new models are outside scope.

## Page diagnostic reports

In chapter controls, select **Page** or leave **Nearest viewport**, then click
**Export Page Report**. This does not rerun detection, OCR or translation.

The local ZIP contains:

- **manifest.json:** schema/build, page/job identity, image hashes/dimensions,
  selected model metadata/settings, counts, acquisition outcomes and missing information.
- **regions.json:** raw boxes/scores and raw-region-to-block mapping, order,
  OCR/translation/render statuses and code-owned preservation/failure reasons.
- **timings.json:** measurable browser acquisition/round-trip/total times and backend
  analysis/rendering stages. These are observed durations, not OCR accuracy.

**Report inclusions** contains three initially unchecked options:

- **OCR and translation text:** adds optional/translation-debug.json with available
  original OCR, adapter translation source and accepted output. Exact serialized LLM
  prompts and raw rejected responses are unavailable unless an engine records them;
  this feature does not invent them.
- **Original page image:** adds optional/original.png when still retained.
- **Translated page image:** adds optional/rendered.png from the existing result.

Review any included text/images before sharing. URLs, raw errors, credentials and local
paths are omitted/redacted. Image attachments are re-encoded without EXIF/ancillary metadata.
No report is uploaded. Browser clipboard/download policies may require an actual click.

The backend snapshot limit is 2 MiB; image output is bounded to 32 MiB; export is capped
at 48 MiB. Only three recent original acquisitions within 24 MiB are kept in memory,
so older pages may explicitly lack original pixels. Metadata/text snapshots share the
existing bounded session memory budget. Clear, reload and navigation discard them.
Saved browser downloads remain until the user removes them. Local reports are ignored by Git.

No OCR confidence is fabricated: detector scores are separately labelled and the
current manga-ocr adapter reports null OCR confidence. Unknown missing/undetected text
stays null. General translation errors are labelled failed; rejection and generation
completeness remain null because the current failure contract does not distinguish
transport failures from rejected/truncated model output. Failed acquisition/whole-request pages export available browser metadata
with an explicit unavailable backend snapshot. Per-block OCR/translation/mask/layout/
inpainting failures retain neighboring results and their diagnostic stage.

Snapshots identify the source bytes by SHA-256 and dimensions; exports check the
current page/source/session again before download. Refreshed pages retain the old
successful snapshot until replacement succeeds; the job ID records which result is shown.

### API compatibility

Existing analyze-image/analyze-page endpoints and default render-page PNG response
are unchanged. Opting into POST /api/v1/render-page?diagnostics=true returns an in-memory
stored ZIP with rendered.png and snapshot.json under the same upload, Host/Origin,
client-header, busy guard and worker ownership. It is transport data, not a saved report.
The extension also accepts an older PNG-only backend and explicitly marks missing diagnostics.
Snapshot collection temporarily includes text in session memory; text leaves the app
only when the user selects its export checkbox.

## Study copy and page refresh

**Copy Japanese** and **Copy English** are keyboard-focusable buttons in the existing
Study popup. Feedback announces success or tells the user to copy selected text manually.
No clipboard permission was added. Popup drag/resize, selectable text, closed Shadow DOM,
focus return and Escape behavior remain available.

**Retranslate Page** bypasses only that page's existing result. The queue remains serial,
including refresh requested while another page is processing. The previous successful
image remains visible and usable with Original/English until a valid replacement arrives.
Failure or Stop retains it; Clear/navigation discards it. Repeated refresh clicks cannot
schedule duplicate jobs. New source revisions reject late results and revoke their URLs.
No persistent cache or stage-aware retranslation is introduced.

## Acquisition retry correction

The suspected issue was reproduced through PageImageAcquirer → ChapterQueue:
after a strategy raised WaitForViewport, the wrapper became AcquisitionError/SkipPage
and visibility changes never retried (one attempt instead of two).

SkipPage now carries retryWhenVisible; AcquisitionError retains strategy causes through
AggregateError and preserves that disposition. Permission, HTTP authentication/error and
unsupported-source failures carry manual-retry classifications through the worker port.
They do not automatically retry when scrolling. Cancellation propagates; automatic viewport
retries remain bounded to three attempts and a new source gets a new record.

## CI and local verification

.github/workflows/ci.yml runs on pushes and pull requests with contents-read permission,
concurrency cancellation and SHA-pinned actions.

- Python 3.13 on Windows/Linux: uv sync --frozen, uv run --frozen pytest and package imports.
- Node 22 on Linux: npm ci, npm test and npm run build from extension/.

Only dependency caches are used. Hugging Face/Transformers are offline during tests and
no model artifacts, copyrighted samples or diagnostic exports are cached/uploaded.
Real inference and browser tests remain opt-in and separate from ordinary CI.

Local commands:

~~~powershell
uv sync --frozen
uv run --frozen pytest
uv run --frozen python -c "import yomiscan.api.main; import yomiscan.diagnostics"
cd extension
npm.cmd ci
npm.cmd test
npm.cmd run build
~~~

The existing isolated Chrome fixture supports **--mock-backend** for synthetic pages and
fake neural results. Build/test first. Launch a separate Chrome profile with
--remote-debugging-port=9231 --enable-unsafe-extension-debugging, then from the repository root:

~~~powershell
node extension/tests/browser-chapter.mjs --mock-backend
~~~

It uses localhost ports 8772–8774, an ignored test build/profile/download directory and
the existing Chrome installation. YOMISCAN_TEST_CDP_PORT overrides 9231. A run without
--mock-backend uses the explicitly started real backend and is a separate inference check.
The fixture changes extensions only in the selected debugging profile; always use an
isolated profile. No models or browser binaries are downloaded by the fixture.

The privacy boundary is recorded in [the decision note](decisions/diagnostic-report-privacy.md).

### Validation recorded for this increment

On Windows with the locked dependencies: **200 backend tests** and **51 extension tests**
passed; package imports and the strict TypeScript/build check passed. Tests used fake
neural engines and synthetic images. The existing Starlette/httpx deprecation warning
remains; no framework or lockfile changes were introduced to suppress it.

The isolated **Chrome 157** fixture passed all **24 checks** with --mock-backend:
Study selection/copy/drag/resize, queue priority and cancellation, successful/failed
refresh, local metadata and optional-image/text ZIP downloads, stale-export rejection,
lazy discovery, source/SPA cleanup, direct/canvas/viewport/stitched acquisition,
permission recovery and a 24-page synthetic queue. Browser downloads and fixture logs
remain ignored local artifacts. These are browser integration checks, not neural quality results.

Workflow YAML, job paths, OS matrix, permissions and action SHA pins were checked locally.
Hosted job results belong to the pull request checks; a local run is not evidence of a
Linux or GitHub-hosted pass. No real inference or accuracy benchmark was performed.
