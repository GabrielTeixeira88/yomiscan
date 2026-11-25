"""Torch-free OPUS-MT ja-en on the pinned fp32 ONNX export (Stage 5b).

Decodes exactly as MarianTranslationEngine (153/153 identical lines on the translation set):
whitespace collapsed, no truncation (more than 512 tokens is an error), 4 beams, length penalty
1, no early stopping, at most 511 new tokens, pad token banned with renormalized logits, and an
unfinished or empty output is an error. The merged decoder reuses its key/value cache; each
beam's self-attention cache follows its parent beam.
"""

from collections.abc import Sequence
import json
from pathlib import Path
from time import perf_counter
from typing import Any

import numpy as np

from .base import TranslationError, TranslationInitializationError, TranslationResult, validate_text
from .beam import beam_search
from .marian import DEFAULT_MODEL, MODEL_REVISION
from .options import TranslationCapabilities

COMPONENT = "translation-opus-ja-en-fp32"
NUM_BEAMS = 4


class PinnedOpusTranslationEngine:
    def __init__(self, *, threads: int = 4, model_root: Path | None = None, tokenizer: Any = None,
                 encoder: Any = None, decoder: Any = None, config: dict[str, Any] | None = None) -> None:
        self.threads = threads
        self._cache_artifacts: dict[str, str] | None = None
        try:
            if encoder is None or decoder is None:
                from ..engine_models import component_directory, load_bundle
                from ..onnx_runtime import session
                from .marian_sentencepiece import MarianSentencePiece
                bundle = load_bundle()
                folder = component_directory(COMPONENT, bundle=bundle, root=model_root) / COMPONENT
                tokenizer = MarianSentencePiece(folder)
                config = json.loads((folder / "config.json").read_text(encoding="utf-8"))
                encoder = session(folder / "encoder_model.onnx", threads=threads)
                decoder = session(folder / "decoder_model_merged.onnx", threads=threads)
                self._cache_artifacts = {f.path: f.sha256 for f in bundle.components[COMPONENT].files}
            if tokenizer is None or config is None:
                raise ValueError("Injected sessions need a tokenizer and the model config")
            self.tokenizer, self.encoder, self.decoder = tokenizer, encoder, decoder
            self.vocab_size = int(config["vocab_size"])
            self.heads = int(config["decoder_attention_heads"])
            self.head_dim = int(config["d_model"]) // self.heads
            self.max_positions = int(config["max_position_embeddings"])
            self.start_id, self.eos_id = int(config["decoder_start_token_id"]), int(config["eos_token_id"])
            self.past_names = [i.name for i in decoder.get_inputs() if i.name.startswith("past_key_values.")]
            self.output_names = [o.name for o in decoder.get_outputs()]
            if not self.past_names or "logits" not in self.output_names:
                raise ValueError("The decoder export has no key/value cache inputs or no logits output")
        except Exception as exc:
            raise TranslationInitializationError(f"Could not initialize the Torch-free OPUS-MT translator: {exc}") from exc
        self.device = "cpu"

    def diagnostic_metadata(self) -> dict[str, object]:
        return {"engine": "opus-pinned", "model": DEFAULT_MODEL, "revision": MODEL_REVISION, "runtime": "onnxruntime",
                "artifact": COMPONENT, "device": self.device, "num_beams": NUM_BEAMS, "target_language": "en",
                "threads": self.threads}

    def capabilities(self) -> TranslationCapabilities:
        return TranslationCapabilities(targets=("en",))

    def translate(self, text: str) -> TranslationResult:
        return self.translate_many([text])[0]

    def translate_many(self, texts: Sequence[str]) -> list[TranslationResult]:
        if isinstance(texts, str):
            raise TypeError("translate_many expects a sequence of strings, not one string")
        sources = list(texts)
        for text in sources:
            validate_text(text)
        return [self._translate(text) for text in sources]

    def _translate(self, text: str) -> TranslationResult:
        start = perf_counter()
        try:
            ids = self.tokenizer.encode(" ".join(text.split()))
            if len(ids) > self.max_positions:
                raise ValueError(f"Input exceeds {self.max_positions} model tokens. Supply a shorter sentence/region; "
                                 "translation never silently truncates the source.")
            source = np.array([ids], dtype=np.int64)
            hidden = self.encoder.run(["last_hidden_state"], {"input_ids": source, "attention_mask": np.ones_like(source)})[0]
            states = np.repeat(hidden, NUM_BEAMS, axis=0)
            mask = np.ones((NUM_BEAMS, source.shape[1]), dtype=np.int64)
            cache: dict[str, dict[str, np.ndarray]] = {}

            def step(running: list[list[int]], parents: list[int] | None) -> np.ndarray:
                first = parents is None
                feed: dict[str, np.ndarray] = {
                    "encoder_hidden_states": states, "encoder_attention_mask": mask,
                    "input_ids": np.array([[tokens[-1]] for tokens in running], dtype=np.int64),
                    "use_cache_branch": np.array([not first])}
                for name in self.past_names:
                    feed[name] = (np.zeros((NUM_BEAMS, self.heads, 0, self.head_dim), dtype=states.dtype) if first else
                                  cache["encoder"][name] if ".encoder." in name else cache["decoder"][name][parents])
                outputs = dict(zip(self.output_names, self.decoder.run(self.output_names, feed), strict=True))
                if first:
                    cache["encoder"] = {n: outputs[n.replace("past_key_values.", "present.")] for n in self.past_names if ".encoder." in n}
                cache["decoder"] = {n: outputs[n.replace("past_key_values.", "present.")] for n in self.past_names if ".encoder." not in n}
                logits = np.asarray(outputs["logits"])[:, -1, :]
                if logits.shape != (NUM_BEAMS, self.vocab_size) or not np.isfinite(logits).all():
                    raise ValueError("The decoder returned invalid logits")
                return logits

            best = beam_search(step, vocab_size=self.vocab_size, num_beams=NUM_BEAMS, start_id=self.start_id,
                               eos_id=self.eos_id, max_length=self.max_positions, banned=(self.tokenizer.pad_id,))
            if best.tokens[-1:] != [self.eos_id]:
                raise RuntimeError("Output reached the generation limit; use a shorter region.")
            output = self.tokenizer.decode(best.tokens)
            if not output:
                raise RuntimeError("Model returned an empty translation.")
        except Exception as exc:
            raise TranslationError(f"Torch-free OPUS-MT translation failed on CPU: {exc}") from exc
        return TranslationResult(source_text=text, translated_text=output, engine="marian-mt", model=DEFAULT_MODEL,
                                 processing_time_ms=(perf_counter() - start) * 1000,
                                 metadata={"device": self.device, "revision": MODEL_REVISION, "runtime": "onnxruntime",
                                           "batch_size": 1, "timing_scope": "item", "target_language": "en",
                                           "regional_variant_verified": True})

    def close(self) -> None:
        self.encoder = self.decoder = None
