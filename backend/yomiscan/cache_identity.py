"""Effective cache identities, separate from redacted/declared diagnostic metadata.

Only known adapters or an explicit cache_identity() contract are reusable. Missing
local artifacts never trigger a download and never fall back to a model's name.
"""

from dataclasses import asdict
from functools import lru_cache
import hashlib
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Any

from .cache import digest


@lru_cache(maxsize=256)
def _hash(path: str, size: int, mtime: int, ctime: int) -> str:
    with Path(path).open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


def file_identity(path: Path) -> str:
    stat = path.stat()
    return _hash(str(path.resolve()), stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns)


def versions(*packages: str) -> dict[str, str]:
    result = {}
    for package in packages:
        try:
            result[package] = version(package)
        except PackageNotFoundError:
            result[package] = "absent"
    return result


def algorithm(*files: str) -> str:
    return digest({name: file_identity(Path(__file__).parent / name) for name in files})


def folder_identity(folder: Path) -> dict[str, str] | None:
    suffixes = {".json", ".bin", ".safetensors", ".onnx", ".txt", ".model", ".gguf", ".dic", ".spm", ".vocab"}
    files = sorted(p for p in folder.iterdir() if p.is_file() and (p.suffix in suffixes or p.name in ("dicrc", "mecabrc")))
    return {p.name: file_identity(p) for p in files} if files else None


def hf_identity(repository: str, revision: str | None, local: Path | None = None) -> dict[str, str] | None:
    if local is not None and local.is_dir():
        return folder_identity(local)
    if not revision:
        return None
    from huggingface_hub import try_to_load_from_cache
    config = try_to_load_from_cache(repository, "config.json", revision=revision)
    return folder_identity(Path(config).parent) if isinstance(config, str) else None


def loaded_hf_identity(model: Any, repository: str, revision: str | None) -> dict[str, str] | None:
    try:
        config = model.config
        location = Path(str(config._name_or_path))
        return hf_identity(repository, getattr(config, "_commit_hash", None) or revision, location)
    except (OSError, ValueError, TypeError, AttributeError):
        return None


def result_metadata(metadata: dict[str, object]) -> dict[str, object]:
    """Diagnostic fields only; no local GGUF/LoRA paths or arbitrary model metadata."""
    from .diagnostics import model_info
    result = model_info(metadata)
    for key in ("timing_scope", "cache_prompt", "recognition_status", "termination", "uncertainty", "confidence_method",
                "confidence", "tokens", "runtime", "prompt_version"):
        value = metadata.get(key)
        if value is None or isinstance(value, (bool, int, float)):
            result[key] = value
        elif isinstance(value, str) and len(value) <= 100 and all(c.isalnum() or c in "_- ." for c in value):
            result[key] = value
    return result


