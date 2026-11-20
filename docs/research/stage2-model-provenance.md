# Stage 2 detector and OCR artifact provenance

Research date: 20 November 2026. This note supports P14–P17 implementation and controlled local evaluation. It records public primary-source metadata and contracts; no neural weights were downloaded or loaded while preparing it. Yomu source was studied, not copied.

## Inspected snapshots and evidence boundaries

- YomiScan Stage 1 base: `c651a3cf6f1a1bc68997f43b5d997dd439c6c104`. The existing [comparison report](../yomiscan-vs-yomu-research.md) remains historical research, not new benchmark evidence.
- Yomu's current HEAD, checked through the GitHub API, remains [`ace87fef9cdfa3c7a79d3a6b57db02bbbc1b5ce5`](https://github.com/artsaraiva/yomu/commit/ace87fef9cdfa3c7a79d3a6b57db02bbbc1b5ce5), dated 14 November 2026. The latest change removes an Android telemetry provider; it does not change the model contracts below.
- Hugging Face model cards, small JSON/vocabulary files, repository histories and LFS metadata were fetched at immutable revisions. Earlier comparison research could not fetch the exact OCR export card; this investigation resolves that access limitation.
- Artifact SHA-256 values below are publisher LFS object identifiers, not hashes computed from locally downloaded weights. Graph signatures stated by cards or consumers still require validation against the downloaded artifact before inference.

## Detector: exact artifacts, and a significant equivalence limit

