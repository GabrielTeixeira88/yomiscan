"""Optional pinned OCR weights/preprocessing controls, using official Transformers APIs."""

from pathlib import Path
from time import perf_counter
from typing import Any
import numpy as np
from PIL import Image

from .base import OCRInitializationError, OCRRecognitionError, OCRResult
from .normalization import normalize_recognition
from ..vision_models import MODELS, model_directory, file_hash


class TransformersOCREngine:
    def __init__(self, *, variant: str = "ocr-2025", grayscale: bool = False,
                 decoding: str = "published", max_tokens: int = 128, device: str = "cpu",
                 model_dir: Path | None = None, model: Any = None, processor: Any = None, tokenizer: Any = None) -> None:
        if variant not in ("ocr-original", "ocr-2025") or decoding not in ("published", "greedy") or not 1 <= max_tokens <= 512:
            raise ValueError("Invalid OCR variant/decoding/token limit")
        if device not in ("cpu", "cuda", "auto"):
            raise ValueError("OCR device must be cpu, cuda or auto")
        self.variant, self.grayscale, self.decoding, self.max_tokens = variant, grayscale, decoding, max_tokens
        try:
            import torch
            self._torch = torch
            self.device = "cuda" if device != "cpu" and torch.cuda.is_available() else "cpu"
            if device == "cuda" and self.device != "cuda":
                raise ValueError("CUDA unavailable; use CPU")
            if model is None:
                from transformers import ViTImageProcessorPil, AutoTokenizer, VisionEncoderDecoderModel, GenerationMixin
                class GeneratingOCRModel(VisionEncoderDecoderModel, GenerationMixin):
                    pass
                folder = model_dir if model_dir is not None else model_directory(variant)
                for filename, expected in MODELS[variant].hashes.items():
                    if file_hash(folder / filename) != expected:
                        raise ValueError(f"OCR artifact hash mismatch: {filename}")
                processor = ViTImageProcessorPil.from_pretrained(folder, local_files_only=True)
                tokenizer = AutoTokenizer.from_pretrained(folder, tokenizer_type="bert-japanese", local_files_only=True)
                model = GeneratingOCRModel.from_pretrained(folder, local_files_only=True,
                            use_safetensors=variant != "ocr-original").to(self.device).eval()
            self.model, self.processor, self.tokenizer = model, processor, tokenizer
            if any(not isinstance(v, int) or v < 0 for v in (tokenizer.cls_token_id, tokenizer.sep_token_id, tokenizer.pad_token_id)):
                raise ValueError("OCR tokenizer must expose CLS, SEP and PAD IDs")
        except Exception as exc:
            raise OCRInitializationError(
                f"Cannot initialize {variant} OCR. Run scripts/setup_vision_models.py {variant}; "
                f"check the pinned local cache/device: {exc}"
            ) from exc

    def diagnostic_metadata(self) -> dict[str, object]:
        artifact = MODELS[self.variant]
        return {"engine": self.variant + "-torch", "model": artifact.repository, "revision": artifact.revision,
                "device": self.device, "preprocessing": "grayscale" if self.grayscale else "rgb",
                "decoding": self.decoding, "max_tokens": self.max_tokens if self.decoding == "greedy" else 299,
                "num_beams": 1 if self.decoding == "greedy" else self.model.generation_config.num_beams}

    def recognize(self, image: Image.Image) -> OCRResult:
        if not isinstance(image, Image.Image) or min(image.size) < 1:
            raise ValueError("OCR expects a nonempty Pillow image")
        start = perf_counter()
        try:
            pixels = self.processor(image.convert("L").convert("RGB") if self.grayscale else image.convert("RGB"),
                                    return_tensors="pt").pixel_values.to(self.device)
            options = {"decoder_start_token_id": self.tokenizer.cls_token_id, "eos_token_id": self.tokenizer.sep_token_id,
                       "pad_token_id": self.tokenizer.pad_token_id, "return_dict_in_generate": True, "use_cache": True}
            if self.decoding == "greedy":
                options.update(num_beams=1, do_sample=False, max_new_tokens=self.max_tokens, max_length=None,
                    no_repeat_ngram_size=0, length_penalty=1.0, early_stopping=False,
                    forced_eos_token_id=None, output_scores=True)
            else:
                options.update(max_length=300)
            with self._torch.inference_mode():
                output = self.model.generate(pixels, **options)
            tokens = output.sequences[0].tolist()[1:]
            if self.tokenizer.sep_token_id not in tokens:
                raise OCRRecognitionError("OCR decoder reached token_limit without SEP; no partial text accepted")
            count = tokens.index(self.tokenizer.sep_token_id) + 1
            tokens = tokens[:count]
            text = normalize_recognition(self.tokenizer.decode(tokens, skip_special_tokens=True))
            confidence = None
            if self.decoding == "greedy":
                probabilities = []
                for token, score in zip(tokens, output.scores[:count], strict=True):
                    logits = score[0].float().cpu().numpy().astype(np.float64)
                    probabilities.append(float(np.exp(logits[token] - logits.max()) / np.exp(logits - logits.max()).sum()))
                confidence = float(np.mean(probabilities))
        except OCRRecognitionError:
            raise
        except Exception as exc:
            raise OCRRecognitionError(f"{self.variant} OCR failed on {self.device}: {exc}") from exc
        metadata = {**self.diagnostic_metadata(), "confidence": confidence,
                    "confidence_method": "mean_token_probability_including_eos" if confidence is not None else None,
                    "recognition_status": "success" if text else "blank", "termination": "eos", "tokens": count,
                    "uncertainty": "uncalibrated" if confidence is not None else "confidence_unavailable"}
        return OCRResult(text, self.variant + "-torch", (perf_counter() - start) * 1000, metadata)

    def close(self) -> None:
        self.model = self.processor = self.tokenizer = None
