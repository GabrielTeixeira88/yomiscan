"""Small, engine-independent OCR contract."""

from dataclasses import dataclass, field
from typing import Protocol

from PIL import Image


@dataclass(frozen=True)
class OCRResult:
    text: str
    engine: str
    processing_time_ms: float
    metadata: dict[str, object] = field(default_factory=dict)


class OCREngine(Protocol):
    def recognize(self, image: Image.Image) -> OCRResult:
        """Recognize text in an already selected image region."""
        ...


class OCRInitializationError(RuntimeError):
    """The engine could not load its dependencies or model."""


class OCRRecognitionError(RuntimeError):
    """The engine could not recognize an image."""
