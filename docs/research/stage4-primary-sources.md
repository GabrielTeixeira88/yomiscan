# Stage 4 primary-source checks

Inspected 2026-11-20. YomiScan Stage 4 starts at Stage 3 merge
`4b51ce5d619f8a7dfb15e7bf7bbe34a2473ba1ef`. Yomu reference pin remains
`ace87fef9cdfa3c7a79d3a6b57db02bbbc1b5ce5`.

- Yomu's [NameGlossary.applyTo](https://github.com/artsaraiva/yomu/blob/ace87fef9cdfa3c7a79d3a6b57db02bbbc1b5ce5/core/src/main/java/com/yomu/core/NameGlossary.kt#L3)
  replaces source substrings, longest first, without token boundaries or normalization.
  Its [store](https://github.com/artsaraiva/yomu/blob/ace87fef9cdfa3c7a79d3a6b57db02bbbc1b5ce5/app/src/main/java/com/yomu/app/translation/NameGlossaryStore.kt#L8)
  is a global reader preference. Stage 4 independently implements scoped normalized
  token-boundary hints, preserving OCR and translated output.
- Yomu's [context ADR amendments](https://github.com/artsaraiva/yomu/blob/ace87fef9cdfa3c7a79d3a6b57db02bbbc1b5ce5/docs/adr/0002-cross-panel-translation-context.md)
  record CAT 0.8B batch/context failures, later page-level adoption on a different
  Qwen model, withdrawal of previous-page memory after overflow/no quality gain,
  and replacement of box-gap panels with drawn white gutters. These are
  model/platform-specific findings, not a Windows accuracy benchmark.
- [ContextAssembler](https://github.com/artsaraiva/yomu/blob/ace87fef9cdfa3c7a79d3a6b57db02bbbc1b5ce5/pipeline/src/main/java/com/yomu/pipeline/context/ContextAssembler.kt#L24)
  and [PaperMask](https://github.com/artsaraiva/yomu/blob/ace87fef9cdfa3c7a79d3a6b57db02bbbc1b5ce5/pipeline/src/main/java/com/yomu/pipeline/context/PaperMask.kt#L7)
  inspire an independent bounded XY-cut experiment. Their straight white gutters
  cannot establish speakers or reliable borderless/slanted panels.
- Yomu's [grammar ADR](https://github.com/artsaraiva/yomu/blob/ace87fef9cdfa3c7a79d3a6b57db02bbbc1b5ce5/docs/adr/0013-grammar-constrained-page-level-batch.md)
  records structural recovery and a later mandatory-newline/EOG failure. Its
  [bridge](https://github.com/artsaraiva/yomu/blob/ace87fef9cdfa3c7a79d3a6b57db02bbbc1b5ce5/ml/src/main/java/com/yomu/ml/LlamaTranslationBridge.kt#L54)
  tolerates partial ID recovery. Our stricter complete-page contract is a user
  requirement, not a direct port of that parser.
- Installed llama.cpp **b11380**, commit
  `eec18f5d32099fb15d4ba15003a231bcc72757d5`, was checked with `--version`
  and actual cached-weight generation. The pinned
  [server parser](https://github.com/ggml-org/llama.cpp/blob/eec18f5d32099fb15d4ba15003a231bcc72757d5/tools/server/server-common.cpp#L1258)
  reads `response_format.json_schema.schema`. This nested wrapper matters: an
  empty schema permits any object. The
  [server documentation](https://github.com/ggml-org/llama.cpp/blob/eec18f5d32099fb15d4ba15003a231bcc72757d5/tools/server/README.md)
  supplies `/apply-template`, `/tokenize` and completion APIs. We verify the actual
  compiled path, include the contract in the prompt and validate again after decoding.
- The pinned [JA→PT card](https://huggingface.co/Helsinki-NLP/opus-mt-ja-pt/blob/15f163ca52b8d17d729d3c76aa3d9eabc4213367/README.md)
  declares Apache-2.0 and generic Portuguese. That checkpoint's vocabulary has
  `>>por<<`; a newer upstream training ZIP's `>>pob<<` is not interchangeable.
  The pinned [JA→ES card](https://huggingface.co/Helsinki-NLP/opus-mt-ja-es/blob/d1693e4d2bc285d02653ff6438fe21e2b3c6025e/README.md)
  declares Apache-2.0 and needs no target prefix. Metadata/config/tokenizer files
  were checked, but neither new weight file was downloaded in this task.
- The [NLLB card](https://huggingface.co/facebook/nllb-200-distilled-600M/blob/f8d333a098d19b4fd9a8b18f94170487ad3f821d/README.md)
  declares CC-BY-NC-4.0 and research-oriented sentence translation. The cached
  tokenizer resolves `jpn_Jpan=256079`, `eng_Latn=256047`, `por_Latn=256141`,
  `spa_Latn=256161`. Generic Portuguese is not a regional-quality guarantee.
- [Noto Sans 2.015](https://github.com/google/fonts/tree/8b0a1d0f5983c89bc2b93f1b5fb55f9e252744b5/ofl/notosans)
  is bundled unmodified with its SIL OFL-1.1 notice as an offline accent fallback.
  The resource's README records its exact checksum. No Yomu font or source was copied.

The earlier [repository comparison](../yomiscan-vs-yomu-research.md) preserves the
broader implementation/history review. [Stage 4 results](stage4-translation-results.md)
separate our measurements from these upstream observations.
