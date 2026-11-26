# YomiScan

**Read manga in Japanese, and study any bubble.** YomiScan is a Chrome extension that finds the speech bubbles on a
manga page, reads their Japanese text, and explains it: the words with their readings and meanings, grammar
patterns, and an English translation. Everything runs on your own computer.

![A study card on a synthetic manga page: furigana over 雨 and 降, the translation "It might rain.", and the
expressions 雨が降る and かもしれない with their meanings](docs/store/screenshots/1-study-card.png)

## What you can do

- **Read Chapter.** Keeps the Japanese and outlines every bubble. Click a bubble, or press <kbd>J</kbd> /
  <kbd>K</kbd> to step through them, and its study card opens. Each page has an English button.
- **Select Text** (<kbd>Ctrl</kbd>+<kbd>Shift</kbd>+<kbd>Y</kbd>). Drag a box around Japanese text on any page.
- **Translate Chapter.** Puts English over every bubble; switch a page back to Japanese at any time.
- **The study card.** Furigana over the words you don't know yet, every word with its dictionary form, reading and
  [JMdict](https://www.edrdg.org/wiki/index.php/JMdict-EDICT_Dictionary_Project) meanings, expressions such as
  かもしれない as one unit, grammar notes, a translation, and **Edit text** to fix a misread character.
- **Keep what you learn.** ☆ Save word and Save sentence; the **Saved** page searches them and exports CSV or a
  file Anki imports directly (**Export for Anki**). **Mark known** folds words you know away and stops furigana over
  them; import a known-word list you already have.

## Install

1. **The extension.** From the Chrome Web Store (link to come with the first public release). Until then: download
   `yomiscan-extension-<version>.zip` from the [releases page](https://github.com/GabrielTeixeira88/yomiscan/releases),
   unzip it, open `chrome://extensions`, turn on **Developer mode**, click **Load unpacked** and choose the folder.
   Chrome 120 or later.
2. **Pin it:** the puzzle-piece icon in Chrome's toolbar, then the pin next to YomiScan.
3. **Optional, Windows: the YomiScan Engine.** A separate program that runs the models faster than Chrome can.
   Download `YomiScan-Engine-Setup-<version>.exe` from the releases page and run it (no administrator rights
   needed). Chrome starts it when YomiScan needs it, and it stops itself after 15 idle minutes.

## First use

Open a manga chapter whose pages are images and click the YomiScan icon. The panel asks once for the reading models
and shows their size and source before downloading anything:

- **In Chrome:** about 525–550 MB from Hugging Face (text detection, OCR, the JMdict dictionary and translation),
  checked against pinned hashes. They run inside Chrome, on your graphics card when it can.
- **With the YomiScan Engine:** the engine downloads its own models (about 845 MB) on first start, after you agree.

After that, YomiScan works without an internet connection, except to load the manga pages themselves. When a
reader's images come from another site, Chrome asks before YomiScan may fetch them.

## Privacy

No account, no analytics, no tracking. Screenshots, page text, saved words and settings stay on your computer;
YomiScan has no servers. It connects only to download its models (once, after you agree) and to fetch the pages you
read. See the [privacy policy](PRIVACY.md).

## Limits

- Machine translation (OPUS-MT) is often rough on casual dialogue; the study card is the reliable part.
- OCR and bubble detection are good on printed manga, weaker on handwritten or stylized text. **Edit text** fixes a
  misread line.
- Read Chapter and Translate Chapter work on readers that show pages as images; not every site's layout is
  supported. Select Text works anywhere.
- Translation is Japanese → English; Portuguese and Spanish are experimental and only in the developer backend.
- On a computer without a capable graphics card, the first pages of a chapter take a while.

## Licenses and attribution

YomiScan's code is [MIT-licensed](LICENSE). The dictionary and models are not: JMdict is © the Electronic Dictionary
Research and Development Group, used under [CC BY-SA 4.0](https://www.edrdg.org/edrdg/licence.html); UniDic is
© the UniDic Consortium (BSD-3-Clause); the text detector, manga-ocr and OPUS-MT models are Apache-2.0. The
extension's **About & licenses** page lists every component and includes the full license texts; see also
[third-party licenses](docs/third-party-licenses.md).

## For developers

- [Developer guide](docs/development.md): running the backend and the extension from source, every stage's controls,
  tests and the historical phase notes.
- [Architecture](docs/architecture.md) and the stage records in [docs/decisions](docs/decisions/).
- [Chrome Web Store listing and package](docs/store/listing.md): `cd extension && node package.mjs` builds and checks
  the store ZIP.
- Report problems at <https://github.com/GabrielTeixeira88/yomiscan/issues>.
