# Evaluation sets

Stage 1 of the [independent-assessment strategy](../independent-assessment/README.md)
creates the evaluation assets that later decisions depend on, including the
[Stage 2 feasibility gate](../decisions/stage-2-feasibility-gate.md). None of them
needs model downloads in CI. Copyrighted pages and their text never enter Git.

| Set | Location | Status |
|---|---|---|
| Lexical golden set | `benchmarks/lexical-golden.jsonl` (committed) | **60 sentences, 138 token expectations, 14 multi-token units** |
| Page corpus (detection/OCR/rendering) | `samples/vision/` (ignored) + manifest | **Specified below; needs owner-supplied pages** |
| Translation set | `benchmarks/manga-dialogue.jsonl` (53 lines, committed) | Expansion with real lines waits for the page corpus |

## Lexical golden set

Each line names tokens of a sentence by surface, with the **correct** top-ranked meaning:

- `spelling`: a spelling or reading of the best entry;
- `pos`: a substring of the best entry's first-sense part of speech;
- `gloss`: a substring of a gloss in the first three senses, which the Study popup shows unfolded.

Expectations describe the right answer, not current output. A mistaken expectation is
corrected only when the expectation itself is linguistically wrong; one was corrected
(会え → 会う, the potential form's dictionary entry). `units` are meaning units spanning
several tokens (しょうがない, かもしれない). They are reported as pending until Stage 3
adds longest-match lookup.

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

**Limits.** The set was written by the same agent that wrote the ranking rules, in
the same session. It is therefore not an independent test, and 99% means "no known
regressions on these cases", not a general accuracy rate. Add your own sentences,
especially from real pages, before treating the number as meaningful. Stage 3's
target (≥90%) applies to an expanded set that includes pending units.

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
`split` (`tuning` or `held_out`) before measuring, so thresholds are not tuned on
held-out pages.

Once pages exist, record the baseline (production PyTorch detector, original manga-ocr):
detection recall, normalized CER, and per-page CPU time. The same manifest then feeds:

- the **ONNX INT8 detector default switch**: adopt only if recall ≥ PyTorch recall −1
  block per 100 (the Stage 2 G7 rule applied early);
- Stage 2 G1–G8;
- furigana leakage and long-block truncation counts (assessment open questions Q17/Q18).

## Translation set

The committed 53-line `manga-dialogue.jsonl` stays the regression set. After the page
corpus exists, add about 100 real lines (text and reference only, kept local when copyrighted)
and use blind A/B rating sheets for the Stage 2 bake-off. The bake-off covers OPUS,
Hy-MT2, and Chrome's built-in Translator as an *optional, experimental* provider only.
