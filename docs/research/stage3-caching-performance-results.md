# Stage 3: cache validation and observed performance

Measured locally on 2026-11-20. No new OCR/detection/translation model or dependency
was selected, installed or downloaded for inference. Raw pages, transcriptions,
SQLite caches, rendered outputs, diagnostic ZIPs and machine paths remain ignored
local artifacts. This report contains aggregate observations only.

## Stage 2 merge and Stage 3 base

PR [#2](https://github.com/GabrielTeixeira88/yomiscan/pull/2) merged through GitHub
using its expected published head `3a98613cf05f622d0dfa8ec4e8906d67d730b43f`.
Actual merge commit: `7a7ece765c335df4d793c272b4b80a4f5353e07b`.
No blocking integration issue or unresolved review was found; defaults and optional
dependencies were preserved. Merged main passed 216 backend tests, 51 extension
tests, strict build/import checks, and its three [hosted CI jobs](https://github.com/GabrielTeixeira88/yomiscan/actions/runs/44796265686).
`feat/post-mvp-caching-performance` was created from that updated main.

## Correctness and integration

Local Windows validation on the final implementation:

| Check | Observed result |
| --- | --- |
| `uv sync --frozen` | Existing 63-package environment checked; lockfile unchanged |
| `uv run --frozen pytest` | **256 passed, 1 skipped** |
| Imports | Package, API, cache, page, service and optional factories import without constructing engines |
| `npm.cmd ci` | 9 packages; audit reported zero vulnerabilities |
| `npm.cmd test` | **56 passed** |
| `npm.cmd run build` | Strict TypeScript check and production build passed |
| Isolated Chrome 157.0.8103.79 | **27 checks passed**, mocked backend explicitly distinguished from model inference |
| `git diff --check` | Clean |

The skipped test attempts atomic replacement of an open SQLite dictionary. Windows
locks that file, so the test documents stopping the backend before reimport; Linux
CI exercises the replace/reopen path. One pre-existing Starlette/httpx deprecation
warning remains. There are no neural weight downloads/loads in ordinary tests.

Counting fakes cross the actual detector/OCR/analyzer/translator/renderer interfaces.
They verify native batch cardinality/order, repeat/restart hits, translator-only and
renderer-only invalidation, detector/OCR descendants, independent lexical invalidation,
exact pixels/re-encoding/dimensions/mode/palette/alpha identity, explicit refresh and
failed-refresh retention. Storage tests cover disabled result access, malformed payload
types, invalid typed JSON/checksums, missing/corrupt databases, inaccessible storage,
rollback, quota eviction, settings bounds/consent, clear, owning-thread protection
and Windows-safe closure. Optional vision identities use verified-artifact test doubles;
NMT CPU/CUDA and unloaded llama.cpp `auto` selections have model-free regression coverage.
The benchmark runner rejects protected/existing output paths before model construction.

The queue tests simulate **1.25 GiB** of cumulative result ownership within a 128 MiB
budget, test LRU touches, visible/refresh/export protection, failure, repeated reload,
deferred release, source revisions, cancellation and disposal. These are call-count
simulations, not model inference or browser heap measurements.

Chrome also transferred **over 192 MiB of actual synthetic PNG responses** through
the production chunk transport: 24 pages processed in **25.327 seconds** with bounded
retention, offscreen eviction and restoration when an evicted page became visible.
The figure includes synthetic transport/render fixtures, not neural inference. It
does not measure JavaScript heap, process RSS or GPU memory. Additional checks cover
overlay geometry, Study selection/copy/move/resize, privacy-controlled reports,
concurrent refresh/export cancellation, lazy/source/navigation changes, capture and
host-permission fallbacks, persistence controls and backend-generation invalidation.

## Real offline page processing

Three previously authorized local reader pages, each **870×1270**, were processed on
Windows with the production PyTorch detector (.50/.50), original manga-ocr and OPUS.
CPU execution used four Torch threads. Runtime versions: Torch **2.14.0**,
Transformers **5.17.0**, manga-ocr **0.1.16**, Pillow **12.3.0**. Hardware identification
reported Intel64 Family 6 Model 183; no machine name was collected.

`scripts/benchmark_page_cache.py` measures an equivalent uncached call through
`PageAnalysisService`/`PageTranslationRenderService` with the same loaded engines,
then a first cache-populating request, repeat, translation refresh and rendering
refresh. A **separate Python process** reloads the persisted cache, proving that
neither service objects nor the RAM/artifact-fingerprint LRU survive the restart.
This is one sequential exploratory run, not a statistical speed/accuracy benchmark.
OS disk caches can remain warm and other local validation can affect latency.

| Sample | Uncached pipeline | First + cache writes | Exact repeat | New-process page reload | Translation refresh | Rendering refresh |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 1 | 9,355.5 ms | 9,974.4 ms | 164.8 ms | 1,246.3 ms | 3,789.3 ms | 811.5 ms |
| 2 | 2,417.5 ms | 2,576.6 ms | 99.2 ms | 152.8 ms | 696.9 ms | 332.1 ms |
| 3 | 4,927.2 ms | 5,162.6 ms | 127.3 ms | 228.2 ms | 1,487.2 ms | 587.9 ms |

These are observed per-call wall times, including stage-cache lookup/serialization,
but excluding browser acquisition, localhost transfer, PNG transport packing and model
initialization. Initial service setup took **11,352.9 ms** after Torch import, with
**760.9 ms** additional lazy detector setup. In the fresh Python process, service setup
took **9,442.2 ms**; total child process wall time was **13,914.0 ms**, including its
imports, image reads, model setup, all three reloads and report write. Sample 1's reload
also includes lazy detector construction and fresh identity work. Startup still loads
the existing selected resources; a cache hit is not a zero-startup backend.

Every exact repeat restored all expensive stages. Every fresh-process reload reported
**zero stage misses** and detection/OCR/translation/lexical inference times of zero
for the current job. Current wall/lookup time remains observed, rather than copying
historical inference times. Translation refresh reused extraction and lexical work;
rendering refresh reused the full analysis.

First, repeat, translation refresh, rendering refresh **and new-process reload output
pixels matched the uncached output exactly on all three pages**. Existing conservative
coverage was unchanged: rendered/preserved counts were 9/4, 1/1 and 2/3. No OCR ground
truth or new translation-quality assessment was performed, and these results do not
claim better text coverage or semantic accuracy.

After all three restored pages, backend RAM accounting was **3,443,252 bytes**
(approximately 3.28 MiB); SQLite size was **3,489,792 bytes** (approximately 3.33 MiB),
below the 64 MiB/512 MiB defaults. This measures cache ownership, not total model/process
memory. No cache eviction was needed for these three real pages; quota/eviction behavior
is demonstrated separately by storage tests and the synthetic large-browser fixture.

Reproduce with authorized local inputs, a **new empty** cache directory and **new**
JSON output path:

```powershell
$env:HF_HUB_OFFLINE = '1'
$env:TRANSFORMERS_OFFLINE = '1'
uv run --frozen python scripts/benchmark_page_cache.py samples/authorized-a.png samples/authorized-b.png `
  --cache-directory .cache/stage3/new-run --output .cache/stage3/new-run.json --threads 4
```

The script explicitly enables persistence in that isolated benchmark directory and
leaves it for local inspection. It never clears a pre-existing cache or overwrites
an input/dictionary/report. Reports contain anonymous counters/timings; intermediate
image fingerprints remain local and are not included in this published aggregate.

## Review and remaining limits

### Standards

Independent review identified mode/alpha identity, omitted extensionless UniDic config
and diagnostic references surviving result eviction. These were corrected and rechecked
in `18d38b3`. The remaining class-name/private-field dispatcher for known neural adapters
is a maintainability advisory, not a blocker; dictionary/tokenizer identities are
adapter-owned. New optional adapters must supply a verified effective identity or bypass.

### Spec

Independent review identified dictionary pathname/live-connection mismatch, malformed
SQLite payload types and alpha identity. All were corrected with regressions and
rechecked. Later validation also covers resolved optional CPU/CUDA identity and a
fresh-process cache reload. No remaining implementation blocker was reported.

The implementation retains model startup cost, conservative rendering limits and
existing reader/acquisition compatibility limits. Idle overlays detect backend changes
on Start/the next render, not by continuous polling. A first unloaded llama.cpp `auto`
selection bypasses reuse until its effective device is known. Loaded model/tokenizer
files are immutable for their instance lifetime; restart after changing them.
Cache storage is local, opt-in and unencrypted; it is not an archival/export system.
One backend owns a cache directory; multi-process shared-cache performance is unmeasured.
Disk journals and in-flight images/reports can temporarily exceed retained-byte figures.
No model manager, context system, new target language, release tag or Stage 4 work is included.
