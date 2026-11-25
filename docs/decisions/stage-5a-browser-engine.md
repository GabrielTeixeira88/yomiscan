# Stage 5a: browser-first engine

Status: **in progress**. Increments 1–4 are done; increment 5 is built and measured, but publishing
the models and the memory decision below are still open. Follows the [Stage 2 results](stage-2-results.md),
where every hard gate passed and the owner chose browser-first even when it is slower or
CPU-only. The Python backend stays available as the optional "local engine" (GPU, Hy-MT2).

## Goal

A Chrome user installs the extension, explicitly downloads pinned models once, and can
study and read manga with no Python, no server and no account. Everything runs on the
device: WebGPU when available, multi-threaded WASM otherwise.

## Increments

Each increment is merged only with its tests and a real-model measurement.

| # | Scope | Status |
|---|---|---|
| 1 | **Engine foundation and vision.** Cross-origin isolated offscreen document running ONNX Runtime Web 1.31.1. Pinned artifact manifest, verified install into Cache Storage, a Setup section. Detector, production grouping/ordering and greedy manga-ocr ported to TypeScript, plus a parity harness against the backend. | Done (see measurements) |
| 2 | **Lexical engine.** lindera-wasm-unidic tokenizer and JMdict SQLite (sqlite-wasm). TypeScript ports of the ranking rules plus the Stage 3 data files (`units.json`, `grammar.json`, `inflections.json`). The lexical golden set is run against the browser engine (target: the Python 96.7%). | Done (see measurements) |
| 3 | **Translation.** OPUS-MT fp16 with transformers-exact beam search (Stage 2: 99/100 lines identical to Python). The Chrome Translator stays optional and experimental. | Done (see measurements) |
| 4 | **Integration.** An engine setting (Browser / Local backend). Study selection, Read Chapter and the edit-text re-analysis run through the browser engine. English in browser mode is HTML text boxes over the page; the pixel renderer stays in the local engine. | Done (see measurements) |
| 5 | **Release readiness.** First-run onboarding with sizes and consent, storage-pressure handling, laptop measurements (integrated GPU, 4-core CPU, 8 GB), and docs. | Built; **full-stack memory misses G8** (see increment 5) |

## Architecture (increment 1)

- **Runtime.** The offscreen document hosts `BrowserEngine` (`extension/src/engine/`). The
  extension is cross-origin isolated (`cross_origin_embedder_policy: require-corp`,
  `cross_origin_opener_policy: same-origin`), so WASM can use threads. The CSP adds only
  `'wasm-unsafe-eval'`. The ONNX Runtime bundles ship in `dist/ort/`, about 42 MB: the
  plain threaded build for CPU and the asyncify build for WebGPU. They are imported at
  runtime and only when the engine is used.
- **Device path.** WebGPU uses q4 OCR, CPU uses int8 OCR (int8 is 10× slower on WebGPU),
  and both use the fp16 detector. One OCR variant is downloaded per device. The detector
  is 82 MiB; q4 OCR is 88 MiB and int8 OCR is 111 MiB.
- **Artifacts.** `scripts/build_browser_artifacts.py` packages the Stage 2 exports and writes
  `extension/src/engine/artifact-manifest.json` (path, size and SHA-256 per file), which
  is committed. Installation is an explicit click. Each file is streamed, its size and
  SHA-256 are checked, and it is stored in Cache Storage under its hash, never its URL, so
  a host can move files but cannot swap them. `unlimitedStorage` keeps them from being
  evicted. Removal is one click.
- **Vision.** `engine/geometry.ts` is a line-for-line port of `page_layout.py`,
  `PageAnalysisService._detect` and the "bands" page order. `engine/vision-models.ts`
  holds the validated Stage 2 ports: PIL-exact resizing, RT-DETR post-processing, and
  greedy manga-ocr with its post-processing. `engine/vision.ts` crops each block with 4 px
  padding and applies the backend's Japanese-script filter.
- **Boundary.** Only the extension's own service worker can drive the engine. Content
  scripts can ask for status, install, cancel and remove; they cannot run recognition yet.

## Increment 1 measurements (2026-11-24)

These come from `extension/tests/browser-engine.mjs`: the real extension build, models
installed through the verified store from the local artifact server, and 10 owner-supplied
sample pages (94 text blocks). Each page is compared with the running Python backend's
`analyze-page` (PyTorch detector fp32, manga-ocr greedy). Development PC (i7-14700K,
RTX 4070 SUPER), headed Chrome 157. Laptop numbers are still missing.

