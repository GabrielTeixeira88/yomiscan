"""Torch-free manga-ocr (original weights) on the pinned int8 ONNX export (Stage 5b).

The files are the browser bundle's CPU OCR. int8 matched PyTorch on 223/225 blocks and was the
fastest variant on CPU; on DirectML it is slower (its integer ops fall back to the CPU), so the
local engine runs OCR on the CPU even when the detector uses the GPU.

Mirrors MangaOCREngine's greedy path: grayscale -> RGB, ViTImageProcessor (PIL bilinear 224x224,
rescale 1/255, normalize mean/std .5), greedy decoding to eos or max_length, tokenizer decode
with special tokens skipped, then manga-ocr's post_process (normalize_recognition).
"""

import json
from pathlib import Path
from time import perf_counter
from typing import Any

import numpy as np
from PIL import Image

from .base import OCRInitializationError, OCRRecognitionError, OCRResult
from .normalization import normalize_recognition

COMPONENT = "ocr-int8"
SIZE = 224
SPECIAL = frozenset({"[PAD]", "[UNK]", "[CLS]", "[SEP]", "[MASK]"})


def ocr_pixels(image: Image.Image) -> np.ndarray:
    rgb = image.convert("L").convert("RGB").resize((SIZE, SIZE), Image.Resampling.BILINEAR)
    pixels = (np.asarray(rgb, dtype=np.float64) * (1 / 255)).astype(np.float32)
    pixels = (pixels - np.float32(.5)) / np.float32(.5)
    return np.ascontiguousarray(pixels.transpose(2, 0, 1)[None])


def decode_tokens(tokens: list[int], vocabulary: list[str]) -> str:
    return normalize_recognition("".join(vocabulary[t].removeprefix("##") for t in tokens if vocabulary[t] not in SPECIAL))


class PinnedMangaOCREngine:
    def __init__(self, *, device: str = "cpu", threads: int = 4,
                 model_root: Path | None = None, encoder: Any = None, decoder: Any = None,
                 vocabulary: list[str] | None = None, generation: dict[str, int] | None = None) -> None:
        self.device, self.threads = device, threads
        self._cache_artifacts: dict[str, str] | None = None
        try:
            if encoder is None or decoder is None:
                from ..engine_models import component_directory, load_bundle
                from ..onnx_runtime import session
                bundle = load_bundle()
                component = COMPONENT
                folder = component_directory(component, bundle=bundle, root=model_root) / component
                vocabulary = (folder / "vocab.txt").read_text(encoding="utf-8").splitlines()
                generation = json.loads((folder / "generation.json").read_text(encoding="utf-8"))
                encoder = session(folder / "encoder.onnx", threads=threads, device=device)  # type: ignore[arg-type]
                decoder = session(folder / "decoder.onnx", threads=threads, device=device)  # type: ignore[arg-type]
                self._cache_artifacts = {f.path: f.sha256 for f in bundle.components[component].files}
            if vocabulary is None or generation is None:
                raise ValueError("Injected OCR sessions need a vocabulary and generation settings")
            self.vocabulary = vocabulary
            self.start_id, self.end_id = int(generation["decoder_start_token_id"]), int(generation["eos_token_id"])
            self.max_length = int(generation["max_length"])
            if not 0 <= self.start_id < len(vocabulary) or not 0 <= self.end_id < len(vocabulary) or self.max_length < 2:
                raise ValueError("OCR generation settings do not fit the vocabulary")
        except Exception as exc:
            raise OCRInitializationError(f"Cannot initialize the Torch-free manga-ocr on {device}: {exc}") from exc
        self.encoder, self.decoder = encoder, decoder

    def diagnostic_metadata(self) -> dict[str, object]:
        return {"engine": "manga-ocr-pinned-onnx", "variant": "int8", "device": self.device,
                "decoding": "greedy", "num_beams": 1, "max_length": self.max_length, "threads": self.threads}

    def recognize(self, image: Image.Image) -> OCRResult:
        if not isinstance(image, Image.Image):
            raise TypeError("image must be a Pillow Image")
        start = perf_counter()
        try:
            hidden = self.encoder.run(["last_hidden_state"], {"pixel_values": ocr_pixels(image)})[0]
            tokens = [self.start_id]
            # The export has no KV cache: each step decodes the whole sequence, as the browser engine.
            while len(tokens) < self.max_length:
                logits = self.decoder.run(["logits"], {"input_ids": np.array([tokens], dtype=np.int64),
                                                       "encoder_hidden_states": hidden})[0]
                row = np.asarray(logits, dtype=np.float32)[0, -1]
                if row.shape != (len(self.vocabulary),) or not np.isfinite(row).all():
                    raise ValueError("OCR decoder returned invalid logits")
                tokens.append(int(np.argmax(row)))
                if tokens[-1] == self.end_id:
                    break
            text = decode_tokens(tokens, self.vocabulary)
        except Exception as exc:
            raise OCRRecognitionError(f"Torch-free manga-ocr failed on {self.device}: {exc}") from exc
        return OCRResult(text, "manga-ocr", (perf_counter() - start) * 1000, self.diagnostic_metadata())

    def close(self) -> None:
        self.encoder = self.decoder = None
