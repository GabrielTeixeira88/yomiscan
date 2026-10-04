"""Optional sentence NMT adapters. Direct Transformers loading; no pipelines."""

from collections.abc import Sequence
from dataclasses import dataclass
from time import perf_counter

from .base import Device, TranslationError, TranslationInitializationError, TranslationResult, select_device, validate_text


@dataclass(frozen=True)
class NMTModel:
    model: str
    revision: str
    license: str


NMT_MODELS = {
    "fugumt": NMTModel("staka/fugumt-ja-en", "f7ce11286e1fb7a8e1f1692ff3ab68c0f9c3aecb", "CC-BY-SA-4.0"),
    "nllb-600m": NMTModel("facebook/nllb-200-distilled-600M", "f8d333a098d19b4fd9a8b18f94170487ad3f821d", "CC-BY-NC-4.0"),
}


class NMTTranslationEngine:
    """One lazily loaded model/tokenizer pair; batch items are independent sentences."""

    def __init__(self, engine: str, *, device: Device = "auto", batch_size: int = 8,
                 local_files_only: bool = False, num_beams: int | None = None) -> None:
        if engine not in NMT_MODELS:
            raise ValueError(f"Unknown NMT engine: {engine}")
        if device not in ("auto", "cpu", "cuda") or batch_size < 1:
            raise ValueError("Use device auto/cpu/cuda and a positive batch_size")
        self.engine, self.spec = engine, NMT_MODELS[engine]
        # This pinned Fugu checkpoint repeats under beam search on the tested stack.
        # Greedy remains deterministic; retain an override for reproducible diagnostics.
        self.num_beams = (1 if engine == "fugumt" else 4) if num_beams is None else num_beams
        if self.num_beams < 1:
            raise ValueError("num_beams must be positive")
        self.requested_device, self.device = device, "unloaded"
        self.batch_size, self.local_files_only = batch_size, local_files_only
        self._model = self._tokenizer = self._torch = None
        self._target_id: int | None = None

    def load(self) -> None:
        if self._model is not None:
            return
        try:
            import torch
            from transformers import AutoModelForSeq2SeqLM, AutoTokenizer

            self.device = select_device(self.requested_device, cuda_available=torch.cuda.is_available())
            options = {"revision": self.spec.revision, "local_files_only": self.local_files_only}
            languages = {"src_lang": "jpn_Jpan", "tgt_lang": "eng_Latn"} if self.engine == "nllb-600m" else {}
            tokenizer = AutoTokenizer.from_pretrained(self.spec.model, **options, **languages)
            target_id = None
            if languages:
                target_id = tokenizer.convert_tokens_to_ids("eng_Latn")
                if target_id is None or target_id == tokenizer.unk_token_id:
                    raise ValueError("NLLB tokenizer is missing the eng_Latn target token")
                if tokenizer.src_lang != "jpn_Jpan":
                    raise ValueError("NLLB tokenizer did not retain jpn_Jpan as source language")
            # Use FP32 consistently with the baseline on CPU; Fugu's artifact is FP16.
            model = AutoModelForSeq2SeqLM.from_pretrained(self.spec.model, **options, dtype=torch.float32)
            model.to(self.device)
            model.eval()
            self._torch, self._tokenizer, self._model = torch, tokenizer, model
            self._target_id = target_id
        except TranslationInitializationError:
            raise
        except Exception as exc:
            # Third-party dependency/model boundary, retaining the original diagnostic.
            raise TranslationInitializationError(
                f"Could not load {self.spec.model} at {self.spec.revision}: {exc}. "
                "Run uv sync; prepare the selected model with scripts/prepare_translation_models.py. "
                "Offline use needs a complete Hugging Face cache; check memory and requested device."
            ) from exc

    def close(self) -> None:
        self._model = self._tokenizer = None
        self._target_id = None
        if self._torch is not None and self.device == "cuda":
            self._torch.cuda.empty_cache()
        self._torch = None

    def translate(self, text: str) -> TranslationResult:
        return self.translate_many([text])[0]

    def translate_many(self, texts: Sequence[str]) -> list[TranslationResult]:
        if isinstance(texts, str):
            raise TypeError("translate_many expects a sequence of strings, not one string")
        sources = list(texts)
        for text in sources:
            validate_text(text)
        if not sources:
            return []
        self.load()
        results = []
        for offset in range(0, len(sources), self.batch_size):
            results.extend(self._translate_batch(sources[offset:offset + self.batch_size]))
        return results

    def _translate_batch(self, sources: list[str]) -> list[TranslationResult]:
        start = perf_counter()
        try:
            inputs = self._tokenizer([" ".join(text.split()) for text in sources],
                                     return_tensors="pt", padding=True, truncation=False)
            # NLLB was trained on <=512-token inputs; do not silently truncate or
            # treat its positional embedding capacity as validated long-context support.
            limit = min(512, self._model.config.max_position_embeddings)
            if inputs["input_ids"].shape[1] > limit:
                raise ValueError(f"Input exceeds {limit} tokens; supply a shorter text region")
            inputs = inputs.to(self.device)
            language = {"forced_bos_token_id": self._target_id} if self._target_id is not None else {}
            with self._torch.inference_mode():
                generated = self._model.generate(**inputs, **language, num_beams=self.num_beams, do_sample=False,
                                                 max_new_tokens=511, max_length=None, forced_eos_token_id=None)
            if any(self._model.config.eos_token_id not in row[1:].tolist() for row in generated):
                raise RuntimeError("Output reached the generation limit without EOS")
            outputs = self._tokenizer.batch_decode(generated, skip_special_tokens=True)
            if len(outputs) != len(sources) or any(not text.strip() for text in outputs):
                raise RuntimeError("Model returned missing or empty translations")
            if self.device == "cuda":
                self._torch.cuda.synchronize()
        except Exception as exc:
            raise TranslationError(f"{self.spec.model} inference failed on {self.device}: {exc}. "
                                   "For memory errors, reduce batch_size or use CPU.") from exc
        elapsed = (perf_counter() - start) * 1000
        return [TranslationResult(source, output.strip(), self.engine, self.spec.model, elapsed,
                                  {"device": self.device, "revision": self.spec.revision, "license": self.spec.license,
                                   "timing_scope": "batch", "batch_size": len(sources), "num_beams": self.num_beams, "dtype": "float32",
                                   "source_language": "jpn_Jpan" if self.engine == "nllb-600m" else "ja",
                                   "target_language": "eng_Latn" if self.engine == "nllb-600m" else "en"})
                for source, output in zip(sources, outputs, strict=True)]