| Path | Blocks matched (IoU ≥ 0.5) | Same order | Identical text | CER vs Python | Median page (after first) | First page incl. model load |
|---|---|---|---|---:|---:|---:|
| WebGPU (q4 OCR, fp16 detector) | 94 / 94 | 10 / 10 pages | 88 / 94 | 0.82% | 1.4 s | 7.2 s |
| CPU, WASM ×8 (int8 OCR, fp16 detector) | 94 / 94 | 10 / 10 pages | **94 / 94** | **0.00%** | 2.3 s | 3.9 s |

The CER column is the difference from the backend's output, not accuracy against ground
truth. q4's small drift matches Stage 2, where q4 measured 1.81% CER against ground truth
and fp32 1.61%. Install from loopback took 0.5–1.2 s. Cross-origin isolation was
confirmed (`crossOriginIsolated`, 8 threads). With isolation on, the mocked reader fixture
still passed its cross-origin, cookie-bearing image acquisition. Its intermittent failures
are in report downloads and also occur on `main`.

The real run also caught one bug that the unit tests could not: the default `fetch` was
stored as a method, which Chrome rejects ("Illegal invocation").

## Increment 2: lexical engine

**Design.** `engine/lexical.ts` is a direct port of `analysis.py` (lookup candidates and
`_analyze_lexical`), `lexical_ranking.py`, `lexical_units.py`, `grammar_patterns.py` and
`inflection.py`. The rule data is not copied: the bundle imports the backend's own JSON from
`backend/yomiscan/resources/lexical/`, so the two engines cannot drift apart.
`engine/lexicon.ts` contains three adapters:
- JMdict: the backend's own SQLite file, opened in memory and read-only with sqlite-wasm
  3.54.1 (`sqlite3_deserialize`), with the same query and `hiragana` key.
- lindera-wasm-unidic 2.1.0: its tokens are mapped to `JapaneseToken` as validated in Stage 2.
- The Study `Analysis` response, which the popup already renders.

Two new artifact components join the verified store: the tokenizer WASM (51.6 MiB, UniDic
embedded; it must match the bundled JS glue from the same pinned npm package) and JMdict
(119.3 MiB, CC BY-SA 4.0, attribution in the popup). sqlite-wasm itself is 0.9 MB and
ships in `dist/sqlite/`. A device downloads about 340–365 MiB uncompressed in total. The
1 GB budget still holds, and Stage 2 measured about 235–245 MB gzip without translation.

**Port parity, golden set (Node, `extension/tests/lexical-parity.ts` +
`scripts/compare_browser_lexical.py`).** The browser's lindera tokens were replayed through
the unchanged Python `TextAnalyzer` on the same database. **60 / 60 golden sentences were
identical**: lookup forms, ranked entry IDs, inflection labels, units and grammar notes.
Golden-set score with the browser stack: **147 / 152 (96.7%)**, the same as the backend
with fugashi + UniDic-lite. All 60 sentences took 123 ms in Node.

**Real browser (WebGPU run, 10 sample pages).** For the 86 blocks that both engines read
identically, browser analysis was compared with the backend's `analyze-page` analysis.
Token segmentation was identical on 86 / 86, units on 86 / 86 and grammar notes on 86 / 86.
Dictionary form plus first entry matched on 81 / 86. All 5 differences come from the
tokenizer data, not the port: lindera's full UniDic and UniDic-lite give different lemma
data for 何 (なに / なん) and full-width digits. The first analysis took 1.4 s, while the
tokenizer and dictionary loaded; after that the median was 6 ms per block.

**Not yet measured:** memory with the dictionary and tokenizer loaded alongside the vision
models (G8 was measured for vision only). An OPFS-backed database would avoid holding the
119 MiB copy in the WASM heap if memory turns out to be tight.

## Increment 3: translation

**Design.** `engine/translation.ts` contains the Stage 2 transformers-exact beam search and
the OPUS-MT decoder, which reuses its key/value cache and reorders it by parent beam. It is
configured exactly as `MarianTranslationEngine`:
- whitespace collapsed;
- no truncation, so an input over 512 tokens is an error;
- 4 beams, length penalty 1, no early stopping, at most 511 new tokens;
- pad token banned and logits renormalized;
- output without an end token is an error, and the output is stripped.

The Marian tokenizer comes from `@huggingface/tokenizers` 0.2.0 (Apache-2.0, 36 KB). It is
the standalone package that Transformers.js 4.3.2 uses, so Transformers.js and its second
ONNX Runtime are not bundled. The model is the Xenova fp16 export (210.4 MiB, CC-BY-4.0),
the sixth pinned component. It always runs on WASM threads: Stage 2 found WebGPU slower for
this decoder and less exact. A full install is now about 550–575 MiB uncompressed, within
the 1 GB budget.

**Real browser, 10 sample pages.** Each block that both engines read identically was
translated in Chrome and compared with the backend's own OPUS output for that block:

| Path | Lines compared | Identical to backend | First line (incl. model load) | Median / p95 per line |
|---|---:|---:|---:|---:|
| WebGPU bundle (OPUS on WASM ×8) | 86 | **86** | 1.7 s | 0.57 / 1.10 s |
| CPU, WASM ×8 | 92 | **89** | 1.6 s | 0.54 / 1.11 s |

The 3 differing lines are among the 6 that only the CPU path read identically. All three are
weak OPUS outputs on hard input: a quoted letter, stretched kana, mismatched brackets. They
differ because the backend runs fp32 in a padded page batch while the browser runs fp16 one
line at a time. Neither engine's version is clearly better. This matches Stage 2's 99/100.
OPUS remains the default because its quality limits are known. The engine choice and the
optional Chrome Translator are unchanged.

## Increment 4: integration

**Setting.** Advanced → Browser engine (preview) → "Engine for Study and reading", either
Local backend or Browser engine, stored as `engineMode` in `chrome.storage.local`. **Local
stays the default** until increment 5 adds first-run model download; a fresh install has no
browser models. Changing it clears the running chapter session.

**With the browser engine selected:**
- **Select Text:** the service worker sends the crop to the engine (`study`). That ports
  `ImageAnalysisService.analyze_image`: with two or more detected blocks, each padded
  block is read in reading order and the results are combined as `analyze_recognized_blocks`
  does; otherwise the whole selection is read.
- **Edit text:** re-analysis uses the engine's `analyze-text` with translation.
- **Read Chapter:** the page port gains a `browser` kind. The engine returns the same JSON as
  `/api/v1/analyze-page`, so the reading layer, J/K and study cards are unchanged. The
  backend health check, glossary profile and configuration identity are skipped; the engine's
  installed models are checked instead.
- **English:** each page's English button draws the block translations as HTML text boxes
  over the bubbles. Each box is fitted to the largest font from 7 to 26 px and may widen to
  2.5× the detected column (vertical Japanese columns are narrow) to stay readable.
  Bubbles stay clickable through the boxes.
- **Translate Chapter:** reads pages and shows their English at once. The pixel renderer
  stays with the local backend.
- **Popup:** shows "Processed by the browser engine in Chrome". Translation targets other
  than English, glossaries and structured contracts remain backend features.

**End to end, real Chrome, backend stopped.** `extension/tests/browser-engine-e2e.mjs`
serves three sample pages as a reader and drives the real UI:

| Check | Result |
|---|---|
| Read Chapter, 3 pages, including first model load | 14.4–14.8 s, 0 failed |
| J → first study card (from retained analysis) | 49 ms |
| English toggle | 5 text boxes, all fit, 15.6–23 px (median 21 px) |
| Select Text over a page's top half | 5 blocks read separately, 5.5–5.6 s |
| Translate Chapter (models warm) | English on every read page, 12 s for 3 pages |

The local-backend paths are unchanged: the mocked reader fixture passed. A visual check of
the overlay showed readable English inside the bubbles, after whole-word wrapping replaced
mid-word breaks. One title block showed OPUS's literal `&gt;&gt;Hugo Barra…` hallucination,
which the Python backend produces identically. It is a model limitation, not part of the port.

## Increment 5: release readiness

**Hosting (owner decision, 2026-11-24): Hugging Face.** `scripts/build_browser_artifacts.py`
now adds a model card (`packaging/browser-models/README.md`, with a generated component table)
and the license texts (Apache-2.0, UniDic BSD-3-Clause, lindera MIT) to the artifact folder.
JMdict is credited to EDRDG under CC BY-SA 4.0, as its licence requires.
`scripts/publish_browser_artifacts.py --repo <owner>/yomiscan-browser-models` uploads the folder,
downloads every pinned file back through the public URL and checks its size and SHA-256.
Only after that does it write `extension/src/engine/artifact-host.json`, so the extension's
default source is an immutable `resolve/<commit>/` URL. Hugging Face sends CORS headers on both
the resolve URL and its CDN redirect, which the cross-origin isolated engine page needs. The OPUS
license label was corrected to Apache-2.0, as its model card declares; no file hash changed.

**Engine choice.** The stored setting is **Automatic** unless the user picks one:
1. the browser engine, once its models are installed;
2. otherwise the local backend, if it answers `/health` within 1.5 s;
3. otherwise first-run setup.

An explicit Local choice is never second-guessed. With an explicit Browser choice and no models,
setup is shown. An existing backend user therefore sees no change until they choose to download.

