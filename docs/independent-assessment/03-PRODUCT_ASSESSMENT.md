# 03 — Product Assessment

This document evaluates YomiScan as a product for someone reading Japanese manga to
learn Japanese. Evidence labels are defined in 01.

---

## 1. Verdict

**The product direction drifted away from the user it names.** YomiScan says it is a
*study* assistant. Since Phase 5, most of its effort has gone into a *scanlation
machine*: erase the Japanese, typeset machine English. For a learner, that feature
removes the very text they are trying to read, and replaces it with translations that
are often wrong [Verified]. Meanwhile the study experience, which is the reason to
choose YomiScan over a translator, still runs on its Phase-2 dictionary logic. That
logic shows "feather, tooth, blade" for the particle は [Verified].

The technical foundations are good. The problem is **what they are pointed at**.

## 2. Is the application solving the right problem?

A learner reading manga faces these problems, roughly in this order of frequency:

1. "I can't type this word into a dictionary." Kanji they can't read, vertical text,
   stylised fonts. **This is the core problem, and OCR solves it.**
2. "I know the words but not how they fit together." Conjugation chains, colloquial
   contractions (〜なきゃ, 〜ちゃう, じゃねえ), sentence-final particles, omitted subjects.
3. "I need a sanity check that I understood the sentence." A translation used as an
   *answer key*, not as a replacement.
4. "I want to remember this." Save words and sentences, and review them later (Anki/SRS).
5. Occasionally: "I just want to get through this page." A gloss of the whole page.

YomiScan addresses (1) partially: one selected region at a time, with text dropped
when a selection holds several blocks. It addresses (3) with a weak model. It barely
addresses (2) or (4). It invested heavily in (5), which is the least learning-relevant need.

**The established community solution is worth naming.** Learners today commonly use
**mokuro**, which runs detection and manga-ocr offline and outputs an HTML reader with
an invisible, selectable Japanese text layer over each bubble. They pair it with
**Yomitan**, a popup dictionary extension with deinflection and Anki export. That
combination solves (1), (2, partly), and (4) very well. It is fully offline, but it
works on local files rather than in web readers, and it has no sentence translation.
YomiScan's real opportunity is **that workflow, live, in the browser, plus sentence-level
help**. Its current direction instead competes with automatic scanlation tools, where
it is weaker and less relevant to learners.

## 3. User experience assessment

### 3.1 Study Mode (drag-select → popup)

| Aspect | Assessment |
|---|---|
| Discoverability | Fine. There is a toolbar action and Ctrl+Shift+Y. |
| Speed | ~0.5 s warm on CPU [Verified]. Fast enough. |
| Friction | **High.** One drag per bubble. For a page with 8–13 bubbles that is 8–13 deliberate selections, each one opening and closing a popup. The page is never "ready to read". |
| Correctness | A selection covering two bubbles loses one silently [Verified]. Users will learn to select tightly, which adds more friction. |
| Recovery | No OCR edit. If manga-ocr misreads a character, the whole token analysis is wrong and cannot be fixed in place. |

### 3.2 The popup

The popup is technically solid: closed Shadow DOM, drag, resize, Escape, copy buttons.
The content model is the problem.

- **Everything is shown at once.** For each token it shows reading, lemma, dictionary
  form, POS, conjugation, and three or more senses. A 15-token line becomes a long
  scroll of identical cards. Function words (は, の, よ, だ) get as much space as
  content words.
- **The noise is actively misleading** [Verified, real JMdict]:

  | Token in context | First senses shown to the learner |
  |---|---|
  | は (topic particle) | feather; plume · tooth · edge of a knife |
  | よ (sentence-final) | night · other · four |
  | た (past auxiliary) | multi- · rice field · other |
  | こと | koto (zither) · ancient city · thing |
  | しょう in しょうがねえ | 41 entries: show, quotient, illness… |

- **Missed meaning units.** 万年 ("perpetual") is shown as 万 + 年. しょうがない and
  なきゃいけない exist in JMdict but are never surfaced. These are exactly the chunks a
  learner most needs explained.
