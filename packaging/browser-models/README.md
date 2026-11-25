---
license: other
license_name: mixed-see-readme
library_name: onnxruntime-web
language:
  - ja
  - en
tags:
  - yomiscan
  - manga
  - ocr
  - translation
  - onnx
---

# YomiScan browser models ($bundle)

These are the model and dictionary files for the [YomiScan](https://github.com/GabrielTeixeira88/yomiscan) Chrome
extension's browser engine. With them, the extension detects text in manga pages, reads it,
looks words up and translates Japanese to English **inside Chrome**, with no server and no
account.

The extension downloads these files only after the user clicks **Download**. It checks every
file against a size and SHA-256 that are compiled into the extension, so the copies here cannot
be swapped. `manifest.json` lists the same values. Nothing is uploaded back.

## Contents

| Component | Files | Size | License | Source |
|---|---|---:|---|---|
$components

A device downloads either `ocr-q4` (WebGPU) or `ocr-int8` (CPU), never both.

## Licenses and attribution

These files are **not** covered by YomiScan's MIT license. Each component keeps its own terms:

- **Text detector**: an ONNX fp16 export of
  [ogkalu/comic-text-and-bubble-detector](https://huggingface.co/ogkalu/comic-text-and-bubble-detector)
  (RT-DETR-v2), Apache-2.0. The weights are unchanged; only the format and precision differ.
- **OCR**: ONNX exports (q4 and int8 quantized) of
  [kha-white/manga-ocr-base](https://huggingface.co/kha-white/manga-ocr-base), Apache-2.0.
  Quantization changes the weights' precision; the vocabulary is unchanged.
- **Translation**: the fp16 ONNX export
  [Xenova/opus-mt-ja-en](https://huggingface.co/Xenova/opus-mt-ja-en) of
  [Helsinki-NLP/opus-mt-ja-en](https://huggingface.co/Helsinki-NLP/opus-mt-ja-en)
  (Apache-2.0 on its model card), from the [OPUS-MT project](https://github.com/Helsinki-NLP/Opus-MT)
  by Jörg Tiedemann and the Language Technology Research Group at the University of Helsinki.
- **Tokenizer**: the WebAssembly build of [lindera](https://github.com/lindera/lindera)
  (`lindera-wasm-unidic` 2.1.0, MIT), which embeds the UniDic 2.1.2 dictionary.
  UniDic: Copyright (c) 2011-2017, The UniDic Consortium, BSD 3-Clause (see `LICENSES/`).
- **Dictionary**: `dictionary/jmdict.sqlite3` contains material from the
  [JMdict](https://www.edrdg.org/wiki/JMdict-EDICT_Dictionary_Project.html) dictionary files in
  accordance with the licence provisions of the Electronic Dictionary Research and Development
  Group ([EDRDG licence](https://www.edrdg.org/edrdg/licence.html)). JMdict is Copyright James
  William Breen and The Electronic Dictionary Research and Development Group, and is used
  under [CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0/). YomiScan's importer
  converted the XML into SQLite: it keeps English glosses and selected lexical metadata and
  adds normalized lookup indexes. The database's `metadata` table records the source file,
  its hash and the conversion. This derived database is shared under CC BY-SA 4.0.

License texts: `LICENSES/Apache-2.0.txt`, `LICENSES/UniDic-BSD-3-Clause.txt` and
`LICENSES/lindera-MIT.txt`.

## Rebuilding

`scripts/build_browser_artifacts.py` in the YomiScan repository rebuilds this folder from the
pinned upstream exports, and `scripts/publish_browser_artifacts.py` uploads it.
