"""Detector-independent original-image coordinates. No OCR or model imports."""

from dataclasses import dataclass, field
from typing import Literal, Protocol
from PIL import Image

Orientation = Literal["vertical", "horizontal", "unknown"]


@dataclass(frozen=True)
class BoundingBox:
    left: int
    top: int
    right: int
    bottom: int

    @property
    def width(self) -> int:
        return self.right - self.left

    @property
    def height(self) -> int:
        return self.bottom - self.top

    def clipped(self, width: int, height: int, padding: int = 0) -> "BoundingBox":
        return BoundingBox(max(0, self.left - padding), max(0, self.top - padding),
                           min(width, self.right + padding), min(height, self.bottom + padding))

    def coordinates(self) -> tuple[int, int, int, int]:
        return self.left, self.top, self.right, self.bottom


@dataclass(frozen=True)
class TextRegion:
    id: int
    bbox: BoundingBox
    confidence: float | None = None
    orientation: Orientation = "unknown"
    polygon: tuple[tuple[float, float], ...] | None = None
    metadata: dict[str, object] = field(default_factory=dict)


class TextDetector(Protocol):
    def detect(self, image: Image.Image) -> list[TextRegion]: ...


class DetectionInitializationError(RuntimeError):
    pass


class DetectionError(RuntimeError):
    pass
