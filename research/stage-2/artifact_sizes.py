"""Stage 2 spike (G6): raw and compressed transfer sizes of candidate browser artifacts.

    uv run --frozen python research/stage-2/artifact_sizes.py
Compression is gzip level 9 (what a static host or CDN would serve at minimum; Brotli is smaller).
"""

import gzip
import json
from pathlib import Path

ROOT = Path(".cache/stage2")
GROUPS = {
    "ocr-fp32": [ROOT / "manga-ocr-onnx" / n for n in ("encoder.onnx", "decoder.onnx", "vocab.txt")],
    "ocr-fp16": [ROOT / "manga-ocr-onnx-fp16" / n for n in ("encoder.onnx", "decoder.onnx", "vocab.txt")],
    "ocr-int8": [ROOT / "manga-ocr-onnx-int8" / n for n in ("encoder.onnx", "decoder.onnx", "vocab.txt")],
    "ocr-q4": [ROOT / "manga-ocr-onnx-q4" / n for n in ("encoder.onnx", "decoder.onnx", "vocab.txt")],
    "detector-fp32": [ROOT / "detector-onnx" / "detector.onnx"],
    "detector-fp16": [ROOT / "detector-onnx" / "detector-fp16.onnx"],
    "ort-web-runtime": sorted((ROOT / "extension" / "ort").glob("*")),
    "tokenizer-lindera-unidic": [Path("research/stage-2/browser/node_modules/lindera-wasm-unidic/lindera_wasm_unidic_bg.wasm")],
    "opus-q8": [ROOT / "hf/Xenova/opus-mt-ja-en" / n for n in ("onnx/encoder_model_quantized.onnx",
                "onnx/decoder_model_merged_quantized.onnx", "tokenizer.json", "config.json", "generation_config.json")],
    "opus-fp16": [ROOT / "hf/Xenova/opus-mt-ja-en" / n for n in ("onnx/encoder_model_fp16.onnx",
                  "onnx/decoder_model_merged_fp16.onnx", "tokenizer.json", "config.json", "generation_config.json")],
    "jmdict-source": [Path("data/JMdict_e.gz")],
    "jmdict-sqlite": [Path("data/jmdict.sqlite3")],
}


def main() -> None:
    sizes = {}
    for name, files in GROUPS.items():
        raw = compressed = 0
        for path in files:
            data = path.read_bytes()
            raw += len(data)
            compressed += len(data) if path.suffix == ".gz" else len(gzip.compress(data, compresslevel=9))
        sizes[name] = {"raw_bytes": raw, "gzip_bytes": compressed, "files": len(files)}
        print(f"{name:18s} raw {raw / 2**20:8.1f} MiB  gzip {compressed / 2**20:8.1f} MiB")
    (ROOT / "artifact-sizes.json").write_text(json.dumps(sizes, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
