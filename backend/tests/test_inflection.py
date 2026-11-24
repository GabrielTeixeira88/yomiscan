"""Inflection labels on synthetic UniDic-shaped tokens (shapes mirror real fugashi output)."""

import json

import pytest

from yomiscan.inflection import inflection_labels, load_rules
from yomiscan.nlp import JapaneseToken


def tok(surface, pos, base=None, form=None):
    return JapaneseToken(surface=surface, lemma=base or surface, part_of_speech=pos,
                         orthographic_base=base or surface, conjugation_form=form)


VERB, AUX, ADJ = "動詞 / 一般", "助動詞", "形容詞 / 一般"


def labels(tokens):
    return [(t.surface, list(l)) for t, l in zip(tokens, inflection_labels(tokens)) if l]


def test_negative_past_on_the_head_only():
    tokens = [tok("食べ", VERB, "食べる", "未然形-一般"), tok("なかっ", AUX, "ない"), tok("た", AUX, "た")]
    assert labels(tokens) == [("食べ", ["negative", "past"])]


def test_polite_negative_past_continues_through_desu():
    tokens = [tok("行き", VERB, "行く"), tok("ませ", AUX, "ます"), tok("ん", AUX, "ん"), tok("でし", AUX, "です"), tok("た", AUX, "た")]
    assert labels(tokens) == [("行き", ["polite", "negative", "past"])]


def test_adjective_nai_is_followed_and_not_labelled_twice():
    tokens = [tok("高く", ADJ, "高い"), tok("なかっ", ADJ, "ない"), tok("た", AUX, "た")]
    assert labels(tokens) == [("高く", ["negative", "past"])]


def test_own_form_and_te_form_closing_the_word():
    assert labels([tok("待て", VERB, "待つ", "命令形")]) == [("待て", ["imperative"])]
    tokens = [tok("見", VERB, "見る"), tok("て", "助詞 / 接続助詞"), tok("いる", VERB, "いる")]
    assert labels(tokens) == [("見", ["te-form"])]  # いる is its own word (and a grammar note)


def test_unknown_auxiliary_ends_the_word():
    tokens = [tok("来る", VERB, "来る"), tok("だ", AUX, "だ")]
    assert labels(tokens) == []


def test_rules_need_a_label_and_a_field(tmp_path):
    assert load_rules().heads == frozenset({"動詞", "形容詞"})
    bad = tmp_path / "inflections.json"
    bad.write_text(json.dumps({"schema_version": 1, "own_forms": [{"label": "x"}], "followers": [],
                               "follower_pos": [], "follower_particles": [], "heads": []}), encoding="utf-8")
    with pytest.raises(ValueError, match="label and at least one match field"):
        load_rules(bad)
