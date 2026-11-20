"""Bounded byte storage for stage results. Owned by the inference worker, never pickle."""

from collections import OrderedDict
from dataclasses import dataclass, field
import hashlib
import json
import logging
import os
from pathlib import Path
import sqlite3
import threading
from time import perf_counter, time_ns
from typing import Literal

from PIL import Image

SCHEMA = 1
MiB = 1024 * 1024
MAX_ENTRY = 48 * MiB
logger = logging.getLogger(__name__)
Refresh = Literal["none", "translation", "render", "all"]


def canonical_json(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def digest(value: object) -> str:
    return hashlib.sha256(canonical_json(value)).hexdigest()


def pixel_identity(image: Image.Image) -> dict[str, object]:
    """API decoding already applies EXIF transpose. Byte digest keeps its old meaning."""
    rgb = image.convert("RGB")
    header = {"normalization": "exif-rgb-v1", "width": rgb.width, "height": rgb.height, "mode": "RGB"}
    h = hashlib.sha256(canonical_json(header))
    h.update(rgb.tobytes())
    return {**header, "sha256": h.hexdigest()}


class ProcessingCache:
    """One connection, byte-accounted RAM, transactional SQLite BLOBs and disk LRU.

    Disabled persistence never opens/reads the result database. Settings contain only
    consent and quota. Failure of this optional storage falls back to ordinary work.
    """

    def __init__(self, directory: Path = Path(".cache/processing"), *, enabled: bool | None = None,
                 memory_bytes: int = 64 * MiB, disk_bytes: int = 512 * MiB) -> None:
        if memory_bytes < 0 or not MiB <= disk_bytes <= 16 * 1024 * MiB:
            raise ValueError("Cache limits: RAM >= 0; disk 1 MiB to 16 GiB")
        self.directory, self.memory_limit, self.disk_limit = directory, memory_bytes, disk_bytes
        self.enabled = False
        self._thread = threading.get_ident()
        self._db: sqlite3.Connection | None = None
        self._ram: OrderedDict[tuple[str, str], bytes] = OrderedDict()
        self._memory = 0
        self.hits = self.misses = self.evictions = self.corruptions = 0
        self.error: str | None = None
        if enabled is None:
            try:
                settings = json.loads((directory / "settings.json").read_text(encoding="utf-8"))
                enabled = settings.get("enabled") is True
                quota = settings.get("disk_bytes")
                if type(quota) is int and MiB <= quota <= 16 * 1024 * MiB:
                    self.disk_limit = quota
            except FileNotFoundError:
                pass
            except (OSError, ValueError, TypeError, AttributeError):
                self.error = "settings_unavailable"
        self.enabled = bool(enabled)
        if self.enabled:
            self._open()

    def _own(self) -> None:
        if threading.get_ident() != self._thread:
            raise RuntimeError("Processing cache must run on its owning inference worker")

    def _failure(self, code: str, exc: Exception) -> None:
        self.error = code
        logger.warning("Processing cache %s; inference remains available", code, exc_info=exc)

    def _open(self) -> None:
        self._own()
        path = self.directory / "stages.sqlite3"
        try:
            self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)
            self._db = sqlite3.connect(path, timeout=1)
            self._db.execute("PRAGMA journal_mode=DELETE")
            version = self._db.execute("PRAGMA user_version").fetchone()[0]
            if version not in (0, SCHEMA) or self._db.execute("PRAGMA quick_check").fetchone()[0] != "ok":
                raise sqlite3.DatabaseError("Cache schema/integrity requires rebuilding")
            self._db.execute("PRAGMA auto_vacuum=FULL")
            self._db.execute("CREATE TABLE IF NOT EXISTS entries (stage TEXT NOT NULL, key TEXT NOT NULL, "
                             "payload BLOB NOT NULL, checksum TEXT NOT NULL, used INTEGER NOT NULL, "
                             "PRIMARY KEY(stage,key))")
            self._db.execute("CREATE INDEX IF NOT EXISTS eviction ON entries(used)")
            self._db.execute(f"PRAGMA user_version={SCHEMA}")
            self._db.commit()
            self._trim()
            os.chmod(path, 0o600)
            self.error = None
        except sqlite3.DatabaseError as exc:
            self._failure("database_unavailable", exc)
            if self._db is not None:
                self._db.close()
                self._db = None
            # A lock/I/O error is not evidence of corruption. Never delete in that case.
            if type(exc) is sqlite3.DatabaseError or getattr(exc, "sqlite_errorcode", None) in (sqlite3.SQLITE_CORRUPT, sqlite3.SQLITE_NOTADB):
                try:
                    for name in ("stages.sqlite3", "stages.sqlite3-journal"):
                        (self.directory / name).unlink(missing_ok=True)
                    self.corruptions += 1
                    # Next operation may reopen; this request can still use RAM.
                except OSError as cleanup_error:
                    self._failure("database_cleanup_failed", cleanup_error)
        except OSError as exc:
            self._failure("storage_unavailable", exc)
            if self._db is not None:
                self._db.close()
                self._db = None

    def _trim(self, incoming: int = 0) -> None:
        if self._db is None:
            return
        # Reserve page/index overhead, then enforce the actual database size too.
        target = max(0, self.disk_limit - 128 * 1024 - incoming)
        total = self._db.execute("SELECT COALESCE(SUM(length(payload)+length(key)+length(stage)+128),0) FROM entries").fetchone()[0]
        while total > target or (self.directory / "stages.sqlite3").stat().st_size > self.disk_limit:
            row = self._db.execute("SELECT stage,key,length(payload)+length(key)+length(stage)+128 FROM entries ORDER BY used LIMIT 1").fetchone()
            if row is None:
                break
            with self._db:
                self._db.execute("DELETE FROM entries WHERE stage=? AND key=?", row[:2])
            total -= row[2]
            self.evictions += 1

    def _remember(self, identity: tuple[str, str], payload: bytes) -> None:
        def cost(key: tuple[str, str], value: bytes) -> int:
            return len(value) + len(key[0].encode()) + len(key[1].encode()) + 256
        old = self._ram.pop(identity, None)
        if old is not None:
            self._memory -= cost(identity, old)
        size = cost(identity, payload)
        if size <= self.memory_limit:
            while self._ram and self._memory + size > self.memory_limit:
                removed_key, removed = self._ram.popitem(last=False)
                self._memory -= cost(removed_key, removed)
                self.evictions += 1
            self._ram[identity] = payload
            self._memory += size

    def get(self, stage: str, key: str) -> tuple[bytes | None, str]:
        self._own()
        identity = (stage, key)
        payload = self._ram.get(identity)
        if payload is not None:
            self._ram.move_to_end(identity)
            self.hits += 1
            return payload, "memory"
        if self.enabled:
            if self._db is None:
                self._open()
            try:
                row = self._db.execute("SELECT payload,checksum FROM entries WHERE stage=? AND key=?", identity).fetchone() if self._db else None
                if row is not None:
                    payload, checksum = row
                    if len(payload) > MAX_ENTRY or hashlib.sha256(payload).hexdigest() != checksum:
                        self.discard(stage, key)
                    else:
                        with self._db:
                            self._db.execute("UPDATE entries SET used=? WHERE stage=? AND key=?", (time_ns(), *identity))
                        self._remember(identity, payload)
                        self.hits += 1
                        return payload, "disk"
            except sqlite3.Error as exc:
                self._failure("read_failed", exc)
        self.misses += 1
        return None, "miss"

    def put(self, stage: str, key: str, payload: bytes) -> None:
        self._own()
        if len(payload) > MAX_ENTRY:
            return
        self._remember((stage, key), payload)
        if not self.enabled or len(payload) + 128 * 1024 > self.disk_limit:
            return
        if self._db is None:
            self._open()
        try:
            if self._db is not None:
                self._trim(len(payload) + 512)
                with self._db:
                    self._db.execute("INSERT OR REPLACE INTO entries VALUES(?,?,?,?,?)",
                                     (stage, key, payload, hashlib.sha256(payload).hexdigest(), time_ns()))
                self._trim()
        except (sqlite3.Error, OSError) as exc:
            self._failure("write_failed", exc)

    def discard(self, stage: str, key: str) -> None:
        self._own()
        old = self._ram.pop((stage, key), None)
        if old is not None:
            self._memory -= len(old) + len(stage.encode()) + len(key.encode()) + 256
        self.corruptions += 1
        if self._db is not None:
            try:
                with self._db:
                    self._db.execute("DELETE FROM entries WHERE stage=? AND key=?", (stage, key))
            except sqlite3.Error as exc:
                self._failure("invalidation_failed", exc)

    def configure(self, enabled: bool, disk_bytes: int | None = None) -> dict[str, object]:
        self._own()
        if type(enabled) is not bool or (disk_bytes is not None and (type(disk_bytes) is not int or not MiB <= disk_bytes <= 16 * 1024 * MiB)):
            raise ValueError("Invalid cache settings")
        quota = self.disk_limit if disk_bytes is None else disk_bytes
        self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        temporary = self.directory / "settings.tmp"
        try:
            with temporary.open("w", encoding="utf-8") as handle:
                os.chmod(temporary, 0o600)
                json.dump({"enabled": enabled, "disk_bytes": quota}, handle)
                handle.flush()
                os.fsync(handle.fileno())
            temporary.replace(self.directory / "settings.json")
        finally:
            temporary.unlink(missing_ok=True)
        self.enabled, self.disk_limit = enabled, quota
        self.close()
        if enabled:
            self._open()
        return self.stats()

    def clear(self) -> dict[str, object]:
        self._own()
        self._ram.clear()
        self._memory = 0
        self.close()
        # Only these application-owned files, no recursive traversal or arbitrary paths.
        for name in ("stages.sqlite3", "stages.sqlite3-journal", "stages.sqlite3-wal", "stages.sqlite3-shm"):
            (self.directory / name).unlink(missing_ok=True)
        return self.stats()

    def stats(self) -> dict[str, object]:
        self._own()
        try:
            disk = (self.directory / "stages.sqlite3").stat().st_size
        except FileNotFoundError:
            disk = 0
        except OSError:
            disk = 0
        return {"schema": SCHEMA, "persistent_enabled": self.enabled, "memory_bytes": self._memory,
                "memory_limit": self.memory_limit, "disk_bytes": disk, "disk_limit": self.disk_limit,
                "hits": self.hits, "misses": self.misses, "evictions": self.evictions,
                "corruptions": self.corruptions, "error_code": self.error}

    def close(self) -> None:
        self._own()
        if self._db is not None:
            self._db.close()
            self._db = None


@dataclass
class CacheRequest:
    cache: ProcessingCache
    refresh: Refresh = "none"
    stages: list[dict[str, object]] = field(default_factory=list)

    def key(self, stage: str, *inputs: object) -> str:
        return digest([SCHEMA, stage, *inputs])

    def get(self, stage: str, key: str | None) -> bytes | None:
        start = perf_counter()
        bypass = self.refresh == "all" or self.refresh == stage or (self.refresh == "translation" and stage == "render")
        payload, source = (None, "unidentified") if key is None else (None, "refresh") if bypass else self.cache.get(stage, key)
        self.stages.append({"stage": stage, "key": key, "source": source,
                            "restored": payload is not None, "lookup_ms": (perf_counter()-start)*1000})
        return payload

    def put(self, stage: str, key: str | None, payload: bytes) -> None:
        if key is not None:
            self.cache.put(stage, key, payload)

    def invalid(self, stage: str, key: str | None) -> None:
        if key is not None:
            self.cache.discard(stage, key)
        self.stages[-1].update(source="corrupt", restored=False)

    def metadata(self) -> dict[str, object]:
        return {**self.cache.stats(), "refresh": self.refresh, "stages": self.stages}
