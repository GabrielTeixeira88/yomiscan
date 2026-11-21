# Post-MVP Stage 5: Reader Experience & Distribution

This increment implements P06/P10/P11/P12/P13 from the original comparison. It keeps
the MV3 extension, local FastAPI worker, original manga-ocr/PyTorch detector and
English OPUS defaults. Stage 4 glossary invalidation and experimental contracts remain.
See [validation](research/stage5-validation-results.md) and
[installation](installation.md) for tested commands and distribution boundaries.

## Translation font and region inspection — P10

Open **Translation font**, select 75%, 100%, 125% or 150%, then **Apply Font**.
**Reset Font** uses 100%. The API accepts finite scales 0.75–1.5. Preferences belong
to the current tab. Absolute 14–30 pixel safeguards remain, so 75% does not produce
text below the readable minimum. Layout wraps complete text without truncation,
expansion into artwork or bypassing mask/inpainting checks. Latin fallback fonts remain.

Applying a scale stops queued chapter work, waits for its owner to finish and submits
render-only refreshes for retained pages. Detection, OCR, dictionary tokens and valid
translations remain reusable. Old images stay visible until replacement succeeds.
Errors, cancellation, unavailable region identity or losing any previously rendered
block retain the old result and show a warning. Try a smaller scale or Reset Font.
Newly processed pages preserve original pixels when text cannot fit. Some pages can
therefore retain an older scale after a rejected refresh. Evicted pages need normal
reprocessing; the processing cache may supply earlier stages.

Choose a completed page and **Inspect Regions**. Temporary controls expose IDs and
actual diagnostic reasons: translated, OCR failed/filtered, translation/analysis
failed, overflow, unsafe mask/background, overlapping geometry, rendering errors and
deliberate SFX preservation. Unknown reasons stay unknown. Detector and OCR scores
are separately labeled uncalibrated; original manga-ocr has no OCR confidence. This
tool cannot identify missed, undetected text.

Text stays hidden until **Show Japanese and translation** is checked. **Study Bubble**
is another explicit text action. Scrolling remains available. Escape or Close
Inspection removes controls and returns focus. Coordinates follow scaling/scroll/
resize; borders, padding and transforms are rejected safely. Smaller overlapping hit
targets sit above larger ones; all remain keyboard-selectable. Source, dimensions,
page/result or navigation changes close inspection. It pins only the inspected result
and releases the pin on close. Missing/evicted/oversized snapshots explain reprocessing.
At most 256 retained regions are offered; no stale analysis attaches to another page.

## Setup and model readiness — P11

**Setup & readiness → Check Setup** is a local read-only probe available during
initialization/inference. It shows backend version, initializing/ready/failed/busy,
configured device, safe failure codes, JMdict/tokenizer, selected engines and an
expandable optional catalog. Unavailable-backend guidance explains `yomiscan-server`.

Rows include pinned identity/revision where known, licenses, target/structured/glossary
capabilities, dependencies, supported device modes, preparation commands and experimental
warnings. Artifact sizes are storage/download estimates, never RAM/VRAM estimates.
Installed files, integrity **not_checked** and currently loaded remain distinct.
Probes do not hash large files or certify contents. Catalog CPU/CUDA support does not
prove runtime compatibility; observed unsupported-device startup is reported. Parent
writability does not prove database integrity. Cache enabled state and glossary
open/not-open/unknown come from separate worker-published observations.

Model identifiers are validated by component kind. Readiness never imports Torch,
loads optional engines, starts llama.cpp, downloads weights or changes selection.
Normal server initialization now requires local pinned artifacts. Prepare explicitly:

```powershell
uv sync --frozen
uv run yomiscan-prepare-defaults
uv run yomiscan-import-jmdict <JMdict_e.xml.gz> --output data/jmdict.sqlite3
uv run yomiscan-server --device cpu
```

Replace the placeholder with a real dictionary path. Package/Windows/Linux commands
are in [installation](installation.md). Existing `YOMISCAN_OCR`, `YOMISCAN_DETECTOR`,
`YOMISCAN_TRANSLATION_ENGINE` and `YOMISCAN_DEVICE` still require restart. Optional
explicit commands are `yomiscan-prepare-vision` and `yomiscan-prepare-translation`;
source wrappers remain compatible. VNTL has no verified artifact at its documented pin.
NLLB is noncommercial; Fugu weights retain CC-BY-SA requirements. Portuguese/Brazilian
register and Spanish quality remain experimental. Strict-ID format correctness does
not establish accurate meaning. Graphical downloads, hot switching, a marketplace
and memory-fit predictions remain deferred.

## Actual stages and resources — P12

