# Chrome Web Store listing

The text and answers to paste into the Chrome Web Store developer dashboard when submitting
YomiScan (Stage 6 increment 5, done by the owner). The package is built and checked by
`cd extension && node package.mjs`. CI attaches it to every run as `yomiscan-store-package-<commit>`.
`extension/tests/store-tests.ts` fails if the manifest requests a permission this page does not justify.

## Store listing tab

**Name** (from the manifest): YomiScan — Local Manga Study & Reading

**Summary** (from the manifest, at most 132 characters): Study Japanese and read or translate manga with models that run on
your computer, in Chrome or a local backend.

**Category:** Education. **Language:** English.

**Description:**

> Read manga in Japanese, and get help only when you want it. YomiScan finds the speech bubbles on a manga page,
> reads their Japanese text, and explains each one: the words, their readings and meanings, grammar patterns, and an
> English translation. Everything runs on your own computer.
>
> THREE WAYS TO READ
> • Read Chapter: keeps the Japanese and outlines every bubble. Click a bubble, or press J / K to step through
>   them, and its study card opens.
> • Select Text (Ctrl+Shift+Y): drag a box around any Japanese text on any page.
> • Translate Chapter: puts English over every bubble, and switches back to Japanese at any time.
>
> THE STUDY CARD
> • Furigana over the words you don't know yet, or over all words, or none.
> • Each word with its dictionary form, reading and JMdict meanings, and expressions such as かもしれない as one unit.
> • Grammar notes for constructions like 〜てしまう.
> • An English translation of the sentence, and an editor to fix a misread character.
>
> KEEP WHAT YOU LEARN
> • Save words and sentences with one click; search them on the Saved page.
> • Export them as CSV, or as a file Anki imports directly.
> • Mark words you know: they fold away, and furigana stops appearing over them. Import a known-word list you
>   already have.
>
> PRIVATE BY DESIGN
> No account, no analytics, no tracking. Screenshots, page text and saved words never leave your computer. The
> reading models are downloaded once, after you agree (about 525–550 MB, from Hugging Face), and run inside Chrome.
> An optional YomiScan Engine for Windows runs them faster as a separate program.
>
> Open source (MIT): https://github.com/GabrielTeixeira88/yomiscan
> Dictionary: JMdict, © the Electronic Dictionary Research and Development Group, CC BY-SA 4.0.

**Graphics:**
- Store icon: `extension/icons/icon-128.png` (96 px artwork with 16 px transparent margin).
- Screenshots (1280 × 800): `docs/store/screenshots/*.png`, made from synthetic pages by
  `node extension/tests/store-screenshots.mjs` (see below).
- Small promotional tile (440 × 280): `docs/store/screenshots/promo-440x280.png`, made by the same script.

**Official URL / homepage:** https://github.com/GabrielTeixeira88/yomiscan.
**Support URL:** https://github.com/GabrielTeixeira88/yomiscan/issues.

## Privacy practices tab

**Single purpose:** Help learners read Japanese manga: find and read the Japanese text in manga pages, and explain it
(words, readings, meanings, grammar and a translation), with everything processed on the user's computer.

**Permission justifications:**

| Permission | Justification |
|---|---|
| `activeTab` | When the user clicks the toolbar button or presses the shortcut, YomiScan opens its panel on that tab and captures the visible tab (`chrome.tabs.captureVisibleTab`) to read the Japanese text the user selects. It has no access to a tab before that click. |
| `scripting` | Injects YomiScan's own packaged content script (`content.js`) into the active tab after the click, to show the reading panel, the bubble outlines and the study cards. No code from anywhere else is injected. |
| `offscreen` | An offscreen document holds page images as Blobs and runs the in-browser reading engine (ONNX Runtime Web, the tokenizer and the dictionary), which outlast the service worker's lifetime limits. |
| `storage` | Keeps settings (engine choice, the local backend's port, furigana) in `chrome.storage.local`, and the optional local engine's per-launch access token in memory-only `chrome.storage.session`. |
| `unlimitedStorage` | The one-time model download (about 525–550 MB) is kept in the extension's Cache Storage, and saved and known words in its IndexedDB; both exceed the default quota. |
| `nativeMessaging` | Talks to the optional YomiScan Engine for Windows (native host `com.yomiscan.engine`), which the user installs separately: to start or stop it and get its local port and access token. Nothing happens when it is not installed. |
| `http://127.0.0.1/*` (host) | Sends page images to the YomiScan Engine (or a developer's local backend) running on the user's own computer, on the loopback address only. |
| `http://*/*`, `https://*/*` (optional hosts) | Requested at run time, per site, only when the user reads or translates a chapter whose page images are hosted on another site: YomiScan fetches those images to read them. Chrome asks the user for exactly those sites. |

**Remote code:** No, I am not using remote code. All JavaScript and WebAssembly ship in the package; extension pages
allow only packaged scripts (`script-src 'self' 'wasm-unsafe-eval'`). The models downloaded on first use are data
(ONNX model weights, a SQLite dictionary and tokenizer JSON files) from a pinned Hugging Face revision, each
checked against a SHA-256 hash before use. `package.mjs` fails the build if any script or WebAssembly would load from
a remote URL, and a unit test fails if the model manifest lists a `.js` or `.wasm` file.

**Data usage:** YomiScan collects none of the listed categories of user data. Page images, screenshots and text
(website content) are processed only on the user's computer, in Chrome or in the YomiScan Engine on 127.0.0.1, and
are not transmitted off the device. Saved words, sentences and known words stay in the extension's own storage.
There are no analytics and no accounts. Certify all three statements:
- I do not sell or transfer user data to third parties, outside of the approved use cases.
- I do not use or transfer user data for purposes that are unrelated to my item's single purpose.
- I do not use or transfer user data to determine creditworthiness or for lending purposes.

**Privacy policy URL:** https://github.com/GabrielTeixeira88/yomiscan/blob/main/PRIVACY.md

## Distribution tab

Proposed (owner decision): visibility **Unlisted** for a first trial, then Public; all regions.

## Notes for the reviewer

> YomiScan needs a page with Japanese text in images (for example a manga page). Click the toolbar icon, then Select
> Text, and drag over the text. On first use the panel offers a one-time download of the reading models (about
> 525–550 MB, from huggingface.co, checked against pinned hashes); after it, everything runs locally. The optional
> native host (com.yomiscan.engine) belongs to a separate Windows installer and is not required for review.

## Screenshots

`node extension/tests/store-screenshots.mjs` (from the repository root) makes the screenshots in
`docs/store/screenshots/` from the synthetic reader fixture (`extension/fixtures/`, no copyrighted pages) with a
mocked engine, in a Chrome started like the other end-to-end tests (`--remote-debugging-port`, default 9231).
