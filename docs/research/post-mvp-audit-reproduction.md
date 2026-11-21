# Post-MVP audit — reproduction and evidence notes

Companion to [the integrated audit](post-mvp-full-application-audit.md), against
`178e506f8bc03ef541f4c4f8d60ecb44476f023a`, 21 November 2026.
These are validation instructions and synthetic examples, not implemented fixes.

## Repeat the supported suites

Use an isolated checkout/environment when repeating the baseline; do not reset an
existing working tree or replace user data. Python 3.13 and Node 22 were used. In
PowerShell at the repository root, ordinary tests can be isolated as follows:

```powershell
uv sync --frozen
$env:HF_HUB_OFFLINE = '1'
$env:TRANSFORMERS_OFFLINE = '1'
$env:HF_HOME = Join-Path $PWD '.cache/audit-repeat/empty-hf'
$env:YOMISCAN_DICTIONARY = Join-Path $PWD '.cache/audit-repeat/missing.sqlite3'
$env:YOMISCAN_GLOSSARY_DATABASE = Join-Path $PWD '.cache/audit-repeat/glossary.sqlite3'
$env:YOMISCAN_CACHE_DIRECTORY = Join-Path $PWD '.cache/audit-repeat/processing'
uv run --frozen pytest
uv run --frozen python -c "import sys; import yomiscan.api.main; import yomiscan.rendering.renderer; import yomiscan.translation.factory; assert 'torch' not in sys.modules"
```

