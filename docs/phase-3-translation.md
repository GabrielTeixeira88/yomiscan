# Phase 3: local Japanese → English translation

## Decision and scope

Selected `Helsinki-NLP/opus-mt-ja-en`, using Marian directly through Transformers.
Revision: `0770961a39ba6bd66305b149c3f4110bcafca2e6`.
This is a practical, replaceable CPU baseline, not a claim of excellent manga quality.
The model is small, its dedicated language direction needs no language routing, and
it performed coherently on the requested short sentences. A larger tested alternative
did not justify its extra memory/latency on this small evaluation set.

Phase 2 started clean on commit `a5faac2`; `main`, local `origin/main`, and `phase-3`
all pointed there. The 36 baseline tests passed before implementation. No remote
fetch was needed to establish consistency of those local refs; no new commit or push
is part of this phase's implementation work.

## Candidates and primary sources

| Candidate | Download / resources | Quality and practical assessment | License |
| --- | --- | --- | --- |
| [OPUS-MT Japanese → English](https://huggingface.co/Helsinki-NLP/opus-mt-ja-en) | ~303 MB PyTorch weights plus ~3 MB tokenizer/config; 75.7M parameters measured | Selected. Short dialogue CPU inference was 138–257 ms. Pronouns/tone are inferred; long casual dialogue can lose meaning. | HF checkpoint card declares Apache-2.0 |
| [M2M100 418M](https://huggingface.co/facebook/m2m100_418M) | ~1.94 GB FP32 weights plus tokenizer; considerably more RAM than Marian | Tested with `src_lang=ja`, forced English BOS. 429–853 ms per input. No clear quality gain on these examples. | MIT |
| [NLLB-200 distilled 600M](https://huggingface.co/facebook/nllb-200-distilled-600M) | ~2.46 GB FP32 weights plus tokenizer; higher CPU/memory cost expected, not measured here | Research alternative, not downloaded/tested. Broad multilingual evaluation does not establish manga performance. Card describes research use, domain/document limitations and a 512-token training limit. | CC-BY-NC-4.0; noncommercial restriction makes it unsuitable as an unrestricted default |

Sources: the linked model cards and their file listings; [Marian documentation](https://huggingface.co/docs/transformers/model_doc/marian),
[M2M100 documentation](https://huggingface.co/docs/transformers/model_doc/m2m_100),
and [NLLB documentation](https://huggingface.co/docs/transformers/model_doc/nllb).
Sizes are approximate decimal bytes for one PyTorch checkpoint, not whole repositories
which may also contain TensorFlow/other formats. Downloading every repository file is
unnecessary. No paid inference endpoint is used.

All three have Transformers seq2seq adapters, CPU/CUDA execution paths, and padded
batch generation. OPUS-MT and M2M100 were actually run on Windows 11 / Python 3.13.9 /
torch 2.14.0+cpu / transformers 5.17.0. NLLB compatibility with this exact environment
is not experimentally verified. SentencePiece 0.2.2 installed from a compatible wheel;
there is no observed Python 3.13 incompatibility and no Python requirement change.
Transformers v5 no longer supports the old translation pipeline shortcut; we use the
model/tokenizer classes directly. Neither GPU execution nor GPU speed was measured.
CUDA should accelerate supported PyTorch operations with a compatible NVIDIA build;
actual benefits depend on hardware and batch size.

These are established checkpoints, not evidence of continuously improving manga
models: OPUS-MT's referenced training export is from 2019, M2M100's paper from 2020,
NLLB's from 2022. Current library support matters more here than checkpoint age alone.
The exact default revision and uv.lock make the tested setup reproducible. Published
general-domain scores are not interchangeable across datasets and are not a manga
ranking. No claim is made that all candidate families were empirically benchmarked.

## Real local evaluation, 2026-09-30

Initial comparison: 11 synthetic inputs, one run per model, CPU, FP32, four beams,
no sampling, 128 new-token cap (none reached), 20 PyTorch CPU threads. Model import,
download, and initialization are excluded from inference times. Initial setup/load
took about 17 seconds for Marian and 35 seconds for M2M100 in these processes; those
numbers include downloads and are not portable startup benchmarks. M2M100 revision
was `55c2e61bbf05dfb8d7abccdc3fae6fc8512fd636`.

| Japanese | OPUS-MT actual output | M2M100 actual output |
| --- | --- | --- |
| でも大丈夫 | But I'm fine. | But okay. |
| 今日は学校に行かなかった。 | I didn't go to school today. | I did not go to school today. |
| 何をしているんだ？ | What are you doing? | What are you doing? |
| そんなこと言ってないぞ。 | I didn't say that. | I don’t say that. |
| 本当に大丈夫なの？ | Are you sure you're okay? | Are you really okay? |
| 彼女は昨日東京に行った。 | She went to Tokyo yesterday. | She went to Tokyo yesterday. |
| これはどういう意味ですか？ | What does this mean? | What does this mean? |
| 行かなきゃ。 | I have to go. | I have to go. |
| うそだろ！ | Oh, my God! | It is a lie! |
| 別にあんたのためじゃないんだからね。 | It's not for you. | Because it is not for you. |
| でも + newline + 大丈夫 | But I'm fine. | But okay. |

A single padded batch of 11 took 563 ms with Marian and 2,047 ms with M2M100; output
order and strings matched their singleton runs. This is a smoke comparison with no
repeated statistical trials or native-speaker panel. The default adapter caps batches
at eight to bound memory; an offline run through that adapter took 661 ms for the 11
inputs in two chunks, with matching singleton/batch outputs. Its cached initialization
including lazy dependency imports took about 6.5 seconds. Other local processes were
active, so do not treat these numbers as controlled hardware benchmarks.

The final CLI translated all seven requested examples in one 348 ms batch. The adapter
allows up to 511 generated tokens, disables forced terminal EOS, and checks for a real
EOS so reaching its output cap cannot silently appear successful. Source length is
limited to 512 tokenizer tokens including special tokens; longer regions raise an
actionable error. Callers must choose complete shorter regions, not dictionary tokens.

Interpretation: basic tense, negation and explicit subjects worked on these examples.
The first input invents a first-person subject where “it's okay” is also plausible.
The exclamation is freely adapted, and gender/register/emphasis are weakened. This
small sample does not settle omitted-subject, slang, sentence-ending particle, or
masculine/feminine speech quality.

Real image validation used the existing ignored local screenshot and imported JMdict
database, with `HF_HUB_OFFLINE=1`. OCR, translation, and analysis all completed on CPU:
OCR 506 ms, translation 535 ms, lexical analysis 54 ms, excluding initialization.
The longer colloquial sentence's translation confused its social-appearance/relaxation
meaning. This is evidence of a translation limitation, not a quality success. No OCR
accuracy score was computed; the crop and full transcript/output remain unversioned.

## Setup, caches, memory, and licenses

```powershell
uv sync
uv run python scripts/translate_text.py "でも大丈夫" --device cpu
uv run python scripts/analyze_text.py "でも大丈夫" --translate --device cpu
uv run python scripts/analyze_image.py samples/test.png --cpu
```

Use your own crop at `samples/test.png`. The actual validation crop is already local:

```powershell
uv run python scripts/analyze_image.py "samples/Screenshot 2026-09-29 154812.png" --cpu
```

Direct dependencies added: torch and transformers (previously transitive through
manga-ocr), sentencepiece and sacremoses. New locked packages include sentencepiece,
sacremoses, joblib, and cloudpickle. No global installs or CUDA package changes.
The generated lock retains the existing torch/transformers versions.

Hugging Face downloads files on first initialization and reuses the cache afterwards.
The default is `~/.cache/huggingface/hub`, configurable via `HF_HOME` (which places the
Hub cache under its `hub` directory) or `HF_HUB_CACHE`. See the official
[cache guide](https://huggingface.co/docs/huggingface_hub/guides/manage-cache).
Set `HF_HUB_OFFLINE=1` after setup to disable Hub requests and require cached files.
Without that setting, a normal run may check Hub metadata but does inference locally.
Neither login nor a paid account is required for these public weights.

~303 MB is only the default model's FP32 parameter storage. Peak process RAM and VRAM
are unknown; allow additional space for PyTorch, tokenizers, generation activations,
four-beam caches, and OCR. Batch size and text length increase memory demand. No
quantization, mixed precision, thread tuning, or specialized runtime is introduced.
CPU is the validated baseline. Explicit CUDA requests fail when unavailable; an
available CUDA runtime that fails during load/inference reports that failure without
silently switching devices. Windows caching works without Developer Mode/symlinks,
but duplicated files may consume extra disk space.

The selected [HF model card](https://huggingface.co/Helsinki-NLP/opus-mt-ja-en/blob/0770961a39ba6bd66305b149c3f4110bcafca2e6/README.md)
declares **Apache-2.0**, separately from YomiScan's MIT source license. Preserve model
attribution and the applicable license/notice when redistributing weights; modifications
must be identified. That declaration has no noncommercial-only restriction. The broader
[OPUS-MT project](https://github.com/Helsinki-NLP/Opus-MT) also refers to CC-BY-4.0 for
its original model distribution; do not confuse that general statement with this HF
checkpoint's metadata. Preserve both provenance references and verify the exact
artifact's terms before packaging/rehosting it. YomiScan currently downloads the
upstream checkpoint into a local cache and does not redistribute weights. See also
[third-party notices](third-party-licenses.md). JMdict and UniDic attribution is unchanged.

## Repeatable manual evaluation

```powershell
$env:HF_HUB_OFFLINE = "1" # only after downloading successfully
uv run python scripts/benchmark_translation.py --device cpu
```

This optional script loads real weights, prints JSON with versions/revision, startup,
per-sentence timings/output, and batch output/timing. It is not collected by pytest.
Run it more than once on a quiet PC for speed comparisons. The 11 sentences above are
starting examples, not expected-string tests and not a sufficient quality benchmark.

Extend the set with casual dialogue, omitted subjects, masculine/feminine speech,
sentence-ending particles, contractions, slang, fragments, narration, short
exclamations, longer sentences, punctuation, deliberate OCR mistakes, and a sentence
split over visual lines. Supply context to the human reviewer, even though the model
currently sees only one region. Compare single and batch results and verify order.
For each item record:

- Japanese and intended meaning/context, plus a human English reference if available.
- Meaning, tense/negation, pronoun choice, tone/register, omissions and invented details.
- Raw model output, model revision/device, elapsed time, and whether OCR introduced errors.

Do not use exact-string equality as a translation-quality measure. Review both
successful and failed cases. Do not commit copyrighted crops, manga transcripts,
downloaded dictionaries, weights, or caches. Synthetic examples are safe to keep here.

## Validation and next milestone

`uv sync` succeeded. `uv run pytest` passed 63 tests, including all 36 prior tests;
ordinary tests use fake translation/OCR models and synthetic dictionary data. Package
and Marian/SentencePiece/sacremoses import checks passed. The lexical-only text CLI,
seven-example translation CLI, optional singleton/batch benchmark, and full image
pipeline were run. Offline inference succeeded. CUDA selection is tested with mocks
only; no real GPU claim is made. Python remains `>=3.13,<3.14`.

Recommended next milestone: broaden human-reviewed manga-dialogue evaluation and set
an acceptable quality baseline before wrapping this pipeline in a local HTTP API.
FastAPI, Chrome extension, screenshot selection, study popup, Translate Chapter, page
discovery, lazy loading, text detection, inpainting, typesetting, and overlays all remain
future work. The ordered batching protocol is the only preparation they need now.
