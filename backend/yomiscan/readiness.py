"""Read-only local artifact inspection. No weight loading, downloading or private paths."""

from dataclasses import asdict, dataclass
from importlib.metadata import version
from importlib.util import find_spec
import os
from pathlib import Path
import re

from .translation.marian import DEFAULT_MODEL, MODEL_REVISION, OPUS_EXPERIMENTS
from .translation.manga import HY_MODEL, HY_REVISION, Q25_MODEL, Q25_REVISION, VNTL_MODEL, VNTL_REVISION
from .translation.nmt import NMT_MODELS
from .vision_models import MODELS
from .detection.rtdetr import MODEL_ID as DETECTOR_MODEL, MODEL_REVISION as DETECTOR_REVISION


# (catalog id, kind, local-bundle component) of the default Torch-free engines.
ENGINE_DEFAULTS = (("detector-pinned", "detection", "detector-fp32"), ("ocr-pinned", "ocr", "ocr-int8"),
                   ("opus-pinned", "translation", "translation-opus-ja-en-fp32"))


def prepare_command(environment: dict[str, str] | None = None) -> str:
    """The command that downloads the default models: the packaged engine sets its own."""
    environment = dict(os.environ) if environment is None else environment
    return environment.get("YOMISCAN_PREPARE_COMMAND", "yomiscan-prepare-defaults")


class SetupUnavailable(RuntimeError):
    def __init__(self, code: str) -> None:
        super().__init__("Local setup is incomplete; inspect readiness and run the explicit preparation command")
        self.code = code


@dataclass(frozen=True)
class ModelDescriptor:
    id: str
    kind: str
    model: str
    revision: str
    license: str
    files: tuple[str, ...] = ()
    weight_files: tuple[str, ...] = ()
    experimental: bool = False
    targets: tuple[str, ...] = ()
    structured: bool = False
    glossary_hints: bool = False
    dependency: str | None = None
    approximate_download_bytes: int | None = None
    devices: tuple[str, ...] = ("cpu", "cuda")
    setup_command: str = ""
    engine_component: str | None = None


def model_catalog() -> tuple[ModelDescriptor, ...]:
    # Defaults first (Stage 5b): the Torch-free engines on the pinned local bundle.
    from .engine_models import default_host, load_bundle
    host, bundle = default_host(), load_bundle()
    catalog = [ModelDescriptor(identifier, kind, host["repository"] or "loopback", host["revision"] or bundle.name,
        bundle.components[component].license, tuple(f.path for f in bundle.components[component].files),
        dependency="onnxruntime", devices=("cpu",), targets=("en",) if kind == "translation" else (),
        approximate_download_bytes=bundle.components[component].size,
        setup_command=prepare_command()+" --component "+kind, engine_component=component)
        for identifier, kind, component in ENGINE_DEFAULTS]
    # PyTorch references (dependency group `reference`): parity checks and CUDA.
    catalog += [
        ModelDescriptor("ocr-current", "ocr", MODELS["ocr-original"].repository, MODELS["ocr-original"].revision, "Apache-2.0",
            MODELS["ocr-original"].files, dependency="manga_ocr", setup_command="yomiscan-prepare-vision ocr-original"),
        ModelDescriptor("detector-current", "detection", DETECTOR_MODEL, DETECTOR_REVISION, "Apache-2.0",
            ("config.json", "preprocessor_config.json"), ("model.safetensors",), dependency="transformers",
            approximate_download_bytes=172_000_000, setup_command="yomiscan-prepare-defaults --reference --component detection"),
        ModelDescriptor("current", "translation", DEFAULT_MODEL, MODEL_REVISION, "Apache-2.0",
            ("config.json", "source.spm", "target.spm", "vocab.json"), ("pytorch_model.bin", "model.safetensors"), targets=("en",),
            dependency="transformers", approximate_download_bytes=312_000_000,
            setup_command="yomiscan-prepare-defaults --reference --component translation"),
    ]
    for identifier, key in (("ocr-2025", "ocr-2025"), ("ocr-onnx", "ocr-onnx"), ("detector-onnx", "detector")):
        spec = MODELS[key]
        catalog.append(ModelDescriptor(identifier, "detection" if identifier.startswith("detector") else "ocr",
            spec.repository, spec.revision, spec.license, spec.files, experimental=True,
            dependency="onnxruntime" if "onnx" in identifier else "transformers",
            devices=("cpu",) if "onnx" in identifier else ("cpu", "cuda"), setup_command="yomiscan-prepare-vision "+key))
    for name, spec in NMT_MODELS.items():
        files = ("config.json", "tokenizer_config.json", "sentencepiece.bpe.model", "tokenizer.json") if name == "nllb-600m" else ("config.json", "source.spm", "target.spm", "vocab.json")
        catalog.append(ModelDescriptor(name, "translation", spec.model, spec.revision, spec.license, files,
            ("pytorch_model.bin", "model.safetensors"), experimental=True, dependency="transformers",
            targets=("en", "pt-BR", "es") if name == "nllb-600m" else ("en",),
            approximate_download_bytes=2_460_457_927 if name == "nllb-600m" else None,
            setup_command="yomiscan-prepare-translation --engine "+name))
    for target, spec in OPUS_EXPERIMENTS.items():
        name = "opus-ja-pt" if target == "pt-BR" else "opus-ja-es"
        catalog.append(ModelDescriptor(name, "translation", spec["model"], spec["revision"], "Apache-2.0",
            ("config.json", "source.spm", "target.spm", "vocab.json"), ("pytorch_model.bin",), experimental=True,
            dependency="transformers", targets=(target,), approximate_download_bytes=311_664_297 if target == "pt-BR" else 305_760_693,
            setup_command="yomiscan-prepare-translation --engine "+name))
    for name, model, revision, license in (("hy-mt2-manga", HY_MODEL, HY_REVISION, "Apache-2.0"),
        ("qwen25-manga", Q25_MODEL, Q25_REVISION, "Apache-2.0"), ("qwen35-vntl", VNTL_MODEL, VNTL_REVISION, "Apache-2.0 publisher claim; artifact unavailable")):
        command = ("No verified VNTL artifact available; retain current translator. See docs/translation-benchmark.md" if name == "qwen35-vntl" else
            "yomiscan-prepare-translation --engine "+name+(" --llama-source <official-b11380-checkout>" if name == "qwen25-manga" else ""))
        catalog.append(ModelDescriptor(name, "translation", model, revision, license, experimental=True,
            targets=("en",), structured=name != "qwen35-vntl", glossary_hints=True,
            dependency="llama.cpp", setup_command=command))
    return tuple(catalog)


