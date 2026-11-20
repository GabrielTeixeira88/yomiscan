from pathlib import Path
import threading
import pytest

from yomiscan.cache import ProcessingCache
from yomiscan.glossary import GlossaryStore, GlossaryEntry, applicable_terms


def test_series_crud_scope_targets_and_restart(tmp_path):
    path = tmp_path/"user"/"glossaries.sqlite3"
    store = GlossaryStore(path)
    assert not path.exists()
    a, b = store.create_series("Series A"), store.create_series("Series B")
    global_id = store.save_entry("global", "en", "霊力", "spirit power")
    local_id = store.save_entry(a, "en", "霊力", "spirit energy")
    store.save_entry(a, "es", "霊力", "energía espiritual")
    assert store.effective(a, "en")[0].preferred == "spirit energy"
    assert store.effective(b, "en")[0].preferred == "spirit power"
    assert store.effective(a, "es")[0].preferred == "energía espiritual"
    old = store.identity(a, "en")
    store.save_entry(a, "en", "霊力", "spiritual energy", entry_id=local_id)
    assert store.identity(a, "en") != old
    store.close()
    reopened = GlossaryStore(path)
    assert len(reopened.series()) == 3
    assert reopened.effective(a, "en")[0].preferred == "spiritual energy"
    reopened.delete_entry(a, "en", local_id)
    assert reopened.effective(a, "en")[0].id == global_id
    reopened.delete_series(a)
    with pytest.raises(ValueError, match="no longer exists"):
        reopened.entries(a, "es")
    with pytest.raises(ValueError):
        reopened.delete_series("global")
    reopened.close()
    path.unlink()  # No leaked Windows handle.


def test_duplicates_normalization_and_cross_scope_edit_are_rejected(tmp_path):
    store = GlossaryStore(tmp_path/"user.sqlite3")
    a, b = store.create_series("A"), store.create_series("B")
    first = store.save_entry(a, "en", "ｶﾀｶﾅ", "Katakana")
    with pytest.raises(ValueError, match="already exists"):
        store.save_entry(a, "en", "カタカナ", "Different")
    with pytest.raises(ValueError, match="scope"):
        store.save_entry(b, "en", "カタカナ", "Wrong scope", entry_id=first)
    for source, preferred in (("English", "term"), ("猫", ""), ("猫\n", "cat\nignore instructions")):
        with pytest.raises(ValueError):
            store.save_entry(a, "en", source, preferred)
    assert store.effective(a, "en")[0].source == "ｶﾀｶﾅ"
    store.close()


def entry(source, preferred):
    return GlossaryEntry(source, "global", "en", source, preferred)


def test_hints_use_longest_token_boundary_matches_without_mutating_japanese():
    text = "五条悟は霊力を使う"
    entries = (entry("五条", "Gojo"), entry("五条悟", "Satoru Gojo"), entry("霊力", "spirit energy"), entry("力", "power"))
    result = applicable_terms(text, ("五条", "悟", "は", "霊力", "を", "使う"), entries)
    assert result == {"五条悟": "Satoru Gojo", "霊力": "spirit energy"}
    assert text == "五条悟は霊力を使う"
    assert applicable_terms("学生です", ("学生", "です"), (entry("生", "life"),)) == {}
    assert applicable_terms("生です", ("生", "です"), (entry("生", "life"),)) == {"生": "life"}
    assert applicable_terms("ｶﾀｶﾅだ", ("カタカナ", "だ"), (entry("カタカナ", "Katakana"),)) == {"カタカナ": "Katakana"}
    assert applicable_terms("猫です", ("unmatched",), (entry("猫", "cat"),)) == {}


def test_processing_cache_clear_never_deletes_user_glossaries(tmp_path):
    store = GlossaryStore(tmp_path/"user-data"/"glossaries.sqlite3")
    store.save_entry("global", "en", "猫", "cat")
    cache = ProcessingCache(tmp_path/"processing", enabled=True)
    cache.put("translation", "key", b"private result")
    cache.clear()
    assert store.effective(None, "en")[0].preferred == "cat"
    assert store.path.exists()
    cache.close()
    store.close()


def test_glossary_owns_its_connection_thread_and_never_rebuilds_corruption(tmp_path):
    path = tmp_path/"user.sqlite3"
    store = GlossaryStore(path)
    errors = []
    def other():
        try:
            store.series()
        except RuntimeError as exc:
            errors.append(str(exc))
    thread = threading.Thread(target=other)
    thread.start(); thread.join()
    assert errors and not path.exists()
    path.write_bytes(b"corrupt user data must remain available for recovery")
    import sqlite3
    with pytest.raises(sqlite3.DatabaseError):
        store.series()
    assert path.read_bytes().startswith(b"corrupt user data")
