# Stage 6: capture and public release

Status: **in progress**. Started on the owner's go-ahead (2026-11-25) after Stage 5b merged.

## Why this stage exists now

The [strategy](../independent-assessment/07-STRATEGY_DECISION.md) ends with Stage 6. Stages 3–5
made YomiScan good at *reading*; nothing yet helps a learner *keep* what they read. The only way
to keep anything is the opt-in Study history: whole sentences, capped at 100, with no way to
save one word or to get it into a flashcard program. Stage 6 adds that, then prepares the
extension for people who are not developers: a Chrome Web Store package, a privacy policy, the
data attributions, a first-run welcome and a README written for users.

## Goal

While reading, a learner saves a word or a sentence with one click, exports saved items as CSV
(including a file Anki imports directly), and marks words as known so furigana appears only over
words they do not know yet. The extension can then be submitted to the Chrome Web Store with its
privacy policy and attributions.

Everything stays local: saved words live in the extension's own storage, and nothing is sent
anywhere else.

## Increments

Each increment is merged only with its tests and a check in real Chrome.

| # | Scope | Status |
|---|---|---|
| 1 | **Saved words and sentences.** "Save word" on every word and expression in the study card, "Save sentence" for the whole card (replacing Save to History; old history entries become saved sentences). A local library in the extension's IndexedDB, a full-page **Saved** view (search, delete, reopen a sentence), CSV export of words and sentences, and a JSON backup and restore. Each word carries its dictionary form *and that form's reading* (食べた → 食べる, たべる), which both engines now report. | Done: real Chrome end to end; lookup 1–2 ms with 10,002 saved words (see increment 1) |
| 2 | ~~**Anki export** through the AnkiConnect add-on.~~ Replaced by an **Export for Anki** CSV file on the Saved page (see increment 2). | Dropped by the owner (2026-11-25); Anki CSV done |
| 3 | **Known words and furigana.** Mark a word as known from the card or the Saved view; import a known-word list (one word per line). The card's Japanese sentence gets furigana with a setting: off, unknown words only (default), all words. Known words fold away in the word breakdown. | Done: real Chrome end to end; known lookup 1–2 ms with 10,003 known words (see increment 3) |
| 4 | **Release preparation.** Welcome page on install (shortcut, reading modes, model download, privacy), an About & licenses page in the extension, `PRIVACY.md`, the Web Store listing text and permission justifications, a store-package script with checks (no remote code, manifest, size) built by CI, screenshots from the synthetic fixtures, and a user-first README. | Planned |
| 5 | **Submission (owner).** The owner registers a Chrome Web Store developer account and submits the package. Once the store ID is known, the companion installer is rebuilt with it pre-filled and attached to a GitHub release. | Waits for the owner |

## Gates

| Gate | Threshold |
|---|---|
| No regressions | `uv run pytest`, the extension tests, the lexical parity harness and the mocked Chrome fixture pass. |
| Saved words in real Chrome | Save, reopen, delete and export work end to end with the real browser engine on sample pages. |
| Card speed | With 10,000 saved words, the card's saved/known lookup adds ≤ 50 ms. |
| Store package | No remotely hosted code, every permission justified in the listing, package size reported. |

## Proposed owner decisions

None of these block increments 1–3; they are needed by increments 4 and 5.

- **Saving needs no separate opt-in.** Study history was off by default and needed a switch
  *and* a Save click. A Save click alone is now the consent: nothing is stored without one. The
  Saved view deletes and exports everything, and uninstalling removes it.
- **Web Store.** The owner registers the developer account (Google charges a one-time
  registration fee; it is the only cost in this stage), chooses the publisher name, and
  submits. Proposed: version 1.0.0, first listed as *unlisted* for a trial, then public.
- **Privacy policy URL.** `PRIVACY.md` in this public repository, linked from the listing.

## Increment 1: saved words and sentences

**Design.**
- **Where it lives.** Saved items go in the extension's own IndexedDB (`yomiscan-library`), not
  `chrome.storage.local`. They can reach tens of thousands of records, and IndexedDB answers a
  card's lookup without reading the whole list. The service worker owns writes from pages
  (content scripts talk to it through one validated message, `libraryRequest`). The Saved page
  is an extension page and opens the same database directly, so long lists never cross a
  message.