- **Jargon.** POS labels are raw UniDic Japanese (`助詞 / 係助詞`, `名詞 / 普通名詞 / 一般`).
  Conjugation shows codes like `五段-カ行 / 未然形-一般`. Intermediate learners can't use
  these, and advanced learners don't need them.
- **No furigana on the sentence itself.** Readings exist only inside token cards.
- The footer admits "meanings are not selected for this context". That is honest, but
  the product should make the likely meaning obvious, not leave the learner to sort through 12 entries.

### 3.3 Translate Chapter

- The overlay mechanics work well. Visible pages come first, the Original/English
  toggle is instant, and the reader DOM is never rewritten.
- The output does not serve the learner. The English replaces the Japanese.
  [Verified] On one real page, 9 of 13 blocks were replaced, and at least three of the
  nine English lines had meaning errors: a wrong name, a wrong idiom, and a question
  turned into "I don't know why you're acting like a witch doctor".
  A learner cannot tell which ones are wrong.
- Text outside bubbles (narration on artwork, signs, SFX) is usually *preserved*,
  meaning left in Japanese, because erasing it safely is hard [Verified: 4 artwork-text
  blocks preserved on page 1]. The repeatedly reported "OCR misses text outside speech
  bubbles" is mostly a **rendering-safety problem, not a detection problem**. The
  repository's own coverage audit says so: all detected dialogue was OCR'd and
  translated, and the renderer declined to paint some of it. Only the 2 large SFX were
  true detector misses [Repo-reported].
- **The control panel is overwhelming.** It has about 30 buttons across Study, Reading,
  Translation View, font, glossary, cache, history, setup, reports and developer
  diagnostics, all in one 280 px floating panel.

### 3.4 Setup

Python 3.13, uv, a manual JMdict download and import, a preparation command for about
1.6 GB of models, and then a terminal server started for every session. Engine choice
is an environment variable. This is acceptable for the developer. It would lose almost
every learner before first use.

## 4. The Japanese learning experience: what a learner actually needs

What follows is my view of what is genuinely useful, ordered by value per pixel.

1. **The sentence, readable.** The Japanese line with **furigana on demand**, either
   over all kanji or only over kanji the user hasn't marked known. Tokens should be
   tappable.
2. **Words as meaning units, not morphemes.** 行かなきゃいけない should be presented as
   行く + 〜なきゃいけない ("have to"). 食べてしまった is 食べる + 〜てしまう (completion or regret)
   + past. This needs longest-match dictionary scanning, a deinflection engine, and a
   small curated grammar-pattern table.
3. **One best meaning first, the rest folded.** Rank by POS and reading agreement with
   the morphological analysis, then by JMdict priority. Show the top sense, and keep
   other entries one click away.
4. **Grammar notes for the inflection chain**, in plain English: "〜なきゃ = 〜なければ
   (colloquial): if not …", "ねえ = ない (rough/colloquial)". These are deterministic
   and rule-based, and therefore trustworthy. LLM-generated grammar explanations are
   attractive but risky: a learner can't detect a confident hallucination.
5. **The translation as an answer key.** Hidden by default ("reveal translation"), or
   shown below the analysis. It should be labelled as machine output and, ideally,
   offered from a stronger model on demand.
6. **Kanji details on request.** Meanings, readings and stroke count (KANJIDIC2),
   reached by tapping a kanji. This should not be shown by default.
7. **Capture.** Save a word with its sentence and page screenshot, to Anki through
   AnkiConnect or to a local list. Mark words as known, so furigana and highlighting adapt.
8. **OCR correction.** Click the original text, fix one character, and re-analyse
   instantly. No OCR re-run is needed. This is essential because every downstream
   feature inherits OCR errors.

Things a learner does *not* need by default: raw UniDic POS hierarchy, conjugation
type codes, per-stage timings, model provenance, or dictionary candidates for
punctuation and particles.

