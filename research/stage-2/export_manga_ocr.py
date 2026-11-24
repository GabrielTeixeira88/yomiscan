"""Stage 2 spike: export the original manga-ocr weights (kha-white/manga-ocr-base) to ONNX.

Run (export tools are ephemeral, not added to the project lock):
    uv run --frozen --extra vision --with onnx --with onnxscript python research/stage-2/export_manga_ocr.py

Writes to .cache/stage2/manga-ocr-onnx/ (ignored):
    encoder.onnx  pixel_values [1,3,224,224] -> last_hidden_state [1,197,768]
    decoder.onnx  input_ids [B,T] int64, encoder_hidden_states [B,197,768] -> logits [B,T,6144]
The decoder has no KV cache: it re-reads the whole prefix each step. It has 2 layers and
manga-ocr sequences are short, so this stays simple; a cached decoder is a later option.
"""

import argparse
import json
from pathlib import Path

import numpy as np
import torch
from transformers import VisionEncoderDecoderModel

from yomiscan.vision_models import model_directory


class Encoder(torch.nn.Module):
    def __init__(self, model: VisionEncoderDecoderModel) -> None:
        super().__init__()
        self.encoder = model.encoder

    def forward(self, pixel_values: torch.Tensor) -> torch.Tensor:
        return self.encoder(pixel_values=pixel_values).last_hidden_state


class Decoder(torch.nn.Module):
    def __init__(self, model: VisionEncoderDecoderModel) -> None:
        super().__init__()
        self.decoder = model.decoder

    def forward(self, input_ids: torch.Tensor, encoder_hidden_states: torch.Tensor) -> torch.Tensor:
        return self.decoder(input_ids=input_ids, encoder_hidden_states=encoder_hidden_states, use_cache=False).logits


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=Path(".cache/stage2/manga-ocr-onnx"))
    args = parser.parse_args()
    source = model_directory("ocr-original")
    # Eager attention: the SDPA path chooses its causal mask from Python-level shape checks,
    # which tracing would freeze for the example sequence length.
    model = VisionEncoderDecoderModel.from_pretrained(source, attn_implementation="eager").eval()
    args.output.mkdir(parents=True, exist_ok=True)
    pixels = torch.randn(1, 3, 224, 224)
    with torch.no_grad():
        hidden = Encoder(model)(pixels)
        ids = torch.tensor([[2, 100, 200], [2, 300, 400]], dtype=torch.long)
        # Reference outputs are taken before exporting: the exporter's tracing can leave the
        # module in a state that no longer reproduces a fresh model (seen as a ~2.0 logit drift).
        expected_hidden = hidden.numpy()
        expected_logits = Decoder(model)(ids, hidden.repeat(2, 1, 1).contiguous()).numpy()
        torch.onnx.export(Encoder(model), (pixels,), args.output / "encoder.onnx", input_names=["pixel_values"],
                          output_names=["last_hidden_state"], dynamo=False, opset_version=17)
        torch.onnx.export(Decoder(model), (ids, hidden.repeat(2, 1, 1).contiguous()), args.output / "decoder.onnx",
                          input_names=["input_ids", "encoder_hidden_states"], output_names=["logits"],
                          dynamic_axes={"input_ids": {0: "batch", 1: "tokens"},
                                        "encoder_hidden_states": {0: "batch"}, "logits": {0: "batch", 1: "tokens"}},
                          dynamo=False, opset_version=17)
    import onnxruntime as ort
    encoder = ort.InferenceSession(str(args.output / "encoder.onnx"), providers=["CPUExecutionProvider"])
    decoder = ort.InferenceSession(str(args.output / "decoder.onnx"), providers=["CPUExecutionProvider"])
    got_hidden = encoder.run(None, {"pixel_values": pixels.numpy()})[0]
    got_logits = decoder.run(None, {"input_ids": ids.numpy(), "encoder_hidden_states": np.repeat(got_hidden, 2, 0)})[0]
    print("encoder max abs diff", float(np.abs(got_hidden - expected_hidden).max()))
    print("decoder max abs diff", float(np.abs(got_logits - expected_logits).max()))
    vocabulary = (source / "vocab.txt").read_text(encoding="utf-8")
    (args.output / "vocab.txt").write_text(vocabulary, encoding="utf-8")
    generation = {key: getattr(model.generation_config, key, None) or model.config.to_dict().get(key)
                  for key in ("decoder_start_token_id", "eos_token_id", "pad_token_id", "max_length", "num_beams",
                              "early_stopping", "no_repeat_ngram_size", "length_penalty")}
    (args.output / "generation.json").write_text(json.dumps(generation, indent=1), encoding="utf-8")
    for path in sorted(args.output.glob("*.onnx")):
        print(path.name, path.stat().st_size)


if __name__ == "__main__":
    main()
