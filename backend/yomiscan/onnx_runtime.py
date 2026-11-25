"""ONNX Runtime boundary shared by the Torch-free engines; onnxruntime is imported only when a session is built."""

import os
from pathlib import Path
from typing import Any, Literal

OnnxDevice = Literal["cpu", "directml"]
PROVIDERS: dict[str, str] = {"cpu": "CPUExecutionProvider", "directml": "DmlExecutionProvider"}


def available_providers() -> list[str]:
    try:
        import onnxruntime as ort
    except ImportError:
        return []
    return list(ort.get_available_providers())


def onnx_device(device: str, environment: dict[str, str] | None = None,
                available: list[str] | None = None) -> OnnxDevice:
    """Map the backend's auto/cpu/cuda setting to an ONNX Runtime device.

    For auto, YOMISCAN_ONNX_DEVICE chooses: `auto` (default) uses DirectML when the installed
    runtime offers it (onnxruntime-directml on Windows) and the CPU otherwise; `cpu` and
    `directml` force one. An explicit cpu setting stays CPU. The Torch-free engines have no
    CUDA path: DirectML is their GPU path.
    """
    environment = dict(os.environ) if environment is None else environment
    if device == "cuda":
        raise ValueError("The Torch-free engines have no CUDA path; DirectML is their GPU path (YOMISCAN_ONNX_DEVICE)")
    if device == "cpu":
        return "cpu"
    choice = environment.get("YOMISCAN_ONNX_DEVICE", "auto")
    if choice == "auto":
        providers = available_providers() if available is None else available
        return "directml" if PROVIDERS["directml"] in providers else "cpu"
    if choice not in PROVIDERS:
        raise ValueError(f"YOMISCAN_ONNX_DEVICE must be auto or one of {tuple(PROVIDERS)}")
    return choice  # type: ignore[return-value]


def session(path: Path, *, threads: int = 4, device: OnnxDevice = "cpu") -> Any:
    if threads < 1:
        raise ValueError("ONNX threads must be positive")
    if device not in PROVIDERS:
        raise ValueError(f"ONNX device must be one of {tuple(PROVIDERS)}")
    if not path.is_file():
        raise FileNotFoundError(f"Missing ONNX artifact {path.name}; run the model setup command first")
    try:
        import onnxruntime as ort
    except ImportError as exc:
        raise RuntimeError("ONNX Runtime is missing; run uv sync (it is a core dependency)") from exc
    provider = PROVIDERS[device]
    if provider not in ort.get_available_providers():
        raise RuntimeError(f"ONNX Runtime {ort.__version__} has no {provider}; "
                           "DirectML needs the onnxruntime-directml package on Windows. Select device cpu.")
    ort.disable_telemetry_events()
    options = ort.SessionOptions()
    options.intra_op_num_threads = threads
    options.inter_op_num_threads = 1
    options.log_severity_level = 3  # errors only; fp16 exports log harmless constant-folding warnings
    options.execution_mode = ort.ExecutionMode.ORT_SEQUENTIAL
    options.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
    if device == "directml":
        # DirectML requires sequential execution without memory pattern optimization.
        options.enable_mem_pattern = False
    providers = [provider] if device == "cpu" else [provider, "CPUExecutionProvider"]
    try:
        return ort.InferenceSession(str(path), sess_options=options, providers=providers)
    except Exception as exc:
        raise RuntimeError(f"ONNX Runtime could not load {path.name} on {device}") from exc


def cpu_session(path: Path, *, threads: int = 4) -> Any:
    """CPU session for the existing experimental engines."""
    return session(path, threads=threads, device="cpu")
