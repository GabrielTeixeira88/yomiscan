# Install an unsigned YomiScan build

Stage 5 produces development artifacts, not a Chrome Web Store package, signed
installer or public release. Download a matching extension ZIP, backend wheel,
`artifact-manifest.json`, `SHA256SUMS`, notices and this guide from one successful
workflow run. The manifest identifies the exact commit and whether its source was
dirty; use clean builds for distribution. Do not mix backend/extension generations.

## Verify the download

Compare SHA-256 against `SHA256SUMS` before installation. Windows PowerShell:

```powershell
Get-FileHash .\yomiscan-0.1.0-py3-none-any.whl -Algorithm SHA256
Get-FileHash .\yomiscan-extension-*.zip -Algorithm SHA256
```

Linux, from the downloaded artifact directory:

```sh
sha256sum --check SHA256SUMS
```

Checksums detect mismatched/corrupt downloads; these unsigned artifacts do not provide
a publisher signature. Keep bundled MIT, dependency and font notices. Models and
dictionary data retain their own licenses and require separate preparation.

## Windows / Python 3.13

Install Python 3.13 and uv. Create an application environment and a separate working
directory for user data; do not put user data in the installed package directory.

```powershell
uv venv .venv --python 3.13
uv pip install --python .venv\Scripts\python.exe .\yomiscan-0.1.0-py3-none-any.whl
New-Item -ItemType Directory -Path yomiscan-data -Force
Set-Location yomiscan-data
..\.venv\Scripts\yomiscan-prepare-defaults.exe
..\.venv\Scripts\yomiscan-import-jmdict.exe <JMdict_e.xml.gz> --output data/jmdict.sqlite3
..\.venv\Scripts\yomiscan-server.exe --device cpu
```

Replace `<JMdict_e.xml.gz>` with the actual downloaded official dictionary path; do
not paste angle brackets into PowerShell. Obtain JMdict from
[EDRDG](https://www.edrdg.org/jmdict/j_jmdict.html), retaining its attribution/license.
The preparation command explicitly downloads only the pinned production OCR,
detector and English translator. Readiness and normal API use do not download weights.
You can prepare one artifact group with `--component ocr`, `detection` or `translation`.

## Linux / Python 3.13

```sh
uv venv .venv --python 3.13
uv pip install --python .venv/bin/python ./yomiscan-0.1.0-py3-none-any.whl
mkdir -p yomiscan-data
cd yomiscan-data
../.venv/bin/yomiscan-prepare-defaults
../.venv/bin/yomiscan-import-jmdict /path/to/JMdict_e.xml.gz --output data/jmdict.sqlite3
../.venv/bin/yomiscan-server --device cpu
```

The wheel's metadata declares compatible dependency ranges. For the exact tested
dependency environment, use the matching source checkout and lockfile instead:
`uv sync --frozen`, then `uv run yomiscan-server`. The workflow installs locked
dependencies. The wheel itself excludes development tests and models. A source archive
includes package/setup scripts/docs/lockfile and can be installed with uv as well.

CPU is the portable starting point. CUDA requires a separately compatible PyTorch
build, driver and hardware; the app reports unsupported requests rather than silently
switching. llama.cpp has its own runtime/device support. Its experimental setup is
documented separately; no runtime or optional weights are included in these artifacts.

## Load Chrome and verify readiness

Extract the extension ZIP to a stable folder. Open `chrome://extensions`, enable
Developer mode and choose **Load unpacked**, selecting the folder containing
`manifest.json`. Use an ordinary manga-reader tab, activate YomiScan, then open
**Setup & readiness → Check Setup**. The server binds only to `127.0.0.1`, on port 47615 by default (`--port` changes it; set the same port in **Setup & readiness**).
The MV3 package keeps settings, saved words and known words in local extension storage; it
does not use Chrome Sync. The extension ZIP is the Chrome Web Store package
(`extension/package.mjs`), so it includes the browser engine's runtimes, the icons and the
license notices. Missing resources are reported with preparation/import commands.

Study Mode: choose Select Text, drag over Japanese, then use the existing readings,
dictionary and copy controls. Chapter mode: choose Translate Chapter on a supported
image reader; switch Original/English reversibly. Image-host access is requested only
when needed, with the existing screenshot alternatives. Site compatibility remains
limited; this is not a universal reader adapter.

Translation font changes rerender retained pages without forcing retranslation.
Inspect Regions exposes reasons and optional text; Study Bubble opens retained
analysis. History is off by default. Enabling it permits the popup's explicit Save
action; no arbitrary page, screenshot or source URL is automatically stored.

## Offline operation and recovery

After explicit model preparation, dictionary import and dependency installation,
the app runs locally. Test offline with the prepared files before removing network
access. If setup fails, keep the backend running to inspect readiness; correct the
missing resource/device and restart. Readiness distinguishes installed files from
loaded models and does not certify unverified files by name. Full model download UI,
live model switching, signed installers and Web Store publishing remain deferred.

Existing optional adapters use the packaged `yomiscan-prepare-vision` and
`yomiscan-prepare-translation` commands, preserving their explicit pinned preparation
contracts. Model selection still uses `YOMISCAN_OCR`, `YOMISCAN_DETECTOR` and
`YOMISCAN_TRANSLATION_ENGINE` followed by a restart. Keep experimental warnings;
NLLB is noncommercial and generic Portuguese does not establish Brazilian quality.

## Update, data retention and uninstall

Install a matching wheel/extension build while retaining the separate working
directory and the same stable unpacked-extension folder. Stop the backend first.
For development builds that still share version `0.1.0`, pass `--reinstall` to
`uv pip install --python <application-python> --reinstall <matching-wheel>`; a version
match alone does not select a newer commit. Reload the unpacked extension in Chrome.
Back up `data/glossaries.sqlite3` deliberately; do not replace it with an installer
template. Saved words, sentences and known words belong to that extension identity/profile:
use **Back up all** on the Saved page before removing/reinstalling the extension or changing
its folder/ID, then **Restore backup**.

- `.cache/processing`: disposable opt-in page processing; clear in the app.
- `data/glossaries.sqlite3`: user terminology; delete entries/series explicitly.
- Saved words, sentences and known words (Stage 6, the extension's IndexedDB): only what you
  save or mark; the Saved page searches, exports, backs up and deletes them.
- Hugging Face/model directories: separately downloaded weights; not user terminology.
- `.venv` and unpacked extension folder: installed application files.

Uninstalling the extension removes its local storage. Back up saved items first if wanted.
Remove the application environment and extension folder after stopping the app.
Delete user data/model caches separately only if you intend to erase them; an app
update or processing-cache clear must not perform that deletion automatically.
