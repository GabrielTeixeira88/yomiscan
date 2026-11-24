"""Stage 2 spike: export the production RT-DETR-v2 detector weights (model.safetensors) to ONNX.

    uv run --frozen --extra vision --with onnx --with onnxscript --with onnxconverter-common \
        python research/stage-2/export_detector.py

Writes .cache/stage2/detector-onnx/detector.onnx (fp32) and detector-fp16.onnx:
    pixel_values [1,3,640,640] (RGB/255, PIL bilinear) -> logits [1,300,3], pred_boxes [1,300,4] (cx,cy,w,h in 0..1)
Post-processing (sigmoid, top-300 over queries x classes, thresholds) stays in JavaScript.
"""

import argparse
from pathlib import Path

import numpy as np
import torch
from transformers import RTDetrV2ForObjectDetection

from yomiscan.detection.rtdetr import MODEL_ID, MODEL_REVISION


class Detector(torch.nn.Module):
    def __init__(self, model: RTDetrV2ForObjectDetection) -> None:
        super().__init__()
        self.model = model

    def forward(self, pixel_values: torch.Tensor) -> tuple[torch.Tensor, torch.Tensor]:
        outputs = self.model(pixel_values=pixel_values)
        return outputs.logits, outputs.pred_boxes


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=Path(".cache/stage2/detector-onnx"))
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    model = RTDetrV2ForObjectDetection.from_pretrained(MODEL_ID, revision=MODEL_REVISION, use_safetensors=True,
                                                       local_files_only=True).eval()
    pixels = torch.rand(1, 3, 640, 640)
    with torch.no_grad():
        expected = [t.numpy() for t in Detector(model)(pixels)]  # before export: tracing may alter module state
        torch.onnx.export(Detector(model), (pixels,), args.output / "detector.onnx", input_names=["pixel_values"],
                          output_names=["logits", "pred_boxes"], dynamo=False, opset_version=17)
    import onnx
    import onnxruntime as ort
    from onnxruntime.transformers.float16 import convert_float_to_float16
    session = ort.InferenceSession(str(args.output / "detector.onnx"), providers=["CPUExecutionProvider"])
    got = session.run(None, {"pixel_values": pixels.numpy()})
    print("logits max abs diff", float(np.abs(got[0] - expected[0]).max()), "boxes", float(np.abs(got[1] - expected[1]).max()))
    # onnxconverter-common mistypes the position-embedding Cast in this graph; ORT's converter
    # keeps such ops in float32 (and GridSample, which has no fp16 kernel on every backend).
    half = convert_float_to_float16(onnx.load(args.output / "detector.onnx"), keep_io_types=True,
                                    op_block_list=["Cast", "GridSample", "Range", "CumSum"])
    onnx.save(half, args.output / "detector-fp16.onnx")
    half_session = ort.InferenceSession(str(args.output / "detector-fp16.onnx"), providers=["CPUExecutionProvider"])
    got16 = half_session.run(None, {"pixel_values": pixels.numpy()})
    print("fp16 logits max abs diff", float(np.abs(got16[0] - expected[0]).max()))
    for path in sorted(args.output.glob("*.onnx")):
        print(path.name, path.stat().st_size)


if __name__ == "__main__":
    main()
