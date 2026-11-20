# Post-MVP Translation Improvements

Stage 3 merged as `4b51ce5d619f8a7dfb15e7bf7bbe34a2473ba1ef`. This increment
implements P09/P18/P19/P20 without replacing the English OPUS production baseline.

## Implementation design

- User-confirmed series and terminology live in a separate local SQLite user-data
  store, never in the disposable processing cache. Series selection is explicit,
  per reader session; no permanent series ID is derived from a URL.
- Small immutable translation options describe target, glossary scope, structured
  mode, ordering and bounded context. Engines explicitly declare capabilities.
  Existing independent-sentence calls remain valid; unsupported combinations fail.
- Glossary hints are selected at normalized Japanese token boundaries, longest
  applicable match first. Raw OCR and final translated sentences are never rewritten.
  Global entries are overridden by the selected series for the same written term.
  OPUS has no glossary enforcement capability and continues its ordinary batching.
- Detection/grouping and crop OCR retain stable block IDs. Optional panel ordering
  happens after extraction, preserving those identities and cached OCR. Ambiguous
  geometry falls back to the existing band order without dropping text.
- Compatible local LLMs can opt into exact-ID JSON-schema generation through the
  existing llama.cpp transport. Complete structure, termination and budgets are
  validated; failed/partial pages have no implicit independent-line fallback.
- Translation keys describe effective target, matched glossary hints, exact IDs,
  ordered source, context and grammar/prompt contract. Renderer lineage inherits
  these changes. Unchanged extraction and lexical entries remain reusable.
- Reader controls carry explicit options and an expected glossary version. Settings
  or glossary edits invalidate affected overlays and reject stale completions.
- Experiments compare ordering separately from translation and structure separately
  from meaning. New targets and panel/context modes remain explicitly experimental.
  Existing cached models are used first; no automatic new model downloads are needed.

Measured results and adoption decisions are recorded in
[Stage 4 results](research/stage4-translation-results.md). Historical reports remain unchanged.

## Reader use

Rebuild/reload the extension and restart the updated backend. Open **Translation &
terminology** in the existing chapter panel. Create a user-confirmed series, select
it, add Japanese/preferred terms, or edit/delete an existing entry. Global defaults
apply underneath series overrides. Entries are scoped by target language. Enable
**Use terminology hints** explicitly. No series is inferred from a website URL.

The local database defaults to `data/glossaries.sqlite3`; an explicit
`YOMISCAN_GLOSSARY_DATABASE` can choose another user-data path. Back it up separately
from caches. Clear Persistent Cache and Clear Session preserve it. Delete Entry and
Delete Series Glossary are the explicit deletion controls; global defaults cannot be
deleted as a series. Limits are 100 named series and 1,000 terms per scope/target.
Corruption is reported, never silently repaired by erasing user data. Stop the backend
before moving/restoring the database. The owning worker creates, uses and closes it.

Changing effective settings removes obsolete overlays. Saving/deleting terminology
invalidates affected active readers, including the editing tab even if its profile
reload fails. A pending request carries the expected effective glossary hash; stale
versions receive HTTP 409. Unrelated terms can reuse backend translation entries.

OPUS, Fugu and NLLB have no glossary-hint enforcement path. OPUS continues ordinary
native batching. Hy-MT2 and Qwen2.5 manga adapters receive only applicable hints;
word senses and spelling enforcement remain model-dependent. Homographs cannot be
disambiguated just from written terms. Hints never rewrite source OCR or final sentences.

## Optional contracts and targets

Existing `YOMISCAN_TRANSLATION_ENGINE` selects a single backend engine; there is no
model manager or automatic selection/download. Existing local model setup is described
in [translation benchmarks](translation-benchmark.md). Reader controls disable
unsupported contract/target combinations.

| Engine | Targets | Structured ID modes | Terminology |
|---|---|---|---|
| `current` (OPUS) | English, default | No | Stored/editable, not applied |
| `hy-mt2-manga`, `qwen25-manga` | English | Experimental line/page/panel | Hints, no guarantee |
| `fugumt` | English | No | Not applied |
| `nllb-600m` | English; experimental PT/ES | No | Not applied; CC-BY-NC-4.0 |
| `opus-ja-pt` | Experimental generic Portuguese | No | Not applied; new weights not tested |
| `opus-ja-es` | Experimental Spanish | No | Not applied; new weights not tested |
| `qwen35-vntl` | English declared; genuine artifact still unavailable | Disabled | Unverified legacy hint path |

