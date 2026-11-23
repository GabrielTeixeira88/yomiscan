"""Order a token's JMdict candidates by agreement with its morphological analysis.

The rules are deterministic and data-driven, so they can be tested without models and
ported unchanged if lexical analysis later moves into the browser. Sense order inside
an entry is never changed: JMdict lists senses from most to least general.
"""

from collections.abc import Callable, Sequence
import re

from .dictionary import DictionaryEntry
from .japanese import hiragana
from .nlp import JapaneseToken

# JMdict's own definition of a "common" word (EDRDG documentation for ke_pri/re_pri).
COMMON_PRIORITY_TAGS = frozenset({"news1", "ichi1", "spec1", "spec2", "gai1"})
_FREQUENCY_TAG = re.compile(r"nf(\d\d)")
_KANJI = re.compile(r"[㐀-鿿豈-﫿]")


def _verb(label: str) -> bool:
    lowered = label.lower()
    return "verb" in lowered and not any(part in lowered for part in ("adverb", "aux", "noun"))


# UniDic first-level part of speech → predicate over JMdict sense POS labels.
# Function words (particles, auxiliaries) use exact labels: broader substrings such as
# "particle" also match "nouns which may take the genitive case particle 'no'".
POS_FAMILIES: dict[str, Callable[[str], bool]] = {
    "名詞": lambda label: "noun" in label or label in ("numeric", "counter", "pronoun"),
    "代名詞": lambda label: label == "pronoun",
    "動詞": _verb,
    "形容詞": lambda label: label.startswith("adjective (keiyoushi)") or label == "'ku' adjective (archaic)",
    "形状詞": lambda label: label.startswith("adjectival nouns") or label in ("'taru' adjective", "archaic/formal form of na-adjective"),
    "副詞": lambda label: label.startswith("adverb"),
    "連体詞": lambda label: label.startswith("pre-noun adjectival"),
    "接続詞": lambda label: label == "conjunction",
    "感動詞": lambda label: label.startswith("interjection"),
    "助詞": lambda label: label == "particle",
    "助動詞": lambda label: label in ("auxiliary verb", "auxiliary", "auxiliary adjective", "copula"),
    "接頭辞": lambda label: "prefix" in label,
    "接尾辞": lambda label: "suffix" in label or label == "counter",
}
# Particles and auxiliaries collide with many content-word homophones (は → 歯, 葉, 刃…).
# When an agreeing function-word entry exists, the non-agreeing candidates are dropped.
FUNCTION_WORD_POS = frozenset({"助詞", "助動詞"})


def primary_pos(token: JapaneseToken) -> str | None:
    return token.part_of_speech.split(" / ")[0] if token.part_of_speech else None


def pos_agrees(entry: DictionaryEntry, pos: str | None) -> bool:
    return pos_rank(entry, pos) < 2


def pos_rank(entry: DictionaryEntry, pos: str | None) -> int:
    """0: the first sense agrees; 1: a later sense agrees; 2: no agreement or unknown POS.

    無い lists its auxiliary use after its adjective senses, while the auxiliary entry
    ない starts with it; the first sense says what an entry primarily is.
    """
    family = POS_FAMILIES.get(pos or "")
    if family is None or not entry.senses:
        return 2
    if any(family(label) for label in entry.senses[0].parts_of_speech):
        return 0
    return 1 if any(family(label) for sense in entry.senses[1:] for label in sense.parts_of_speech) else 2


def _lemma(token: JapaneseToken) -> str | None:
    # UniDic lemmas may carry a gloss suffix (アイス-ice); keep the written form only.
    return token.lemma.split("-")[0] if token.lemma else None


def lemma_rank(entry: DictionaryEntry, token: JapaneseToken) -> int:
    """0: a kanji lemma is a spelling (事 for こと, 何 for なん); 1: it shares a kanji
    with a spelling (行く for the potential いける → 行ける); 2: no evidence."""
    lemma = _lemma(token)
    kanji = set(_KANJI.findall(lemma or ""))
    if not kanji:
        return 2
    if lemma in entry.spellings:
        return 0
    return 1 if any(kanji & set(spelling) for spelling in entry.spellings) else 2


def headword_agrees(entry: DictionaryEntry, matched_form: str | None) -> bool:
    """The matched form is the entry's first spelling or first reading, not an alternate."""
    if not matched_form:
        return False
    first = [form for form in (entry.spellings[:1] + tuple(r.text for r in entry.readings[:1]))]
    return hiragana(matched_form) in {hiragana(form) for form in first}


def reading_agrees(entry: DictionaryEntry, token: JapaneseToken) -> bool:
    reading = token.lemma_reading
    return bool(reading and any(hiragana(item.text) == reading for item in entry.readings))


def priority(entry: DictionaryEntry, matched_form: str | None) -> tuple[bool, int]:
    """(is common, nf band) for the forms equal to the matched lookup form."""
    target = hiragana(matched_form) if matched_form else None
    tags = [tag for form, values in entry.form_priority.items()
            if target is None or hiragana(form) == target for tag in values]
    bands = [int(match.group(1)) for tag in tags if (match := _FREQUENCY_TAG.fullmatch(tag))]
    return any(tag in COMMON_PRIORITY_TAGS for tag in tags), min(bands, default=99)


def rank_entries(token: JapaneseToken, matched_form: str | None,
                 entries: Sequence[DictionaryEntry]) -> tuple[DictionaryEntry, ...]:
    """Best candidate first; function-word homophones removed when a match exists."""
    pos = primary_pos(token)
    candidates = list(entries)
    if pos in FUNCTION_WORD_POS and any(pos_agrees(entry, pos) for entry in candidates):
        candidates = [entry for entry in candidates if pos_agrees(entry, pos)]

    def key(item: tuple[int, DictionaryEntry]) -> tuple[object, ...]:
        index, entry = item
        common, band = priority(entry, matched_form)
        return (lemma_rank(entry, token), pos_rank(entry, pos), not headword_agrees(entry, matched_form),
                not reading_agrees(entry, token), not common, band, index)

    return tuple(entry for _, entry in sorted(enumerate(candidates), key=key))


def choose_matches(token: JapaneseToken, forms: Sequence[str],
                   lookup: Callable[[str], tuple[DictionaryEntry, ...]]) -> tuple[str | None, tuple[DictionaryEntry, ...]]:
    """Look up forms in order and return the matched form with ranked entries.

    The first form with any match wins, except for particles and auxiliaries: there,
    the form whose entries agree best on part of speech wins, earlier forms breaking
    ties. For the contracted ん (lemma の), ん only has an interjection whose *later*
    sense is a particle, while の is primarily a particle.
    """
    pos = primary_pos(token)
    best: tuple[int, str, tuple[DictionaryEntry, ...]] | None = None
    for form in forms:  # Lazy: later forms are looked up only when still needed.
        matches = lookup(form)
        if not matches:
            continue
        rank = min(pos_rank(entry, pos) for entry in matches) if pos in FUNCTION_WORD_POS else 0
        if best is None or rank < best[0]:
            best = (rank, form, matches)
        if best[0] == 0:
            break
    if best is None:
        return None, ()
    return best[1], rank_entries(token, best[1], best[2])