In `extension/`, run `npm.cmd ci`, `npm.cmd test`, then `npm.cmd run build`.
For the existing browser fixture, use a fresh owned Chrome profile with remote
debugging and unsafe-extension-debugging enabled as documented in
[the existing browser instructions](../post-mvp-reliability-qol.md#ci-and-local-verification).
From the root, set `$env:YOMISCAN_TEST_CDP_PORT='9241'` to the owned profile's actual
port, then run:

```powershell
node extension/tests/browser-chapter.mjs --mock-backend
```

The audit observed 316 Python passes/one Windows skip, 68 Node passes and 37 browser
checks. The existing atomic replacement test skips on Windows because an open database
is locked. Linux hosted CI ran 317 tests. Do not turn mock-browser time into a model
throughput claim. Close only the profile/process started for the test.

Build and install checks, from a clean baseline checkout with dependencies prepared:

```powershell
python scripts/build_distribution.py --skip-tests --output .cache/audit-repeat/artifacts
uv run --frozen python scripts/validate_distribution.py --artifacts .cache/audit-repeat/artifacts --environment .cache/audit-repeat/package-installed
node scripts/validate_extension_package.mjs --extension .cache/audit-repeat/package-installed/unpacked-extension --report .cache/audit-repeat/package-chrome.json
```

`--skip-tests` here separates gates already run above; it is not an assertion that the
builder ran the suites itself. The ZIP validator owns/closes its own Chrome. Keep the
matching artifact manifest, tools/lock versions, clean/dirty source indicator and hashes.
The audit's standalone install smoke used locked cached runtime dependencies; testing
unconstrained wheel-range resolution is an identified remaining gate.

## Reproduce the browser findings without manga content

The targeted probes used a temporary CDP harness, a loopback mock API and a task-owned
extension copy/profile. That harness is not added to the product or ordinary test suite.
The committed [browser JSON](evidence/post-mvp-audit-browser.json) records observations;
the following specifies fixtures/steps for independent reproduction or future regression
tests. The existing browser fixture supplies ZIP packaging and Chrome messaging patterns.

Use an 800×1100 PNG filled with a solid color, a page with `body{margin:0}` and a main
element containing that image. For geometry tests, give the mock render bundle the same
PNG and a snapshot block B1 with source box `[100,100,300,250]`, rendered status and
invented Study text. No detector/OCR is required. Baseline fixture DTO validators must
still be satisfied; keep input byte hash/dimensions/result ownership consistent.

| Finding | Controlled steps | Baseline failure to observe |
| --- | --- | --- |
| AU-01, before capture | Start with red `(220,20,20)`; delay `chrome.tabs.captureVisibleTab` at its test-only native boundary by 1,000 ms. Select a rectangle; before capture, `history.pushState` to chapter B and replace pixels with blue `(20,20,220)` without scrolling/resizing. Release capture and inspect uploaded PNG's center. | Blue `[20,20,220,255]` is submitted even though the selection originated on red; popup appears. |
| AU-01, after capture | Permit capture; delay mock analyze-image response 1,400 ms, then pushState and replace page pixels before returning the original response. | Old result popup appears after reader replacement. |
| AU-02, independent rotation | Display at 600×825; apply `image.style.rotate='180deg'` while computed `transform` remains `none`. Enable Inspect Regions. | Target at `(75,75)` size `150×112.5`, while rotated B1 starts at `(375,637.5)`. |
| AU-02, object-fit | Display the natural 800×1100 source in a 400×550 CSS box; `object-fit:none;object-position:50% 50%`. | B1 is outside the visible source crop `[200,275,600,825]` but target appears at `(50,50)`, size `100×75`. |
| AU-03 | With translated overlay visible, set the containing main element's opacity to zero and allow observer/repaint cycles. | Overlay remains `display:block;opacity:1` with its translated source set. |
| AU-04 | Open a synthetic Study result; inspect Save to History's bounding/client/scroll dimensions. | Button `30×30`, client height 28, scroll height 148; label overflows. |
| AU-09 | Delay first readiness reply `initializing` 1,200 ms; allow second check to return `ready` immediately. | Old reply overwrites the newer ready display. |

Use runtime/response injection only in the owned harness. Do not modify an installed
normal extension or external website. The [popup screenshot](evidence/post-mvp-audit-synthetic-popup.png)
contains only the solid-blue fixture and invented text. Normal extension-version reload
via the experimental CDP route was inconclusive; reproduce updates through the documented
stable-folder process before claiming ordinary update behavior.

## Model-free adapter failure probes

The three observations below were run in the audit and are summarized in
[API evidence](evidence/post-mvp-audit-api.json). They require existing dependencies,
not Torch imports, model files or network. Run each in a fresh process using the locked
environment; keep generated files under a new ignored task directory.

AU-05: a synthetic tokenizer failure leaves diagnostic device set before the model
exists. This is the essential executable probe:

```python
import sys
from types import SimpleNamespace
from unittest.mock import patch
from yomiscan.analysis import TextAnalyzer
from yomiscan.service import ImageAnalysisService
from yomiscan.translation.base import TranslationInitializationError
from yomiscan.translation.nmt import NMTTranslationEngine

def unavailable(*args, **kwargs):
    raise OSError("synthetic unavailable tokenizer")

assert "torch" not in sys.modules
with patch.dict(sys.modules, {
    "torch": SimpleNamespace(cuda=SimpleNamespace(is_available=lambda: False)),
    "transformers": SimpleNamespace(
        AutoTokenizer=SimpleNamespace(from_pretrained=unavailable),
        AutoModelForSeq2SeqLM=object()),
}):
    engine = NMTTranslationEngine("fugumt", device="cpu", local_files_only=True)
    service = ImageAnalysisService(object(), TextAnalyzer(object(), object(), engine))
    try:
        engine.load()
    except TranslationInitializationError:
        pass
    else:
        raise AssertionError("synthetic failure expected")
    assert engine._model is None
    assert service.runtime_state()["translation"]["loaded"] is True
    service.close()
assert "torch" not in sys.modules
```

AU-06: the marker is synthetic; the monkeypatched transport makes no HTTP connection.
The assertion below records the current undesired behavior, not a desirable regression
expectation after a fix:

```python
from io import BytesIO, StringIO
import logging
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError
from yomiscan.analysis import TextAnalyzer
from yomiscan.translation.manga import LlamaServer, MangaTranslationEngine

runtime = LlamaServer(Path("unused.gguf"), executable=Path("unused.exe"), device="cpu")
runtime.url = "http://127.0.0.1:1"
marker = "AUDIT_SYNTHETIC_PRIVATE_PROMPT"
def reject(*args, **kwargs):
    raise HTTPError(runtime.url, 400, "Bad Request", {}, BytesIO(marker.encode()))
class Tokenizer:
    def tokenize(self, text): return []
class Dictionary:
    def lookup(self, text): return ()
stream = StringIO()
logger = logging.getLogger("yomiscan.analysis")
handler = logging.StreamHandler(stream)
logger.addHandler(handler)
try:
    with patch.object(runtime, "load", return_value=None), patch(
            "yomiscan.translation.manga.urlopen", reject):
        analyzer = TextAnalyzer(Tokenizer(), Dictionary(), MangaTranslationEngine("hy-mt2-manga", runtime))
        assert isinstance(analyzer.analyze_many(["猫"])[0], Exception)
finally:
    logger.removeHandler(handler)
assert runtime.record_debug is False
assert marker in stream.getvalue()
```

AU-07: create a separate tiny schema with `entries(entry_id,payload)`,
`forms(form,entry_id)` and `PRAGMA user_version=1`; no JMdict content is needed. With
patched environment selecting current engines and `YOMISCAN_DEVICE=bogus`, call
`open_local_service(tiny_dictionary_path, device="cpu")`. The current baseline raises
`SetupUnavailable` with code `invalid_configuration` before engine creation. The server
CLI's effective environment handling is a separate, working path; do not conflate them.

AU-08: reuse `resources()`/`page()` from `backend/tests/test_processing_cache.py` with
an isolated processing directory and persistence disabled. Wrap its fake OCR's
`recognize` to set a threading Event after the first call. Pass that Event as `cancel`
to `translate_and_render_page`. Baseline raises `StructuredTranslationError` code
`cancelled`, but the counter records two OCR calls. Check the counter, not elapsed
seconds, to make this deterministic without neural inference.

## Repeat bounded real inference measurements

Do not reuse the empty HF_HOME above for actual models. In a separate shell, point to
the already prepared pinned production cache, keep Hugging Face/Transformers offline,
select current OCR/detector/OPUS and CPU, and use a separate task glossary/processing
directory. Do not download alternatives or mutate a user's glossary/history. Only use
images you are authorized to evaluate; the audit's aliases/hashes identify private
local inputs without redistributing them.

Start a fresh owned server and time readiness from process creation. Request sequence:
Study crop → repeated crop → page A → exact A repeat → page B → A with
`refresh=translation` → A with `refresh=render&font_scale=1.25` → stop/restart the same
server configuration with the same task processing directory → A disk restore.
Request the existing render diagnostic bundle, parse counts/cache-stage observations/
timings and discard raw text/images from any shareable summary. Include the actual
client header, options, owned job ID and configuration version required by the API;
do not bypass its guards for timing.

Measure request wall time inside the request thread, separately from 800 ms status
polling. For Windows process memory/CPU, identify Uvicorn's application process, not
the virtualenv launcher; query working set/peak working set/process CPU time. Record
thread settings, CPU, OS, libraries and cache state. No VRAM estimate should be derived
from checkpoint size. Fresh process does not establish cold disk caches.

The published [measurement JSON](evidence/post-mvp-audit-measurements.json) retains
numeric counters, timings, stage-hit metadata and public model identities. Single-run
times are exploratory; further comparisons need repeated trials. A font candidate with
8 rendered regions must not replace an existing 9-region browser result: the real API
candidate and separately tested browser retention guard are distinct observations.

No raw authorized pages, OCR/model replies, browser URLs, user database files, private
filesystem paths or server logs are needed in the audit PR. Keep them local if needed
for authorized review, following the diagnostic privacy ADR.