- **What a word is.** A saved word is keyed by its best JMdict entry (`jmdict:<id>`), so 食べた,
  食べて and 食べる are one saved word; a word without a dictionary match is keyed by its form
  and reading. Saving it again keeps the first date and takes the newest sentence.
- **Its reading.** Anki cards and lists need the reading of the *dictionary form*, which the
  card did not have (it shows the surface reading: 食べ → たべ). Both engines now add
  `dictionary_reading` to every token and unit (`backend/yomiscan/headword.py` and
  `dictionaryReading` in `extension/src/engine/lexicon.ts`, tested on the same cases): the best
  entry's readings that apply to that spelling (JMdict `re_restr`, never `re_nokanji`), with the
  tokenizer's reading as the tie-break. Older servers omit it; the extension then keeps a
  reading only when the word appears uninflected.
- **Sentences.** A saved sentence is the card's full analysis, sanitized as Study history was
  (no URL, path, image or unknown field; at most 128 KiB), so **Open** shows the same card
  again without new OCR.
- **Study history.** Its entries move into saved sentences once, then the old key is removed;
  broken entries are skipped and counted. If moving fails, the old entries stay where they were.
- **Limits.** 50,000 words and 2,000 sentences. A full list refuses new items with a message;
  it never deletes old ones silently.
- **Export.** CSV for words (Expression, Reading, Meaning, Part of speech, Sentence, Sentence
  translation, Added) and for sentences, every field quoted, UTF-8 with a byte-order mark. A JSON
  backup holds everything; restoring it checks every record before writing anything and keeps
  items that are already saved.

**Measurements (2026-11-25, development machine, real Chrome, installed companion engine).**
- `extension/tests/library-e2e.mjs` on two sample pages: Read Chapter, J to the first bubble
  with two words (page 1, bubble 2: へーそう), ☆ Save word on both and Save sentence. Reopening
  that bubble marked both ★ Saved. The Saved page listed both words with meaning and the word
  marked in its sentence, and the old Study history entry had become a saved sentence (the
  broken one skipped). CSV export, Open (same card, saved words marked), Back up all, Delete all
  and Restore backup all passed, and the backup holds no page URL.
- With 10,002 saved words, the card's lookup of 60 words took 1.2–2.4 ms (median of 20; gate
  50 ms), and the Saved page loaded in 0.27 s.
