"""Stage 2 spike: quantized variants of the exported manga-ocr ONNX graphs.

    uv run --frozen --extra vision --with onnx --with onnx-ir --with sympy python research/stage-2/quantize_manga_ocr.py

Variants (each a folder with encoder.onnx + decoder.onnx next to the fp32 export):
    fp16  - float16 weights and activations (inputs/outputs stay float32)
    int8  - dynamic int8 MatMul weights (ONNX Runtime quantize_dynamic, QUInt8)
    q4    - 4-bit block-wise MatMul weights (MatMulNBits, block 32), float32 activations
"""

import argparse
import shutil
from pathlib import Path

import onnx
from onnxruntime.quantization import QuantType, quantize_dynamic
from onnxruntime.transformers.float16 import convert_float_to_float16
from onnxruntime.quantization.matmul_nbits_quantizer import MatMulNBitsQuantizer


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path(".cache/stage2"))
    parser.add_argument("variants", nargs="*")
    args = parser.parse_args()
    source = args.root / "manga-ocr-onnx"
    for variant in (args.variants or ("fp16", "int8", "q4")):
        target = args.root / f"manga-ocr-onnx-{variant}"
        target.mkdir(parents=True, exist_ok=True)
        for name in ("encoder.onnx", "decoder.onnx"):
            if variant == "fp16":
                # onnxconverter-common mistypes attention Cast nodes (session creation fails);
                # ORT's converter with Cast kept in float32 produces a loadable graph.
                model = convert_float_to_float16(onnx.load(source / name), keep_io_types=True, op_block_list=["Cast"])
                onnx.save(model, target / name)
            elif variant == "int8":
                quantize_dynamic(source / name, target / name, weight_type=QuantType.QUInt8)
            else:
                quantizer = MatMulNBitsQuantizer(onnx.load(source / name), block_size=32, is_symmetric=True)
                quantizer.process()
                quantizer.model.save_model_to_file(str(target / name), use_external_data_format=False)
            print(variant, name, (target / name).stat().st_size)
        for extra in ("vocab.txt", "generation.json"):
            shutil.copy(source / extra, target / extra)


if __name__ == "__main__":
    main()
