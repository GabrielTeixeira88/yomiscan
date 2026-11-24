"""Multi-token meaning units: longest JMdict match over consecutive tokens.

Token-level analysis splits expressions such as かもしれない, しょうがない or てしまう into
pieces whose individual meanings mislead a learner. This module finds spans of 2+ tokens
whose written form, or the form ending in the last token's dictionary form, is a JMdict
headword. Colloquial spellings are normalized with rule data (resources/lexical/units.json)
that a browser engine can share.

Selection is global, not left-to-right: longer spans win, then earlier ones, so そうか does
not block the longer かもしれない in そうかもしれない. Units are an extra layer; token analysis is
unchanged.
"""

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from functools import lru_cache
import json
from pathlib import Path
import unicodedata

from .dictionary import DictionaryEntry
from .lexical_ranking import FUNCTION_WORD_POS, headword_agrees, primary_pos, priority
from .nlp import JapaneseToken

RULES_PATH = Path(__file__).parent / "resources" / "lexical" / "units.json"
INFLECTING_POS = frozenset({"動詞", "形容詞"})


@dataclass(frozen=True)
class UnitRules:
    max_tokens: int
    variants: tuple[tuple[str, str], ...]
    clause_initial_only_pos: tuple[str, ...] = ()
    function_edge_entry_pos: tuple[str, ...] = ()
    function_edge_common_pos: tuple[str, ...] = ()
    verb_span_excluded_pos: tuple[str, ...] = ()
    never_initial_surfaces: frozenset[str] = frozenset()
    clause_initial_preferred_pos: tuple[str, ...] = ()


@dataclass(frozen=True)
class LexicalUnit:
    start: int  # first token index
    end: int  # exclusive token index
    surface: str
    lookup_form: str
    entry_ids: tuple[int, ...]


@lru_cache(maxsize=4)
def load_rules(path: Path = RULES_PATH) -> UnitRules:
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("schema_version") != 1:
        raise ValueError(f"{path}: unsupported unit rules schema {data.get('schema_version')!r}")
    max_tokens = data["max_tokens"]
    if not isinstance(max_tokens, int) or not 2 <= max_tokens <= 12:
        raise ValueError(f"{path}: max_tokens must be an integer from 2 to 12")
    variants = tuple((item["colloquial"], item["standard"]) for item in data["variants"])
    if any(not a or not b or a == b for a, b in variants):
        raise ValueError(f"{path}: variants need distinct nonempty colloquial/standard forms")
    return UnitRules(max_tokens, variants, tuple(data.get("clause_initial_only_pos", ())),
                     tuple(data.get("function_edge_entry_pos", ())), tuple(data.get("function_edge_common_pos", ())),
                     tuple(data.get("verb_span_excluded_pos", ())), frozenset(data.get("never_initial_surfaces", ())),
                     tuple(data.get("clause_initial_preferred_pos", ())))


def _symbolic(token: JapaneseToken) -> bool:
    return all(unicodedata.category(c)[0] in "PSZ" for c in token.surface)


def candidate_forms(span: Sequence[JapaneseToken], rules: UnitRules) -> tuple[str, ...]:
    """Written form, then the form ending in the last token's dictionary form, then variants."""
    surface = "".join(token.surface for token in span)
    last = span[-1]
    base = last.orthographic_base or last.lemma
    forms = [surface]
    if base and base != last.surface:
        forms.append("".join(token.surface for token in span[:-1]) + base)
    for form in list(forms):
        for colloquial, standard in rules.variants:
            if colloquial in form:
                forms.append(form.replace(colloquial, standard))
    return tuple(dict.fromkeys(forms))


def clause_initial(tokens: Sequence[JapaneseToken], start: int) -> bool:
    return start == 0 or _symbolic(tokens[start - 1])


def _first_pos_in(entry: DictionaryEntry, labels: Sequence[str]) -> bool:
    first = entry.senses[0].parts_of_speech if entry.senses else ()
    # Prefix match: "particle" must not match "nouns which may take the genitive case particle".
    return any(pos.lower().startswith(label) for pos in first for label in labels)


def rank_unit_entries(form: str, entries: Sequence[DictionaryEntry]) -> tuple[DictionaryEntry, ...]:
    def key(item: tuple[int, DictionaryEntry]) -> tuple[object, ...]:
        index, entry = item
        common, band = priority(entry, form)
        return (not headword_agrees(entry, form), not common, band, index)
    return tuple(entry for _, entry in sorted(enumerate(entries), key=key))


def find_units(tokens: Sequence[JapaneseToken], lookup: Callable[[str], tuple[DictionaryEntry, ...]],
               rules: UnitRules | None = None) -> tuple[tuple[LexicalUnit, tuple[DictionaryEntry, ...]], ...]:
    """Non-overlapping units with their ranked entries, in token order."""
    rules = rules or load_rules()
    found: list[tuple[LexicalUnit, tuple[DictionaryEntry, ...]]] = []
    for start in range(len(tokens)):
        if _symbolic(tokens[start]) or tokens[start].surface in rules.never_initial_surfaces:
            continue
        for end in range(min(len(tokens), start + rules.max_tokens), start + 1, -1):
            span = tokens[start:end]
            if any(_symbolic(token) for token in span):
                continue
            match = next(((form, entries) for form in candidate_forms(span, rules) if (entries := lookup(form))), None)
            if match is not None:
                form, entries = match
                ranked = rank_unit_entries(form, entries)
                if primary_pos(span[0]) in FUNCTION_WORD_POS or primary_pos(span[-1]) in FUNCTION_WORD_POS:
                    # A particle/auxiliary edge only forms functional units; は+と is not "pigeon".
                    ranked = tuple(entry for entry in ranked if _first_pos_in(entry, rules.function_edge_entry_pos) or (
                        priority(entry, form)[0] and _first_pos_in(entry, rules.function_edge_common_pos)))
                    if not ranked:
                        continue
                if any(primary_pos(token) in INFLECTING_POS for token in span):
                    # Verb し + particle て is not the particle して.
                    ranked = tuple(entry for entry in ranked if not _first_pos_in(entry, rules.verb_span_excluded_pos))
                    if not ranked:
                        continue
                if not clause_initial(tokens, start):
                    # Stable: mid-clause, conjunction readings follow particle/expression readings.
                    ranked = tuple(sorted(ranked, key=lambda entry: _first_pos_in(entry, rules.clause_initial_preferred_pos)))
                if not clause_initial(tokens, start) and _first_pos_in(ranked[0], rules.clause_initial_only_pos):
                    continue  # e.g. しまった in 食べてしまった is the auxiliary, not "oh no"
                unit = LexicalUnit(start, end, "".join(t.surface for t in span), form, tuple(e.entry_id for e in ranked))
                found.append((unit, ranked))
                break  # the longest span starting here; shorter ones only compete via other starts
    chosen: list[tuple[LexicalUnit, tuple[DictionaryEntry, ...]]] = []
    taken: set[int] = set()
    for unit, entries in sorted(found, key=lambda item: (-(item[0].end - item[0].start), item[0].start)):
        span = set(range(unit.start, unit.end))
        if not span & taken:
            chosen.append((unit, entries))
            taken |= span
    return tuple(sorted(chosen, key=lambda item: item[0].start))