**First-run setup.** Clicking the toolbar icon, Read Chapter, Translate Chapter or Select Text
with no usable engine shows a card at the top of the panel. It gives the download size for this
device (e.g. 579 MB on WebGPU, 603 MB on CPU), the host, the fingerprint check, the licenses and
how to remove the models later, with **Download** and **Not now** buttons. Nothing is fetched
before the click. Progress shows the component and MB. Cancel and Try again resume from the
files that finished. If installed models later disappear (Chrome clearing data), the card says
so ("Download the reading models again") instead of looking like a first run.

**Storage pressure.**
- Before any download, the engine compares the missing bytes plus a 256 MiB margin with
  `navigator.storage.estimate()`. If they don't fit, it refuses and says how many MB to free.
- A `QuotaExceededError` while saving names the file and keeps the finished ones.
- `unlimitedStorage` is what protects the models. `navigator.storage.persist()` is requested
  but returned false in the offscreen document without a user gesture.
- Advanced → Browser engine shows the storage used and the space available.

**End to end** (`extension/tests/first-run-e2e.mjs`: real Chrome, backend stopped, storage
cleared, three sample pages; the loopback server stood in for Hugging Face until the upload):

| Check | WebGPU, 8 threads | CPU (`--disable-gpu`), 4 threads emulated |
|---|---|---|
| Offer before any byte is fetched | 579 MB | 603 MB |
| Not now, then Read Chapter | Card shown again, nothing downloaded | Same |
| Download from loopback (verify + store) | 4.5 s | 2.2 s |
| Automatic → Read Chapter, 3 pages incl. model load | 23.5–24.4 s | 34.9–37.1 s |
| Cache Storage after install | 552 MiB | 575 MiB |
| Models removed behind the extension's back | "Download the reading models again", reinstalled in 3.7 s | 3.8 s |

The CPU column caps WASM at 4 threads on the development CPU, so it is an upper bound for a
4-core laptop, not a laptop measurement. Real-download time from Hugging Face is measured after
the upload. No integrated-GPU or 8 GB machine was available.

### Memory: the full stack misses G8

Stage 2's hard gate G8 (offscreen peak ≤ 1.5 GB) was measured with vision only. With every
model loaded, the extension renderer's Windows private bytes are well above it:

| Step (fresh engine page) | Extension process, CPU path | Extension process, WebGPU path |
|---|---:|---:|
| Empty engine page | 94 MiB | 311 MiB |
| + lexical (lindera UniDic + JMdict) | 942 MiB | 968 MiB |
| + OPUS translator | 2,086 MiB | 2,146 MiB |
| + vision (detector + OCR, one page) | 1,955 MiB | 2,026 MiB |

On WebGPU, Chrome's GPU process also grows by about 0.5 GB with vision. In Node with the same
packages, lindera's tokenizer holds about 430 MB once UniDic is unpacked, and JMdict about
120 MB in the sqlite heap plus a transient copy. OPUS alone, measured in the engine page with
4 threads:

| OPUS variant | Extension process | 20 decoder steps (beam 4 input) |
|---|---:|---:|
| fp16, optimization `all` (shipped) | 1,269 MiB | 1.15 s |
| fp16, optimization `basic` | 1,145 MiB | 1.15 s |
| fp16, optimization `disabled` | 927 MiB | 1.51 s |
| fp32 | 1,794 MiB | 0.46 s |
| int8 quantized | 637 MiB | 0.78 s |

`enableCpuMemArena: false` changed nothing. No single setting brings the stack under 1.5 GB.
Candidates for a memory increment:
- int8 OPUS with beam search. It needs Stage 2's parity and quality check again; q8 *greedy*
  was worse there.
- JMdict in OPFS (sqlite `opfs-sahpool` in a worker) instead of in the heap: about −120 MiB.
- Smaller or lazily loaded lexical data.
- Loading OPUS only when English is requested (Read Chapter's study cards don't need it).

**Owner decision needed:** accept about 2 GB (plus about 0.5 GB of GPU memory on WebGPU) as
the browser engine's footprint and revise G8, or fund a memory increment before the models are
offered to everyone.

## Development commands

```powershell
uv run python scripts/build_browser_artifacts.py      # package exports and pin hashes
uv run python scripts/serve_browser_artifacts.py      # http://127.0.0.1:47620/
uv run hf auth login                                  # once, write token
uv run python scripts/publish_browser_artifacts.py --repo <owner>/yomiscan-browser-models
# Chrome (test profile) with --remote-debugging-port=9231 --enable-unsafe-extension-debugging
node extension/tests/browser-engine.mjs samples/vision/008.jpg samples/vision/1.jpg
# First-run setup, backend stopped. YOMISCAN_MODEL_SOURCE=http://127.0.0.1:47620/ uses loopback;
# YOMISCAN_TEST_THREADS=4 emulates a 4-core CPU (Chrome with --disable-gpu).
node extension/tests/first-run-e2e.mjs samples/vision/008.jpg samples/vision/1.jpg
```
