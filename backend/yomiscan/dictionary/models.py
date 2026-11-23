from dataclasses import dataclass, field


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
    # JMdict ke_pri/re_pri tags per exact spelling or reading (schema 2+; empty for schema 1).
    form_priority: dict[str, tuple[str, ...]] = field(default_factory=dict)


class DictionaryError(RuntimeError):
    """Local dictionary could not be opened, built, or queried."""
