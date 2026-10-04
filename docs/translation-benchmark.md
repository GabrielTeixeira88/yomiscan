# Manga translation benchmark and selection

**2026-10-03 decision: keep `current` (OPUS-MT) as the application default.**
Hy-MT2 Q4_K_M is the strongest experimental candidate: compact, fast, and better on
several slang/name examples. It still makes important meaning errors. Qwen2.5 adds
unsupported dialogue; Qwen3.5 VNTL's published repository has no model artifacts.
No tested candidate earns a recommended “quality mode.” Deferring replacement does
not mean the baseline's known errors are acceptable or solved.
The subsequent FuguMT/NLLB comparison below retains that decision: Fugu greedy decoding
is a useful fast CPU experiment, but neither new candidate established semantic superiority.

## Architecture and lifecycle

The original `TranslationEngine` contract remains. An optional
`ContextualTranslationEngine` adds keyword-only `TranslationContext` with previous/
following lines, glossary and tone. `TranslationResult.device` reads existing
metadata, preserving older constructors. Tokenization and JMdict are unchanged.

`translation/factory.py` selects the baseline or an optional adapter. Normal startup
never loads/downloads all candidates. Each manga engine loads on first use; benchmarks
explicitly load first to time initialization. It owns one hidden, authenticated
**127.0.0.1-only llama.cpp subprocess**, reused until `close()`. Service shutdown
closes it. Its HTTP protocol is local inference, **not a paid OpenAI API call**.

Hy and Qwen2.5 translate independent lines sequentially with the same loaded model;
that is not native tensor batching. Marian retains its real batching. VNTL sends
ordered lines in one prompt, validates output count, then removes context outputs.
Empty/truncated responses, incorrect counts, markup and multi-line Qwen2.5 responses
raise errors. Count checks cannot detect semantic reordering or multiple bubbles
blended onto one line; real Qwen2.5 output demonstrates this limitation. No parser
silently chooses the first line or substitutes another engine's translation.

## Exact models and licenses

| Engine | Artifact/revision | Download | License |
|---|---|---|---|
| `current` | `Helsinki-NLP/opus-mt-ja-en`, `0770961a39ba6bd66305b149c3f4110bcafca2e6` | ~303 MB weights + tokenizer | HF checkpoint declares Apache-2.0; existing OPUS/data caveats remain |
| `hy-mt2-manga` | `fumetodev/Hy-MT2-1.8B-JP-Manga-Finetune-v5-GGUF`, `e17bc6a8dd92ddf930bd7858ceb916117ee5f916`, `manga-v5-Q4_K_M.gguf` | 1,133,080,512 bytes | Publisher Apache-2.0; upstream Hy-MT2 license also Apache-2.0 |
| `qwen35-vntl` | `0xBrandon/Qwen3.5-4B-VNTL-V1`, `bf7b11333a9ef958ed4646dcc18dea9f757a6e08` | **No weights/config/adapter published** when checked through HF API; only README and `.gitattributes` | Card declares Apache-2.0 |
| `qwen25-manga` | `NaelShichida/qwen2.5-7b-manga-translator-full`, `4267f42e98fcc2daa36096cea8524a926cbb84d1` + `Qwen/Qwen2.5-7B-Instruct` | 161,533,192-byte LoRA + base | Adapter card and base declare Apache-2.0 |

Qwen2.5 uses official `Qwen/Qwen2.5-7B-Instruct-GGUF`, revision
`bb5d59e06d9551d752d08b292a50eb208b07ab1f`, both
`qwen2.5-7b-instruct-q4_k_m-00001-of-00002.gguf` (3,993,201,344 bytes) and
`...00002-of-00002.gguf` (689,872,288 bytes). Total **4.68 GB decimal** plus LoRA.
The downloaded adapter converts to ~80.7 MB F16 GGUF using official llama.cpp tools.
Base configuration is pinned to `a09a35458c702b33eeacc393d103063234e8bc28`.
This is quantized-base + LoRA inference, not an unadapted base, training or fine-tuning.

