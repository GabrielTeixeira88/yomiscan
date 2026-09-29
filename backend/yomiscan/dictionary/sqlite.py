"""Indexed exact-form lookups using one read-only connection per instance."""

import json
from pathlib import Path
import sqlite3
from typing import Self

from yomiscan.japanese import hiragana

from .models import DictionaryEntry, DictionaryError, DictionaryReading, DictionarySense

SCHEMA_VERSION = 1


def decode_entry(payload: str) -> DictionaryEntry:
    data = json.loads(payload)
    return DictionaryEntry(
        entry_id=data["entry_id"], spellings=tuple(data["spellings"]),
        readings=tuple(DictionaryReading(r["text"], tuple(r["spellings"]), r["no_kanji"])
                       for r in data["readings"]),
        senses=tuple(DictionarySense(**{key: tuple(value) for key, value in s.items()})
                     for s in data["senses"]),
    )


class SQLiteDictionary:
    def __init__(self, path: Path) -> None:
        self._connection: sqlite3.Connection | None = None
        try:
            self._connection = sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)
            version = self._connection.execute("PRAGMA user_version").fetchone()[0]
            if version != SCHEMA_VERSION:
                raise DictionaryError("Unsupported dictionary schema; reimport JMdict.")
            self._connection.execute("SELECT entry_id, payload FROM entries LIMIT 0")
            self._connection.execute("SELECT form, entry_id FROM forms LIMIT 0")
        except (sqlite3.Error, DictionaryError) as exc:
            self.close()
            raise DictionaryError(
                f"Cannot open dictionary '{path}': {exc}. "
                "Run scripts/import_jmdict.py first (see README)."
            ) from exc

    def lookup(self, text: str) -> tuple[DictionaryEntry, ...]:
        if self._connection is None:
            raise DictionaryError("Dictionary is closed.")
        if not text:
            return ()
        try:
            rows = self._connection.execute(
                "SELECT e.payload FROM forms f JOIN entries e USING (entry_id) "
                "WHERE f.form = ? ORDER BY e.entry_id", (hiragana(text),),
            )
            return tuple(decode_entry(row[0]) for row in rows)
        except (sqlite3.Error, ValueError, KeyError, TypeError) as exc:
            raise DictionaryError(f"Dictionary lookup failed; reimport JMdict: {exc}") from exc

    def close(self) -> None:
        if self._connection is not None:
            self._connection.close()
            self._connection = None

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *args: object) -> None:
        self.close()
