# Post-MVP Caching & Performance

P07 and P08 extend the existing MVP. Stage 2 was merged through PR #2 as
`7a7ece765c335df4d793c272b4b80a4f5353e07b`; this work starts from that merged main on
`feat/post-mvp-caching-performance`. No production detector, OCR or translator changed.

## Reader controls and privacy

The browser previously stopped admitting results once retained PNGs/snapshots reached
128 MiB. It now evicts least recently used eligible results and continues through the
chapter. Visible pages, queued/active refreshes and exact results pinned for exports
are protected. Overlays detach/switch obsolete URLs before they are revoked. Decoded
bitmaps still release their `src` outside the nearby viewport range.

PNG Blob sizes, original report Blob sizes and estimated serialized metadata belong
to one result and one budget entry. Successful contexts have no second WeakMap owner.
Up to three failed-job contexts share a reserved 256 KiB inside the 128 MiB total.
Small page records and the site's DOM/images are not an exact JavaScript heap/RSS
measurement. Acquisition/transport have existing 10 MiB input and 32 MiB PNG limits;
one active report/download has a separate 48 MiB ZIP limit and a one-second URL lease.
These transient buffers and models are not part of the retained-result byte budget.

An evicted page is marked in the page selector and reloads through the normal serial
queue when it enters the viewport and can fit. Eviction itself never enqueues work.
Failed reloads become explicit failures for Retry; oversized pages skip with a reason.
If protected results fill the budget, distant new results wait in the evicted state.
Scroll after releasing an export/protected page to retry admission. Clear/navigation,
source revisions and late cancelled jobs cannot resurrect released results.

Expand **Local processing cache** in the chapter controls:

- **Save page processing on disk (pixels and text)** is unchecked by default. This
  explicitly permits retaining processed manga pixels, Japanese, lexical data and
  English locally. It is separate from diagnostic-export inclusion consent.
- **Refresh Cache Usage** shows approximate database and backend RAM bytes.
- **Clear Persistent Cache** removes backend disk entries and its RAM entries. It
  keeps the persistence preference and existing browser overlays.
- **Clear Session** releases browser overlays/results and failed reports. It does
  not delete backend RAM/disk entries or saved user downloads.
- Disabling persistence closes result storage and drops backend RAM entries; disk
  entries remain until cleared. Enabled storage applies to subsequent requests.

No synchronization, telemetry, uploads, source URL, title, cookie, request header or
browsing metadata is stored. Disk entries nevertheless contain private/copyrighted
content: protect the local directory. POSIX creation uses private directory/file
modes; Windows inherits the user's directory ACL. Storage is not encrypted. Model
metadata is allowlisted before persistence; GGUF/LoRA paths are not saved as metadata.
Diagnostic reports remain metadata-only unless text/images are explicitly selected.

## Local storage, settings and limits

Default storage, relative to the backend's working directory:

```text
.cache/processing/
  settings.json      # consent and disk quota only
  stages.sqlite3     # metadata + checksummed JSON/PNG BLOBs
```

The directory, SQLite files and local outputs are ignored by Git. Set the server-only
`YOMISCAN_CACHE_DIRECTORY` environment variable before startup to use another local
private directory. There is no browser-selectable path or arbitrary file endpoint.

The RAM LRU defaults to 64 MiB including payload/key/entry accounting. SQLite defaults
to 512 MiB; its configurable quota accepts 1 MiB–16 GiB. A single byte entry cannot
exceed 48 MiB or fit beyond its disk quota. LRU trimming includes payload and index
overhead and checks actual database size. SQLite FULL auto-vacuum returns freed pages.
Transaction journals can temporarily use additional bounded space during publication;
these are not a second permanent artifact store. A shared directory is intended for
one backend process, not multiple independently configured servers.

Cache metadata and payload publish together in SQLite transactions. There are no
external artifact files, pickle, engine instances or image paths to deserialize.
Checksums, payload types and typed JSON/PNG validation catch damaged entries. Invalid
entries are deleted/recomputed; missing databases are recreated; malformed/unsupported
database schemas rebuild the application-owned cache. A locked/read-only/unavailable
store falls back to RAM/ordinary processing and records a safe error code. Disk full
or interrupted transactions do not advertise partially committed entries. Clear only
deletes the cache's fixed owned filenames and never traverses unrelated files.
Settings use a flushed temporary JSON file and atomic replace. Close releases RAM and
the SQLite handle on the owning worker, including Windows shutdown.

The localhost controls are available without the extension:

```powershell
$headers = @{ 'X-YomiScan-Client' = 'study-extension-v1' }
Invoke-RestMethod http://127.0.0.1:8765/api/v1/cache
Invoke-RestMethod http://127.0.0.1:8765/api/v1/cache/settings -Method Post -Headers $headers `
  -ContentType application/json -Body '{"enabled":true,"disk_bytes":536870912}'
