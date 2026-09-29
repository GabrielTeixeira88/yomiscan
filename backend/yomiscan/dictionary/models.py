from dataclasses import dataclass


@dataclass(frozen=True)
class DictionaryReading:
    text: str
    spellings: tuple[str, ...] = ()
    no_kanji: bool = False


@dataclass(frozen=True)
class DictionarySense:
    glosses: tuple[str, ...]
    parts_of_speech: tuple[str, ...]
    spellings: tuple[str, ...] = ()
    readings: tuple[str, ...] = ()
    notes: tuple[str, ...] = ()
    labels: tuple[str, ...] = ()


@dataclass(frozen=True)
class DictionaryEntry:
    entry_id: int
    spellings: tuple[str, ...]
    readings: tuple[DictionaryReading, ...]
    senses: tuple[DictionarySense, ...]


class DictionaryError(RuntimeError):
    """Local dictionary could not be opened, built, or queried."""
