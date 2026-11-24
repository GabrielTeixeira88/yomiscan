"""Grammar notes over synthetic UniDic-shaped tokens (no tokenizer or dictionary needed).

Token shapes mirror real fugashi + UniDic-lite output for each construction.
"""

import json

import pytest

from yomiscan.grammar_patterns import find_grammar, load_patterns, pattern_by_id
from yomiscan.nlp import JapaneseToken


def tok(surface, pos, base=None, form=None):
    return JapaneseToken(surface=surface, lemma=base or surface, part_of_speech=pos,
                         orthographic_base=base or surface, conjugation_form=form)


def notes(tokens):
    return [(m.pattern, "".join(t.surface for t in tokens[m.start:m.end])) for m in find_grammar(tokens)]


VERB, PARTICLE, AUX = "動詞 / 一般", "助詞 / 接続助詞", "助動詞"


def test_every_pattern_is_valid_data_with_forms_and_meaning():
    patterns = load_patterns()
    assert len(patterns) >= 30
    assert all(p.forms and p.meaning and p.alternatives for p in patterns)


def test_te_shimau_full_and_contracted():
    full = [tok("食べ", VERB, "食べる"), tok("て", PARTICLE), tok("しまっ", "動詞 / 非自立可能", "しまう"), tok("た", AUX)]
    assert notes(full) == [("te-shimau", "てしまっ")]
    assert notes([tok("食べ", VERB, "食べる"), tok("ちゃっ", AUX, "ちゃう"), tok("た", AUX)]) == [("te-shimau", "ちゃっ")]


def test_longest_match_at_a_start_and_nested_matches_dropped():
    temoii = [tok("もらっ", VERB, "もらう"), tok("て", PARTICLE), tok("も", "助詞 / 係助詞"), tok("いい", "形容詞", "いい")]
    assert notes(temoii) == [("te-mo-ii", "てもいい")]
    must = [tok("行か", VERB, "行く"), tok("なけれ", AUX, "ない", "仮定形-一般"), tok("ば", PARTICLE),
            tok("なら", VERB, "なる"), tok("ない", AUX, "ない")]
    assert notes(must) == [("must", "なければならない")]  # the ば inside is not reported again


def test_sou_da_appearance_and_hearsay_are_told_apart_by_pos():
    looks = [tok("降り", VERB, "降る"), tok("そう", "形状詞 / 助動詞語幹"), tok("だ", AUX)]
    heard = [tok("降る", VERB, "降る"), tok("そう", "名詞 / 助動詞語幹"), tok("だ", AUX)]
    assert notes(looks) == [("sou-appearance", "そう")]
    assert notes(heard) == [("sou-hearsay", "そうだ")]


def test_conjecture_uses_conjugation_form():
    assert notes([tok("雨", "名詞"), tok("だろう", AUX, "だ", "意志推量形")]) == [("darou", "だろう")]
    assert notes([tok("雨", "名詞"), tok("だ", AUX, "だ", "終止形-一般")]) == []


def test_pattern_lookup_and_invalid_rules(tmp_path):
    assert pattern_by_id("te-iru").name == "〜ている"
    bad = tmp_path / "grammar.json"
    bad.write_text(json.dumps({"schema_version": 1, "patterns": [
        {"id": "x", "name": "x", "forms": ["x"], "meaning": "x", "alternatives": [[{"colour": ["red"]}]]}]}), encoding="utf-8")
    with pytest.raises(ValueError, match="unknown step field"):
        load_patterns(bad)


def test_api_response_carries_grammar_notes():
    from yomiscan.analysis import AnalyzedToken, TextAnalysisResult
    from yomiscan.api.models import ImageAnalysisResponse
    from yomiscan.grammar_patterns import GrammarMatch
    tokens = tuple(AnalyzedToken(t, None, ()) for t in (tok("見", VERB, "見る"), tok("て", PARTICLE), tok("いる", "動詞", "いる")))
    result = TextAnalysisResult("見ている", tokens, {}, grammar=(GrammarMatch("te-iru", 1, 3),))
    grammar = ImageAnalysisResponse.from_analysis(result).model_dump()["grammar"]
    assert grammar == [{"id": "te-iru", "name": "〜ている", "meaning": pattern_by_id("te-iru").meaning,
                        "start_token": 1, "end_token": 3}]


def test_te_patterns_need_a_preceding_verb_adjective_or_auxiliary():
    # 僕でも ("even me"): で after a noun is not the connective て, so not 〜ても.
    assert notes([tok("僕", "代名詞"), tok("で", "助詞 / 格助詞"), tok("も", "助詞 / 係助詞")]) == []
    assert notes([tok("行っ", VERB, "行く"), tok("て", PARTICLE), tok("も", "助詞 / 係助詞")]) == [("te-mo", "ても")]