Invoke-RestMethod http://127.0.0.1:8765/api/v1/cache/clear -Method Post -Headers $headers
```

Settings reject unknown fields, coercions, invalid quotas and bodies over 1 KiB.
Existing localhost Host/origin/client-header protection applies. Controls receive 429
while inference owns the single worker. The client header is a browser-origin guard,
not an authentication secret; keep the server bound to loopback.

## Stage identity and reuse

`pixel_identity()` hashes normalized decoded colors, dimensions, source mode and a
normalization version. Alpha and palette colors matter for library callers. HTTP
decoding still applies EXIF transpose and converts to RGB. Exact re-encoding is eligible
for reuse; resolution changes or different pixels are not. Stage 1 `input_sha256` still
hashes uploaded bytes; its historical `pixel_sha256` also remains unchanged. The new
`canonical_pixels` field explicitly identifies the stage-cache contract.

| Stage | Effective key inputs |
| --- | --- |
| Detection/grouping | Canonical image; verified loaded artifact; detector thresholds/preprocessing/runtime; minimum side; grouping and reading-order implementation |
| Crop OCR | Detection lineage, ordered block ID, exact padded crop geometry/pixels; loaded OCR artifact; preprocessing; decoding/generation/KV/thread configuration and implementation |
| Lexical | Exact Japanese; loaded UniDic files including `dicrc`/`mecabrc`, tokenizer/runtime versions; connected JMdict file/WAL content and schema; analysis implementation |
| Translation | Exact ordered Japanese and block IDs/OCR lineage; effective artifact/runtime/generation/prompt implementation; English target; ordered native batch contract and current empty-context/glossary behavior |
| Rendering | Image/mode/alpha; geometry/status/OCR/translation inputs and lineage; mask/inpainting/layout versions/settings; bundled font artifact and size settings; runtime versions |

Ordinary OPUS batching and its known per-block retry behavior remain unchanged. Cached
translation batches preserve order/cardinality; they do not become unrelated individual
calls. Lexical entries contain no sentence translation. Rendering excludes unused
dictionary meanings/tokens so dictionary updates do not force a visual rerender.

Known adapters hash actual local artifacts; declared/sanitized diagnostic model names
are insufficient. Optional ONNX/Transformers experiments use their verified artifacts.
Unverified injected sessions and engines without an effective identity bypass reuse.
LLM identities include GGUF, LoRA, executable/shared-library hashes, runtime context,
prompt code and generation parameters. Unconfigured VNTL cannot obtain a guessed key.
An unloaded llama.cpp `auto` device also bypasses reuse until its actual CPU/CUDA
selection is known; explicit CPU permits a cache read before loading the model.
No model download is performed to compute an identity. Loaded model/tokenizer artifacts
are immutable for their lifetime; recreate the backend after replacing model/UniDic
files. Dictionary replacement reopens the connected file where supported. On Windows,
stop the backend before reimporting its locked JMdict file. Publication checks dictionary
identity again so a detected update during lexical work does not poison an old key.

| Request/change | Restored | Recomputed |
| --- | --- | --- |
| Exact same page/settings | All valid stages | Lookup, decoding/validation and response packing |
| Backend restart, persistence enabled | All valid persisted stages | Model startup/lazy detector construction, lookup/response work |
| Translation model/settings | Detection, OCR, lexical | Native translation batch and rendering |
| OCR weights/preprocessing | Detection, unchanged lexical text | OCR, dependent translation and rendering |
| Detector thresholds/artifact | Unchanged lexical text | Detection/grouping, OCR and dependent translation/rendering |
| Font/layout settings | Detection, OCR, lexical, translation | Rendering |
| JMdict/tokenizer update | Detection, OCR, translation, identical render | Lexical analysis |
| Retranslate Page / `refresh=translation` | Detection, OCR, lexical | Translation and rendering |
| `refresh=render` | Analysis stages | Rendering |
| `refresh=all` | Nothing | All stages |

Force-refresh failures return an error to the existing chapter queue, which preserves
the old successful visible result. Failed translation batches and runtime-failed renders
do not overwrite good entries. Intentional conservative skips remain legitimate cached
outputs; caching does not improve detection/OCR/translation accuracy.

Backend session generations/configuration IDs invalidate browser results on Start or
the next render when settings/backend change. A mismatch rejects the job and disposes
obsolete overlays. An idle page does not continuously poll for backend changes. A legacy
backend gets a fresh browser generation on every Start. Persistent stage keys remain
usable across backend session generations.
The modern health response publishes its generation in an additive header without
waiting for inference or cache administration, so Start/Retry during a busy job does
not mistake a 429 from cache controls for changed output settings.

## Diagnostics and validation

Snapshots retain region→block→OCR→translation→render lineage on hits and misses.
Cache provenance includes schema, safe key digests, memory/disk/eviction counters,
refresh choice, each stage's source (`memory`, `disk`, `miss`, `refresh`, `unidentified`
or `corrupt`) and observed lookup/compute times. Restored inference fields are zero
for the current request; old inference latency is not presented as work just performed
or an invented estimate of time saved. Pipeline total includes extraction and rendering.
Reports allowlist this metadata plus current browser memory statistics.

Model-free tests count real interface calls across repeated requests, new service
instances, changed models/settings/inputs, lexical-only invalidation, forced refresh,
failed refresh retention, typed/checksum corruption, missing storage, rollback, quotas,
consent, clear, shutdown and owning-thread protection. Optional vision configuration
tests load no weights. Browser tests exercise actual large PNG payloads, overlays,
source/navigation races, exports, cache controls and configuration generations. See
[measured validation and limits](research/stage3-caching-performance-results.md).

Historical Phase 1–7 and Stage 1–2 reports remain intact. Study Mode's existing crop
analysis path is unchanged; these stage caches apply to page analysis/rendering.
No model manager, cloud service, narrative context, new language or release tag is added.
