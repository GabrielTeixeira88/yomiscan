# Post-MVP Stage 4 — Translation results and adoption decisions

Measured locally on **2026-11-20**. Stage 3 was merged through PR #3 as
`4b51ce5d619f8a7dfb15e7bf7bbe34a2473ba1ef`; Stage 4 branches from that commit.
The historical Phase 1–7 and previous translation/vision/cache reports are unchanged.
This report describes working optional functionality and limited experiments, not
a new quality winner. English OPUS, original manga-ocr and PyTorch detection at
0.50/0.50 remain production defaults.

## Reproduction and evidence boundaries

Implementation: `glossary.py`, `translation/options.py`, `translation/structured.py`,
`translation/manga.py`, `translation/marian.py`, `translation/nmt.py`, `panel_order.py`,
`analysis.py`, `page.py`, `service.py`, and the extension's `chapter/translation-*`.
Commands/contracts are in [Stage 4 usage](../post-mvp-translation-improvements.md).
[Primary-source checks](stage4-primary-sources.md) pin Yomu history, runtime APIs and
model cards. All implementation is independent; no AGPL source was imported.

Environment: Windows, Python 3.13, Intel i7-14700K, NVIDIA RTX 4070 SUPER with
12,282 MiB reported VRAM/driver 621.01. Installed Torch 2.14.0 is CPU-only;
Transformers 5.17.0, tokenizers 0.23.2, Pillow 12.3.0, NumPy 2.5.3. llama.cpp's
separate CUDA build works on that GPU. An explicit NLLB CUDA attempt failed clearly;
the documented multilingual results use CPU. No replacement CUDA install was made.

All inference used already cached weights with HF/Transformers offline flags.
The unchanged OPUS baseline is `Helsinki-NLP/opus-mt-ja-en` at
`0770961a39ba6bd66305b149c3f4110bcafca2e6`, weight SHA-256
`ed649116c143fc2d7aea690246f4b2b7caa814e9e00a8d5bbe047822b18de022`.
Only model cards/config/tokenizer metadata and a licensed font were fetched during
this increment; no new model weights were downloaded. No CAT or smaller Qwen candidate
was added merely to populate a benchmark. VNTL's genuine artifact remains unavailable.

The source is the existing original `benchmarks/manga-dialogue.jsonl`, SHA-256
`1d7727c08e70517a03616744ede1d7c313df7f5445ab3018a3c1282f4bc16962`.
Structure set: `casual-2`, `subject-2`, `negation-long`, `direction`, `context-left`,
`context-refusal`, `context-acceptance`, `page-training`: **8 cases / 15 lines**.
Context set: the three `context-*` contrasts plus `page-training`: **4 cases / 11 lines**.
Multilingual set: `casual-2`, `subject-2`, `tone-rough`, `tone-teen`, `negation-long`,
`direction`, `context-refusal`, `page-training`: **8 cases / 15 lines per target**.
The page scene is eight developer-authored bubbles. These tiny sets are not a
representative accuracy corpus; no copyrighted pages were added.

Each model was loaded once per run, then evaluated sequentially, temperature 0,
seed 0, repeat penalty 1.0 for llama.cpp. Prompt cache reuse was disabled. Measurements
are single-run wall times, not confidence intervals or controlled CPU-vs-GPU speed
rankings. Initialization is a fresh engine/process with potentially warm OS caches;
it excludes subsequent cache-identity hashing. Page latency is measured around the
whole request, never the sum of per-result group timings. RSS/peak RAM/peak VRAM were
**not measured**: optional psutil was absent and process snapshots would not establish
peaks. Available VRAM is hardware capacity, not observed usage.

Raw results, raw model replies and blank review CSVs remain local in ignored
`.cache/stage4/` (`hy-structure`, `qwen-structure`, `hy-context`, `hy-glossary`,
`nllb-targets-cpu`, `opus-baseline`, `ordering`). Human fields remain blank. The
observations below are source/reference-based assistant spot checks, not native
PT-BR/Spanish review or a scored bilingual study. No BLEU/accuracy percentages were invented.

