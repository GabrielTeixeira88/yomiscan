# Phase 2 validation — 2026-09-29

Environment: Windows, CPython 3.13.9, fugashi 1.5.2, UniDic-lite 1.0.8.
`uv sync` succeeded with Python unchanged. These tokenizer packages were already
installed transitively by manga-ocr and are now explicit runtime dependencies.

`uv run pytest`: **36 passed**, including the original 13 Phase 1 tests. New tests
use actual lightweight fugashi tokenization, hand-authored JMdict fixtures, and mocked
OCR. They do not require downloaded weights or the full JMdict source.

The official `JMdict_e.gz` was downloaded and successfully imported locally:
**218,844 English entries**. The database and source are ignored by Git. The database
metadata table records the source SHA-256 and import timestamp; a later JMdict release
may produce different counts and dictionary candidates.

These commands were run against that actual database:

```powershell
uv run python scripts/analyze_text.py "でも大丈夫"
uv run python scripts/analyze_text.py "食べました"
uv run python scripts/analyze_text.py "高かった。猫とYomiScan！"
```

Observed: `大丈夫` has reading `だいじょうぶ` and dictionary senses including safe,
all right, and okay. UniDic-lite splits the opening into `で / も`. Inflected `食べ`
resolves to `食べる` with "to eat" among its meanings; `高かっ` resolves to `高い`.
Punctuation is retained without lookup, and `YomiScan` has no entry or invented reading.
Homonyms and archaic senses are also returned; these results do not validate automatic
sense disambiguation or phrase-level understanding.

After a local screenshot was supplied, the full pipeline was run successfully:

```powershell
uv run python scripts/analyze_image.py "samples/Screenshot 2026-09-29 154812.png" --cpu
```

The command exited successfully, with 303 ms of OCR inference time (excluding model
startup), followed by 23 tokens and local JMdict candidates. The screenshot and full
analysis report remain local and ignored by Git.

This real-image run also exposed limitations: `世間体` was split into `世間 / 体`,
multi-token expressions were not reconstructed, and unrelated homonyms appeared in
dictionary results. Successful execution does not establish broad OCR accuracy or
context-specific dictionary sense selection.
