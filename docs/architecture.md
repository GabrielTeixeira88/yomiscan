# YomiScan architecture

## Phase 1: implemented OCR boundary

Local cropped image → Pillow decoding → `OCREngine.recognize(image)` → `OCRResult`

The `yomiscan` package lives under `backend/`. `ocr/base.py` defines a structural
Protocol and a dataclass containing text, engine name, inference milliseconds, and
optional metadata (an empty dictionary by default). It does not define bounding boxes.
`ocr/manga_ocr.py` adapts manga-ocr, imports it lazily, initializes once per instance,
and preserves third-party exceptions as causes of contextual errors. `ocr/cli.py`
validates input and formats results; `scripts/ocr_image.py` is its entry point.

Inference runs locally. Initial dependency/model downloads require internet; cached
weights support offline use. Unit tests mock the neural network and cannot establish
recognition accuracy. Phase 1 has successfully run on real screenshots; broader
accuracy evaluation remains required.

## Phase 2: implemented analysis boundary

```text
image → OCREngine → OCRResult.text
                          ↓
text → JapaneseTokenizer → ordered JapaneseToken values
                          ↓
               indexed local SQLite JMdict lookup
                          ↓
                   TextAnalysisResult
```

`nlp/base.py` defines the token dataclass and structural tokenizer protocol.
`FugashiTokenizer` owns one fugashi Tagger using the explicitly selected UniDic-lite
dictionary. It retains lemma, written reading, POS hierarchy, conjugation type/form,
orthographic base, and base reading. Missing UniDic values become `None`.
Kana is normalized to hiragana without inventing long vowels or unknown readings.

`dictionary/importer.py` streams official JMdict XML/XML.gz once into SQLite.
`entries` stores each entry's spellings, readings, English senses, expanded POS labels,
reading/sense restrictions, and notes as JSON. Omitted sense POS inherits the preceding
sense POS. `forms` has a composite primary-key index `(form, entry_id)` for parameterized
exact lookup; normalized forms use NFKC and katakana-to-hiragana conversion. `metadata`
records provenance, source hash, import time, attribution, and the transformation.
The importer builds in a temporary sibling file and replaces the destination only
after a successful complete import; the schema has an explicit version.

`SQLiteDictionary` keeps one read-only connection for its context-manager lifetime.
It never creates an empty database on a missing-file lookup. `TextAnalyzer` accepts
the tokenizer and a small dictionary lookup protocol, so tokenizer benchmarks need
not change the dictionary or OCR adapters. A per-analysis query cache avoids repeating
lookups; no persistent/global cache is needed.

Lookup tries the written base (`orthBase`), UniDic lemma, surface, and base reading in
that order, stopping at the first exact match. There is no substring matching or
handwritten deconjugation. Written base forms avoid UniDic lemma labels with foreign
suffixes. Punctuation/symbol-only tokens are preserved but skipped for lookup.

`TextAnalysisResult` retains original text, ordered `AnalyzedToken` values, and a map
of unique entries keyed by JMdict ID. Each analyzed token contains the morphological
token, matched query, and entry IDs. This avoids copying large entries for repeated
words. `ImageAnalysisResult` combines the OCR result with text analysis. The text CLI
does not construct an OCR engine; the image CLI constructs it once per invocation.

Full candidate entries are exposed, including restrictions. This version does not
select a context-specific sense, filter homophones by POS, join multi-token expressions,
or apply restrictions as a grammatical interpretation. Those limitations are visible
in CLI output. Source XML/databases live in ignored `data/`; they are never committed.

## Study mode: FUTURE WORK

```text
Chrome Extension [FUTURE WORK]
  ↓
screenshot selection [FUTURE WORK]
  ↓
FastAPI [FUTURE WORK]
  ↓
OCR [IMPLEMENTED]
  ↓
Japanese morphological analysis [IMPLEMENTED]
  ↓
JMdict / local lexical database [IMPLEMENTED]
  ↓
local sentence translation [IMPLEMENTED]
  ↓
single detailed study popup [FUTURE WORK]
```

The eventual popup will combine original Japanese, English sentence translation,
readings, dictionary forms, meanings, parts of speech, verbs, particles, and optional
JLPT information. The UI and JLPT grading remain future work.
Tokens, readings, lemmas, POS, conjugation, and dictionary candidates are implemented.

## Full-page translation: FUTURE WORK

