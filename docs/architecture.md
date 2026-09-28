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
recognition accuracy. Real screenshot evaluation remains required.

## Study mode: FUTURE WORK

```text
Chrome Extension [FUTURE WORK]
  ↓
screenshot selection [FUTURE WORK]
  ↓
FastAPI [FUTURE WORK]
  ↓
OCR [implemented adapter; real-image validation pending]
  ↓
Japanese morphological analysis [FUTURE WORK]
  ↓
JMdict / local lexical database [FUTURE WORK]
  ↓
local sentence translation [FUTURE WORK]
  ↓
single detailed study popup [FUTURE WORK]
```

The eventual popup will combine original Japanese, English sentence translation,
readings, dictionary forms, meanings, parts of speech, verbs, particles, and optional
JLPT information. None of that UI or linguistic processing is implemented.

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
translation [FUTURE WORK]
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
compare PaddleOCR or other Japanese recognizers behind that interface. A future
`TranslationEngine` boundary may serve the same purpose for translation, but it is not
implemented. No plugin registry or speculative framework is needed. Benchmark accuracy,
latency, resource use, licenses, and Windows/Python compatibility before choosing major
components. CPU support must remain possible; paid/cloud APIs are outside the design.
