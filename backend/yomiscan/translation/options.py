"""Request-scoped translation choices; independent of browser identity and model state."""

from dataclasses import dataclass
from typing import Literal

TargetLanguage = Literal["en", "pt-BR", "es"]
TranslationMode = Literal["sentences", "structured-line", "structured-page", "structured-panel"]
ContextMode = Literal["none", "neighbor", "panel", "page"]
OrderStrategy = Literal["bands", "panels"]
TARGET_NAMES = {"en": "English", "pt-BR": "Brazilian Portuguese (experimental)", "es": "Spanish (experimental)"}


@dataclass(frozen=True)
class TranslationOptions:
    target_language: TargetLanguage = "en"
    series_id: str | None = None
    glossary_enabled: bool = False
    glossary_version: str | None = None
    mode: TranslationMode = "sentences"
    ordering: OrderStrategy = "bands"
    context: ContextMode = "none"

    def __post_init__(self) -> None:
        if self.target_language not in TARGET_NAMES or self.mode not in (
            "sentences", "structured-line", "structured-page", "structured-panel"):
            raise ValueError("Unsupported translation target or mode")
        if self.ordering not in ("bands", "panels") or self.context not in ("none", "neighbor", "panel", "page"):
            raise ValueError("Unsupported ordering or context")
        if self.context != "none" and self.mode == "sentences":
            raise ValueError("Bounded dialogue context requires an explicit structured experiment")


@dataclass(frozen=True)
class TranslationCapabilities:
    targets: tuple[TargetLanguage, ...] = ("en",)
    glossary_hints: bool = False
    structured: bool = False
    bounded_context: bool = False
    experimental_targets: tuple[TargetLanguage, ...] = ()


def capabilities(engine: object) -> TranslationCapabilities:
    describe = getattr(type(engine), "capabilities", None)
    result = describe(engine) if callable(describe) else TranslationCapabilities()
    if not isinstance(result, TranslationCapabilities):
        raise TypeError("Engine capabilities must be a TranslationCapabilities value")
    return result


def validate_options(engine: object, options: TranslationOptions) -> TranslationCapabilities:
    support = capabilities(engine)
    if options.target_language not in support.targets:
        raise ValueError("The selected translation engine does not support this target language")
    if options.mode != "sentences" and not support.structured:
        raise ValueError("The selected engine does not support structured page translation")
    if options.context != "none" and not support.bounded_context:
        raise ValueError("The selected engine does not support bounded dialogue context")
    return support