## P09 — Scoped terminology: ADAPT

**Working behavior.** Local SQLite user data at `data/glossaries.sqlite3`, separate
from disposable processing entries. Reader UI creates/selects/deletes series and
adds/edits/deletes target-specific terms. Global terms apply underneath selected
series overrides. An explicit user label/UUID identifies a series; no URL, browsing
history or manga pixels are stored for identification. Cache clear preserves terms.
Bad user databases are preserved and reported, never auto-deleted as cache corruption.

`applicable_terms()` normalizes source/entries with NFKC, aligns actual morphology
token surfaces, then selects exact matches beginning/ending at complete token
boundaries, longest nonoverlapping term first. Failed alignment yields no hints.
The original OCR and final translated sentence are never rewritten. Written
homographs remain ambiguous; scope and manual editing reduce mistakes but cannot
provide word-sense disambiguation.

**Engine distinction.** Hy-MT2 and Qwen2.5 have a functional hint prompt path in
native and optional structured modes. OPUS/Fugu/NLLB do not enforce glossary terms;
they keep normal sentence translation. VNTL's legacy prompt path is not validated
by real inference and has no structured capability. Yomu's arbitrary source substring
replacement was deliberately not adopted.

**Real hint smoke.** On the original eight-line page, Hy received `レン→Ren` and
`霊力→spirit energy`. Native, singleton-ID, whole-page-ID and panel-ID outputs used
those preferred forms. This confirms a usable hint path on one small example,
not reliable enforcement: the same outputs still confused subjects/possessors
elsewhere. With glossary plus panel context, the previously failing Hy singleton
panel case terminated successfully in this run; that is not a general causal result.

**Regression evidence.** Model-free tests cover CRUD/restart, series/target isolation,
global overrides, normalized duplicates, overlapping entries, token/substrings,
homographs, disabled/unsupported engines and unchanged OCR. Integration tests show
matched edits invalidate translation/render while reusing extraction and lexical
work; unmatched edits reuse backend results. The browser invalidates changed
glossaries in other active tabs and immediately in the editing tab, even if the
profile reload fails. Backend expected-version checks reject obsolete jobs with 409.

**Decision.** Adopt management/storage and adapt terminology as bounded hints.
Do not claim OPUS enforcement or apply global post-translation replacements.

## P18 — Exact-ID local translation: EXPERIMENTAL

**Runtime and artifacts.** llama.cpp b11380, commit
`eec18f5d32099fb15d4ba15003a231bcc72757d5`; executable SHA-256
`ca0a54c79b6045c7fa76718ab4f616d21bb2a15e625ab2380fdc429b28fe137b`.
Both engines used context 4,096, one slot, existing loopback/auth/subprocess ownership.

| Model | Exact artifact identity | License boundary |
|---|---|---|
| Hy-MT2 manga v5 Q4_K_M | `fumetodev/Hy-MT2-1.8B-JP-Manga-Finetune-v5-GGUF` at `e17bc6a8dd92ddf930bd7858ceb916117ee5f916`; `manga-v5-Q4_K_M.gguf`, SHA `e4ed3cf8535c4e99e4b9f3d930ecc6f93bc3b3e0b4b5edca872c4cff5a112abe` | Pinned GGUF card declares Apache-2.0; Tencent's upstream license/notice remains separate from YomiScan MIT; no weights bundled |
| Qwen2.5 7B manga LoRA | Adapter `NaelShichida/qwen2.5-7b-manga-translator-full` at `4267f42e98fcc2daa36096cea8524a926cbb84d1`; converted F16 LoRA SHA `cc97fcc06f52aec7a6df135b677eab521ba5018c095812c95b47bc0dac2ff880` | Apache-2.0 publisher/base declarations; retain artifact provenance separately |
| Qwen base GGUF | `Qwen/Qwen2.5-7B-Instruct-GGUF` at `bb5d59e06d9551d752d08b292a50eb208b07ab1f`, two Q4_K_M shards; first SHA `dfce12e3862a5283ccfb88221b48480e58745165de856439950d0f22590580db`; all-shard identity digest `d8cf4823534b583118699ce5262137c72f1141938d22547965346a240438e0c4` | Both actual shards, converted adapter and runtime libraries participate in cache identity |

