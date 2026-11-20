# Stage 2 detection and OCR: measured findings and decisions

Measured 20 November 2026 on Windows 11, Python 3.13, Intel Core i7-14700K
(20 cores/28 logical processors), CPU only, four requested inference threads.
Torch 2.14.0, Transformers 5.17.0, manga-ocr 0.1.16, ONNX Runtime 1.32.0,
NumPy 2.5.3 and Pillow 12.3.0. All inference used pinned cached models with
HF_HUB_OFFLINE and TRANSFORMERS_OFFLINE enabled. No training was performed.

**Decision: keep the original detector, 0.50/0.50 thresholds, original manga-ocr
and OPUS defaults.** Adopt configurable thresholds, optional evaluation adapters,
reproducible tools and diagnostic confidence. No confidence rejection gate is adopted.

## Provenance and reproducibility

Stage 1 PR #1 was merged at `c651a3cf6f1a1bc68997f43b5d997dd439c6c104`.
Stage 2 started from that merged main on `feat/post-mvp-detection-ocr`.
See [exact model revisions, hashes, licenses and source/export contracts](stage2-model-provenance.md)
and [commands, annotation schema and metric definitions](../post-mvp-detection-ocr.md).
The implementation uses original Python and official runtime APIs; no Yomu source was copied.

Local manifests and raw results are `.cache/stage2/pages.json`, `ocr.json`,
`detect-{a,b,c,d,e}.json`, `ocr-*.json`, `production-*.json` and `matrix-status.json`.
All 13 sequential isolated-process runs completed successfully. These files contain
private page/transcription data and remain ignored, together with source images and logs.
Each report records dataset/image fingerprints, artifact SHA-256/size, versions,
configuration, split, timings, failures and memory scope. Aggregate findings are below.

The corpus comprises the three previously authorized Jujutsu Kaisen audit pages:
22 approximate text rectangles, including 16 dialogue units and two large SFX.
References were visually transcribed from original pixels, independently of saved OCR.
They have **not received independent human adjudication**. Nineteen manga regions have
scorable main-text references (203 characters); uncertain subtitle/SFX text is unscored.
Three separately labelled synthetic font cases, a blank control and a derived low-resolution
crop bring isolated OCR evaluation to 24 references/232 characters. The derived crop stays
with its source's tuning split. Page 1 is tuning; pages 2–3 are exploratory held-out cases
from the same previously audited chapter. This is not an independent representative test set.

Each image/crop has one unmeasured warmup and three measured repeats. Detection latency
has nine warm observations per arm; isolated OCR has 72 successful warm reads per arm.
Initialization means a fresh process/model instance using cached files, not an OS cold
disk cache. Original manga-ocr includes its own constructor example warmup.
Host affinity, frequency and unrelated user workloads were not controlled. An earlier
pilot PyTorch median was about 414 ms versus 1,077 ms in the final matrix; latency varies.
Use the final recorded matrix below, not a universal speed multiplier or a threshold-speed claim.

## P14/P15: detection and downstream outcomes

All arms kept preprocessing/downstream OCR, OPUS, JMdict and renderer safeguards fixed.
Suppression E is an independent benchmark-only policy, not a production change.

| Arm | Detector; bubble/free floor | Regions | Dialogue found | FP / merges / duplicates | Complete rectangle proxy | Rendered / preserved | Init ms | Warm median / p95 ms |
|---|---|---:|---:|---|---:|---|---:|---|
| A | PyTorch; .50/.50 | 20 | 16/16 | 0 / 0 / 0 | 9/16 | 12 / 8 | 6269.1 | 1077.0 / 1104.4 |
| B | PyTorch; .25/.50 | 20 | 16/16 | 0 / 0 / 0 | 9/16 | 12 / 8 | 7242.4 | 981.6 / 1016.8 |
| C | INT8 ONNX; .50/.50 | 20 | 16/16 | 0 / 0 / 0 | 13/16 | 12 / 8 | 719.0 | 111.1 / 122.0 |
| D | INT8 ONNX; .25/.50 | 20 | 16/16 | 0 / 0 / 0 | 13/16 | 12 / 8 | 660.4 | 109.9 / 122.0 |
| E | PyTorch .50/.50; coverage suppression | 20 | 16/16 | 0 / 0 / 0 | 9/16 | 12 / 8 | 6410.1 | 948.0 / 1025.9 |

