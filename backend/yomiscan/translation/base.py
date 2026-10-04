"""Sentence translation contracts; no model imports or downloads."""

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Literal, Protocol

Device = Literal["auto", "cpu", "cuda"]


@dataclass(frozen=True)
class TranslationResult:
    source_text: str
    translated_text: str
    engine: str
    model: str
    processing_time_ms: float
    metadata: dict[str, object] = field(default_factory=dict)

    @property
    def device(self) -> str:
        """Compatible with existing result constructors and saved Phase 3 results."""
        return str(self.metadata.get("device", "unknown"))


class TranslationEngine(Protocol):
    def translate(self, text: str) -> TranslationResult: ...

    def translate_many(self, texts: Sequence[str]) -> list[TranslationResult]:
        """Translate independent regions in order; [] returns []; blank items fail."""
        ...


@dataclass(frozen=True)
class TranslationContext:
    previous: tuple[str, ...] = ()
    following: tuple[str, ...] = ()
    glossary: dict[str, str] = field(default_factory=dict)
    tone: str = ("Natural manga dialogue. Preserve exact meaning and speaker tone. "
                 "Output only the English translation, without notes or explanations. Do not invent missing information.")


class ContextualTranslationEngine(TranslationEngine, Protocol):
    """Optional capability; legacy engines/callers retain the original interface."""

    def translate(self, text: str, *, context: TranslationContext | None = None) -> TranslationResult: ...

    def translate_many(self, texts: Sequence[str], *, context: TranslationContext | None = None) -> list[TranslationResult]: ...


class TranslationInitializationError(RuntimeError):
    """Dependencies, device, or cached/downloaded model could not be initialized."""


class TranslationError(RuntimeError):
    """Translation inference failed."""


def select_device(requested: Device, *, cuda_available: bool) -> str:
    if requested not in ("auto", "cpu", "cuda"):
        raise ValueError("device must be auto, cpu, or cuda")
    if requested == "cuda" and not cuda_available:
        raise TranslationInitializationError(
            "CUDA was requested but is unavailable. Use --device cpu or install a "
            "PyTorch CUDA build compatible with your NVIDIA GPU and driver."
        )
    return "cuda" if requested != "cpu" and cuda_available else "cpu"


def validate_text(text: str) -> None:
    if not isinstance(text, str):
        raise TypeError("translation input must be a string")
    if not text.strip():
        raise ValueError("translation input must not be empty or whitespace-only")
