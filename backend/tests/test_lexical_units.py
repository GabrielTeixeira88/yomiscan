"""Multi-token unit matching on synthetic JMdict-shaped entries (no dictionary download).

Each case mirrors a false or missing unit observed on the Stage 1 corpus or golden set.
"""

from pathlib import Path
import json

import pytest

from yomiscan.dictionary import DictionaryEntry, DictionaryReading, DictionarySense
from yomiscan.lexical_units import RULES_PATH, candidate_forms, find_units, load_rules
from yomiscan.nlp import JapaneseToken

EXP = "expressions (phrases, clauses, etc.)"
NOUN = "noun (common) (futsuumeishi)"
NO_NOUN = "nouns which may take the genitive case particle 'no'"


def entry(entry_id, form, gloss, *pos, common=False):
    return DictionaryEntry(entry_id, (), (DictionaryReading(form),), (DictionarySense((gloss,), tuple(pos)),),
                           {form: ("ichi1",)} if common else {})


def token(surface, pos, base=None):
    return JapaneseToken(surface=surface, lemma=base or surface, reading=surface, part_of_speech=pos,
                         orthographic_base=base or surface, lemma_reading=base or surface)


def lookup_from(*entries):
    table: dict[str, list[DictionaryEntry]] = {}
    for item in entries:
        table.setdefault(item.readings[0].text, []).append(item)
    return lambda form: tuple(table.get(form, ()))


def units(tokens, *entries):
    return [(unit.surface, unit.lookup_form, unit.entry_ids) for unit, _ in find_units(tokens, lookup_from(*entries))]


PARTICLE = "助詞 / 格助詞"
AUX = "助動詞"
VERB = "動詞 / 非自立可能"


def test_rules_file_is_valid_shared_data():
    rules = load_rules()
    data = json.loads(Path(RULES_PATH).read_text(encoding="utf-8"))
    assert data["schema_version"] == 1 and rules.max_tokens == data["max_tokens"]
    assert ("ねえ", "ない") in rules.variants


def test_longest_unit_wins_over_an_earlier_shorter_one():
    tokens = [token("そう", "副詞"), token("か", "助詞 / 副助詞"), token("も", "助詞 / 係助詞"),
              token("しれ", VERB, "しれる"), token("ない", AUX)]
    found = units(tokens, entry(1, "そうか", "is that so", EXP), entry(2, "かもしれない", "maybe", EXP))
    assert found == [("かもしれない", "かもしれない", (2,))]


def test_last_token_dictionary_form_and_colloquial_variant():
    tokens = [token("しょう", "名詞"), token("が", PARTICLE), token("ねえ", AUX, "ない")]
    assert candidate_forms(tokens, load_rules())[:2] == ("しょうがねえ", "しょうがない")
    assert units(tokens, entry(1, "しょうがない", "it can't be helped", EXP)) == [("しょうがねえ", "しょうがない", (1,))]


def test_particle_edge_only_forms_functional_units():
    # は + と is not "pigeon"; a functional reading of the same span would be kept.
    tokens = [token("は", "助詞 / 係助詞"), token("と", PARTICLE)]
    assert units(tokens, entry(1, "はと", "pigeon", NOUN, NO_NOUN)) == []
    assert units(tokens, entry(1, "はと", "pigeon", NOUN), entry(2, "はと", "topic + quote", "particle")) == [("はと", "はと", (2,))]


def test_genitive_noun_label_is_not_a_particle():
    tokens = [token("た", AUX), token("そう", "名詞 / 助動詞語幹")]
    # "nouns which may take the genitive case particle 'no'" must not pass as "particle".
    assert units([token("あっ", VERB, "ある"), *tokens], entry(1, "たそう", "multilayer", NOUN, NO_NOUN)) == []


def test_verb_plus_te_is_not_the_particle_shite():
    tokens = [token("準備", "名詞"), token("し", VERB, "する"), token("て", "助詞 / 接続助詞")]
    assert units(tokens, entry(1, "して", "by means of", "particle")) == []


def test_interjection_only_at_clause_start():
    shimatta = entry(1, "しまった", "oh no", "interjection (kandoushi)")
    middle = [token("食べ", VERB, "食べる"), token("て", "助詞 / 接続助詞"), token("しまっ", VERB, "しまう"), token("た", AUX)]
    assert units(middle, shimatta) == []
    assert units([token("しまっ", VERB, "しまう"), token("た", AUX)], shimatta) == [("しまった", "しまった", (1,))]


def test_past_ending_never_starts_a_unit():
    tokens = [token("し", VERB, "する"), token("なかっ", AUX, "ない"), token("た", AUX), token("し", "助詞 / 接続助詞")]
    assert units(tokens, entry(1, "たし", "want to", "auxiliary verb")) == []


def test_symbols_split_units():
    tokens = [token("気", "名詞"), token("…", "補助記号"), token("を", PARTICLE)]
    assert units(tokens, entry(1, "気…を", "never", EXP)) == []


def test_invalid_rules_are_rejected(tmp_path):
    bad = tmp_path / "units.json"
    bad.write_text(json.dumps({"schema_version": 1, "max_tokens": 1, "variants": []}), encoding="utf-8")
    with pytest.raises(ValueError, match="max_tokens"):
        load_rules(bad)


def test_api_response_carries_units_with_meanings():
    from yomiscan.analysis import AnalyzedToken, TextAnalysisResult
    from yomiscan.api.models import ImageAnalysisResponse
    from yomiscan.lexical_units import LexicalUnit
    maybe = entry(7, "かもしれない", "maybe", EXP)
    tokens = tuple(AnalyzedToken(token(s, "助詞"), None, ()) for s in ("か", "も", "しれ", "ない"))
    result = TextAnalysisResult("かもしれない", tokens, {7: maybe},
                                units=(LexicalUnit(0, 4, "かもしれない", "かもしれない", (7,)),))
    response = ImageAnalysisResponse.from_analysis(result).model_dump()
    assert response["units"] == [{"surface": "かもしれない", "dictionary_form": "かもしれない", "start_token": 0, "end_token": 4,
                                  "meanings": [{"entry_id": 7, "glosses": ["maybe"], "parts_of_speech": [EXP], "spellings": [],
                                                "readings": [], "notes": [], "labels": []}]}]