`id-json-v1` requires exactly the actual stable `Bnnn` keys, no additional keys, and
string-or-null values. Null permits refusal without forcing invented content; a
null, blank, missing, extra, duplicate or oversized value fails the complete result.
JSON must be complete; `finish_reason=length` fails even if a plausible prefix exists.
The server receives `response_format:{type:"json_schema",json_schema:{schema:…}}`.
The validator still independently checks the response; grammar is not trusted alone.

Input is counted by the actual model chat template plus tokenizer API. Full Japanese
is rejected when source/context/token budgets exceed limits. There is no silent
string truncation. Cancellation stops the owned process; timeout/runtime failures
are explicit. No model substitution, automatic line fallback or partial-page cache
publication occurs. The prior good refresh/original page remains available.

| Engine/mode | Complete cases | Actual completion calls | Rejected structural calls | Median case ms | Eight-line page ms |
|---|---:|---:|---:|---:|---:|
| OPUS native CPU baseline | 8/8 | Native batches, no IDs | ID metric not applicable | 242.9 | 865.8 |
| Hy native CUDA | 8/8 | 15 independent lines | ID metric not applicable | 81.1 | 798.3 |
| Hy structured line | 8/8 | 15 | 0 | 159.6 | 1,659.6 |
| Hy structured page | 8/8 | 8 | 0 | 183.9 | 910.4 |
| Hy structured panel | 8/8 | 11 | 0 | 172.2 | 1,385.1 |
| Qwen native CUDA | 8/8 | 15 independent lines | ID metric not applicable | 289.2 | 2,708.6 |
| Qwen structured line | 7/8 | 15 | 1 | 632.3 | 6,092.7 |
| Qwen structured page | 7/8 | 8 | 1 | 642.4 | 3,142.8 |
| Qwen structured panel | 7/8 | 11 | 1 | 620.1 | 4,073.5 |

Hy initialization: **1,591.6 ms**; Qwen **6,266.9 ms**; OPUS **8,342.2 ms**.
Successful structured input-token ranges: Hy line135–158/page135–331/panel135–175;
Qwen line145–162/page145–355/panel145–182. Raw usage and output token counts are
retained locally; native calls use each unchanged adapter's existing output budget.
Structured output budgets are bounded by group size and capped at 2,048 tokens.

The three Qwen failures are the same `subject-2` source under three contracts:
generation reached its token limit, the raw JSON was incomplete, and the whole case
was rejected. This is **1/15, 1/8, 1/11 completion calls**, respectively, not three
independent linguistic samples. Missing/extra/duplicate/wrong-count counters were
zero among parseable completed replies; incomplete replies are counted separately
as invalid format/truncation/failed termination, not silently scored as aligned.
Synthetic panel calls use adjacent pairs; they are not a real-panel segmentation score.

**Semantics.** Exact keys did not prevent wrong speaker content inside a string.
In the eight-line scene Hy page mode assigned the observation about shaking hands
to “my hand,” then translated the promise as not pushing “you” too hard. Singleton
and panel arms differed on those references. These are warning examples, not a
human-rated improvement/regression rate. There is no demonstrated quality winner.

**Decision.** Retain strict optional structure and clear failure provenance.
Keep both LLMs experimental; do not replace OPUS or claim schema fixes meaning.
The page contract's smaller call count did not beat native independent Hy on this page.

## P19 — Geometry and context: EXPERIMENTAL / INCONCLUSIVE

### Ordering measured independently

