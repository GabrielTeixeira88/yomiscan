"""Explicit user-managed terminology, separate from disposable processing results."""

from dataclasses import dataclass
import os
from pathlib import Path
import sqlite3
import threading
import unicodedata
from uuid import UUID, uuid4

from .cache import digest
from .japanese import contains_japanese
from .translation.options import TargetLanguage, TARGET_NAMES

GLOBAL_SCOPE = "global"
MAX_SERIES = 100
MAX_ENTRIES = 1000


def normalized_term(value: str) -> str:
    return unicodedata.normalize("NFKC", value).strip()


def valid_scope(value: str) -> str:
    if value == GLOBAL_SCOPE:
        return value
    try:
        if str(UUID(value)) == value:
            return value
    except (ValueError, AttributeError):
        pass
    raise ValueError("Invalid glossary scope")


@dataclass(frozen=True)
class GlossaryEntry:
    id: str
    scope: str
    target_language: TargetLanguage
    source: str
    preferred: str


def applicable_terms(text: str, surfaces: tuple[str, ...], entries: tuple[GlossaryEntry, ...]) -> dict[str, str]:
    """Exact normalized matches at tokenizer boundaries; no source/output rewriting.

    Alignment failure yields no hints rather than an unsafe substring fallback.
    Written homographs remain ambiguous; hints are never a word-sense guarantee.
    """
    normalized = normalized_term(text)
    boundaries = {0, len(normalized)}
    cursor = 0
    for surface in surfaces:
        token = unicodedata.normalize("NFKC", surface)
        start = normalized.find(token, cursor)
        if not token or start < 0 or normalized[cursor:start].strip():
            return {}
        boundaries.update((start, start+len(token)))
        cursor = start+len(token)
    if normalized[cursor:].strip():
        return {}
    candidates = []
    for entry in entries:
        source = normalized_term(entry.source)
        start = normalized.find(source)
        while start >= 0:
            end = start+len(source)
            if start in boundaries and end in boundaries:
                candidates.append((start, end, source, entry.preferred))
            start = normalized.find(source, start+1)
    chosen: list[tuple[int, int, str, str]] = []
    for match in sorted(candidates, key=lambda m: (-(m[1]-m[0]), m[0], m[2])):
        if not any(match[0] < old[1] and match[1] > old[0] for old in chosen):
            chosen.append(match)
    return {source: preferred for _, _, source, preferred in sorted(chosen)}


