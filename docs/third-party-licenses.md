# Third-party resources

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
