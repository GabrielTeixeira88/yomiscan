"""One-time streaming import of official JMdict XML (plain or gzip)."""

from dataclasses import asdict
from datetime import datetime, timezone
import gzip
import hashlib
import json
from pathlib import Path
import sqlite3
import tempfile
import xml.etree.ElementTree as ET

from yomiscan.japanese import hiragana

from .models import DictionaryEntry, DictionaryError, DictionaryReading, DictionarySense
from .sqlite import SCHEMA_VERSION

SOURCE_URL = "https://www.edrdg.org/pub/Nihongo/JMdict_e.gz"
LICENSE_URL = "https://www.edrdg.org/edrdg/licence.html"


def _texts(element: ET.Element, tag: str) -> tuple[str, ...]:
    return tuple(child.text for child in element.findall(tag) if child.text)


def _entry(element: ET.Element) -> DictionaryEntry:
    senses = []
    pos: tuple[str, ...] = ()
    for sense in element.findall("sense"):
        # JMdict POS is inherited from the preceding sense when omitted.
        pos = _texts(sense, "pos") or pos
        glosses = tuple("".join(g.itertext()) for g in sense.findall("gloss")
                        if g.get("{http://www.w3.org/XML/1998/namespace}lang", "eng") == "eng")
        if glosses:
            senses.append(DictionarySense(
                glosses, pos, _texts(sense, "stagk"), _texts(sense, "stagr"),
                _texts(sense, "s_inf"),
                _texts(sense, "misc") + _texts(sense, "field") + _texts(sense, "dial"),
            ))
    readings = tuple(DictionaryReading(
        r.findtext("reb", ""), _texts(r, "re_restr"), r.find("re_nokanji") is not None,
    ) for r in element.findall("r_ele"))
    if not readings or any(not r.text for r in readings):
        raise ValueError("JMdict entry has no valid reading")
    return DictionaryEntry(int(element.findtext("ent_seq", "")),
                           _texts(element, "k_ele/keb"), readings, tuple(senses))


def import_jmdict(source: Path, destination: Path) -> int:
    """Build beside the destination and replace it only after a successful import."""
    if source.resolve() == destination.resolve():
        raise DictionaryError("Source XML and destination database must be different files.")
    temporary: Path | None = None
    try:
        destination.parent.mkdir(parents=True, exist_ok=True)
        with source.open("rb") as stream:
            digest = hashlib.file_digest(stream, "sha256").hexdigest()
        with tempfile.NamedTemporaryFile(dir=destination.parent, suffix=".sqlite3", delete=False) as temp:
            temporary = Path(temp.name)
        connection = sqlite3.connect(temporary)
        try:
            connection.executescript("""
                CREATE TABLE entries (entry_id INTEGER PRIMARY KEY, payload TEXT NOT NULL);
                CREATE TABLE forms (form TEXT NOT NULL, entry_id INTEGER NOT NULL,
                    PRIMARY KEY (form, entry_id), FOREIGN KEY (entry_id) REFERENCES entries);
                CREATE TABLE metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL);
            """)
            opener = gzip.open if source.suffix.lower() == ".gz" else open
            count = 0
            with opener(source, "rb") as stream, connection:
                parser = ET.iterparse(stream, events=("start", "end"))
                _, root = next(parser)
                if root.tag != "JMdict":
                    raise ValueError("Expected a JMdict XML document")
                for event, element in parser:
                    if event != "end" or element.tag != "entry":
                        continue
                    entry = _entry(element)
                    if entry.senses:
                        connection.execute("INSERT INTO entries VALUES (?, ?)",
                                           (entry.entry_id, json.dumps(asdict(entry), ensure_ascii=False)))
                        forms = {hiragana(s) for s in entry.spellings}
                        forms.update(hiragana(r.text) for r in entry.readings)
                        connection.executemany("INSERT INTO forms VALUES (?, ?)",
                                               ((form, entry.entry_id) for form in forms))
                        count += 1
                    root.remove(element)
                    element.clear()
                if not count:
                    raise ValueError("Source contains no English JMdict entries")
                metadata = {
                    "source": source.name, "source_url": SOURCE_URL, "sha256": digest,
                    "imported_at": datetime.now(timezone.utc).isoformat(), "entries": str(count),
                    "attribution": "JMdict: JMdict contributors / EDRDG; CC BY-SA 4.0",
                    "license_url": LICENSE_URL,
                    "transformation": "English senses and normalized exact lookup forms in SQLite",
                }
                connection.executemany("INSERT INTO metadata VALUES (?, ?)", metadata.items())
                connection.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
        finally:
            connection.close()
        temporary.replace(destination)
        return count
    except (OSError, EOFError, ET.ParseError, sqlite3.Error, ValueError, StopIteration) as exc:
        raise DictionaryError(f"JMdict import failed; existing database kept: {exc}") from exc
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