def component_identity(component: Any) -> object | None:
    explicit = getattr(type(component), "cache_identity", None)
    if callable(explicit):
        try:
            result = explicit(component)
            digest(result)  # The contract returns canonical JSON data, never live objects.
            return result
        except (ValueError, TypeError, OSError):
            return None
    if component is None:
        return {"engine": "none"}
    cls = type(component)
    name = cls.__module__ + "." + cls.__name__
    try:
        # Third-party adapters below are enumerated deliberately. An arbitrary
        # diagnostic_metadata() method is NOT an effective configuration contract.
        if name == "yomiscan.rendering.renderer.ConservativePageRenderer":
            from .rendering.inpainting import OpenCVInpaintingEngine
            from .rendering.typesetting import PillowTypesetter
            from .rendering.masks import UniformBackgroundMaskGenerator
            if (type(component.typesetter) is not PillowTypesetter or type(component.inpainter) is not OpenCVInpaintingEngine
                or type(component.masks) is not UniformBackgroundMaskGenerator):
                return None
            font = component.typesetter
            import PIL.ImageFont
            return {"font_sizes": [font.minimum_size, font.maximum_size, font.preferred_size, font.margin],
                    "bundled_font": file_identity(Path(PIL.ImageFont.__file__)),
                    "masks": asdict(component.masks.config), "inpaint": vars(component.inpainter).copy(),
                    "algorithm": algorithm(*("rendering/"+f+".py" for f in (
                        "renderer", "service", "masks", "inpainting", "typesetting", "layout_regions", "coverage", "artwork"))),
                    **versions("pillow", "opencv-python-headless", "numpy")}
        supported = {
            "yomiscan.detection.rtdetr.ComicTextDetector", "yomiscan.detection.onnx.ONNXComicTextDetector",
            "yomiscan.ocr.manga_ocr.MangaOCREngine", "yomiscan.ocr.transformers.TransformersOCREngine",
            "yomiscan.ocr.onnx.ONNXMangaOCREngine", "yomiscan.translation.marian.MarianTranslationEngine",
            "yomiscan.translation.nmt.NMTTranslationEngine", "yomiscan.translation.manga.MangaTranslationEngine",
        }
        if name not in supported:
            return None
        metadata = component.diagnostic_metadata() if hasattr(component, "diagnostic_metadata") else {"engine": "manga-ocr"}
        metadata = dict(metadata)
        artifacts = getattr(component, "_cache_artifacts", "unset")
        if artifacts == "unset":
            if name.endswith("MangaOCREngine") and ".manga_ocr." in name:
                model = component._model.model
                config = model.config
                location = Path(str(config._name_or_path))
                artifacts = hf_identity(str(config._name_or_path), getattr(config, "_commit_hash", None), location)
            elif name.endswith("MangaTranslationEngine"):
                runtime = component.runtime
                if runtime is None:
                    return None
                artifacts = {label: file_identity(path) for label, path in (
                    ("gguf", runtime.model), ("runtime", runtime.executable), ("lora", runtime.lora)) if path is not None}
                artifacts["runtime_libraries"] = digest({p.name: file_identity(p) for p in runtime.executable.parent.iterdir()
                    if p.is_file() and p.suffix.lower() in (".dll", ".so", ".dylib")})
            else:
                artifacts = hf_identity(str(metadata["model"]), metadata.get("revision"))
            component._cache_artifacts = artifacts
        if not artifacts:
            return None
        model = getattr(component, "_model", None) or getattr(component, "model", None)
        if name.endswith("MangaOCREngine") and ".manga_ocr." in name:
            model = component._model.model
        generation = getattr(model, "generation_config", None)
        processor = getattr(component, "_processor", None) or getattr(component, "processor", None)
        if name.endswith("MangaOCREngine") and ".manga_ocr." in name:
            metadata["device"] = str(model.device)
            metadata["preprocessing"] = "manga-ocr-grayscale-rgb-max-length-300"
            processor = component._model.processor
        if name.endswith("MangaTranslationEngine"):
            metadata.pop("device", None)
            metadata["requested_device"] = component.runtime.requested_device
            metadata["context_size"] = component.runtime.context_size
        if name.endswith("NMTTranslationEngine"):
            # Before and after lazy load describe the same requested configuration.
            metadata["device"] = component.requested_device
            # Pinned on-disk generation config is already included in artifacts.
            generation = None
        return {"class": name, "artifacts": artifacts, "settings": metadata,
                "generation": generation.to_dict() if generation is not None else None,
                "preprocessing": processor.to_dict() if processor is not None and hasattr(processor, "to_dict") else None,
                "implementation": file_identity(Path(__import__(cls.__module__, fromlist=[cls.__name__]).__file__)),
                "shared_algorithms": algorithm("ocr/normalization.py", "translation/base.py", "onnx_runtime.py"),
                **versions("transformers", "torch", "tokenizers", "manga-ocr", "onnxruntime", "pillow", "numpy")}
    except (OSError, ValueError, TypeError, AttributeError, KeyError):
        # Unknown/unavailable identity is an intentional cache miss, not permission
        # to download a model or to guess from its human-readable name.
        return None