## 5. OCR and translation quality

### 5.1 OCR

- **manga-ocr (original weights) is the right default recogniser.** It is the de facto
  community standard and handles vertical text natively. [Repo-reported] It was more
  accurate than the 2025 variant on the tested crops. Keep it.
- **Vertical text.** manga-ocr handles vertical blocks directly. The weak link is
  *reading order* across blocks (band heuristic) and *long blocks*: manga-ocr is
  trained on short blocks, and long narration boxes risk truncation, which the original
  engine cannot report. Recommendation: benchmark splitting long blocks into column
  lines before OCR.
- **Text outside bubbles.** The detector already has a `text_free` class and found the
  narration and artwork text on the tested pages. If the product stops trying to
  *paint over* it, and instead overlays an interactive text layer, the "outside
  bubble" problem mostly disappears. True misses (large stylised SFX) need a manual
  region-select fallback. That fallback should run detection on the crop instead of
  treating it as one block.
- **Furigana.** manga-ocr usually ignores small ruby text. Sometimes it merges it,
  which creates garbage tokens. Recommendation: (a) measure how often ruby leaks into
  OCR output on a real corpus; (b) if it is frequent, filter thin side-columns by
  geometry before OCR. Furigana in the *source* is valuable, because it is the
  author's reading for a rare kanji or a name. Capturing it separately is a stretch
  goal, not an MVP feature.
- **SFX.** Low priority for learning. Mostly undetected. Manual select works.
- **Mixed layouts** (horizontal English or numbers inside vertical text, tategaki with
  horizontal digits, as in 万年４級). manga-ocr handles short mixed blocks acceptably.
  No special pipeline is justified until a real corpus shows a failure pattern.

### 5.2 Translation

- **OPUS-MT ja-en is not adequate for manga dialogue.** It makes meaning errors that a
  learner can't detect. The repository's own benchmark reaches the same conclusion,
  and kept it only because nothing tested was *reliably* better.
- That framing is wrong for a learner product. **The translation is an answer key, not
  the output**, so its job is to be *more often right* and *clearly labelled*. Hy-MT2
  1.8B manga fine-tune (Apache-2.0, ~1.1 GB Q4) was faster on GPU [Repo-reported:
  84 ms/line] and better on slang and names. It should be the default for GPU users,
  and offered on CPU too (~270 ms/line, [Repo-reported]), with OPUS as a lightweight fallback.
- **Page or sentence context helps humans more than models.** The repository's
  experiments show context leaking into neighbouring lines. For a learner product,
  translate per bubble, show it next to that bubble's Japanese, and let the learner
  supply the context.
- A larger local LLM (7–8B class) could give better translations *and* explanations
  on a 12 GB GPU. It is opt-in and experimental until measured on a representative
  set. The cost is 4–6 GB VRAM, slower first token, and hallucination risk in explanations.

## 6. Features that add complexity without proportional value

| Feature | Recommendation |
|---|---|
| Automatic erase-and-typeset chapter translation | **Demote** to an optional "glance" mode later. Keep the renderer code. |
| Series glossary editor | **Remove** from the UI until an engine that honours it is the default. |
| PT/ES targets | **Remove** from the product. Keep the research results. |
| NLLB, Qwen2.5, VNTL adapters | **Move out** of the runtime package into `research/`. |
| Diagnostic ZIP export with consent tiers | **Replace** with "Copy debug info" plus logs. |
| Persistent stage cache with lineage identities | **Replace** with one simple result cache keyed by image hash. |
| Developer diagnostics in the end-user panel | **Move** behind a developer flag. |

## 7. What the core experience should be

> **Open any manga page and it becomes readable Japanese: every bubble is tappable.
> Tap a bubble to see furigana, meaning-unit breakdown, grammar notes and (on request)
> a translation; tap a word to save it. Nothing leaves your computer.**

Translation is a supporting feature. Automatic English typesetting is an optional extra
for later. Doc 04 describes this design in detail.
