# Stage 5: Reader Experience & Distribution — validation

Validation date: 2026-11-20 (America/Sao_Paulo). This is functional evidence, not a
new recognition/translation quality benchmark. Stage 1–4 reports remain unchanged.

## Baseline and scope

Stage 4 PR [#4](https://github.com/GabrielTeixeira88/yomiscan/pull/4) was reviewed at
head `3469e1319740792040455536a59013975f81059c`: six successful checks, no unresolved
review threads, clean mergeable state. Its actual merge commit and the Stage 5 base
is **`78dd83ba8322fa60c0a81fd7f98c979de6a42431`**. The descriptive branch
`feat/post-mvp-reader-experience-distribution` was created from updated main.
Merged-main validation passed 299 backend tests (one existing Windows skip),
59 extension tests, strict build and imports.

Scope is P10 font/inspection, P11 readonly readiness, P12 actual progress, P13 optional
history/exact-analysis reuse, then P06 packaging. Defaults remain original manga-ocr,
PyTorch comic detector and English OPUS. Stage 4 glossary invalidation remains intact.

## Automated regression evidence

Windows, Python 3.13.9, Node 22.19.0; locked uv/npm environment. Ordinary backend tests
use an empty HF cache with `HF_HUB_OFFLINE=1` and `TRANSFORMERS_OFFLINE=1`.

| Gate | Result | Evidence |
| --- | --- | --- |
| `uv sync --frozen` | Passed; lock unchanged | Locked local environment |
| Final full `uv run --frozen pytest` | 316 passed, 1 skipped | Existing regressions plus Stage 5 contracts |
| Focused render/cache run after failure-progress change | 34 passed | Renderer error status and retained refresh output |
| Final readiness run | 6 passed | Requires the exact production detector safetensors artifact; cache/glossary state stays current |
| `npm.cmd test` | 68 passed | Queue, history, identity, status and reader contracts |
| `npm.cmd run build` | Passed | Strict TypeScript and actual bundles |
| API/rendering/translation/package imports | Passed without Torch in `sys.modules` | Imports do not load engines |

The existing Windows skip is atomic replacement of an open dictionary database,
which Windows file locking prevents. The existing Starlette warning about httpx
TestClient remains. No failed tests remain in these passing runs. One cleanup test
was updated to mock the current OCR factory/preflight seam, retaining its assertion
that optional translation resources close after OCR initialization fails.

New coverage includes finite/bounded font scales, accents/wrapping, original-pixel
preservation, render-only upstream reuse, Study DTO reuse, renderer-error rejection,
expiring/bounded job records, mixed cached/failed stages, protected status during
slow initialization/busy inference, wrong-kind model IDs, no readiness downloads,
cache enable/disable/glossary-open publication without an image job, history restart/
CRUD/export/count/byte limits and metadata filtering, font replacement losing specific
rendered IDs, and stale instance/version/job rejection.

## Isolated Chrome reader integration

`extension/tests/browser-chapter.mjs --mock-backend` uses synthetic authorized images
and an owned headless Chrome profile. Existing checks cover Study selection/copy/resize,
chapter/Original-English/retry/navigation, acquisition fallbacks, long-chapter LRU,
report consent and Stage 4 terminology/target invalidation. New checks cover font/reset
retention during slow/error/overflow responses, explicit region text/reasons, exact
bubble dictionary reuse, history off/save/open/copy/export/delete/clear, resize mapping/
Escape, slow/unavailable readiness, actual mock stage transitions and source-change
cleanup. These do not measure real-model recognition or translation accuracy.

The final complete run passed **37 checks on Chrome 157.0.8103.79**, including normal
HTTP overflow-response retention. The 24-page/192 MiB cumulative queue stayed within
its 128 MiB session budget and restored evictions. Its recorded wall time was
187,271 ms while local packaging checks also ran; an earlier run was 25,301 ms.
These synthetic browser timings are not a controlled performance comparison.

## Real cached-production inference smoke

`scripts/validate_reader_smoke.py` ran one authorized local page using already cached
production weights, local JMdict and an isolated processing cache. No model downloads.
Source pixels/text and raw outputs remain ignored.

| Observation | Measured result |
| --- | --- |
| Page geometry / grouped blocks | 870 × 1270 / 13 |
| Rendered / preserved | 9 / 4 |
| Independent Study crop | Nonblank actual OCR, 6 analyzed tokens |
| Bubble Study | 6 retained tokens, validated without pipeline invocation/additional OCR |
| Repeat page | Every stage restored from cache |
| Font scale 1.25 | Detection/OCR/lexical/translation restored; rendering recomputed |
| Initial service setup | 36,673.75 ms |
| First page pipeline | 9,654.57 ms |
| Detection / OCR / translation / lexical | 938.06 / 4,683.59 / 2,181.31 / 23.71 ms |
| Font-only page pipeline | 776.87 ms; current upstream stage work 0 ms |

The smoke recorded actual initialization/detection/OCR/ordering/lexical/translation/
render callbacks and cache reuse. Setup includes cold imports/identity hashes;
single-run timings are not a controlled speed benchmark. The default detector used
its existing PIL fallback with torchvision unavailable. Semantic accuracy, broad
detector recall and general rendering quality were not scored. Stage 2/4 model
matrices were not rerun.

## Packaging execution

An explicitly dirty local preview produced actual extension ZIP, wheel, sdist,
checksums, manifest, notices and installation guide. A fresh Python 3.13 environment
installed 59 cached locked runtime packages. Both wheel and sdist passed isolated
import/version/font/OFL checks, six CLI help checks, protected API missing-resource
startup/readiness and checksum verification. The extracted ZIP loaded in Chrome
157.0.8103.79: MV3, packaged service worker and reader controls all activated.
These were executed checks. Preview provenance is dirty and is not a clean release.

Clean exact-commit builds, same-host byte reproducibility and hosted artifact checks
are recorded in final delivery evidence. CI gates Windows/Linux backend and Node
before an exact checkout, package build/install, actual extracted-ZIP Chrome load and
run-associated upload. Manual dispatch is supported. No model downloads/inference,
version tag or GitHub Release is part of packaging. Local Windows evidence alone
does not establish Linux/hosted execution.

## Independent pre-commit reviews

Separate architecture/correctness, privacy/distribution and specification agents
reviewed tracked/untracked changes before commits. Concrete findings were fixed and
independently rechecked:

- Font replacements losing previously rendered IDs are rejected even with unchanged
  counts. The existing backend refresh error gate was confirmed and directly tested.
- Valid catalog IDs belonging to another component kind fail configuration validation.
- Artifact metadata comes from the synchronized project interpreter, not unrelated
  global packages; versions are validated against `uv.lock`.
- Cache enabled/glossary open observations are distinct from disk writability, and
  refresh immediately after administration on the owning worker.
- Available detector confidence and OCR confidence remain separately labeled.

All reviewers cleared those blockers. A shared neutral Study serializer is optional
maintenance; the current renderer reuses the existing API DTO rather than duplicating
the wire contract. Device probes explicitly limit claims to catalog support and
observed runtime rejection, without importing Torch.

## Decisions and boundaries

| ID | Decision | Remaining limit |
| --- | --- | --- |
| P10 | Implemented | Safe 75–150%; unsupported geometry rejected; old scale may remain after rejected refresh |
| P11 | Implemented readiness subset | No graphical downloader/hot switching; installed does not mean verified or runtime-compatible |
| P12 | Implemented | Actual stages/cache bytes/timings; no RSS/VRAM/performance prediction |
| P13 | Implemented | Off plus explicit Save; evicted/missing analysis needs reprocessing |
| P06 | Implemented development distribution | Unsigned ZIP/wheel/sdist; external models/JMdict, no bundled installer/public release |

History adds local storage permission and explicit retention: 100 entries/2 MiB,
128 KiB per entry, oldest eviction; disable retains, delete/clear erase, exports
remain where saved. Cache clear never erases history/glossaries. Default reports
still omit text/images/Study DTO. No AGPL source was copied. Private pages, weights,
databases, browser profiles and raw benchmark outputs remain outside committed files.
