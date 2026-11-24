# Evaluation sets

Stage 1 of the [independent-assessment strategy](../independent-assessment/README.md)
creates the evaluation assets that later decisions depend on, including the
[Stage 2 feasibility gate](../decisions/stage-2-feasibility-gate.md). None of them
needs model downloads in CI. Copyrighted pages and their text never enter Git.

| Set | Location | Status |
|---|---|---|
| Lexical golden set | `benchmarks/lexical-golden.jsonl` (committed) | **60 sentences, 138 token expectations, 14 multi-token units (scored since Stage 3)** |
| Page corpus (detection/OCR/rendering) | `samples/vision/` (ignored) + manifest | **23 pages, 10 series, 253 regions; draft annotations, owner review pending** |
| Translation set | `benchmarks/manga-dialogue.jsonl` (53 lines, committed) | Expansion with real lines waits for the page corpus |

## Lexical golden set

Each line names tokens of a sentence by surface, with the **correct** top-ranked meaning:

- `spelling`: a spelling or reading of the best entry;
- `pos`: a substring of the best entry's first-sense part of speech;
- `gloss`: a substring of a gloss in the first three senses, which the Study popup shows unfolded.

Expectations describe the right answer, not current output. A mistaken expectation is
corrected only when the expectation itself is linguistically wrong; one was corrected
(会え → 会う, the potential form's dictionary entry). `units` are meaning units spanning
several tokens (しょうがない, かもしれない). Since Stage 3 they are scored. A unit passes when
the analysis has a unit whose surface or dictionary form equals the text, or a larger
unit containing it, or a single token that already is the expression, and when its top
entry shows the gloss.

```powershell
uv run python scripts/evaluate_lexical.py                                   # data/jmdict.sqlite3
uv run python scripts/evaluate_lexical.py --dictionary path\to\jmdict.sqlite3 --output .cache\lexical.json --min-pass-rate 0.9
```

### Recorded results (2026-11-23, local JMdict, UniDic-lite)

| Analyzer | Scored | Pass | Fail | Pass rate | Pending units |
|---|---:|---:|---:|---:|---:|
| Before Stage 1 (`main` @ `cb446ab`, entry-ID order) | 138 | 105 | 33 | 76.1% | 14 |
| Stage 1 ranking, JMdict schema 1 database | 138 | 137 | 1 | 99.3% | 14 |
| Stage 1 ranking, JMdict schema 2 database | 138 | 137 | 1 | 99.3% | 14 |

Before ranking, failures were concentrated on function words and common homophones:
ない ×4, よ ×3, ね ×3, た ×2, こと ×2, な ×2, だ ×2, and は, なきゃ, いけ, て, なん.
The remaining failure is 金 in 金がある: UniDic-lite tags it as the surname キン, so
"gold" ranks above "money". That is a tokenizer error, evidence for the planned
UniDic/SudachiPy comparison, not a ranking rule to special-case. Schema 2 changes
some rankings that this set does not cover (e.g., しょう: "show" → "chapter"; both are
wrong until しょうがない is matched as a unit).

### Stage 3 units (2026-11-24, same dictionary)

| Analyzer | Scored | Pass | Fail | Missing unit | Pass rate |
|---|---:|---:|---:|---:|---:|
| Stage 3 units, tokens and units scored | 152 | 145 | 6 | 1 | 95.4% |
| Stage 3 units + grammar notes | 152 | 147 | 5 | 0 | **96.7%** |

Units match the expected expression in 13 of 14 cases. With grammar notes, all 14 are
found; てしまう and だろう come from notes, since they are constructions, not JMdict headwords. Four of the six failures
have the right meaning in different words ("that might be so" for "maybe", "have to do"
for "must", "and yet" for "although", "to be able" for "can"); by the correction rule
above, they stay failures. だろう is one token that looks up the copula だ, a grammar-pattern
case, and 金 is the tokenizer error. On the 209 corpus lines, 170 units were found after
the false merges seen in the first run were removed by rule. Remaining known errors are
child-spelled kana (けんきうしてる) and a mid-sentence でも shown as "but".

**Limits.** The set was written by the same agent that wrote the ranking rules, in
the same session. It is therefore not an independent test, and 99% means "no known
regressions on these cases", not a general accuracy rate. Add your own sentences,
especially from real pages, before treating the number as meaningful. Stage 3's
target (≥90%) applies to the set with units scored, which the Stage 3 results above meet.

## Page corpus (owner-supplied)

The gate and the ONNX-detector decision need **at least 40 pages from at least 6 series**:
shōnen, shōjo, seinen, slice-of-life, a narration-heavy title and an SFX-heavy action title.
Pages come from the owner's own reading, stay in ignored `samples/vision/`, and are
referenced by hash only.

Use the existing `vision_benchmark` manifest format and commands
([format, annotation rules and commands](../post-mvp-detection-ocr.md#local-corpus-and-annotations)).
For each page, annotate every text region:

- `bbox`: an XYXY box in original pixels;
- `category`: `dialogue`, `narration`, `artwork` (text drawn on art) or `sfx`;
- `text`: the reference transcription, excluding ruby (furigana);
- `tags`: add `ruby` where furigana is present, and `vertical`/`small` as applicable.

Reading order is not in the manifest schema yet; extend it when ordering is measured.
Set `annotations_complete` only when every region is annotated. Assign each page's
`split` (`tune` or `held_out`, the values the benchmark `--split` option accepts) before
measuring, so thresholds are not tuned on held-out pages. Split by series, never by page.

Once pages exist, record the baseline (production PyTorch detector, original manga-ocr):
detection recall, normalized CER, and per-page CPU time. The same manifest then feeds:

- the **ONNX INT8 detector default switch**: adopt only if recall ≥ PyTorch recall −1
  block per 100 (the Stage 2 G7 rule applied early);
- Stage 2 G1–G8;
- furigana leakage and long-block truncation counts (assessment open questions Q17/Q18).

### Recorded baseline (2026-11-24, draft annotations)

**Corpus.** 23 owner-supplied pages from 10 series (action/SFX-heavy shōnen, seinen,
shōjo, slice-of-life, isekai and narration-heavy titles; 4 in colour). The `held_out` split is 9 pages
from 4 whole series; `tune` is 14 pages from 6 series. 253 regions: 179 dialogue,
32 narration, 9 artwork, 33 SFX. 18 regions have `text: null` (unreadable stylised SFX,
oval "dot" glyphs, a Latin logo); they count for detection only.

**How the annotations were made.** Reference text was transcribed visually from the
page images by the AI assistant, never from OCR output. Candidate boxes were the union of both
detectors' proposals at a 0.25 threshold, below the production 0.5. Each page was
then reviewed. 13 false positives were dropped (ornaments, page numbers,
bubble outlines), 5 split bubbles were merged and 22 missed regions (mostly SFX) were
drawn by hand. `annotations_complete` stays `false` until the owner checks the text and
boxes, so these numbers are a **draft baseline**. The box source is biased towards what
the detectors already find, so recall is an upper bound. Measured on an i7-14700K desktop
(CPU, 4 threads), which is faster than the reference laptop. Latencies are not gate evidence.

**Detection** (production thresholds 0.5; a region counts as found when one raw
prediction covers ≥50% of it):

| Detector | All | Dialogue | Narration | Artwork | SFX | Held-out | Load | Median page | p95 page |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| PyTorch RT-DETR-v2 (`current`) | 85.8% | 95.0% | 100% | 8/9 | 21.2% | 87.6% | 7.7 s | 940 ms | 972 ms |
| ONNX INT8 (`onnx-int8`) | 83.4% | 93.9% | 100% | 7/9 | 12.1% | 81.9% | 1.0 s | 228 ms | 242 ms |

**ONNX default decision: not adopted.** The pre-agreed rule (recall ≥ PyTorch −1 region
per 100) fails. Overall the gap is −2.4 per 100, dialogue −1.1 and held-out −5.7. ONNX is
about 4× faster per page and loads about 8× faster, so it stays the selectable experimental
engine. Revisit when the corpus is reviewed and reaches 40 pages, or test a lower ONNX threshold
on the `tune` split only.

**OCR** (original manga-ocr, `current`, crops from the annotated boxes, NFKC/whitespace
normalised CER):

| Subset | Crops | CER | Exact |
|---|---:|---:|---:|
| All | 235 | 4.05% | 74.5% |
| Dialogue | 177 | 3.38% | 78.0% |
| Narration | 32 | 3.25% | 68.8% |
| Artwork | 8 | 6.38% | 62.5% |
| SFX | 18 | 44.2% | 55.6% |
| Ruby-tagged | 143 | 2.83% | 77.6% |
| Held-out | 101 | 4.15% | 71.3% |

Median 371 ms per crop, p95 557 ms. Much of the non-SFX error is ellipsis length (`…` read as
`．．．` with a different dot count) and dash versus long-vowel mark. Ignoring punctuation and
dashes, non-SFX character error is 1.77%. The remaining errors are mostly single-character
substitutions between similar-looking glyphs.

- **Q17 furigana leakage:** none observed. 3 of 143 ruby crops produced longer output, all
  from punctuation or a misread character, not ruby text.
- **Q18 long-block truncation:** none. 0 of 22 blocks of ≥25 characters lost more than 2
  characters.
- **SFX** are the weakest class for both detection and OCR. The product does not translate
  SFX today, so this is a known gap, not a regression.

## Translation set

The committed 53-line `manga-dialogue.jsonl` stays the regression set. After the page
corpus exists, add about 100 real lines (text and reference only, kept local when copyrighted)
and use blind A/B rating sheets for the Stage 2 bake-off. The bake-off covers OPUS,
Hy-MT2, and Chrome's built-in Translator as an *optional, experimental* provider only.
