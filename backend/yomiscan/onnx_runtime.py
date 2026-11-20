"""Optional CPU runtime boundary shared by vision experiments, never startup imports."""

from pathlib import Path
from typing import Any


def cpu_session(path: Path, *, threads: int = 4) -> Any:
    if threads < 1:
        raise ValueError("ONNX threads must be positive")
    if not path.is_file():
        raise FileNotFoundError(f"Missing ONNX artifact {path.name}; run scripts/setup_vision_models.py")
    try:
        import onnxruntime as ort
    except ImportError as exc:
        raise RuntimeError("ONNX experiments require uv sync --extra vision; the default engine needs no ONNX runtime") from exc
    ort.disable_telemetry_events()
    options = ort.SessionOptions()
    options.intra_op_num_threads = threads
    options.inter_op_num_threads = 1
    options.execution_mode = ort.ExecutionMode.ORT_SEQUENTIAL
    options.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
    return ort.InferenceSession(str(path), sess_options=options, providers=["CPUExecutionProvider"])
