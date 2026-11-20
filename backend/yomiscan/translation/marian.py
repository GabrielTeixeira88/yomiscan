"""Local OPUS-MT adapter. One tokenizer/model pair per engine instance."""

from collections.abc import Sequence
from time import perf_counter
from .options import TargetLanguage, TranslationCapabilities

from .base import (
    Device, TranslationError, TranslationInitializationError, TranslationResult,
    select_device, validate_text,
)

DEFAULT_MODEL = "Helsinki-NLP/opus-mt-ja-en"
MODEL_REVISION = "0770961a39ba6bd66305b149c3f4110bcafca2e6"
OPUS_EXPERIMENTS = {
    "pt-BR": {"model": "Helsinki-NLP/opus-mt-ja-pt", "revision": "15f163ca52b8d17d729d3c76aa3d9eabc4213367",
              "weight_sha256": "e183e563daba1765d122bb750befd10970dd2d6d4a8a8b766bcc58b757e3ade6", "prefix": ">>por<< "},
    "es": {"model": "Helsinki-NLP/opus-mt-ja-es", "revision": "d1693e4d2bc285d02653ff6438fe21e2b3c6025e",
           "weight_sha256": "df2ef58064ec5bcb42bd35d6aa7ea1b19856d6f1a73b73e94d401cc12971f29f", "prefix": ""},
}


class MarianTranslationEngine:
    def __init__(self, *, device: Device = "auto", batch_size: int = 8,
                 target_language: TargetLanguage = "en") -> None:
        if batch_size < 1:
            raise ValueError("batch_size must be positive")
        if device not in ("auto", "cpu", "cuda"):
            raise ValueError("device must be auto, cpu, or cuda")
        self.batch_size = batch_size
        if target_language not in ("en", *OPUS_EXPERIMENTS):
            raise ValueError("Unsupported OPUS target")
        self.target_language = target_language
        spec = OPUS_EXPERIMENTS.get(target_language)
        self.model_id = spec["model"] if spec else DEFAULT_MODEL
        self.revision = spec["revision"] if spec else MODEL_REVISION
        self.prefix = spec["prefix"] if spec else ""
        self.num_beams = 6 if spec else 4
        try:
            import torch
            from transformers import MarianMTModel, MarianTokenizer

            self._torch = torch
            self.device = select_device(device, cuda_available=torch.cuda.is_available())
            options = {"revision": self.revision, **({"local_files_only": True} if spec else {})}
            self._tokenizer = MarianTokenizer.from_pretrained(self.model_id, **options)
            self._model = MarianMTModel.from_pretrained(self.model_id, **options)
            self._model.to(self.device)
            self._model.eval()
            from ..cache_identity import loaded_hf_identity
            self._cache_artifacts = loaded_hf_identity(self._model, self.model_id, self.revision)
            if spec and (not self._cache_artifacts or self._cache_artifacts.get("pytorch_model.bin") != spec["weight_sha256"]):
                raise ValueError("Experimental OPUS weight checksum differs from its pinned artifact")
            if self.prefix and self._tokenizer.convert_tokens_to_ids(">>por<<") == self._tokenizer.unk_token_id:
                raise ValueError("Pinned Portuguese tokenizer is missing its required >>por<< target tag")
        except TranslationInitializationError:
            raise
        except Exception as exc:
            # Third-party boundary: keep the original cause for diagnostics.
            raise TranslationInitializationError(
                f"Could not initialize {self.model_id}: {exc}. Run uv sync; check "
                "the Hugging Face download/cache, available memory, and requested device. "
                "First use requires internet; offline use requires a complete cache."
            ) from exc

    def diagnostic_metadata(self) -> dict[str, object]:
        return {"engine": "current" if self.target_language == "en" else "opus-ja-"+self.target_language,
                "model": self.model_id, "revision": self.revision, "device": self.device,
                "batch_size": self.batch_size, "num_beams": self.num_beams, "target_language": self.target_language,
                "regional_variant_verified": self.target_language != "pt-BR"}

    def capabilities(self) -> TranslationCapabilities:
        return TranslationCapabilities(targets=(self.target_language,),
            experimental_targets=(self.target_language,) if self.target_language != "en" else ())

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
                [self.prefix+" ".join(text.split()) for text in texts],
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
                    **inputs, num_beams=self.num_beams, do_sample=False, max_new_tokens=limit - 1,
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
                f"{self.model_id} translation failed on {self.device}: {exc}. "
                "For memory errors, reduce batch_size or use CPU."
            ) from exc
        elapsed = (perf_counter() - start) * 1000
        return [TranslationResult(
            source_text=source, translated_text=output.strip(), engine="marian-mt",
            model=self.model_id, processing_time_ms=elapsed,
            metadata={"device": self.device, "revision": self.revision,
                      "batch_size": len(texts), "timing_scope": "batch", "target_language": self.target_language,
                      "regional_variant_verified": self.target_language != "pt-BR"},
        ) for source, output in zip(texts, outputs, strict=True)]