Current-page messages follow acquisition, known model initialization, detection,
OCR, ordering/lexical analysis, translation, rendering and finalization. Unknown
intervals say **Processing locally**. Cached stages say reused from cache. Mixed pages
retain computation/hit observations; failed attempts are not relabeled entirely cached.
There are no simulated percentages, completion estimates or additional scheduler.

Each render request gets a random UUID. Protected `GET /api/v1/jobs/{job_id}` returns
bounded text-free stage/state metadata, instance identity and increasing version.
Polling is every 800 ms while active, stopping on completion/cancellation. At most
16 server records are retained; terminal records expire after 30 seconds. Wrong jobs,
old versions and a restarted instance are ignored. Existing source/session checks
reject late results. Cancellation keeps worker ownership until work actually ends;
ordinary neural calls are not assumed immediately interruptible. HTTP errors remain
authoritative if optional polling fails.

**Processing details** shows actual retained-page cache provenance/timings and backend
cache RAM/disk bytes. Existing browser session usage retains its 128 MiB budget.
RSS, peak model RAM, allocated VRAM and system RAM are not measured or inferred.
Status contains no OCR, URLs, images or raw exceptions. There is no telemetry.

## Local history and Study Bubble — P13

History is **off by default**. Enable **Study history**, then use the popup's
**Save to History** for each desired sentence. Enabling alone records nothing.
Entries retain selected Japanese, actual sentence target/translation, existing
token/dictionary data, date/time and bounded allowlisted provenance. JMdict meanings
remain explicitly English. Glossaries never rewrite OCR.

Background-owned `chrome.storage.local` retains up to **100 entries / 2 MiB total**;
oldest entries are evicted at either limit. Entries above **128 KiB** are rejected.
Images, screenshots, source URLs, headers, paths and arbitrary extras are excluded.
The added MV3 `storage` permission supports history; Chrome Sync is unused. Browser
profile access remains a local-data boundary.

**Open** reuses the existing popup without OCR/translation. **Delete** removes one;
**Clear History** removes all entries. Disabling stops new saves while retaining
existing entries for access/export/deletion. **Export History** explicitly downloads
JSON; downloaded files remain where saved. Processing-cache clears do not clear
history/glossaries. Uninstalling removes Chrome-local data: export first and retain
the same stable unpacked folder/profile across updates.

**Inspect Regions → Study Bubble** reuses that exact block's OCR, lexical/dictionary
analysis and sentence translation in the existing popup. No screenshot/OCR/translation
request occurs. Original/English selection, copying, dragging/resizing and Escape
remain. Missing lexical data/evicted snapshots explain reprocessing. No flashcards,
vocabulary lists, Anki, spaced repetition or grading were added.

## Unsigned distributions — P06

The workflow supports pushes, pull requests and manual dispatch. Python 3.13 on
Windows/Linux and Node 22 gates precede an exact-commit distribution job producing:

- Version/commit-named unsigned MV3 ZIP: seven runtime files, MIT license and notices;
  no source maps, fixtures or signing keys.
- Backend wheel/sdist with bundled fonts/OFL notices and six command entry points.
- `INSTALLATION.md`, `THIRD-PARTY-NOTICES.md`, matching `uv.lock`,
  `artifact-manifest.json` and `SHA256SUMS`.

The manifest records commit, dirty flag, version/source epoch, platform/tool versions,
actual project-interpreter package versions, lock hashes, unsigned status, external
setup requirements and artifact hashes. Installation validation checks versions against
the lockfile. Run-associated artifacts retain 14 days; these are development builds.
Normal builds reject dirty source. `--allow-dirty` previews are marked; `--skip-tests`
requires completed external gates.

```powershell
python scripts/build_distribution.py --output .cache/distribution-new
uv run --frozen python scripts/validate_distribution.py --artifacts .cache/distribution-new --environment .cache/package-smoke-new
node scripts/validate_extension_package.mjs --extension .cache/package-smoke-new/unpacked-extension
```

Choose new output/environment directories. Chrome must already exist. Linux CI uses
runner Chrome with `--no-sandbox` only in that isolated runner. The validator starts/
closes its own profile. Python validation uses cached locked dependencies offline,
installs wheel and sdist, checks imports/fonts/CLI/version, and starts protected API
readiness with deliberately missing dictionary/models. It does not run inference or
download weights. Build dependencies are separate from model preparation.

Models, JMdict, samples, caches, glossaries and history are excluded. Checksums detect
corruption/mixing, not publisher identity. Same-host byte reproducibility is tested
separately; cross-OS identity is not promised. Signed installers, bundled all-model
environments, Web Store publishing, version tags and GitHub Releases are deferred.
Stage 1 reports retain metadata-only defaults and separate text/image consent; Study
reuse does not silently export dictionary details. Text exports can remain sensitive;
review reports/history before sharing and keep copyrighted/private pages out of Git.
