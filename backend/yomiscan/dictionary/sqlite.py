"""Indexed exact-form lookups using one read-only connection per instance."""

import json
import logging
from pathlib import Path
import sqlite3
from typing import Self

from yomiscan.japanese import hiragana

from .models import DictionaryEntry, DictionaryError, DictionaryReading, DictionarySense

SCHEMA_VERSION = 2
# Schema 1 lacks JMdict priority tags; it stays readable, with frequency ranking disabled.
SUPPORTED_SCHEMA_VERSIONS = (1, 2)


def decode_entry(payload: str) -> DictionaryEntry:
    data = json.loads(payload)
    return DictionaryEntry(
        entry_id=data["entry_id"], spellings=tuple(data["spellings"]),
        readings=tuple(DictionaryReading(r["text"], tuple(r["spellings"]), r["no_kanji"])
                       for r in data["readings"]),
        senses=tuple(DictionarySense(**{key: tuple(value) for key, value in s.items()})
                     for s in data["senses"]),
        form_priority={form: tuple(tags) for form, tags in data.get("form_priority", {}).items()},
    )


class SQLiteDictionary:
    def __init__(self, path: Path) -> None:
        self._path = path.resolve()
        self._connection: sqlite3.Connection | None = None
        self._open()

    def _open(self) -> None:
        try:
            self._opened_inode = self._path.stat().st_ino
            self._connection = sqlite3.connect(self._path.as_uri() + "?mode=ro", uri=True)
            version = self._connection.execute("PRAGMA user_version").fetchone()[0]
            if version not in SUPPORTED_SCHEMA_VERSIONS:
                raise DictionaryError("Unsupported dictionary schema; reimport JMdict.")
            if version < SCHEMA_VERSION and not getattr(self, "_warned_schema", False):
                self._warned_schema = True
                logging.getLogger(__name__).warning(
                    "JMdict database uses schema %s; re-import JMdict to enable common-word ranking.", version)
            self.schema_version = version
            self._connection.execute("SELECT entry_id, payload FROM entries LIMIT 0")
            self._connection.execute("SELECT form, entry_id FROM forms LIMIT 0")
        except (sqlite3.Error, DictionaryError, OSError) as exc:
            self.close()
            raise DictionaryError(
                f"Cannot open dictionary '{self._path}': {exc}. "
                "Run scripts/import_jmdict.py first (see README)."
            ) from exc

    def _ensure_current(self) -> None:
        if self._connection is None:
            raise DictionaryError("Dictionary is closed.")
        try:
            replaced = self._path.stat().st_ino != self._opened_inode
        except OSError as exc:
            raise DictionaryError("Dictionary file unavailable; check setup and restart the backend.") from exc
        if replaced:
            self.close()
            self._open()

    def cache_identity(self) -> dict[str, object] | None:
        from ..cache_identity import file_identity, algorithm
        try:
            self._ensure_current()
            wal = Path(str(self._path)+"-wal")
            return {"database": file_identity(self._path), "wal": file_identity(wal) if wal.exists() else None,
                    "schema": self._connection.execute("PRAGMA user_version").fetchone()[0],
                    "algorithm": algorithm("dictionary/sqlite.py", "dictionary/models.py", "japanese.py")}
        except (DictionaryError, sqlite3.Error, OSError):
            return None  # Ordinary lexical lookup still reports its actionable failure.

    def lookup(self, text: str) -> tuple[DictionaryEntry, ...]:
        self._ensure_current()
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