Yomu downloads `detector-v4-s_int8.onnx` from `ogkalu/comic-text-and-bubble-detector` at revision `16e8a622f91fabc6b5b65c96d32d1183f8843546`. Its [model registry](https://github.com/artsaraiva/yomu/blob/ace87fef9cdfa3c7a79d3a6b57db02bbbc1b5ce5/app/src/main/java/com/yomu/app/service/ModelManager.kt#L61) agrees with the publisher's [immutable artifact listing](https://huggingface.co/api/models/ogkalu/comic-text-and-bubble-detector/tree/16e8a622f91fabc6b5b65c96d32d1183f8843546?recursive=false&expand=false).

| File at that revision | Bytes | Publisher SHA-256 |
|---|---:|---|
| `model.safetensors` | 171,543,900 | `037930a861e67870eb345be01b28cc70d7e2b7956528e48ee0ebdb0c093df80d` |
| `detector.onnx` | 168,481,531 | `065744e91c0594ad8663aa8b870ce3fb27222942eded5a3cc388ce23421bd195` |
| `detector_int8.onnx` | 43,838,857 | `b5022ad46416b6fe4f88b0cc082cfd2ff5b1cfc624088c2f19879485493f5913` |
| `detector-v4-s_int8.onnx` | 11,120,765 | `5fe9e4f576e49d4e7e8b0e029d6d3cdc252abd4694113e1cae120e62c931ea79` |

The pinned [card](https://huggingface.co/ogkalu/comic-text-and-bubble-detector/blob/16e8a622f91fabc6b5b65c96d32d1183f8843546/README.md) describes an RT-DETR-v2 R50vd trained on approximately 11,000 comic-style images at size 640. The [configuration](https://huggingface.co/ogkalu/comic-text-and-bubble-detector/blob/16e8a622f91fabc6b5b65c96d32d1183f8843546/config.json) identifies `RTDetrV2ForObjectDetection`, a ResNet backbone, 300 queries and FP32 tensors. These describe the repository's Transformers checkpoint. They do **not** prove that every ONNX file in that repository contains an equivalent architecture or the same trained parameters.

The publisher's [commit history](https://huggingface.co/api/models/ogkalu/comic-text-and-bubble-detector/commits/main) records the original checkpoint upload in March 2025, `detector.onnx` in September 2025, `detector_int8.onnx` in May 2026, and repeated additions/replacements of the separately named `detector-v4-s_int8.onnx` on 14–15 May 2026. Neither the pinned card nor available repository text supplies an export recipe or an explicit source-checkpoint mapping for these files. File size alone establishes neither architecture nor equivalence.

**Implementation consequence:** treat Yomu's `v4-s` artifact as a separately pinned candidate. The previous report's shared-repository/revision finding remains true; an equivalent-weight PyTorch-versus-ONNX comparison is **not established** by that fact. Yomu's [ADR-0020](https://github.com/artsaraiva/yomu/blob/ace87fef9cdfa3c7a79d3a6b57db02bbbc1b5ce5/docs/adr/0020-rtdetr-text-detector.md#L5) calls the export RT-DETR-v2/R50vd, but this remains the application author's characterization until the actual graph/provenance is verified. The separately named 43.8 MB int8 file is a possible future control, not a proven equivalent-weight control. Do not add downloads or a third permanent adapter solely to chase a filename inference.

### Detector consumer contract

Verified from Yomu's current [ONNX boundary](https://github.com/artsaraiva/yomu/blob/ace87fef9cdfa3c7a79d3a6b57db02bbbc1b5ce5/ml/src/main/java/com/yomu/ml/OnnxRuntime.kt#L143):

| Tensor | Consumer contract |
|---|---|
| `images` | Float32, `[1, 3, 640, 640]`, RGB channel-first, plain bilinear resize/stretch, values divided by 255; no mean/std normalization or letterbox. |
| `orig_target_sizes` | Int64, `[1, 2]`, values **`[original_width, original_height]`**. This is this export's consumer convention, not Transformers' `target_sizes` convention. |
| `labels` | Read as Int64. Class IDs: 0 balloon outline, 1 in-bubble text, 2 free text. |
| `boxes` | Read as Float32, four XYXY original-page coordinates per score. The application does not perform another resize scaling. |
| `scores` | Read as Float32, one score per predicted box. |

The consumer flattens output buffers. Its source does not establish a static batch/query output shape for the `v4-s` graph. Verify names, dtypes, dimensions, cardinality, finite coordinates and bounds with `InferenceSession.get_inputs()/get_outputs()` and real inference. Do not assume the repository's 300-query configuration describes this particular artifact.

Class 0 is discarded. Class 1 follows the user's threshold, default `0.25`; class 2 uses `max(user_threshold, 0.5)`. See [parser](https://github.com/artsaraiva/yomu/blob/ace87fef9cdfa3c7a79d3a6b57db02bbbc1b5ce5/ml/src/main/java/com/yomu/ml/OnnxRuntime.kt#L258) and [detector defaults](https://github.com/artsaraiva/yomu/blob/ace87fef9cdfa3c7a79d3a6b57db02bbbc1b5ce5/pipeline/src/main/java/com/yomu/pipeline/bubble/BubbleDetector.kt#L17). It applies score-ranked duplicate suppression with IoU `0.80` and directional containment `0.90`; a second pass can recover a lower-confidence containing prediction when that retains otherwise uncovered text. This can preserve a merged OCR crop, not split its speakers. Benchmark threshold, runtime/export and suppression independently. YomiScan's ordinary region IDs/classes/original-coordinate semantics should remain intact.

The current Android dependency is [ONNX Runtime 1.26.0](https://github.com/artsaraiva/yomu/blob/ace87fef9cdfa3c7a79d3a6b57db02bbbc1b5ce5/ml/build.gradle.kts#L42). Its [session creation](https://github.com/artsaraiva/yomu/blob/ace87fef9cdfa3c7a79d3a6b57db02bbbc1b5ce5/ml/src/main/java/com/yomu/ml/OnnxRuntime.kt#L37) uses default options without explicit NNAPI/thread settings. That is not a Python runtime recommendation or a Windows performance measurement.

## OCR: pinned source and export identities

| Role | Repository and immutable revision | Principal weight artifact |
|---|---|---|
| Original PyTorch baseline | [`kha-white/manga-ocr-base@aa6573bd10b0d446cbf622e29c3e084914df9741`](https://huggingface.co/kha-white/manga-ocr-base/tree/aa6573bd10b0d446cbf622e29c3e084914df9741) | `pytorch_model.bin`, 444,135,475 bytes; SHA-256 `c63e0bb5b3ff798c5991de18a8e0956c7ee6d1563aca6729029815eda6f5c2eb`. |
| 2025 PyTorch candidate | [`jzhang533/manga-ocr-base-2025@1e64d5beb41ee6bee72c200838ddb93ad541482a`](https://huggingface.co/jzhang533/manga-ocr-base-2025/tree/1e64d5beb41ee6bee72c200838ddb93ad541482a) | `model.safetensors`, 121,337,608 bytes; SHA-256 `6152295c6d796ff92ed024b3ed5a0246a7865568e36d73c64b4bed2a71e4acb0`. |
| Current Yomu ONNX candidate | [`artsaraiva/manga-ocr-2025-onnx-past@151898756903f03a2682fa6be4507dfeff71fb7e`](https://huggingface.co/artsaraiva/manga-ocr-2025-onnx-past/tree/151898756903f03a2682fa6be4507dfeff71fb7e) | Encoder plus merged decoder, detailed below. |
| Historical 2025 ONNX without past | [`l0wgear/manga-ocr-2025-onnx@e8b27bbd3f424fe3877e0bda704d6a920e4f0a33`](https://huggingface.co/l0wgear/manga-ocr-2025-onnx/tree/e8b27bbd3f424fe3877e0bda704d6a920e4f0a33) | `encoder_model.onnx` / `decoder_model.onnx`; historical Yomu path, not necessary for the first new adapter. |

Weight hashes/sizes above come from the exact [original listing](https://huggingface.co/api/models/kha-white/manga-ocr-base/tree/aa6573bd10b0d446cbf622e29c3e084914df9741?recursive=false&expand=false), [2025 listing](https://huggingface.co/api/models/jzhang533/manga-ocr-base-2025/tree/1e64d5beb41ee6bee72c200838ddb93ad541482a?recursive=false&expand=false) and [ONNX listing](https://huggingface.co/api/models/artsaraiva/manga-ocr-2025-onnx-past/tree/151898756903f03a2682fa6be4507dfeff71fb7e?recursive=false&expand=false).

The exact ONNX [publisher card](https://huggingface.co/artsaraiva/manga-ocr-2025-onnx-past/blob/151898756903f03a2682fa6be4507dfeff71fb7e/README.md) explicitly names the `1e64d5b...` source revision and states that its weights are unchanged. This is a materially stronger mapping than the detector's shared-repository claim; it remains the publisher's statement rather than an independent tensor comparison. The [export history](https://huggingface.co/api/models/artsaraiva/manga-ocr-2025-onnx-past/commits/main) has one model-file publication commit, `1518987...`, on 20 October 2026.

The card records a custom Optimum BERT-decoder configuration to enable a with-past export; tool versions were Optimum 2.1.0, optimum-onnx 0.1.0, Transformers 4.57.6, torch 2.14.1, ONNX 1.23.2 and ORT 1.31.0. It links Yomu's spike issue, not permissively licensed export code to transplant. The same card reports matching greedy text on tested crops against the old l0wgear export; this is a small publisher check, not a universal equivalence/accuracy result.

### Source configuration and token IDs

The original [configuration](https://huggingface.co/kha-white/manga-ocr-base/blob/aa6573bd10b0d446cbf622e29c3e084914df9741/config.json) uses a ViT encoder with hidden size 768, 12 layers and 12 heads. The 2025 [configuration](https://huggingface.co/jzhang533/manga-ocr-base-2025/blob/1e64d5beb41ee6bee72c200838ddb93ad541482a/config.json) names a DeiT-tiny encoder with hidden size 192, 12 layers and 3 heads. Both have a 2-layer BERT decoder, hidden size 768, 12 attention heads, head width 64 and vocabulary size 6,144. Therefore the newer model changes architecture/weights as well as possible recognition quality; its smaller footprint must not be attributed to ONNX alone.

All inspected original/source/export vocabularies share the same Git blob `c2bd4e463e91d61f0c6e9a0cdaa221a50384c4dc`. Their first entries are IDs 0 PAD, 1 UNK, 2 CLS, 3 SEP and 4 MASK. The 24,072-byte vocabulary SHA-256 is `344fbb6b8bf18c57839e924e2c9365434697e0227fac00b88bb4899b78aa594d`, also pinned in [Yomu's registry](https://github.com/artsaraiva/yomu/blob/ace87fef9cdfa3c7a79d3a6b57db02bbbc1b5ce5/app/src/main/java/com/yomu/app/service/ModelManager.kt#L346).

**Important:** the 2025 top-level `config.json` contains start ID 2 and pad ID 0 but no usable top-level EOS value. Its separate [generation_config.json](https://huggingface.co/jzhang533/manga-ocr-base-2025/blob/1e64d5beb41ee6bee72c200838ddb93ad541482a/generation_config.json) supplies EOS 3, start 2 and pad 0, as well as 4 beams, max length 300, no-repeat-ngram size 3, length penalty 2 and early stopping. Load/validate the generation configuration and vocabulary rather than guessing an English-BERT SEP ID of 102. The original configuration directly contains EOS 3 and the same principal beam/ngram/length settings.

The [2025 tokenizer configuration](https://huggingface.co/jzhang533/manga-ocr-base-2025/blob/1e64d5beb41ee6bee72c200838ddb93ad541482a/tokenizer_config.json) selects `BertJapaneseTokenizer` with character subword tokenization and MeCab/UniDic-lite. Decoding must handle special tokens and wordpiece continuations consistently; retaining raw token IDs and normalized text separately helps distinguish model error from detokenization differences.

The exact [source processor](https://huggingface.co/jzhang533/manga-ocr-base-2025/blob/1e64d5beb41ee6bee72c200838ddb93ad541482a/preprocessor_config.json) and [export processor](https://huggingface.co/artsaraiva/manga-ocr-2025-onnx-past/blob/151898756903f03a2682fa6be4507dfeff71fb7e/preprocessor_config.json) specify bilinear resize (`resample=2`) to 224×224, RGB channels, rescaling by 1/255 and channel mean/std 0.5. The source names `ViTImageProcessorFast`, the export `ViTImageProcessor`. YomiScan's upstream original package also converts to grayscale then RGB before its processor; color/grayscale and image-resize implementations are experimental variables, not proof of runtime-only differences.

### Current ONNX OCR files and decoder contract

| File | Bytes | SHA-256 |
|---|---:|---|
| `encoder_model.onnx` | 22,279,960 | `2398ca8799bcc30a6240f2f309b3f9a1b697b5192afa9231338d2f69c3f866ef` |
| `decoder_model_merged.onnx` | 118,131,111 | `ac0ac6f48fa89bbfff1ab8d53ffcaa76839a72b145fe20a70923dc59b0b9349e` |
| `vocab.txt` | 24,072 | `344fbb6b8bf18c57839e924e2c9365434697e0227fac00b88bb4899b78aa594d` |

The repository additionally includes `config.json`, `generation_config.json`, `preprocessor_config.json`, card and attributes. Use these small source files for validated metadata; do not treat Yomu's three-file download list as the entire provenance/configuration contract.

The exact export card supplies these signatures; [Yomu's OCR consumer](https://github.com/artsaraiva/yomu/blob/ace87fef9cdfa3c7a79d3a6b57db02bbbc1b5ce5/pipeline/src/main/java/com/yomu/pipeline/ocr/OcrEngine.kt#L57) and [state ownership](https://github.com/artsaraiva/yomu/blob/ace87fef9cdfa3c7a79d3a6b57db02bbbc1b5ce5/ml/src/main/java/com/yomu/ml/PastKeyValueDecode.kt#L28) agree:

- Encoder: `pixel_values`, Float32 `[1,3,224,224]`; output `last_hidden_state`, Float32 `[1,197,192]`.
- Decoder: `input_ids`, Int64 `[1,1]`; `encoder_hidden_states`, Float32 encoder output; `use_cache_branch`, Boolean `[1]`; eight Float32 state inputs named `past_key_values.{0,1}.{decoder,encoder}.{key,value}` with shape `[1,12,n,64]`.
- Outputs: Float32 `logits` `[1,1,6144]` and corresponding `present.{0,1}.{decoder,encoder}.{key,value}` tensors. Actual static/dynamic shape/type metadata must be checked locally before relying on it.
- First step: start with CLS 2, `use_cache_branch=false`, and empty state sequence lengths `[1,12,0,64]`.
- Later steps: feed the selected next token and `use_cache_branch=true`; replace self-attention state with the newest nonempty presents. Retain the first step's encoder cross-attention state because cache-branch cross-attention presents are empty.
- Release obsolete outputs/state references as decoding progresses; retain only state still used. Release the complete request's tensors/encoder output afterward. A missing/failed step must not masquerade as an ordinary successful EOS termination.

Yomu's [greedy decoding](https://github.com/artsaraiva/yomu/blob/ace87fef9cdfa3c7a79d3a6b57db02bbbc1b5ce5/pipeline/src/main/java/com/yomu/pipeline/ocr/OcrDecoding.kt#L43) hardcodes CLS ID 2, resolves SEP from the vocabulary in its engine, and caps at 128 steps. Its confidence is the arithmetic mean of the selected token's softmax probability over the full vocabulary at each executed step, **including the stopping SEP choice**. Output text excludes SEP. A step failure and a maximum-step termination are distinguishable conditions a new adapter should expose, even though Yomu's text-return loop does not fully distinguish them.

Do not compare this greedy/cap-128 loop to the source's 4-beam/cap-300/ngram-3 defaults and attribute all differences to the runtime. A matched-runtime control needs the same weights, crop pixels, resampling, normalization, greedy/beam setting, repetition processing, token budget, stopping and text normalization. The production baseline arm should retain its existing settings as a separate arm.

### Other original-weight ONNX exports

The inspected publisher cards for [`mayocream/manga-ocr-onnx@24b12778d85800835e2ca409236de281b8ab7b9f`](https://huggingface.co/mayocream/manga-ocr-onnx/blob/24b12778d85800835e2ca409236de281b8ab7b9f/README.md) and [`onnx-community/manga-ocr-base-ONNX@f9023406bb2f6b17df67bc4a327c56ecd20611f0`](https://huggingface.co/onnx-community/manga-ocr-base-ONNX/blob/f9023406bb2f6b17df67bc4a327c56ecd20611f0/README.md) explicitly name `kha-white/manga-ocr-base`, declare Apache-2.0, and describe conversion. Neither inspected card pins the original input revision. The onnx-community repository also contains many quantizations. These are possible later controls, not evidence that arbitrary exports are equivalent or required Stage 2 dependencies. The precisely mapped 2025 source/export pair is the clearer initial runtime control.

The old l0wgear card names both the original and 2025 models but does not pin the input revision or declare a license in its card metadata. The current artsaraiva export's explicit source pin/license makes it preferable for this investigation. Its publisher's claims do not independently establish legacy-export equivalence.

## License evidence and implementation boundary

- Detector: the exact pinned [publisher card](https://huggingface.co/ogkalu/comic-text-and-bubble-detector/blob/16e8a622f91fabc6b5b65c96d32d1183f8843546/README.md) and [API metadata](https://huggingface.co/api/models/ogkalu/comic-text-and-bubble-detector/revision/16e8a622f91fabc6b5b65c96d32d1183f8843546) declare Apache-2.0. The repository has no separate inspected license/notice file or export recipe. This supports a licensed experimental download while leaving artifact lineage/training-image provenance unresolved.
- Original OCR: the exact pinned [card](https://huggingface.co/kha-white/manga-ocr-base/blob/aa6573bd10b0d446cbf622e29c3e084914df9741/README.md) declares Apache-2.0. Its model artifact is separate from YomiScan's MIT code.
- 2025 OCR: the exact source contains a full [Apache-2.0 LICENSE](https://huggingface.co/jzhang533/manga-ocr-base-2025/blob/1e64d5beb41ee6bee72c200838ddb93ad541482a/LICENSE); the pinned export card explicitly inherits Apache-2.0 from that exact source. The source card is mostly an unfilled template, so training data, detailed training procedure and independent accuracy evidence remain unknown.
- Yomu application source remains [AGPL-3.0](https://github.com/artsaraiva/yomu/blob/ace87fef9cdfa3c7a79d3a6b57db02bbbc1b5ce5/LICENSE). Independently implement Python adapters using official runtime APIs; do not translate/copy its Kotlin or export-script expression into MIT modules. Separately licensed weights do not become AGPL merely because Yomu downloads them.
- Preserve model licenses, notices and source/export revision/hash attribution if distributing artifacts; do not label the weights as YomiScan MIT. No model weights or sample pages belong in Git. A model's permissive declaration does not establish rights in unpublished training images.

## Official ONNX Runtime integration guidance

The official [Python API](https://onnxruntime.ai/docs/api/python/api_summary.html) defines `InferenceSession`, named NumPy input feeds, provider ordering and metadata inspection. Select `CPUExecutionProvider` explicitly for the baseline; inspect input/output names/shapes/types rather than assuming an export layout. GPU providers and I/O binding are separate experiments.

The official [threading guide](https://onnxruntime.ai/docs/performance/tune-performance/threading.html) documents intra-op thread count, sequential/parallel graph execution, graph optimization and spinning. Record the chosen settings and available providers in reports; multiple encoder/decoder/detector sessions can otherwise contend through independent pools. No Android/emulator timing or file-size ratio predicts local Windows speed. Test actual Python 3.13/Windows installation/inference with the locked optional runtime before calling compatibility established.

## Recommended evidence labels for Stage 2

1. **Detector A/B:** same PyTorch artifact/preprocessing, thresholds only. This isolates P14.
2. **Detector ONNX candidate:** exact `v4-s` artifact, comparable thresholds and independently varied suppression. Describe this as an export/model-candidate comparison until equivalence is demonstrated.
3. **OCR weights:** original baseline versus 2025 PyTorch, with production and matched decoding/preprocessing arms identified separately.
4. **OCR runtime:** precisely mapped 2025 PyTorch/ONNX weights, matched greedy decoding and pixels; record any remaining implementation differences. A KV-cache speed claim additionally needs an equivalent no-past loop/control, not the original heavyweight OCR baseline.
5. **Confidence:** optional diagnostic scores, method/token inclusion, termination/truncation status and provenance. Do not transplant Yomu's 0.85 rejection threshold. Only annotated held-out transcription errors can calibrate an automatic gate.

Real local measurements, graph inspection, sample permissions/annotations and production adoption decisions belong in the Stage 2 validation report. This note alone proves none of detection recall, OCR accuracy, local speed, memory improvement or default suitability.
