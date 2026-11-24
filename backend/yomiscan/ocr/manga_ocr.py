"""Adapter for manga-ocr; importing this module does not load the model.

Decoding defaults to greedy. manga-ocr's published generation config (4 beams,
no_repeat_ngram_size=3, length_penalty=2) forbids any repeated 3-token sequence, which
alters genuinely repeated text (doubled words, laughter). On the Stage 2 corpus, greedy
decoding halved normalized CER (3.19% -> 1.61%) and lowered the CPU median from
415 to 310 ms per block; see docs/decisions/stage-2-results.md. "published" keeps the library's own call for comparison.
"""

from time import perf_counter
from pathlib import Path
from typing import Any, Literal

from PIL import Image

from .base import OCRInitializationError, OCRRecognitionError, OCRResult

Decoding = Literal["greedy", "published"]
MAX_LENGTH = 300  # manga-ocr's own limit, including the start token


class MangaOCREngine:
    decoding: Decoding = "greedy"

    def __init__(self, *, force_cpu: bool = False, model_path: Path | None = None,
                 decoding: Decoding = "greedy") -> None:
        if decoding not in ("greedy", "published"):
            raise ValueError("OCR decoding must be greedy or published")
        self.decoding = decoding
        try:
            from manga_ocr import MangaOcr

            options = {"pretrained_model_name_or_path": str(model_path)} if model_path is not None else {}
            self._model = MangaOcr(force_cpu=force_cpu, **options)
            self._post_process: Any = None
            if decoding == "greedy":
                from manga_ocr.ocr import post_process
                self._post_process = post_process
            from ..cache_identity import loaded_hf_identity
            self._cache_artifacts = loaded_hf_identity(self._model.model, "kha-white/manga-ocr-base", None)
        except Exception as exc:
            # Translate third-party failures at the adapter boundary, preserving cause.
            raise OCRInitializationError(
                f"Could not initialize manga-ocr: {exc}. "
                "Run uv sync and check the model download/cache and available memory."
            ) from exc

    def diagnostic_metadata(self) -> dict[str, object]:
        return {"engine": "manga-ocr", "decoding": self.decoding,
                "num_beams": 1 if self.decoding == "greedy" else "published", "max_length": MAX_LENGTH}

    def _greedy(self, image: Image.Image) -> str:
        # Mirrors MangaOcr.__call__ (grayscale -> RGB, its processor, tokenizer decode,
        # post_process) with only the generation settings replaced.
        model = self._model.model
        pixels = self._model._preprocess(image.convert("L").convert("RGB"))
        tokens = model.generate(pixels[None].to(model.device), max_length=MAX_LENGTH, num_beams=1, do_sample=False,
                                no_repeat_ngram_size=0, length_penalty=1.0, early_stopping=False)[0].cpu()
        return self._post_process(self._model.tokenizer.decode(tokens, skip_special_tokens=True))

    def recognize(self, image: Image.Image) -> OCRResult:
        if not isinstance(image, Image.Image):
            raise TypeError("image must be a Pillow Image")
        start = perf_counter()
        try:
            text = self._greedy(image) if self.decoding == "greedy" else self._model(image)
        except Exception as exc:
            raise OCRRecognitionError(f"manga-ocr recognition failed: {exc}") from exc
        return OCRResult(
            text=text,
            engine="manga-ocr",
            processing_time_ms=(perf_counter() - start) * 1000,
        )

    def close(self) -> None:
        self._model = None