English stays the default. PT is represented by `pt-BR` in the request contract,
but the tested models target generic Portuguese: Brazilian register is unverified.
All new targets are labeled experimental, with observed quality limitations in the
results report. Study's sentence label follows the backend engine's actual target;
JMdict definitions remain English. Full UI localization is outside this increment.

New OPUS target engines require an explicitly prepared pinned local cache and fail
clearly otherwise. The following commands are **optional downloads**, not part of
startup or validation; they were not run during this task:

```powershell
uv run python scripts/prepare_translation_models.py --engine opus-ja-pt
uv run python scripts/prepare_translation_models.py --engine opus-ja-es
$env:YOMISCAN_TRANSLATION_ENGINE = 'opus-ja-es'
```

Structured generation uses the same owned, keyed loopback llama.cpp subprocess.
Use the verified b11380 build. Schema requires every requested `Bnnn` key exactly
once and forbids extra keys; null represents refusal but fails the whole-page
validator. No partial result, changed model or silent per-line fallback is published.
Failure preserves original pixels or the previous successful refresh.

Limits: 32 nonblank blocks / 8,000 source characters; six complete context lines /
2,000 characters; 16 matched hints / 1,000 characters; exact templated-token count,
64-token reserve and at most 2,048 output tokens in the configured context. Over-budget
input fails without truncating Japanese. Cancellation interrupts the owned runtime
and may require a subsequent reload. Source/token limits can reject a dense page;
choose ordinary sentences explicitly instead of expecting an automatic fallback.

**Panel order** independently enables conservative white-gutter XY cuts on a maximum
640-pixel raster. Unclear dark, borderless, diagonal/crossed gutters and unsafe cuts
can fall back to bands. Every ID is emitted exactly once; geometry never infers speakers.
Optional context is separate read-only data: neighbors, same-panel, or nearest page
lines. Selection is capped by whole lines, never cropped strings. No previous-page
memory or generated narrative is retained. Page mode already sees all requested
source lines, so adding the same lines as context is intentionally unnecessary.

## Reproduce bounded experiments

All raw JSON and blank human-rating sheets should remain under ignored `.cache/`.
The runner forces offline model loading, selects one engine, and never downloads
weights. Input manifests accept only the known local artifact variables.

```powershell
uv run --frozen python scripts/benchmark_ordering.py --output .cache/ordering-new.json
uv run --frozen python scripts/benchmark_translation_improvements.py --engine hy-mt2-manga --device cuda --local-manifest models/manga/hy-mt2-manga-paths.json --llama-server .cache/llama-b11380/llama-server.exe --case page-training --limit 1 --output .cache/structure-new.json
uv run --frozen python scripts/benchmark_translation_improvements.py --engine hy-mt2-manga --device cuda --local-manifest models/manga/hy-mt2-manga-paths.json --llama-server .cache/llama-b11380/llama-server.exe --case context-refusal --case page-training --limit 2 --modes structured-line,structured-panel --contexts none,neighbor,panel,page --glossary --output .cache/context-new.json
uv run --frozen python scripts/benchmark_translation_improvements.py --engine nllb-600m --device cpu --targets en,pt-BR,es --modes sentences --limit 8 --output .cache/targets-new.json
```

Ordering optionally accepts `--annotations .cache/local-order.json`: a JSON array
of `{id,image,blocks:[{id,bbox:[left,top,right,bottom]}],order:[ids],ambiguous:false}`.
Image paths are relative to that manifest. Use null order for unscorable ambiguity.
No supplied images or private annotations belong in Git. Synthetic adjacent pairs
in the text runner are grouping controls, not validated real manga panel membership.

Structural counters and warm wall time are independent of semantic ratings. Raw replies
are retained only by this explicit local benchmark, not exported by normal reader
diagnostics. Human scores remain blank until qualified review. See the results report
for failed candidates and the limits of this small original-text corpus.
