"""Local OPUS-MT adapter. One tokenizer/model pair per engine instance."""

from collections.abc import Sequence
from time import perf_counter

from .base import (
    Device, TranslationError, TranslationInitializationError, TranslationResult,
    select_device, validate_text,
)

DEFAULT_MODEL = "Helsinki-NLP/opus-mt-ja-en"
MODEL_REVISION = "0770961a39ba6bd66305b149c3f4110bcafca2e6"


class MarianTranslationEngine:
    def __init__(self, *, device: Device = "auto", batch_size: int = 8) -> None:
        if batch_size < 1:
            raise ValueError("batch_size must be positive")
        if device not in ("auto", "cpu", "cuda"):
            raise ValueError("device must be auto, cpu, or cuda")
        self.batch_size = batch_size
        try:
            import torch
            from transformers import MarianMTModel, MarianTokenizer

            self._torch = torch
            self.device = select_device(device, cuda_available=torch.cuda.is_available())
            self._tokenizer = MarianTokenizer.from_pretrained(DEFAULT_MODEL, revision=MODEL_REVISION)
            self._model = MarianMTModel.from_pretrained(DEFAULT_MODEL, revision=MODEL_REVISION)
            self._model.to(self.device)
            self._model.eval()
        except TranslationInitializationError:
            raise
        except Exception as exc:
            # Third-party boundary: keep the original cause for diagnostics.
            raise TranslationInitializationError(
                f"Could not initialize {DEFAULT_MODEL}: {exc}. Run uv sync; check "
                "the Hugging Face download/cache, available memory, and requested device. "
                "First use requires internet; offline use requires a complete cache."
            ) from exc

    def translate(self, text: str) -> TranslationResult:
        return self.translate_many([text])[0]

    def translate_many(self, texts: Sequence[str]) -> list[TranslationResult]:
        if isinstance(texts, str):
            raise TypeError("translate_many expects a sequence of strings, not one string")
        sources = list(texts)
        for text in sources:
            validate_text(text)
        results = []
        for offset in range(0, len(sources), self.batch_size):
            chunk = sources[offset:offset + self.batch_size]
            results.extend(self._translate_batch(chunk))
        return results

    def _translate_batch(self, texts: list[str]) -> list[TranslationResult]:
        start = perf_counter()
        try:
            # Retain the original in results; normalize only visual whitespace here.
            inputs = self._tokenizer(
                [" ".join(text.split()) for text in texts],
                return_tensors="pt", padding=True, truncation=False,
            )
            limit = self._model.config.max_position_embeddings
            if inputs["input_ids"].shape[1] > limit:
                raise ValueError(
                    f"Input exceeds {limit} model tokens. Supply a shorter sentence/region; "
                    "translation never silently truncates the source."
                )
            inputs = inputs.to(self.device)
            with self._torch.inference_mode():
                generated = self._model.generate(
                    **inputs, num_beams=4, do_sample=False, max_new_tokens=limit - 1,
                    max_length=None, forced_eos_token_id=None,
                )
            # An unfinished generation is an error, not a plausible partial translation.
            eos = self._model.config.eos_token_id
            if any(eos not in row[1:].tolist() for row in generated):
                raise RuntimeError("Output reached the generation limit; use a shorter region.")
            outputs = self._tokenizer.batch_decode(generated, skip_special_tokens=True)
            if len(outputs) != len(texts) or any(not output.strip() for output in outputs):
                raise RuntimeError("Model returned missing or empty translations.")
            if self.device == "cuda":
                self._torch.cuda.synchronize()
        except Exception as exc:
            raise TranslationError(
                f"{DEFAULT_MODEL} translation failed on {self.device}: {exc}. "
                "For memory errors, reduce batch_size or use CPU."
            ) from exc
        elapsed = (perf_counter() - start) * 1000
        return [TranslationResult(
            source_text=source, translated_text=output.strip(), engine="marian-mt",
            model=DEFAULT_MODEL, processing_time_ms=elapsed,
            metadata={"device": self.device, "revision": MODEL_REVISION,
                      "batch_size": len(texts), "timing_scope": "batch"},
        ) for source, output in zip(texts, outputs, strict=True)]