- Dictionary-form readings: browser and Python engines identical on all 60 lexical golden
  sentences (`scripts/compare_browser_lexical.py`, which now also compares readings). All 126
  kanji words and expressions there got a reading, for example 行か → 行く (いく), 来 → 来る
  (くる), 早く → 早い (はやい), 年をとっ → 年をとる (としをとる). Two follow the tokenizer
  rather than the most common reading: 私 → わたくし (UniDic reads 私 as わたくし, and the
  ranking then picks JMdict's わたくし entry) and 明日 → あす (JMdict lists あした first). Both are
  valid readings, and both match the reading line the card already shows.
- The installed companion was built from main, so the end-to-end run's words came without
  `dictionary_reading`; the words saved there were kana (へー, そう), which need none.
- Tests: `uv run pytest` 445 passed, 1 skipped; extension 127/127; the mocked Chrome fixture
  passed twice (its Study history steps now save a sentence and a word and check the saved mark
  on reopening).
- The developer ZIP from scripts/build_distribution.py lists extension files explicitly and has lacked the browser engine's ort/ and sqlite/ folders since Stage 5a; increment 4's store package replaces it.

## Increment 2: dropped; Anki-ready CSV instead

**Decision (owner, 2026-11-25).** No AnkiConnect integration. Sending notes into Anki would
depend on a third-party add-on and on YomiScan writing into another program's collection, for
something a file import already does. No AnkiConnect code was ever written; the engine's default
port (47615, not AnkiConnect's 8765) stays, since it avoids a clash for anyone running both.

**What replaces it.** The Saved page has **Export for Anki** next to Export CSV, on both tabs. It
writes a CSV with the header lines Anki 2.1.54 and later reads on **File > Import**
([Anki manual, "File Headers"](https://docs.ankiweb.net/importing/text-files.html)):

    #separator:comma
    #html:false
    #tags:yomiscan
    #columns:Expression,Reading,Meaning,Part of speech,Sentence,Sentence translation

then one quoted row per word (sentences: `Japanese,Translation`). There is no column-name row,
which Anki would import as a note, and no date column. The facts it relies on, from Anki's
`rslib/src/import_export/text/csv/metadata.rs` and `import.rs`: header keys and the separator
name are case-insensitive; a UTF-8 byte-order mark before the first header line is stripped;
`#columns` names map to note fields with exactly the same name (unmatched columns are left out,
and the first field takes column 1 by default); with `#html:false` Anki escapes the text and
turns line breaks into `<br>`; quoted fields may contain line breaks; the import dialog still
lets the user change note type, deck and field mapping. The plain **Export CSV** keeps its
column-name row and date for spreadsheets.

**Checks.** Unit test of both files' exact bytes; `library-e2e.mjs` downloads Export for Anki in
real Chrome and checks the header lines and one row per saved word (passed twice on 2026-11-25
with the installed companion; the rest of that run unchanged). Extension tests 128/128, `uv run
pytest` 445 passed, 1 skipped. Importing the file into a
real Anki was not run (the owner chose not to use AnkiConnect, and no Anki import was automated).

## Increment 3: known words and furigana

**Design.**
- **What a known word is.** Its dictionary form, normalized (NFKC, trimmed, no spaces, at most 50
  characters, some kana or kanji): 食べる, not an entry ID. A plain list from elsewhere (an Anki
  deck, a word list) has no JMdict IDs, and the form is what both the list and the card have.
  Marking 食べる covers 食べた and 食べて. Homographs share a form (生 as なま and せい), which is
  acceptable for "I know this word". A kana form is not matched to a kanji spelling (knowing たべる
  does not hide furigana over 食べる), since that would mark every homophone known.
- **Storage.** A third store, `known`, in the same IndexedDB database (version 2; the upgrade
  keeps saved words and sentences). Up to 100,000 known words. Backups are schema 2 with a
  `known` list; schema 1 backups still restore. Delete all also deletes known words.
- **The card.** Every word and expression gets **Mark known** next to ☆ Save word. The card asks
  the service worker once which of its forms are known (alongside the saved-word lookup), then
  draws itself again if any are, keeping its scroll position. Known rows fold into "N known: …"
  under their section. A token is known when its own dictionary form is, or when the expression
  it belongs to is.
- **Furigana.** The Japanese sentence now shows furigana, built from the tokens and their
  readings (`sentenceFurigana`, which always joins back to exactly the original text; a token
  the text does not contain is left plain). The **Furigana** menu next to the sentence chooses
  *Unknown words* (the default), *All words* or *Off*; it is stored in `chrome.storage.local`
  and applies to every card.
- **Saved page.** A **Known** tab with search, **Not known** per word, **Import list** and **Export
  list** (one word per line, which Import list reads back). Saved words get a Mark known toggle.
  An imported list uses the first column of each line (tab, comma or semicolon separated), skips
  lines starting with `#` (Anki export headers) and lines that are not a Japanese word, and
  removes quotes, HTML tags and Anki's bracket furigana (食[た]べる).

**Measurements (2026-11-25, development machine, real Chrome, installed companion engine).**
- `extension/tests/library-e2e.mjs` (passed four times): Edit text turns a real card into
  猫が魚を食べた, analyzed by the real engine. Furigana showed over 猫, 魚 and 食; after Mark known
  on 猫 the card folded it into "1 known: 猫" and furigana stayed over 魚 and 食 only. Off removed
  all furigana, All words brought 猫 back, and the setting was stored. The Known tab listed 猫;
  importing a CSV list (a `#` header, 食べる, a quoted 魚, 猫 again and `hello`) added 2, counted 1
  as already known and skipped 1; Export list wrote the 3 words back. Backup, Delete all and
  Restore brought back all 3 known words with the saved words and sentences.
- Importing a 10,000-word list took 0.6–1.2 s. With 10,003 known words the card's known lookup of
  60 forms took 1.2–2.4 ms (median of 20; gate 50 ms; one run had a single 34.6 ms maximum).
- Tests: extension 133/133 (known forms, list parsing, import limits, backup schema 2, sentence
  furigana); the mocked Chrome fixture passed twice; `uv run pytest` 445 passed, 1 skipped.
