import gzip
import sqlite3

import pytest

from yomiscan.dictionary import DictionaryError, SQLiteDictionary
from yomiscan.dictionary.importer import import_jmdict


def test_exact_spelling_reading_and_english_only(dictionary_path):
    with SQLiteDictionary(dictionary_path) as dictionary:
        entry = dictionary.lookup("猫")[0]
        assert dictionary.lookup("ねこ") == (entry,)
        assert dictionary.lookup("ネコ") == (entry,)
        assert dictionary.lookup("ﾈｺ") == (entry,)
        assert entry.senses[0].glosses == ("cat",)
        assert entry.senses[1].parts_of_speech == ("noun",)
        assert dictionary.lookup("食べ") == ()
        assert dictionary.lookup("YomiScan") == ()
        assert dictionary.lookup("' OR 1=1 --") == ()
        assert dictionary.lookup("") == ()


def test_preserves_restrictions(dictionary_path):
    with SQLiteDictionary(dictionary_path) as dictionary:
        entry = dictionary.lookup("試験")[0]
        assert entry.readings[0].spellings == ("試験",)
        assert entry.readings[1].no_kanji
        assert entry.senses[0].spellings == ("試験",)
        assert entry.senses[0].readings == ("しけん",)
        assert entry.senses[0].notes == ("test note",)
        assert entry.senses[0].labels == ("test label",)


def test_gzip_and_metadata(jmdict_source, tmp_path):
    compressed = tmp_path / "source.xml.gz"
    compressed.write_bytes(gzip.compress(jmdict_source.read_bytes()))
    output = tmp_path / "result.sqlite3"
    assert import_jmdict(compressed, output) == 6
    connection = sqlite3.connect(output)
    try:
        metadata = dict(connection.execute("SELECT key, value FROM metadata"))
        assert len(metadata["sha256"]) == 64
        assert metadata["entries"] == "6"
        assert "CC BY-SA" in metadata["attribution"]
        plan = connection.execute("EXPLAIN QUERY PLAN SELECT entry_id FROM forms WHERE form = ?", ("猫",)).fetchall()
        assert "INDEX" in str(plan)
    finally:
        connection.close()


@pytest.mark.parametrize("content", ["<broken>", "<JMdict/>", "<wrong/>", ""])
def test_failed_import_preserves_database(content, dictionary_path, tmp_path):
    before = dictionary_path.read_bytes()
    source = tmp_path / "broken.xml"
    source.write_text(content)
    with pytest.raises(DictionaryError):
        import_jmdict(source, dictionary_path)
    assert dictionary_path.read_bytes() == before
    assert list(tmp_path.glob("*.sqlite3")) == [dictionary_path]


def test_missing_database_is_not_created(tmp_path):
    path = tmp_path / "absent.sqlite3"
    with pytest.raises(DictionaryError, match="import_jmdict"):
        SQLiteDictionary(path)
    assert not path.exists()


def test_wrong_schema_and_closed_connection(tmp_path, dictionary_path):
    wrong = tmp_path / "wrong.sqlite3"
    sqlite3.connect(wrong).close()
    with pytest.raises(DictionaryError, match="schema"):
        SQLiteDictionary(wrong)
    with SQLiteDictionary(dictionary_path) as dictionary:
        assert dictionary.lookup("猫")
    with pytest.raises(DictionaryError, match="closed"):
        dictionary.lookup("猫")


def test_same_path_is_rejected(jmdict_source):
    before = jmdict_source.read_bytes()
    with pytest.raises(DictionaryError, match="different"):
        import_jmdict(jmdict_source, jmdict_source)
    assert jmdict_source.read_bytes() == before
