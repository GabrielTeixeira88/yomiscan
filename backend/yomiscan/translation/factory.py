"""Explicit developer selection. Optional engines never affect baseline startup."""

import os
from pathlib import Path

from .base import Device, TranslationEngine, TranslationInitializationError

ENGINE_NAMES = ("current", "hy-mt2-manga", "qwen35-vntl", "qwen25-manga", "fugumt", "nllb-600m", "opus-ja-pt", "opus-ja-es", "opus-pinned")


def create_translation_engine(name: str | None = None, *, device: Device = "auto") -> TranslationEngine:
    name = name or os.environ.get("YOMISCAN_TRANSLATION_ENGINE", "current")
    if name == "current":
        from .marian import MarianTranslationEngine
        return MarianTranslationEngine(device=device)
    if name not in ENGINE_NAMES:
        raise ValueError(f"Unknown translation engine {name!r}; choose one of {', '.join(ENGINE_NAMES)}")
    if name == "opus-pinned":
        if device == "cuda":
            raise TranslationInitializationError("The Torch-free OPUS-MT translator has no CUDA path; it runs on the CPU")
        from .opus_onnx import PinnedOpusTranslationEngine
        return PinnedOpusTranslationEngine()
    if name in ("opus-ja-pt", "opus-ja-es"):
        from .marian import MarianTranslationEngine
        return MarianTranslationEngine(device=device, target_language="pt-BR" if name == "opus-ja-pt" else "es")
    if name in ("fugumt", "nllb-600m"):
        from .nmt import NMTTranslationEngine
        return NMTTranslationEngine(name, device=device, local_files_only=True)
    from .manga import LlamaServer, MangaTranslationEngine
    key = {"hy-mt2-manga": "HY_MT2", "qwen35-vntl": "QWEN35", "qwen25-manga": "QWEN25"}[name]
    model = os.environ.get(f"YOMISCAN_{key}_GGUF")
    executable = os.environ.get("YOMISCAN_LLAMA_SERVER")
    if name == "qwen35-vntl" and not model:
        return MangaTranslationEngine(name, None)
    if not model or not executable:
        raise TranslationInitializationError(
            f"{name} requires YOMISCAN_LLAMA_SERVER and YOMISCAN_{key}_GGUF. "
            "No optional weights are downloaded automatically; see docs/translation-benchmark.md. "
            "Use YOMISCAN_TRANSLATION_ENGINE=current for the existing translator."
        )
    lora = None
    if name == "qwen25-manga":
        adapter = os.environ.get("YOMISCAN_QWEN25_LORA")
        if not adapter:
            raise TranslationInitializationError("Qwen2.5 manga requires YOMISCAN_QWEN25_LORA: the converted LoRA adapter. Refusing to label the unadapted base as the manga fine-tune.")
        lora = Path(adapter)
    return MangaTranslationEngine(name, LlamaServer(Path(model), executable=Path(executable), device=device, lora=lora))