```text
manga page [FUTURE input workflow]
  ↓
text detection [FUTURE WORK]
  ↓
OCR [adapter exists; page integration is FUTURE WORK]
  ↓
sentence reconstruction [FUTURE WORK]
  ↓
translation [adapter exists; page integration is FUTURE WORK]
  ↓
text masks [FUTURE WORK]
  ↓
inpainting [FUTURE WORK]
  ↓
typesetting [FUTURE WORK]
  ↓
translated manga page [FUTURE WORK]
```

Recognition and localization are separate responsibilities. Detection will eventually
provide regions and reading order; manga-ocr currently receives an already cropped image.

## Replaceability

Consumers can accept `OCREngine` without depending on manga-ocr. Future benchmarks may
compare PaddleOCR or other Japanese recognizers behind that interface. The
`TranslationEngine` boundary serves the same purpose for translation and is now
implemented. No plugin registry or speculative framework is needed. Benchmark accuracy,
latency, resource use, licenses, and Windows/Python compatibility before choosing major
components. `JapaneseTokenizer` allows a later comparison with SudachiPy without
changing the analysis pipeline. CPU support must remain possible; paid/cloud APIs are
outside the design.

## Phase 3: implemented sentence translation

```text
cropped image → OCREngine → Japanese text
                                ↓
                         TranslationEngine → TranslationResult
                                ↓
                      tokenizer + local JMdict lookup
                                ↓
                         TextAnalysisResult
```

`translation/base.py` defines `TranslationResult` and a structural `TranslationEngine`
protocol with `translate(text)` and `translate_many(texts)`. Results retain the exact
source, translated text, engine/model identifiers, elapsed milliseconds, and metadata.
The sequence contract preserves order and cardinality. Empty batches return `[]`;
blank members reject the request before inference. Exceptions propagate with context.

`MarianTranslationEngine` loads one pinned OPUS-MT tokenizer/model pair, sets eval mode,
and reuses it under PyTorch inference mode. No model imports occur until construction.
The adapter owns whitespace normalization, generation parameters, input length checks,
and device handling. It pads independent regions in bounded batches (default eight),
does not silently truncate source text, and rejects incomplete generated text.
Results within a batch share the complete batch elapsed time; this is not per-item
latency or an amortized estimate. Timing covers tokenization, transfers, generation,
decoding, and CUDA synchronization, excluding model setup/download.

`auto` uses available CUDA, otherwise CPU; explicit unavailable CUDA fails. CUDA
runtime failures do not silently retry on CPU. No global mutable model state, plugin
registry, configuration framework, or cloud service exists. Model instances are used
sequentially; thread-safe concurrent inference is not promised by this interface.

`TextAnalyzer` optionally accepts an existing translator, calls it once per nonblank
region, then performs the unchanged lexical lookup. `TextAnalysisResult.translation`
is a separate optional result; `dictionary_entries` still holds lexical candidates.
`processing_time_ms` on text analysis measures NLP/dictionary work only. Without a
translator, or with blank input, translation is `None`; Phase 2 callers continue to
work. A requested translation failure raises instead of masquerading as lexical-only
success. `ImageAnalysisResult` retains separate OCR and analysis results/times.

The standalone translation CLI accepts multiple quoted regions. Text analysis adds
opt-in `--translate`, while image analysis translates by default with an explicit
`--no-translation` option. Models are constructed once per invocation, never per token.
Dictionary attribution remains visible independently of generated English.

## Translate Chapter: future orchestration only

```text
chapter reader
  → discover manga page images
  → process each page independently
  → detect ordered Japanese text regions
  → OCR / reconstruct complete sentences within those regions
  → translate sentences (existing batch-capable boundary)
  → inpaint Japanese → typeset English
  → overlay translated image; offer Original / English switch
  → continue through chapter and newly lazy-loaded images
```

The user-facing unit is a chapter; the internal image-processing unit is normally one
manga page. A future caller can prioritize visible/current pages, then later pages,
and react to lazy loading. It can associate ordered translation results with region
IDs outside the engine and reuse one model across pages. A batch contains independent
regions, not a concatenated chapter or dictionary tokens. Cross-region conversational
context is not provided by Phase 3. No page discovery, browser code, queues, detection,
inpainting, typesetting, or image replacement is implemented here. See the
[model decision and evaluation](phase-3-translation.md).