`benchmark_ordering.py` runs **eight original synthetic layouts** without OCR or
translation: tall right panel/stacked left panels, regular grid, tall columns,
horizontal rows, borderless, dark gutters, a crossing block and diagonal crossing art.
Four have explicit unique reading-order labels; the four ambiguous cases are left
unscored for correctness and instead checked for fallback/integrity.

| Layout | Bands exact | Panel candidate exact | Candidate fallback | Candidate ms |
|---|---|---|---|---:|
| Tall right / stacked left | No; pairwise4/6 | Yes;6/6 | No | 8.08 |
| Regular grid | Yes | Yes | No | 1.18 |
| Tall columns | No;4/6 | Yes;6/6 | No | 1.01 |
| Horizontal rows | Yes | Yes | No | 0.84 |
| Borderless | Unscored | Unscored | Insufficient evidence | 0.23 |
| Dark gutters | Unscored | Unscored | No unambiguous white gutter | 1.84 |
| Crossing block | Unscored | Unscored | No safe cut | 1.00 |
| Diagonal crossing art | Unscored | Unscored | No safe cut | 1.20 |

Labeled exact orders: bands **2/4**, candidate **4/4**. All **16 strategy/layout
combinations** emitted exactly the same input ID set/count and were deterministic
under reversed input enumeration. Those are synthetic test results, not a real manga
accuracy estimate. No trustworthy per-panel real-page annotation corpus was available;
the runner supports private local annotation manifests for that next test.

The independent algorithm downsamples to at most640 pixels, finds interior near-white
horizontal/vertical projection cuts, refuses cuts through text blocks, reads rows
top-down and columns RTL, and keeps band order inside terminal leaves. Sparse evidence,
unseparable art and invalid partitioning fall back deterministically. Stable IDs and
OCR crop identities remain unchanged; selected ordering is its own cached dependency.
Whitespace inside artwork can still masquerade as a panel. Speakers/genders are never inferred.

### Bounded context experiment

After the geometry test, the text-only control compares the same frozen sources in
structured-line and synthetic-panel modes with no/neighbor/panel/page context. The
single-line contrasts have explicit original previous/following lines in the dataset;
these are read-only benchmark inputs, not persistent cross-page memory. The eight-line
scene supplies page-local lines. Context ID provenance is retained; no context-only
ID is requested as output.

Hy completed **31/32 case/configuration trials**. The failed arm is singleton plus
panel context on the eight-line scene, with one capped, incomplete generation; its
entire result was rejected. No/neighbor/page singleton arms completed4/4 each;
all four panel-mode context arms completed4/4 each. No lost/extra IDs occurred in
parseable completed replies. One null or partial reply would still reject the case.

| Contrast | No context | Bounded context | Interpretation |
|---|---|---|---|
| Refusal `いい。` after an offer, followed by being full | “Yes.” | “Yes. That's fine.” | Still conflicts with the supplied refusal reference |
| Approval with the same current Japanese | “Yes.” | “Yes. That's fine.” | Does not demonstrate successful contextual disambiguation |
| Absent Ren / already went home | “Already gone home?” | Same | No demonstrated reference recovery |

The page scene's shaking-hand/subject references still varied with context. An ID
contract prevents translating the *ID* of a neighbor, but cannot detect dialogue
contamination inside an allowed string. The earlier failed context experiments and
Yomu's withdrawn cross-page memory remain reasons for caution.

**Decision.** Optional geometry is benchmarkable and safe against ID loss; keep bands
as default until representative labeled pages support it. Context remains experimental;
semantic benefit is inconclusive with observed negative examples. Do not enable
unrestricted memory or infer identity from coordinates.

## P20 — PT-BR/Spanish: EXPERIMENTAL, Brazilian quality INCONCLUSIVE