Sources: [baseline](https://huggingface.co/Helsinki-NLP/opus-mt-ja-en),
[Hy](https://huggingface.co/fumetodev/Hy-MT2-1.8B-JP-Manga-Finetune-v5-GGUF),
[Hy upstream license](https://huggingface.co/tencent/Hy-MT2-1.8B/blob/main/LICENSE.txt),
[VNTL](https://huggingface.co/0xBrandon/Qwen3.5-4B-VNTL-V1),
[Qwen adapter](https://huggingface.co/NaelShichida/qwen2.5-7b-manga-translator-full),
[Qwen GGUF base](https://huggingface.co/Qwen/Qwen2.5-7B-Instruct-GGUF).
Weights are not bundled or covered by YomiScan's MIT license. Preserve their licenses,
attribution and applicable NOTICE material when redistributing. llama.cpp is MIT;
the optional psutil dependency is BSD-3-Clause.

## Setup and selection

Windows/Python **3.13.9** worked without changing the Python requirement. Installed
PyTorch is `2.14.0+cpu`; llama.cpp provides CUDA independently. No PEFT, bitsandbytes
or Python llama binding is required for normal startup. No dependency incompatibility
was encountered. The only new Python dependency is optional benchmark-only psutil.

```powershell
uv sync --extra benchmark
```

From [llama.cpp b11380](https://github.com/ggml-org/llama.cpp/releases/tag/b11380),
extract `llama-b11380-bin-win-cuda-12.4-x64.zip` (~264 MB) and
`cudart-llama-bin-win-cuda-12.4-x64.zip` (~391 MB) into ignored
`.cache/llama-b11380/`. Preserve accompanying DLLs. CPU-only users can instead
extract `llama-b11380-bin-win-cpu-x64.zip` (~19 MB). Other operating systems require
their native executable; Linux/macOS were not tested. No global install is necessary.

```powershell
$env:YOMISCAN_LLAMA_SERVER = (Resolve-Path '.cache/llama-b11380/llama-server.exe').Path
uv run python scripts/prepare_translation_models.py --engine hy-mt2-manga
$paths = Get-Content models/manga/hy-mt2-manga-paths.json | ConvertFrom-Json
$env:YOMISCAN_HY_MT2_GGUF = $paths.YOMISCAN_HY_MT2_GGUF
uv run python scripts/translate_text.py --engine hy-mt2-manga --device auto "何してんだよ"
```

Preparation downloads pinned artifacts and verifies Hy's published SHA-256. Weights
use the normal HF cache (`~/.cache/huggingface/hub`, or `HF_HOME`); Windows without
symlinks can require extra disk space. Later inference reads local files only.
Generated paths, weights and converter outputs stay under ignored directories.

Optional Qwen2.5:

```powershell
git clone --depth 1 --branch b11380 https://github.com/ggml-org/llama.cpp.git .cache/llama-converter
uv run python scripts/prepare_translation_models.py --engine qwen25-manga --llama-source .cache/llama-converter
$paths = Get-Content models/manga/qwen25-manga-paths.json | ConvertFrom-Json
$env:YOMISCAN_QWEN25_GGUF = $paths.YOMISCAN_QWEN25_GGUF
$env:YOMISCAN_QWEN25_LORA = $paths.YOMISCAN_QWEN25_LORA
```

The helper verifies converter commit `eec18f5d32099fb15d4ba15003a231bcc72757d5`.
Both base shards must remain beside each other; llama.cpp opens the second automatically.
Selecting this fine-tune without its converted LoRA fails explicitly.

VNTL has a prompt/parser adapter and mocked tests, **not validated real inference**.
It currently gives an unavailable-artifact error. A future genuine fine-tuned GGUF
can be supplied through `YOMISCAN_QWEN35_GGUF`; do not substitute generic Qwen weights.

Set `YOMISCAN_TRANSLATION_ENGINE` to `current`, `hy-mt2-manga`, `qwen35-vntl` or
`qwen25-manga` for application-service/FastAPI/page-render selection. The translation
CLI supports explicit `--engine`; legacy text/image analysis CLIs retain baseline
behavior. Selecting an unavailable engine never silently falls back. Unset the
environment variable or set it to `current` to restore normal backend startup.

## Benchmark and human review

```powershell
uv run --extra benchmark python scripts/benchmark_translation.py --engine current --device cpu --output .cache/current.json
uv run --extra benchmark python scripts/benchmark_translation.py --engine hy-mt2-manga --device cuda --output .cache/hy.json
uv run --extra benchmark python scripts/benchmark_translation.py --engine qwen25-manga --device cuda --output .cache/qwen25.json
uv run --extra benchmark python scripts/benchmark_translation.py --engine all --device auto --output .cache/all.json
```

`all` processes engines sequentially, records failures, and closes optional runtimes.
The console then groups outputs by source line across engines, including inference,
case-wall and translate_many timings. Unavailable engines and inference failures stay
visible beside successful translations.
It exits nonzero if any engine is unavailable/fails, so today's missing VNTL artifact
cannot be mistaken for a successful four-model benchmark. `--limit 10` allows a short
check; `--dataset` accepts an alternate JSONL path.

The committed developer-authored evaluation contains **46 cases / 53 lines**:
casual speech, slang, contractions, omitted subjects, particles, ambiguous fragments,
politeness, character tone, long negation/passive direction, OCR damage, context
contrasts and an eight-bubble original scene. References are examples, not unique gold.
No copyrighted source pages or extracted manga datasets are committed.

```powershell
uv run --extra benchmark python scripts/benchmark_translation.py --engine qwen25-manga --context-mode previous --output .cache/previous.json
uv run --extra benchmark python scripts/benchmark_translation.py --engine qwen25-manga --context-mode page --output .cache/page.json
uv run --extra benchmark python scripts/benchmark_translation.py --engine qwen25-manga --context-mode page --glossary --output .cache/glossary.json
uv run --extra benchmark python scripts/benchmark_translation.py --engine hy-mt2-manga --glossary --output .cache/hy-glossary.json
```

Qwen2.5 context is a prompt hint around each current line, not native aligned page
decoding. Hy/Marian report dialogue context as unsupported. Hy accepts glossary hints;
Marian does not. VNTL's glossary metadata extension remains unverified.

Each JSON result has an adjacent `.ratings.csv`: fill accuracy/naturalness/tone/context
1–5, major-meaning-error/overly-formal/invented-meaning yes/no, reviewer and notes.
Blank fields remain unreviewed. Validate and summarize with:

```powershell
uv run python scripts/summarize_translation_ratings.py .cache/hy.ratings.csv
```

Prioritize semantics, participant direction, negation and tense over fluent style.
Judge ambiguous fragments in context. No BLEU/chrF winner is selected. Independent
human ratings are **pending**; observations below are assistant qualitative review,
not a blinded study or statistical quality score.

## Measured evidence

[Committed synthetic results](../benchmarks/results/2026-10-03.json) retain outputs,
errors, timings, memory snapshots and repeated-output consistency. Windows 11,
i7-14700K, 32 GiB RAM, RTX 4070 SUPER 12 GiB, driver 616.92. This was a working PC,
not an isolated performance lab.

| Run | Load | First case | Warm mean/line | Eight lines: independent / translate_many | RSS after inference |
|---|---:|---:|---:|---:|---:|
| Marian CPU, 53 lines | 6.36 s | 131 ms | 120 ms | 1.446 / **0.470 s** | 0.71 GiB |
| Hy Q4_K_M CUDA, 53 lines | 1.49 s | 79 ms | **84 ms** | 0.938 / 0.954 s | 1.54 GiB |
| Qwen2.5 Q4_K_M + F16 LoRA CUDA, 53 lines | 3.08 s | 195 ms | 216 ms | 1.784 / 1.731 s | 4.72 GiB |
| Hy CPU, first 10 lines only | 1.29 s | 301 ms | 269 ms | Not measured | 1.77 GiB |
| VNTL | Unavailable | — | — | — | — |

Warm mean is total second-pass time divided by source-line count. Page independent
time is its second pass; translate_many is a separate measured call. RSS includes
Python and owned children/shared mappings, not peak private RAM. Whole-GPU load
snapshots increased approximately **1.54 GiB (Hy)** and **4.73 GiB (Qwen2.5)**;
other applications were active, so these are approximate deltas, not exact process
VRAM peaks. Allow headroom for OCR/detection and longer context. Qwen2.5 CPU was
not benchmarked. Marian CUDA was not tested with the CPU-only Torch installation.

Final LLM comparisons use temperature 0, seed 0, repeat penalty 1, 4096-token runtime
context, and disabled prompt-cache reuse. This differs from Hy's recommended
low-temperature sampling; conclusions apply to the tested configuration. Exploratory
cached-prompt runs are local-only, excluded from the table. Floating-point/device
differences can still change outputs despite deterministic settings.

### Semantic and tone comparison

- Marian is not uniformly too formal: some slang was already casual. It mistranslated
  `ダサい` as disgust, reduced `最悪` to an exclamation, contradicted the passive-agent
  example, and reversed both desire-to-help and endangered-party meaning in the double negative.
- Hy improved those slang choices and the passive example. But `じゃねぇ` became
  “See ya.” It also mishandled the double negative and invented fragment completions.
  On the synthetic page, it gave the shaking hands to the wrong person and changed
  a promise about oneself into pushing someone else.
- Qwen2.5 produced some good colloquial phrases but converted intention into command,
  reversed the double negative and added commentary. Model size did not ensure quality.
- VNTL has no measured output or quality/resource evidence.

Context did not establish a win. Qwen's refusal example became “Sure. No thanks.
I'm full.” It confused an absent person's return/home direction. Full-page context
exceeded the output budget on the eight-line case and failed explicitly. Previous-only
context took **2.92 s**, and context+glossary **3.57 s**, but both blended surrounding
dialogue into individual outputs. These are measured poor translations, not successful
page alignment. Glossary hints made Hy use **spirit energy** and helped Qwen spell
**Ren**, without resolving participant direction or contextual leakage.

### Local real examples

Used existing OCR from `samples/coverage-jjk-{1,2,3}-after/metadata.json`: five
problematic lines and all 13 first-page blocks in order. Visually inspected the
original third page to verify combat direction. Copyrighted OCR and outputs remain
ignored in `.cache/benchmark-real-*.json`/CSV. Some headings/credits were OCR-damaged
and cannot be treated as clean-reference translation cases.

Both manga engines corrected the name and extreme-strength failures in the baseline.
Neither reliably translated the perpetual low-rank idiom. The long-weapon/closing-
distance sentence and barely-managing-to-dodge/block narration remained wrong or
materially incomplete. Qwen page-context occasionally found a better rank phrase
but contaminated other bubbles with invented names and unrelated dialogue.

Retain the current default until independent review; use Hy only as an explicit
experiment. Marian remains the minimal-dependency CPU option. Do not market Qwen2.5
as a quality upgrade from this evidence. Revisit VNTL when its actual weights are
published. Quantization, sampling, incomplete OCR, unseen names and missing visual
context remain limitations for every recommendation here.

## Validation scope

Model-free tests cover selection/lazy loading, deterministic requests, order, malformed
output, missing artifacts/adapter, serialization, ratings and cleanup alongside the
existing backend/API/rendering tests. Extension tests and build are unchanged.
Real default Study Mode API inference produced Japanese, translation and two lexical
tokens. Real page rendering returned original-size PNG with **9 rendered / 4 preserved**
blocks. Validation passed **171 Python tests**, **38 extension tests**, the extension
TypeScript/build checks, dependency sync and package imports. An initial smoke attempt failed printing Japanese through Windows CP1252;
the UTF-8 rerun completed. No default change occurred, so a new browser chapter smoke
was not required or claimed.

## NMT extension: FuguMT and NLLB-600M

This extends the benchmark above; the earlier Hy/Qwen results are retained. The
original JSONL dataset is unchanged (SHA-256
`c42c63888c36f63196a2c6feb79e9e7f1d6c7b26e6956d08509af02b9d0b5d7e`).

| Engine | Exact model | Pinned revision | Weight download |
|---|---|---|---:|
| `fugumt` | `staka/fugumt-ja-en` | `f7ce11286e1fb7a8e1f1692ff3ab68c0f9c3aecb` | 121,192,965 bytes (~121 MB) |
| `nllb-600m` | `facebook/nllb-200-distilled-600M` | `f8d333a098d19b4fd9a8b18f94170487ad3f821d` | 2,460,457,927 bytes (~2.46 GB) |

Tokenizer/config downloads add approximately 2.46 MB for Fugu and 22.2 MB for NLLB.
Fugu is the **Japanese-to-English** checkpoint, not `fugumt-en-ja`. NLLB explicitly
sets `src_lang=jpn_Jpan`, `tgt_lang=eng_Latn`, and forces the English language token
when generating. Both use direct `AutoTokenizer`/`AutoModelForSeq2SeqLM` loading,
without pipelines, remote model code, a Transformers downgrade or new dependencies.

Construction/import/empty batches do not load models. The selected engine loads once
on first translation or explicit `load()`, reuses one model/tokenizer, batches up to
eight independent inputs, preserves order and releases references on `close()`.
There is no cross-sentence context or glossary capability. Requests for those modes
are reported as unsupported, not silently ignored. Errors retain their original cause;
no alternative model is silently substituted. Ordinary tests use mocks.

CPU evaluation uses FP32 and no sampling. The initial controlled run used four beams
for every NMT model; Fugu's adapter now uses greedy decoding after the beam-search
failure described below. NLLB and OPUS retain four beams. Fugu's downloaded weights
are FP16 but are expanded to FP32. Inputs over 512
tokens fail rather than truncate. The output budget is 511 new tokens, with no forced
EOS at the limit; incomplete generations fail explicitly. NLLB's larger positional
capacity is not treated as validated long-context support.

### Setup and four-model commands

```powershell
uv sync --extra benchmark
uv run python scripts/prepare_translation_models.py --engine fugumt
uv run python scripts/prepare_translation_models.py --engine nllb-600m
uv run python scripts/translate_text.py --engine fugumt --device cpu "何してんだよ"
uv run python scripts/translate_text.py --engine nllb-600m --device cpu "何してんだよ"
```

Preparation downloads pinned files into the normal HF cache. Neither candidate is
downloaded during normal OPUS startup. After preparation, `HF_HUB_OFFLINE=1` supports
fully offline inference; the Python constructor also accepts `local_files_only=True`.
Use the same `YOMISCAN_TRANSLATION_ENGINE` setting for backend selection, or `--engine`
in the translation/benchmark CLI. The default remains `current` unless explicitly set.

After the previously documented Hy runtime/path setup:

```powershell
$env:HF_HUB_OFFLINE = '1'
uv run --extra benchmark python scripts/benchmark_translation.py --engine core --device cpu --output .cache/nmt-core.json
uv run --extra benchmark python scripts/benchmark_translation.py --engine core --device cpu --dataset .cache/local-manga-eval.jsonl --output .cache/nmt-real.json
```

`core` selects only current, Fugu, NLLB and Hy. Qwen models are not rerun. `all` still
includes every registered engine. The local real-manga dataset above is an ignored
artifact from the earlier evaluation, not distributed source material. New machines
must supply their own local examples. JSON/ratings CSV format and the rating-summary
command are unchanged. No BLEU winner or new rating format was introduced.

### Licensing constraints

[FuguMT's publisher](https://huggingface.co/staka/fugumt-ja-en) declares
**CC-BY-SA-4.0**. The [license](https://creativecommons.org/licenses/by-sa/4.0/)
allows commercial use subject to its terms, including attribution and identification
of changes; sharing adaptations of the licensed material invokes ShareAlike.
Do not relicense redistributed/adapted weights as MIT. This does not automatically
change the license of independently written YomiScan code.

[NLLB's publisher](https://huggingface.co/facebook/nllb-200-distilled-600M) declares
**CC-BY-NC-4.0**. The [license](https://creativecommons.org/licenses/by-nc/4.0/)
restricts licensed use to non-commercial purposes and requires attribution. An MIT
wrapper does not remove that restriction. NLLB cannot be recommended as an unrestricted
commercial-compatible universal default, even if it scores best technically. Its model
card also describes a research model rather than production/document translation.

These are model licenses, separate from YomiScan MIT and from licenses on manga
source material. No weights are added to Git. Distribution plans must retain the
applicable model notices and account for each license independently.

### Measured NMT comparison (2026-10-03)

The unchanged 46-case / 53-line dataset was run on an i7-14700K with 32 GiB RAM,
Windows, Python 3.13.9 and Torch 2.14.0+cpu. See
[complete synthetic evidence](../benchmarks/results/2026-10-03-nmt.json) and the
[existing-format rating worksheet](../benchmarks/results/2026-10-03-nmt.ratings.csv).
All four final configurations completed 46/46 cases. All two-pass isolated outputs
were identical within each configuration. Completion does **not** mean correctness.

| CPU engine | Load ms | First inference ms | Warm ms/line | Eight-line batch ms | RSS loaded / after, GiB |
|---|---:|---:|---:|---:|---:|
| OPUS, 4 beams | 5919 | 146 | 154 | 588 | 0.62 / 0.71 |
| Fugu, greedy | 4628 | 38 | 68 | 196 | 0.75 / 0.58 |
| NLLB, 4 beams | 1635 | 928 | 939 | 2729 | 1.77 / 3.06 |
| Hy Q4_K_M, CPU | 1459 | 281 | 296 | 2814 | 2.23 / 2.28 |

Warm latency is total second-pass wall time divided by 53 lines, not an unweighted
average of case averages. Eight-line independent second passes took 1658 / 763 /
9273 / 2901 ms respectively. Hy's `translate_many` loops over sentences; the three
NMT engines perform actual batching. None of these measurements claim page context.
Load times are not directly comparable cold starts: OPUS and standalone Fugu include
runtime imports; NLLB loaded after Torch was already imported. RSS is a snapshot,
not peak RAM or required hardware capacity, and includes Python/runtime/shared pages.
Sequential runs can retain allocator/import memory. Whole-GPU snapshots in JSON
include other applications and are **not** model VRAM measurements.

Fugu and NLLB CUDA were **not tested**: installed Torch is CPU-only. No Torch change
was made. Their adapters support CUDA selection and have mocked device tests; this
is not a claim of verified GPU inference. Earlier Hy GPU measurements remain above.

#### Fugu decoding investigation

The initial four-beam run completed only 42/46 cases. `tone-arrogant`, `ocr-damaged`,
`context-left` and `page-training` reached the generation limit without EOS; other
outputs contained repetition/invented material. This failed run is retained in the
synthetic evidence as `diagnostic-four-beam`, not removed from the comparison.
Its 522 ms warm mean covers successful cases only and is not the final Fugu result.

On failed probes, explicitly using MarianTokenizer matched AutoTokenizer's tokens.
FP32, eager attention and disabling the generation cache did not fix four-beam output.
The checkpoint's published 12-beam setting also failed probes. Greedy decoding fixed
those probes and then completed the **entire original dataset**, so the Fugu adapter
uses one beam by default. A constructor `num_beams` override retains reproducibility.
This is an observed checkpoint/runtime/search interaction, not a proven explanation
of all Fugu versions. Greedy decoding still makes semantic errors.

#### Meaning and register review

This is assistant qualitative inspection, **not independent human scoring**. The
212-row worksheet is deliberately unscored for human review. No BLEU ranking or
fabricated accuracy percentage selects the default.

| Probe | Fugu greedy | NLLB | Interpretation |
|---|---|---|---|
| 知らねーよ | “i don't know.” | “You know what I mean.” | Fugu preserves negation; NLLB loses it. |
| じゃねぇ | “no, no.” | “Oh, my God.” | Fugu retains a negative fragment; NLLB invents an exclamation. Hy also failed this fragment previously. |
| キモい | “slick” | “That's cute.” | Both wrong; NLLB reverses the negative evaluation. |
| ダサい | “sloppy” | “It sucks.” | Neither precisely captures uncool/tacky; Hy's “Lame.” was better. |
| 最悪 | “worst” | “The worst.” | Both improve OPUS's unrelated “I'm sorry.” |
| やだ | “no” | “Let's go.” | Fugu preserves refusal; NLLB does not. |
| Passive-agent case (`direction`) | Correct teacher→brother scolding | Correct teacher→brother rebuke | Both improve the baseline's direction mistake. |
| Rough prohibition (`tone-rough`) | “you touch my luggage!” | Preserves “Don't touch…” | Fugu loses the prohibition, a serious regression. |
| Double negative / endangered party (`negation-long`) | “Don't want to help me…” | “I don't want to help you.” | Both reverse meaning; NLLB drops the second sentence. Hy/OPUS also fail this difficult case. |
| どうなさいましたか | “what do you want?” | “How'd you do?” | Neither preserves the intended polite inquiry well. |

Fugu is often brief and conversational, but slang can become unrelated English
(`めっちゃ`→“jerk.”, `ふざけんな`→“sly”). It is not consistently too formal;
it can instead become too blunt or erase politeness. NLLB sometimes preserves polite
wording well, yet over-intensifies casual speech, invents pronouns or repeats fragments
(`待てよ` produced repeated “Wait.”). More fluent wording does not compensate for this.
Hy remains the strongest experimental register candidate, but fluent subject/negation
errors remain. OPUS stays fast and predictable operationally, not reliably accurate.

In the eight-line original scene, Fugu correctly translated the shaking **other
person's** hands but then changed “I won't push myself” into “I won't force you” and
“You said that earlier” into “I told you that.” NLLB changed the hands to **my** hands
and also lost later speaker direction. Batch inference supplies no shared context;
neither new engine claims previous/page/glossary support. Context hooks for the LLM
adapters remain intact.

#### Local real-manga retest

Reused the earlier three local pages' OCR: five difficult single examples and the
first page's complete 13-block text (18 lines including repeated examples). All four
engines completed all six cases. Copyrighted page/text/output artifacts remain ignored
under `samples/` and `.cache/`; only qualitative observations are distributed here.

- Character name: Fugu and Hy preserved the intended name; OPUS substituted another
  name and NLLB substituted a generic question.
- Rank: all four failed the perpetual-low-rank nuance; school-grade/year readings
  remained. NLLB's shorter grade output was still not a contextual solution.
- Strength statement: Fugu and Hy preserved exceptional strength. OPUS changed it
  to attractiveness; NLLB changed it to nerve/audacity.
- Long weapon / closing distance: none fully preserved the weapon-and-distance
  relationship. Hy retained closing distance but omitted the long weapon.
- Dodge/block narration: all four failed the struggle-to-keep-up meaning; some
  invented commands or declarations. Neither new engine fixes this combat failure.
- First-page additional lines: Fugu reversed a relief statement to restlessness.
  OCR-damaged heading and author text caused inventions across engines. Better
  translation cannot be credited with fixing already incorrect OCR.

Real-set weighted warm latency was OPUS 213, Fugu 84, NLLB 990 and Hy 325 ms/line.
The 13-block batch took 1979 / 535 / 6201 / 4548 ms respectively. No new page image
rendering or browser chapter smoke test was required by a default change: **there
was no default change**. This retest evaluates saved OCR, not newly claimed OCR accuracy.

#### Recommendation and validation

**Keep `current` OPUS as default.** Neither new model meaningfully establishes greater
semantic reliability across the full synthetic review and difficult local examples.
Fugu is an optional **fast CPU experiment**, not a quality upgrade. Hy remains an
optional manga-register experiment. NLLB is an optional **non-commercial research**
engine: approximately six times OPUS's warm CPU latency here, higher RAM, significant
meaning errors, and licensing that precludes a universal commercial-compatible default.
No tested engine earns a reliable quality-mode recommendation. Fugu's ShareAlike
obligations also remain relevant to model redistribution/adaptation.

Validation: `uv sync --extra benchmark`; `uv run pytest` (**190 passed**, one existing
Starlette/httpx deprecation warning); extension `npm test` (**38 passed**),
`npm run build` (includes TypeScript check); real four-model CPU synthetic and local
OCR runs; cached model preparation. Ordinary tests never load/download weights.
The prior Hy/Qwen evidence and default are preserved. Independent human ratings and
GPU measurements for these two models remain outstanding, explicitly not invented.