Matching is a geometric proxy: 50% annotation coverage establishes a match; 95% of an
approximate rectangle covered by a grouped/padded crop establishes the completeness proxy.
Extra rectangle whitespace can lower that score without missing any glyph. It is not
evidence that seven baseline dialogue reads were truncated. No split candidates or
grouped dialogue merges occurred. FP counts apply only to this annotated local corpus.

Every arm yielded OCR and translations for all 20 detected blocks. Twelve dialogue units
rendered; four dialogue units translated successfully but were preserved by the renderer.
Four additional preserved blocks were caption/branding/credits. The two large SFX were
not detected by either candidate; they are not renderer-preserved detections. This
separates genuine misses from downstream preservation and reproduces the prior audit.

Lower thresholds and alternative suppression supplied no additional dialogue or rendered
coverage. Retain .50 defaults; suppression stays in the benchmark module only. A future
adoption test needs independently annotated missed-dialogue pages from several series,
with tuning held apart from final testing and visual merge/crop adjudication.

The candidate is `detector-v4-s_int8.onnx`, 11,120,765 bytes, compared with the current
171,543,900-byte safetensors checkpoint. Both share repository revision `16e8a622...`,
but **weight/architecture equivalence is unverified**. Faster candidate inference is
observed; a pure runtime/quantization speedup is not established. Actual ORT metadata
verified dynamic batch inputs and 300 outputs, RGB/255 640², Int64 width/height targets,
and original-coordinate XYXY boxes. Bounds and class semantics are tested.

Detector-loaded whole-process RSS was about 487.4 MiB for A and 108.1 MiB for C.
End-to-end Windows lifetime peaks were about 1.38 GiB for both because original OCR/OPUS
also loaded. These are whole-process observations, not incremental model RAM or guaranteed
memory requirements. Sampled peaks are lower bounds; Windows peaks are lifetime high-water marks.
ONNX remains a useful optional experiment, with a broader-corpus adoption/removal decision
required before treating it as a permanently supported second production detector.

## P16: OCR weights, preprocessing and runtime

Original weights are pinned to `kha-white/manga-ocr-base@aa6573b...` (444,135,475 bytes).
The 2025 source is `jzhang533/manga-ocr-base-2025@1e64d5b...` (121,337,608 bytes).
Its encoder hidden size is 192 versus original 768; this is a different architecture,
not merely newer weights. The mapped ONNX encoder/decoder total 140,411,071 bytes.

Published decoding uses four beams, maximum length 300 and the checkpoint's repetition
settings. The matched greedy arms use RGB/PIL bilinear 224², normalization .5/.5,
one beam, 128 new tokens, no repeat-ngram rule and the same text normalization.
Start/stop IDs are checked against vocabulary/configuration. KV state resets per crop.

| Arm | Strict CER | Normalized CER | Normalized exact | Init ms | Warm median / p95 ms |
|---|---:|---:|---|---:|---|
| Original package, grayscale, published | 17.24% | 9.05% | 19/24 | 6861.1 | 330.5 / 503.0 |
| Original weights, RGB, published | 17.24% | 9.05% | 19/24 | 5975.1 | 326.0 / 506.3 |
| 2025 PyTorch, RGB, published | 23.28% | 16.81% | 14/24 | 5389.7 | 135.4 / 278.3 |
| 2025 PyTorch, RGB, matched greedy | 25.00% | 18.53% | 14/24 | 5185.3 | 100.3 / 211.2 |
| 2025 ONNX, matched greedy + KV | 25.00% | 18.53% | 14/24 | 1036.4 | 60.7 / 169.4 |
| 2025 ONNX, matched greedy, full prefix | 25.00% | 18.53% | 14/24 | 955.4 | 115.6 / 377.7 |

The aggregate deliberately includes difficult synthetic/blank controls; do not present it
as manga-only accuracy. On the **19 real manga crops**, normalized CER/exact were:
original 1.97% and 17/19; published 2025 6.90% and 12/19; greedy 2025 7.88% and 12/19.
The seven held-out real references had original CER 0%, published 2025 2.54% and greedy
2025 5.93%. These small, single-reviewer results do not establish general error rates.

