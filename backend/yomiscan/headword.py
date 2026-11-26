"""The reading of a word's dictionary form (食べた -> 食べる, たべる), for saved words and their exports.

The browser engine mirrors this rule in extension/src/engine/lexicon.ts (`dictionaryReading`);
both are tested on the same cases.
"""

from collections.abc import Iterable
import re

from yomiscan.dictionary import DictionaryEntry
from yomiscan.japanese import hiragana

KANJI = re.compile(r"[㐀-䶿一-鿿豈-﫿\U00020000-\U000323af々〆ヶ]")


def dictionary_reading(form: str | None, entry: DictionaryEntry | None, hints: Iterable[str | None]) -> str | None:
    """The JMdict reading of `form` in its best `entry`; `hints` (readings in hiragana) break ties, in order.

    A kana form is its own reading. A written form takes the entry's readings that apply to it
    (JMdict re_restr, and never a re_nokanji reading). Without an entry, the first hint.
    """
    if not form:
        return None
    hints = [hint for hint in hints if hint]
    if not KANJI.search(form):
        if entry is not None:
            for reading in entry.readings:
                if hiragana(reading.text) == hiragana(form):
                    return reading.text
        return form
    if entry is None or form not in entry.spellings:
        return hints[0] if hints else None
    candidates = [r.text for r in entry.readings if not r.no_kanji and (not r.spellings or form in r.spellings)]
    for hint in hints:
        for candidate in candidates:
            if hiragana(candidate) == hint:
                return candidate
    return candidates[0] if candidates else (hints[0] if hints else None)