| Candidate | Pinned revision | Target handling | Actual evaluation |
|---|---|---|---|
| `Helsinki-NLP/opus-mt-ja-pt` | `15f163ca52b8d17d729d3c76aa3d9eabc4213367` | Six beams; tokenizer prefix`>>por<<` at ID2; generic Portuguese | Adapter/model-free tests and metadata verified; new weights not downloaded/inferred |
| `Helsinki-NLP/opus-mt-ja-es` | `d1693e4d2bc285d02653ff6438fe21e2b3c6025e` | Six beams; no target prefix | Adapter/model-free tests and metadata verified; new weights not downloaded/inferred |
| `facebook/nllb-200-distilled-600M` | `f8d333a098d19b4fd9a8b18f94170487ad3f821d` | Japanese source, explicit forced EN/PT/ES target token; four beams,FP32 | Real cached CPU inference,8 cases/15 lines per target |

OPUS PT weight descriptor:311,664,297 bytes, SHA
`e183e563daba1765d122bb750befd10970dd2d6d4a8a8b766bcc58b757e3ade6`.
ES:305,760,693 bytes, SHA
`df2ef58064ec5bcb42bd35d6aa7ea1b19856d6f1a73b73e94d401cc12971f29f`.
Cards declare **Apache-2.0**. These hashes are publisher metadata checked against
the loading/preparation contract, not a claim that unacquired bytes were locally hashed.
The adapter fails without the pinned local artifact; English behavior is unchanged.

NLLB's actually cached weight is2,460,457,927 bytes, SHA
`c266c2cfd19758b6d09c1fc31ecdf1e485509035f6b51dfe84f1ada83eefcc42`.
Its **CC-BY-NC-4.0** license is a material noncommercial constraint; it is not an
unrestricted deployment recommendation. No weights were redistributed. Forced tokens
are verified against the actual tokenizer; changing a UI language does not relabel an
English-only engine or introduce an English pivot.

| NLLB target | Completed cases/lines | Median case ms | Eight-line page ms |
|---|---|---:|---:|
| English | 8/8;15/15 | 1,374.5 | 3,288.5 |
| Generic Portuguese (`pt-BR` experimental request) | 8/8;15/15 | 1,406.2 | 3,309.3 |
| Spanish | 8/8;15/15 | 1,764.7 | 2,892.7 |

Initialization was 11,260.8 ms. Completion means count/source identity and EOS checks
passed; it does not mean meaning was preserved. The Spanish refusal took25,349.8 ms
and emitted a long repetition of “No” before EOS. Thus EOS/format checks alone cannot
classify a degenerate translation as semantically successful.

**PT observations.** `知らねーよ` produced “Eu sei.”, losing negation. The double-negation
case began “Não quero ajudá-lo.”, contrary to the supplied meaning. “ainda estás a
treinar” and “As mãos estão a tremer” show generic/European Portuguese phrasing rather
than validated Brazilian register. Names may be retained, but the power term and
subjects varied across sentences. Honorifics and broader manga register are not
covered adequately by these selected15 lines and remain unverified.

**ES observations.** The dismissive negative produced “Ya lo sabes.” and the longer
double negation lost its intended meaning. The refusal repeated “No”; the eight-line
scene still changed subjects/intentions. Sampled outputs looked Portuguese/Spanish
in gross language terms; no calibrated wrong-language classifier or native review was
performed, so there is no asserted wrong-language error rate or naturalness score.

**Rendering.** Tests exposed missing accents in Pillow's Aileron subset. Stage 4 adds
unmodified Noto Sans2.015 (OFL-1.1,2,049,096 bytes; exact source/hash/notice bundled)
only when the existing font lacks glyphs. PT/ES punctuation and accent samples now
fit and paint; ASCII English keeps Aileron. Unsupported scripts still fail before
erasing original artwork. This validates the renderer path, not translation quality.

**UI decision.** English remains default. Only actual engine capabilities enable a
target, and PT/ES are explicitly experimental. Portuguese states Brazilian usage is
unverified/generic. NLLB gives a working evaluated path; direct OPUS targets remain
clearly experimental adapters pending weights and bilingual evaluation. Qwen/Hy manga
fine-tunes remain English-only. Study's generated-sentence label follows its backend
target; JMdict meanings remain English. No full UI/dictionary localization or model
manager was implemented.