Original RGB supplied no accuracy benefit. All 24 matched-greedy PyTorch/ONNX texts
were identical; maximum confidence difference was approximately 0.00000114. On this
control, ONNX median latency was 60.7 versus 100.3 ms. KV reuse reduced the ONNX median
from 115.6 to 60.7 ms with unchanged text. These are measured local effects on equivalent
2025 source/export weights, not an accuracy improvement or an Android speedup claim.

Original OCR-loaded process RSS was about 783.5 MiB; 2025 PyTorch about 439.6 MiB;
2025 ONNX about 233.4 MiB. Lifetime peaks were approximately 794.6, 485.3 and 334.6 MiB
respectively. Native allocation, runtime imports and model construction differ; these
are whole-process observations. No GPU/VRAM measurements were performed.

The additional production-crop runs reused the same 20 baseline grouped/four-pixel-padded
detector crops. Only 11 uniquely matched, sufficiently covered references were scored:
original normalized CER 0% / exact 11/11; ONNX 2025 4.95% / exact 8/11. Warm medians were
339.5 and 60.2 ms. Nine unscored crops are excluded from CER, not treated as correct;
the rectangle filter creates selection bias, so this subset is not full-page OCR accuracy.

All experimental arms completed without observed token-limit errors. Original package
termination and confidence are opaque, so absence of reported limit errors is not proof
of zero original truncation. Blank reads, inserted characters on blank references,
substitutions, deletions and insertions remain separately available in raw/summary JSON.
Keep original OCR: the tested 2025 candidate sacrificed accuracy despite speed/memory gains.

## P17: confidence is diagnostic, not calibrated probability

Greedy adapters report the mean selected-token probability including EOS, with method,
model/revision, preprocessing, token count, termination and an uncalibrated marker.
Original and published beam-mode confidence remain unavailable. Detection scores stay separate.
No low-score rejection, retry or preservation rule is installed.

On 24 labelled isolated reads, the ONNX 0.85 exploratory cutoff flagged six errors but
missed four wrong reads above threshold: precision 1.0, recall 0.60. At .95 it flagged
eight errors and missed two. Confidence/CER Pearson r was approximately -0.933, heavily
influenced by the tiny corpus and synthetic controls; correlation does not calibrate
probability or validate a warning policy.

On the 11 scored **production crops**, .85 flagged none of three incorrect reads
(recall 0). At .95 it flagged all three but also one correct read (precision .75).
This transfer failure is direct evidence against copying .85. Short/mixed-script and
other tagged subset accuracy is retained in summary JSON; representative independent
calibration, including high-confidence omissions/ruby and valid short dialogue, remains missing.

## Decisions and adoption gates

| Improvement | Baseline | Candidate | Result | Decision |
|---|---|---|---|---|
| P14 threshold | .50/.50 | .25/.50 | Same 16 dialogue / 12 rendered | Inconclusive beyond this corpus; retain default |
| P15 detector | PyTorch | pinned INT8 v4-s | Faster/lower detector RSS; same coverage, lineage confound | Optional experiment; no replacement |
| P15 suppression | Existing grouping | independent coverage policy | No duplicates to fix, no change | Reject production adoption; benchmark-only |
| P16 preprocessing | Grayscale original | RGB original | Identical transcripts | Reject default change |
| P16 weights | Original | Smaller 2025 | Worse measured CER/exact | Reject replacement on current evidence |
| P16 runtime | 2025 PyTorch greedy | Matched ONNX KV | Identical 24 texts, faster local reads | Retain optional evaluation adapter |
| P16 KV reuse | Full-prefix ONNX | Per-crop cached ONNX | Same text, lower measured latency | Adopt within optional ONNX adapter |
| P17 confidence | Unavailable original | Explicit greedy sequence score | .85 misses production errors | Diagnostic only; defer filtering |

The optional controls exist to make these comparisons reproducible, not as a promise
of permanent model support. Reassess or remove them after a broader independent corpus
test. Stage 3 caching, multilingual work, model-manager UI, translator changes and
learning features were not started. The original MVP interfaces and safeguards remain.
