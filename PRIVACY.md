# YomiScan privacy policy

Effective 2026-11-25. This policy covers the YomiScan Chrome extension and the optional YomiScan Engine for Windows.

**In short:** YomiScan has no accounts, no analytics and no servers of its own. What you read, save and study stays on
your computer.

## What YomiScan processes, and where

| Data | Where it goes | How long it stays |
|---|---|---|
| Screenshots of the area you select (Select Text) | Processed in Chrome, or by the YomiScan Engine on your own computer (`127.0.0.1`) | In memory while it is read; never stored |
| Manga page images (Read Chapter, Translate Chapter) | Fetched from the site that hosts them, then processed as above | In memory for the session; the most recent originals are released when you close the panel or leave the page |
| The Japanese text, word analysis and translations | Shown in the page; nowhere else | Until you close the panel, unless you save them |
| Saved words, saved sentences and known words | The extension's own storage in Chrome (IndexedDB), on this computer | Until you delete them on the Saved page, or uninstall YomiScan |
| Settings (engine choice, furigana, local engine port) | Chrome's extension storage, on this computer | Until you change them or uninstall YomiScan |
| Optional local processing cache (off by default) | The YomiScan Engine's folder on this computer, without page URLs | Until you clear it in the panel |

Saved sentences keep the text and its analysis only, never the page address, the image or a screenshot.

## Network connections

YomiScan connects to the internet only for these:

- **Model download, once, after you agree.** The panel shows the size and source and downloads only after you click.
  The files come from Hugging Face (`huggingface.co`), from a pinned revision, and are checked against fixed SHA-256
  hashes. The YomiScan Engine for Windows downloads its models the same way on first start. Hugging Face receives
  an ordinary download request (your IP address and browser details), as with any download; YomiScan sends it
  nothing else.
- **Manga page images,** from the site that hosts them, when you read or translate a chapter there. Chrome asks you
  before YomiScan may fetch images from a site for the first time.
- **The YomiScan Engine, on your own computer,** over `127.0.0.1` with a per-launch access token. This connection
  does not leave your computer.

YomiScan sends no telemetry, analytics, crash reports or usage data, and shows no ads.

## Things you choose to export

**Export CSV**, **Export for Anki**, **Export list**, **Back up all** and the panel's page reports write files to
your Downloads folder when you click them. They contain what you saved or what the report lists (page reports hold
metadata only unless you tick the options for text or images). YomiScan does not upload them anywhere; what you do
with them is up to you.

## Chrome's built-in translator

An experimental setting can use Chrome's own on-device Translator. If you turn it on, Chrome's terms for that
feature apply. It is off by default.

## Sharing and selling

YomiScan does not sell, share or transfer your data, and does not use it for anything other than showing you your
reading help. Nothing is used for advertising or credit decisions.

## Children

YomiScan collects no personal information from anyone, including children.

## Deleting your data

On the Saved page, **Delete all** removes every saved word, sentence and known word. Uninstalling the extension
removes all of its storage, including the downloaded models. Uninstalling the YomiScan Engine (Windows Settings →
Apps) removes the engine and asks whether to remove its downloaded models, processing cache and glossaries too
(`%LOCALAPPDATA%\YomiScan`).

## Changes and contact

Changes to this policy are made in this file, in the public repository, with their date above. Questions or
concerns: open an issue at <https://github.com/GabrielTeixeira88/yomiscan/issues>.