class GlossaryStore:
    """One worker owns this non-disposable database. Corruption is never auto-deleted."""

    def __init__(self, path: Path = Path("data/glossaries.sqlite3")) -> None:
        self.path = path
        self._owner = threading.get_ident()
        self._connection: sqlite3.Connection | None = None

    def _db(self) -> sqlite3.Connection:
        if threading.get_ident() != self._owner:
            raise RuntimeError("Glossaries must run on their owning worker")
        if self._connection is None:
            self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            connection = sqlite3.connect(self.path, timeout=1)
            try:
                version = connection.execute("PRAGMA user_version").fetchone()[0]
                if version not in (0, 1):
                    raise ValueError("Unsupported glossary schema; preserve this user database and check setup")
                connection.execute("PRAGMA foreign_keys=ON")
                with connection:
                    connection.execute("CREATE TABLE IF NOT EXISTS series(id TEXT PRIMARY KEY,label TEXT NOT NULL)")
                    connection.execute("CREATE TABLE IF NOT EXISTS terms(id TEXT PRIMARY KEY,scope TEXT NOT NULL REFERENCES series(id) ON DELETE CASCADE,"
                                       "target TEXT NOT NULL,source TEXT NOT NULL,normalized TEXT NOT NULL,preferred TEXT NOT NULL,UNIQUE(scope,target,normalized))")
                    connection.execute("INSERT OR IGNORE INTO series VALUES(?,?)", (GLOBAL_SCOPE, "Global defaults"))
                    connection.execute("PRAGMA user_version=1")
                os.chmod(self.path, 0o600)
            except (sqlite3.Error, OSError, ValueError):
                connection.close()
                raise
            self._connection = connection
        return self._connection

    def series(self) -> list[dict[str, str]]:
        return [{"id": row[0], "label": row[1]} for row in self._db().execute("SELECT id,label FROM series ORDER BY id<>?,label,id", (GLOBAL_SCOPE,))]

    def create_series(self, label: str) -> str:
        label = label.strip()
        if not 1 <= len(label) <= 100 or any(unicodedata.category(c).startswith("C") for c in label):
            raise ValueError("Series label must contain 1–100 printable characters")
        db = self._db()
        if db.execute("SELECT COUNT(*) FROM series").fetchone()[0] > MAX_SERIES:
            raise ValueError("Series limit reached")
        identifier = str(uuid4())
        with db:
            db.execute("INSERT INTO series VALUES(?,?)", (identifier, label))
        return identifier

    def delete_series(self, scope: str) -> None:
        if valid_scope(scope) == GLOBAL_SCOPE:
            raise ValueError("Global defaults cannot be deleted; delete their entries instead")
        with self._db() as db:
            if db.execute("DELETE FROM series WHERE id=?", (scope,)).rowcount != 1:
                raise ValueError("Series no longer exists")

    def entries(self, scope: str, target: TargetLanguage) -> tuple[GlossaryEntry, ...]:
        valid_scope(scope)
        if target not in TARGET_NAMES:
            raise ValueError("Unsupported glossary target")
        db = self._db()
        if db.execute("SELECT 1 FROM series WHERE id=?", (scope,)).fetchone() is None:
            raise ValueError("Selected series no longer exists")
        return tuple(GlossaryEntry(*row) for row in db.execute(
            "SELECT id,scope,target,source,preferred FROM terms WHERE scope=? AND target=? ORDER BY normalized,id", (scope, target)))

    def save_entry(self, scope: str, target: TargetLanguage, source: str, preferred: str, *, entry_id: str | None = None) -> str:
        existing = self.entries(scope, target)
        source, preferred = source.strip(), preferred.strip()
        if not 1 <= len(source) <= 120 or not contains_japanese(source) or not 1 <= len(preferred) <= 200 or any(
            unicodedata.category(c).startswith("C") for c in source+preferred):
            raise ValueError("Use a Japanese term (1–120 characters) and printable preferred text (1–200 characters)")
        if entry_id is not None and not any(e.id == entry_id for e in existing):
            raise ValueError("Glossary entry no longer exists in this scope/target")
        if any(normalized_term(e.source) == normalized_term(source) and e.id != entry_id for e in existing):
            raise ValueError("This normalized Japanese term already exists; edit its entry")
        if entry_id is None and len(existing) >= MAX_ENTRIES:
            raise ValueError("Glossary entry limit reached")
        identifier = entry_id or str(uuid4())
        with self._db() as db:
            db.execute("INSERT INTO terms VALUES(?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET source=excluded.source,"
                       "normalized=excluded.normalized,preferred=excluded.preferred",
                       (identifier, scope, target, source, normalized_term(source), preferred))
        return identifier

    def delete_entry(self, scope: str, target: TargetLanguage, entry_id: str) -> None:
        self.entries(scope, target)
        with self._db() as db:
            if db.execute("DELETE FROM terms WHERE id=? AND scope=? AND target=?", (entry_id, scope, target)).rowcount != 1:
                raise ValueError("Glossary entry no longer exists in this scope/target")

    def effective(self, scope: str | None, target: TargetLanguage) -> tuple[GlossaryEntry, ...]:
        merged = {normalized_term(e.source): e for e in self.entries(GLOBAL_SCOPE, target)}
        if scope and scope != GLOBAL_SCOPE:
            merged.update((normalized_term(e.source), e) for e in self.entries(scope, target))
        return tuple(merged[key] for key in sorted(merged))

    def identity(self, scope: str | None, target: TargetLanguage) -> str:
        return digest([(normalized_term(e.source), e.preferred) for e in self.effective(scope, target)])

    def close(self) -> None:
        if threading.get_ident() != self._owner:
            raise RuntimeError("Glossaries must close on their owning worker")
        if self._connection is not None:
            self._connection.close()
            self._connection = None
