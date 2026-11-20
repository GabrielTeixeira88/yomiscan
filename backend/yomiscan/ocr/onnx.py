"""Pinned 2025 OCR, greedy ONNX decoding with optional KV reuse; confidence is diagnostic."""

from pathlib import Path
import json
from time import perf_counter
from typing import Any
import numpy as np
from PIL import Image

from .base import OCRInitializationError, OCRRecognitionError, OCRResult
from .normalization import normalize_recognition
from ..onnx_runtime import cpu_session
from ..vision_models import MODELS, model_directory, file_hash


class ONNXMangaOCREngine:
    def __init__(self, *, model_dir: Path | None = None, max_tokens: int = 128,
                 grayscale: bool = False, use_kv_cache: bool = True, threads: int = 4,
                 encoder: Any = None, decoder: Any = None) -> None:
        if not 1 <= max_tokens <= 512:
            raise ValueError("OCR token limit must be between 1 and 512")
        self.max_tokens, self.grayscale, self.use_kv_cache, self.threads = max_tokens, grayscale, use_kv_cache, threads
        self._cache_artifacts = None
        try:
            folder = model_dir if model_dir is not None else model_directory("ocr-onnx")
            self.vocabulary = (folder / "vocab.txt").read_text(encoding="utf-8").splitlines()
            self.start_id, self.end_id = self.vocabulary.index("[CLS]"), self.vocabulary.index("[SEP]")
            self.special_ids = {i for i, token in enumerate(self.vocabulary) if token in {"[PAD]", "[UNK]", "[CLS]", "[SEP]", "[MASK]"}}
            if encoder is None or decoder is None:
                for filename, expected in MODELS["ocr-onnx"].hashes.items():
                    if file_hash(folder / filename) != expected:
                        raise ValueError(f"OCR artifact hash mismatch: {filename}")
                config = json.loads((folder / "config.json").read_text(encoding="utf-8"))
                self._cache_artifacts = dict(MODELS["ocr-onnx"].hashes)
                generation = json.loads((folder / "generation_config.json").read_text(encoding="utf-8"))
                preprocessing = json.loads((folder / "preprocessor_config.json").read_text(encoding="utf-8"))
                if (config["decoder_start_token_id"] != self.start_id or generation["eos_token_id"] != self.end_id
                    or config["decoder"]["vocab_size"] != len(self.vocabulary)
                    or preprocessing["size"] != {"height": 224, "width": 224}
                    or preprocessing["resample"] != 2
                    or preprocessing["image_mean"] != [.5, .5, .5] or preprocessing["image_std"] != [.5, .5, .5]):
                    raise ValueError("OCR tokenizer/config/preprocessing differs from the supported pinned export")
            self.encoder = encoder if encoder is not None else cpu_session(folder / "encoder_model.onnx", threads=threads)
            self.decoder = decoder if decoder is not None else cpu_session(folder / "decoder_model_merged.onnx", threads=threads)
            self.cache_shapes = {}
            for spec in self.decoder.get_inputs():
                if not spec.name.startswith("past_key_values."):
                    continue
                if (spec.type != "tensor(float)" or len(spec.shape) != 4 or
                    not isinstance(spec.shape[1], int) or not isinstance(spec.shape[3], int)):
                    raise ValueError("Unsupported OCR cache tensor layout")
                self.cache_shapes[spec.name] = (1, spec.shape[1], 0, spec.shape[3])
            self.outputs = [output.name for output in self.decoder.get_outputs()]
            if not self.cache_shapes or "logits" not in self.outputs or any(
                name.replace("past_key_values.", "present.") not in self.outputs for name in self.cache_shapes
            ):
                raise ValueError("OCR merged decoder is missing cache inputs/outputs")
        except Exception as exc:
            raise OCRInitializationError(
                "Cannot initialize optional 2025 ONNX OCR. Run uv sync --extra vision and "
                f"uv run --extra vision python scripts/setup_vision_models.py ocr-onnx: {exc}"
            ) from exc

    def diagnostic_metadata(self) -> dict[str, object]:
        artifact = MODELS["ocr-onnx"]
        return {"engine": "manga-ocr-2025-onnx", "model": artifact.repository, "revision": artifact.revision,
                "source_revision": MODELS["ocr-2025"].revision, "device": "cpu", "max_tokens": self.max_tokens,
                "preprocessing": "grayscale" if self.grayscale else "rgb", "decoding": "greedy",
                "kv_cache": self.use_kv_cache, "threads": self.threads}

    def recognize(self, image: Image.Image) -> OCRResult:
        if not isinstance(image, Image.Image) or min(image.size) < 1:
            raise ValueError("OCR expects a nonempty Pillow image")
        start = perf_counter()
        try:
            rgb = image.convert("L").convert("RGB") if self.grayscale else image.convert("RGB")
            pixels = np.asarray(rgb.resize((224, 224), Image.Resampling.BILINEAR), dtype=np.float32)
            pixels = np.ascontiguousarray(((pixels / np.float32(255) - np.float32(.5)) / np.float32(.5)).transpose(2, 0, 1)[None])
            hidden = self.encoder.run(["last_hidden_state"], {"pixel_values": pixels})[0]
            # All state belongs to this one crop; never carry another bubble's KV tensors.
            cache = {name: np.empty(shape, dtype=np.float32) for name, shape in self.cache_shapes.items()}
            tokens, probabilities = [self.start_id], []
            terminated = False
            for step in range(self.max_tokens):
                cached = self.use_kv_cache and step > 0
                feed = {"input_ids": np.array([[tokens[-1]]] if cached else [tokens], dtype=np.int64),
                        "encoder_hidden_states": hidden, "use_cache_branch": np.array([cached], dtype=np.bool_), **cache}
                outputs = dict(zip(self.outputs, self.decoder.run(self.outputs, feed), strict=True))
                logits = np.asarray(outputs["logits"])[0, -1].astype(np.float64)
                if logits.shape != (len(self.vocabulary),) or not np.isfinite(logits).all():
                    raise ValueError("OCR decoder returned invalid vocabulary/logits")
                chosen = int(np.argmax(logits))
                probabilities.append(float(1 / np.exp(logits - logits[chosen]).sum()))
                tokens.append(chosen)
                if chosen == self.end_id:
                    terminated = True
                    break
                if self.use_kv_cache:
                    for name in cache:
                        # Cached-branch cross-attention presents may be empty: retain step one's tensors.
                        if ".decoder." in name or not cached:
                            cache[name] = outputs[name.replace("past_key_values.", "present.")]
            if not terminated:
                raise OCRRecognitionError(f"OCR decoder reached token_limit ({self.max_tokens}) without SEP; no partial text accepted")
            text = normalize_recognition("".join(self.vocabulary[token].removeprefix("##")
                                                for token in tokens[1:] if token not in self.special_ids))
        except OCRRecognitionError:
            raise
        except Exception as exc:
            raise OCRRecognitionError(f"2025 ONNX OCR failed on CPU: {exc}") from exc
        metadata = {**self.diagnostic_metadata(), "confidence": float(np.mean(probabilities)),
                    "confidence_method": "mean_token_probability_including_eos", "recognition_status": "success" if text else "blank",
                    "termination": "eos", "tokens": len(probabilities), "uncertainty": "uncalibrated"}
        return OCRResult(text, "manga-ocr-2025-onnx", (perf_counter() - start) * 1000, metadata)

    def close(self) -> None:
        self.encoder = self.decoder = None
