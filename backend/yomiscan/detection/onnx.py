"""Optional, independently implemented reader for the pinned v4-s INT8 export.

The export is not proven weight-equivalent to our Transformers checkpoint.
Its orig_target_sizes contract is width/height, unlike Transformers postprocessing.
"""

import math
from pathlib import Path
from typing import Any
import numpy as np
from PIL import Image

from .base import DetectionError, DetectionInitializationError, TextRegion
from .rtdetr import MODEL_ID, MODEL_REVISION, decode_regions
from ..onnx_runtime import cpu_session


class ONNXComicTextDetector:
    def __init__(self, *, model_path: Path | None = None, threshold: float = .5,
                 bubble_threshold: float | None = None, free_threshold: float | None = None,
                 threads: int = 4, session: Any = None) -> None:
        self.bubble_threshold = threshold if bubble_threshold is None else bubble_threshold
        self.free_threshold = threshold if free_threshold is None else free_threshold
        if any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) or not 0 < v <= 1
               for v in (threshold, self.bubble_threshold, self.free_threshold)):
            raise ValueError("Detection thresholds must be in (0, 1]")
        self.threshold, self.device, self.threads = threshold, "cpu", threads
        self._cache_artifacts = None
        try:
            if session is None:
                from ..vision_models import MODELS, model_directory, file_hash
                if model_path is None:
                    model_path = model_directory("detector") / "detector-v4-s_int8.onnx"
                if file_hash(model_path) != MODELS["detector"].hashes["detector-v4-s_int8.onnx"]:
                    raise ValueError("Detector artifact differs from the supported pinned v4-s export")
                session = cpu_session(model_path, threads=threads)
                self._cache_artifacts = dict(MODELS["detector"].hashes)
            inputs = {i.name: i for i in session.get_inputs()}
            if (set(inputs) != {"images", "orig_target_sizes"} or inputs["images"].type != "tensor(float)"
                or inputs["orig_target_sizes"].type != "tensor(int64)"
                or len(inputs["images"].shape) != 4 or inputs["images"].shape[1:] != [3, 640, 640]
                or isinstance(inputs["images"].shape[0], int) and inputs["images"].shape[0] != 1):
                raise ValueError("Unsupported detector input contract; use the pinned v4-s export")
            if not {"labels", "boxes", "scores"} <= {o.name for o in session.get_outputs()}:
                raise ValueError("Detector must expose labels, boxes and scores")
            self._session = session
        except Exception as exc:
            raise DetectionInitializationError(
                "Cannot initialize optional ONNX detector. Run uv sync --extra vision and "
                f"uv run --extra vision python scripts/setup_vision_models.py detector: {exc}"
            ) from exc

    def diagnostic_metadata(self) -> dict[str, object]:
        return {"engine": "onnx-int8", "model": MODEL_ID, "revision": MODEL_REVISION,
                "artifact": "detector-v4-s_int8.onnx", "device": self.device, "threads": self.threads,
                "bubble_threshold": self.bubble_threshold, "free_threshold": self.free_threshold}

    def detect(self, image: Image.Image) -> list[TextRegion]:
        if not isinstance(image, Image.Image) or min(image.size) < 1:
            raise ValueError("Detector expects a nonempty Pillow image")
        try:
            rgb = image.convert("RGB").resize((640, 640), Image.Resampling.BILINEAR)
            pixels = np.asarray(rgb, dtype=np.float32).transpose(2, 0, 1)[None] / np.float32(255)
            labels, boxes, scores = self._session.run(["labels", "boxes", "scores"], {
                "images": np.ascontiguousarray(pixels),
                "orig_target_sizes": np.array([[image.width, image.height]], dtype=np.int64)})
            return decode_regions(np.asarray(boxes).reshape(-1, 4).tolist(), np.asarray(scores).reshape(-1).tolist(),
                np.asarray(labels).reshape(-1).tolist(), image.size,
                bubble_threshold=self.bubble_threshold, free_threshold=self.free_threshold)
        except Exception as exc:
            raise DetectionError(f"ONNX comic detection failed on CPU: {exc}") from exc

    def close(self) -> None:
        self._session = None
