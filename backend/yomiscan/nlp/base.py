from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class JapaneseToken:
    surface: str
    lemma: str | None = None
    reading: str | None = None
    part_of_speech: str | None = None
    conjugation_type: str | None = None
    conjugation_form: str | None = None
    orthographic_base: str | None = None
    lemma_reading: str | None = None


class JapaneseTokenizer(Protocol):
    def tokenize(self, text: str) -> list[JapaneseToken]: ...


class TokenizerError(RuntimeError):
    """Tokenizer initialization or analysis failed."""