def local_artifacts(spec: ModelDescriptor, environment: dict[str, str]) -> tuple[list[Path], bool]:
    """Return private paths internally; endpoints only receive counts/status."""
    if spec.engine_component is not None:
        from .engine_models import installed_files
        return installed_files(spec.engine_component, environment)
    if spec.dependency != "llama.cpp" and find_spec("huggingface_hub") is None:
        return [], False  # Hugging Face cache models need the `reference` dependency group
    if spec.dependency == "llama.cpp":
        key = {"hy-mt2-manga": "HY_MT2", "qwen25-manga": "QWEN25", "qwen35-vntl": "QWEN35"}[spec.id]
        raw = environment.get("YOMISCAN_"+key+"_GGUF", "")
        if not raw or not environment.get("YOMISCAN_LLAMA_SERVER"):
            return [], False
        model = Path(raw)
        paths = [model, Path(environment["YOMISCAN_LLAMA_SERVER"])]
        split = re.fullmatch(r"(.+)-[0-9]{5}-of-([0-9]{5})\.gguf", model.name)
        if split:
            count = int(split[2])
            if not 1 <= count <= 32:
                return [], False
            paths += [model.with_name(f"{split[1]}-{i:05d}-of-{count:05d}.gguf") for i in range(1, count+1)]
        if spec.id == "qwen25-manga":
            if not environment.get("YOMISCAN_QWEN25_LORA"):
                return paths, False
            paths.append(Path(environment["YOMISCAN_QWEN25_LORA"]))
        return paths, all(path.is_file() for path in paths)
    from huggingface_hub import try_to_load_from_cache
    paths = []
    complete = True
    for filename in spec.files:
        path = try_to_load_from_cache(spec.model, filename, revision=spec.revision)
        if isinstance(path, str) and Path(path).is_file():
            paths.append(Path(path))
        else:
            complete = False
    weights = [try_to_load_from_cache(spec.model, name, revision=spec.revision) for name in spec.weight_files]
    weights = [Path(path) for path in weights if isinstance(path, str) and Path(path).is_file()]
    paths.extend(weights)
    return paths, complete and (bool(weights) if spec.weight_files else True)


def selected_models(environment: dict[str, str]) -> dict[str, str]:
    ocr = environment.get("YOMISCAN_OCR", "pinned")
    detector = environment.get("YOMISCAN_DETECTOR", "pinned")
    return {"ocr": "ocr-current" if ocr in ("current", "original-rgb") else "ocr-2025" if ocr in ("2025", "2025-greedy") else
                "ocr-onnx" if ocr in ("2025-onnx", "2025-onnx-no-cache") else "ocr-pinned" if ocr == "pinned" else "invalid",
        "detection": "detector-current" if detector == "current" else "detector-onnx" if detector == "onnx-int8" else
                "detector-pinned" if detector == "pinned" else "invalid",
        "translation": environment.get("YOMISCAN_TRANSLATION_ENGINE", "opus-pinned")}


def storage_status(path: Path) -> str:
    candidate = path if path.is_dir() else path.parent
    while not candidate.exists() and candidate != candidate.parent:
        candidate = candidate.parent
    return "writable" if os.access(candidate, os.W_OK) else "unavailable"


