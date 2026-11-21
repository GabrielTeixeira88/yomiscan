# Third-party resources

## Optional Stage 2 vision experiments

ONNX Runtime is **MIT**; the optional `vision` extra currently locks its CPU Python
wheel to 1.32.0. See the [runtime license](https://github.com/microsoft/onnxruntime/blob/v1.32.0/LICENSE)
and retain wheel/bundled-library notices if redistributing it. The `benchmark` extra's
psutil dependency remains BSD-3-Clause. No optional runtime or model is loaded by default.

The tested `detector-v4-s_int8.onnx` artifact declares Apache-2.0 under its exact
publisher revision; equivalence to the repository's PyTorch checkpoint is unverified.
The 2025 OCR source and precisely mapped ONNX export separately declare **Apache-2.0**.
Exact revisions, SHA-256 values, source/license links and remaining provenance limits
are recorded in [the Stage 2 artifact note](research/stage2-model-provenance.md).

These declarations support local experimentation; they do not establish rights in
training images or relicense weights as MIT. No weights, vocabulary files, manga images
or AGPL-covered Yomu implementation are bundled. Architecture and tensor contracts were
studied; the Python adapters were independently implemented. Preserve attribution,
applicable LICENSE/NOTICE material and modification notices before redistributing
model artifacts or modified weights. This task changes no project license.

## Optional manga translation benchmark

The additional `staka/fugumt-ja-en` checkpoint declares **CC-BY-SA-4.0** (attribution
and ShareAlike terms for adaptations). `facebook/nllb-200-distilled-600M` declares
**CC-BY-NC-4.0**, restricting use to **non-commercial** purposes. These optional model
weights are not MIT; NLLB is not an unrestricted commercial-compatible default.
See the [NMT extension and license sources](translation-benchmark.md#nmt-extension-fugumt-and-nllb-600m).

Hy-MT2 manga v5, Qwen3.5 VNTL and Qwen2.5 manga adapter publishers declare Apache-2.0;
the tested Hy-MT2 and Qwen2.5 bases also declare Apache-2.0. VNTL currently publishes
no weights, so its runtime artifact cannot yet be verified. No optional weights are
bundled or relicensed under YomiScan MIT. llama.cpp is MIT; psutil is BSD-3-Clause.
See [exact artifacts, primary sources and redistribution notes](translation-benchmark.md).

YomiScan's MIT license covers its original code, not downloaded dictionaries, model
weights, or third-party packages. No dictionary dataset is committed here.

## JMdict

This project uses the JMdict dictionary from the Electronic Dictionary Research and
Development Group (EDRDG), built by its contributors and coordinated by Jim Breen.
Copyright belongs to the resource's rights holders, including James William Breen
and EDRDG. Japanese/English JMdict data is available under **CC BY-SA 4.0**.

- [Project documentation](https://www.edrdg.org/wiki/JMdict-EDICT_Dictionary_Project.html)
- [EDRDG license and attribution requirements](https://www.edrdg.org/edrdg/licence.html)
- [CC BY-SA 4.0 license](https://creativecommons.org/licenses/by-sa/4.0/)
- [Official download](https://www.edrdg.org/pub/Nihongo/JMdict_e.gz)
- [XML format](https://www.edrdg.org/jmdict/jmdict_dtd_h.html)

The SQLite database is transformed JMdict data: YomiScan selects English glosses,
preserves selected lexical metadata, and builds normalized lookup indexes. Its
metadata table records source, hash, time, attribution, and changes. Do not label
this derived data MIT. If distributing it, preserve attribution and licensing,
identify the transformation, and meet applicable ShareAlike and EDRDG documentation
requirements. Include the resource's documentation/license files with redistributed
data. The CLI prints source attribution; future UI must also provide attribution.

Refresh downloaded data and reimport it periodically using the README commands;
review EDRDG's current update and distribution requirements before packaging releases.

## fugashi and UniDic-lite

[fugashi](https://github.com/polm/fugashi) wraps MeCab and is MIT-licensed. Its binary
distribution includes MeCab notices; retain them when redistributing binaries.
YomiScan explicitly selects [UniDic-lite](https://github.com/polm/unidic-lite), a
packaged, modified UniDic 2.1.2 baseline. UniDic Consortium dictionary data uses BSD
terms; the package wrapper offers MIT/WTFPL licensing. Keep the data's original
copyright, conditions, and disclaimer when redistributing it.

See the [UniDic data license](https://github.com/polm/unidic-lite/blob/master/LICENSE.unidic)
and the license files shipped with the installed packages. UniDic supplies morphology
and readings; it does not supply YomiScan's English meanings. It is distinct from JMdict.

## OCR and other packages

manga-ocr, its model weights, PyTorch, Pillow, and all other dependencies retain their
own licenses. Consult the [manga-ocr repository](https://github.com/kha-white/manga-ocr)
and [model card](https://huggingface.co/kha-white/manga-ocr-base) for their terms and
training-resource information. No model or training dataset is relicensed by this repo.
## Phase 3 translation model

The local default is Helsinki-NLP's `opus-mt-ja-en` checkpoint, revision
`0770961a39ba6bd66305b149c3f4110bcafca2e6`. Its
[Hugging Face model card](https://huggingface.co/Helsinki-NLP/opus-mt-ja-en/blob/0770961a39ba6bd66305b149c3f4110bcafca2e6/README.md)
declares **Apache-2.0**. These weights are not covered by YomiScan's MIT license.
Retain applicable attribution, license and notices, and identify modifications if
redistributing. The broader [OPUS-MT project](https://github.com/Helsinki-NLP/Opus-MT)
also describes original model releases under CC-BY-4.0; preserve source provenance
and verify the exact artifact's terms before redistributing it. No weights are bundled
with this repository. They are downloaded directly to the user's local cache.

The evaluated M2M100 checkpoint declares MIT; NLLB-200 distilled declares
CC-BY-NC-4.0 and carries a noncommercial restriction. Neither is the default or bundled.
See [Phase 3 research and evaluation](phase-3-translation.md) for source links and limits.

## Phase 5 detector

The publisher of [`ogkalu/comic-text-and-bubble-detector`](https://huggingface.co/ogkalu/comic-text-and-bubble-detector)
lists **Apache-2.0** for the selected RT-DETR-v2 weights. YomiScan downloads the pinned
revision documented in [Phase 5](phase-5-page-analysis.md); weights are not committed
or relicensed under YomiScan's MIT license. No third-party detector source is vendored.

Apache-2.0 permits use, modification and distribution, including commercial use,
subject to its conditions. If distributing the model, include its license, retain
applicable attribution and NOTICE material, and identify modifications where required.
The license does not grant trademark rights or ownership of training images. Preserve
the publisher's provenance and review all bundled artifacts before packaging an extension
or installer. See the [official Apache-2.0 text](https://www.apache.org/licenses/LICENSE-2.0).
Current Chrome screenshots are processed locally; only initial weights are downloaded.

## Phase 6 rendering and font

OpenCV 4.x is [Apache-2.0](https://opencv.org/license/); the headless Python wheel
also carries its own package/bundled-library notices. NumPy uses BSD-3-Clause.
Keep dependency notices when redistributing an application/runtime. No new neural
inpainting weights are used, so there is no additional model license or model download.
Existing detector/OCR/translation licenses still apply independently.

English rendering uses the **Aileron Regular subset embedded in Pillow**, not an OS
font. The [font author's terms](https://dotcolon.net/fonts/aileron/) state
**No Rights Reserved** and permit modification/redistribution. Pillow's code remains
under [MIT-CMU](https://github.com/python-pillow/Pillow/blob/main/LICENSE).
For the historical English default, Pillow supplies this font during
installation. This font is not relicensed under YomiScan's MIT license. Preserve Pillow
and relevant third-party notices in future packaged runtimes. The subset does not cover
every Unicode character; unsupported translations are safely skipped.

## Stage 4 Latin font and translation candidates

Portuguese/Spanish accents missing from that subset use the unmodified **Noto Sans
2.015** font bundled in `backend/yomiscan/resources/fonts/`, under **SIL OFL-1.1**.
Its full notice, source pin and checksum accompany the resource. OFL permits
bundling with software while retaining the font's notice/license; rendered page
images do not inherit OFL. YomiScan source remains MIT. There is no runtime font download.

The pinned Helsinki JA→PT and JA→ES candidates declare **Apache-2.0** on their model
cards. NLLB-200 distilled 600M declares **CC-BY-NC-4.0**, a noncommercial limitation;
it remains an optional research adapter, with no weights bundled. Generic Portuguese
support is not validation of Brazilian manga usage. Exact revisions, checksums,
primary-source links and evaluation limits appear in
[Stage 4 results](research/stage4-translation-results.md).