## Cache, diagnostics and regression decision

Translation identities include actual model/runtime artifacts (including every GGUF
shard), target, source order/IDs, effective matched target-specific hints, exact
context, prompt/grammar versions and algorithm identities. Changing these invalidates
translation and dependent rendering. Detection/OCR and unchanged morphology/dictionary
entries are independently reusable; renderer font identity changes only rendering.
Expected glossary versions and browser generations prevent stale attachments. Failed
structured refreshes never poison a prior successful cached result.

Normal diagnostics expose bounded target/mode/context IDs, grammar and token metadata,
failure codes, order/fallback and cache provenance. They do not export raw model replies,
glossary databases or context prompt text by default. Benchmark raw replies are an
explicit local-only tool feature; Stage 1 consent/redaction and ZIP ownership remain.

The frozen local model-free backend suite passed **299 tests with one existing Windows
atomic-replacement skip** and the existing Starlette/httpx deprecation warning.
The extension passed **59 tests**, clean `npm ci` and strict build. Package imports and
wheel build passed; the wheel contains the font and its license. Isolated Chrome157
passed **31 checks** with a mocked backend (no browser-model accuracy claim), including
Study selection/copy/drag/resize, reader/capture/refresh/report controls, a24-page
192MiB LRU workload, glossary CRUD, target invalidation and successful-save/failed-profile
invalidation, including repeated edits after failed profile reloads. That run's long
mocked queue took 22,942 ms; it is not neural latency.
Final suite counts and hosted checks are recorded in the PR/final implementation report.
Model-free tests include persistence/restart, clear separation, real
capability routing, target switching/font coverage, selective translation refresh,
exact schema/invalid output, token budgets, timeout and in-flight cancellation,
ordering integrity and settings-based cache reuse. They are not model-accuracy tests.

### Standards review

The separate standards review against Stage 3 found two related stale-overlay cases:
a successful write followed by a failed profile reload, and a subsequent event when
the editor still had an unknown hash but a newly started session knew the latest hash.
Both are fixed by immediate explicit invalidation independent of option equality,
with browser fault-injection coverage. The reviewer rechecked `a660b3d` and found no
remaining blocker. A narrow analyzer accessor instead of private-field inspection
remains a nonblocking maintainability advisory; this stage does not introduce a rewrite.

### Spec review

The independent specification review identified the successful-write/failed-reload
gap, then verified its correction, null-cache rejection, cancellation and target
contracts. It found no unrelated scope expansion and accepted the report's explicit
limits on synthetic geometry, unrun OPUS target weights, generic PT, human review and
single-run timings. No remaining concrete blocker was identified in that axis.

## Final adoption decisions

| Item | Decision | Evidence needed before promotion |
|---|---|---|
| P09 scoped management + safe hint path | **ADAPT** | Broader terminology/homograph review; never imply OPUS enforcement |
| P18 strict structured local capability | **EXPERIMENTAL** | Larger frozen multi-bubble set, independent semantic/speaker review, repeated timing; Qwen cap failures remain |
| P19 white-gutter order | **EXPERIMENTAL** | Labeled real pages including borderless/dark/diagonal/art-crossed gutters |
| P19 context quality | **INCONCLUSIVE** | Bilingual paired meaning/contamination study; current refusal contrast is negative evidence |
| P20 multilingual adapters/controls | **EXPERIMENTAL** | Exact direct OPUS weight evaluation plus native PT-BR/ES review of negation/register/names/honorifics |
| P20 Brazilian quality | **INCONCLUSIVE** | Region-specific references and qualified reviewers; current generic PT is insufficient |
| Automatic default/model migration; unrestricted memory | **REJECT** | No evidence warrants replacing the functioning MVP |

The useful adoption is local terminology management plus explicit, bounded experimental
contracts and reproducible evaluation. Do not ship a claim that grammar, larger models,
more context, or a language dropdown has solved manga translation accuracy.