def readiness_snapshot(*, initialization: str, busy: bool, failure_code: str | None = None,
                       loaded: dict[str, object] | None = None, environment: dict[str, str] | None = None) -> dict:
    environment = dict(os.environ) if environment is None else environment
    selected = selected_models(environment)
    requested_device = environment.get("YOMISCAN_DEVICE", "auto")
    catalog = {spec.id: spec for spec in model_catalog()}
    selected = {kind: identifier if identifier in catalog and catalog[identifier].kind == kind else "invalid"
                for kind, identifier in selected.items()}
    valid = requested_device in ("auto", "cpu", "cuda") and "invalid" not in selected.values()
    runtime = loaded or {}
    cache_state = runtime.get("processing_cache", {})
    models = []
    for spec in model_catalog():
        try:
            paths, installed = local_artifacts(spec, environment)
            available_bytes = sum(path.stat().st_size for path in set(paths))
        except (OSError, ValueError):
            installed, available_bytes = False, None
        dependency = (bool(environment.get("YOMISCAN_LLAMA_SERVER")) and Path(environment["YOMISCAN_LLAMA_SERVER"]).is_file()) if spec.dependency == "llama.cpp" else spec.dependency is None or find_spec(spec.dependency) is not None
        state = (loaded or {}).get(spec.kind, {}) if selected.get(spec.kind) == spec.id else {}
        models.append({**asdict(spec), "selected": selected.get(spec.kind) == spec.id, "installed": installed,
            "verification": "not_checked", "loaded": bool(state.get("loaded")) if isinstance(state, dict) else False,
            "dependency_available": dependency, "available_artifact_bytes": available_bytes,
            "compatible": (requested_device == "auto" or requested_device in spec.devices) and failure_code != "unsupported_device",
            "compatibility_basis": "runtime_rejection" if failure_code == "unsupported_device" else "catalog_support_only",
            "warnings": (["Noncommercial model license"] if spec.license == "CC-BY-NC-4.0" else [])+
                (["Brazilian Portuguese quality is unverified"] if "pt-BR" in spec.targets else [])+
                (["Valid structured output does not guarantee accurate meaning"] if spec.structured else [])})
    from .engine_models import default_dictionary
    dictionary = default_dictionary(environment)
    return {"schema": 1, "version": version("yomiscan"), "initialization": initialization, "busy": busy,
        "failure_code": failure_code, "configuration_valid": valid, "selected_device": requested_device if valid else "invalid",
        "selected": selected, "models": models,
        "dictionary": {"installed": dictionary.is_file(), "loaded": initialization == "ready",
            "setup_command": prepare_command(environment)+" --component dictionary"},
        "tokenizer": {"installed": find_spec("fugashi") is not None and find_spec("unidic_lite") is not None,
            "loaded": initialization == "ready", "setup_command": "uv sync --frozen"},
        "storage": {"processing_cache": {
            "disk_parent": storage_status(Path(environment.get("YOMISCAN_CACHE_DIRECTORY", ".cache/processing"))),
            "persistent_enabled": cache_state.get("persistent_enabled") if isinstance(cache_state, dict) else None},
            "glossary": {"disk_parent": storage_status(Path(environment.get("YOMISCAN_GLOSSARY_DATABASE", "data/glossaries.sqlite3"))),
                "accessibility": "open" if runtime.get("glossary_open") is True else
                    "not_open" if "glossary_open" in runtime else "unknown"}},
        "documentation": "https://github.com/GabrielTeixeira88/yomiscan/blob/main/docs/post-mvp-reader-experience-distribution.md"}


def require_local_models(environment: dict[str, str], *, kinds: tuple[str, ...] = ("ocr", "translation")) -> dict[str, Path]:
    selected = selected_models(environment)
    catalog = {spec.id: spec for spec in model_catalog()}
    result = {}
    if environment.get("YOMISCAN_DEVICE", "auto") not in ("auto", "cpu", "cuda"):
        raise SetupUnavailable("invalid_configuration")
    if any(identifier not in catalog or catalog[identifier].kind != kind for kind, identifier in selected.items()):
        raise SetupUnavailable("invalid_configuration")
    for kind in kinds:
        identifier = selected[kind]
        if identifier not in catalog:
            raise SetupUnavailable("invalid_configuration")
        spec = catalog[identifier]
        if spec.dependency not in (None, "llama.cpp") and find_spec(spec.dependency) is None:
            raise SetupUnavailable("optional_dependency_missing")
        if environment.get("YOMISCAN_DEVICE") == "cuda" and "cuda" not in spec.devices:
            raise SetupUnavailable("unsupported_device")
        paths, complete = local_artifacts(spec, environment)
        if not complete:
            raise SetupUnavailable(kind+"_artifacts_missing")
        result[kind] = paths[0].parent
    return result
