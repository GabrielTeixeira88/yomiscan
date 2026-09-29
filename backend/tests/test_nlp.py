import pytest

from yomiscan.nlp import FugashiTokenizer, JapaneseTokenizer


@pytest.fixture(scope="module")
def tokenizer() -> JapaneseTokenizer:
    return FugashiTokenizer()


def test_reading_and_surface_order(tokenizer):
    text = "でも大丈夫。"
    tokens = tokenizer.tokenize(text)
    assert "".join(t.surface for t in tokens) == text
    word = next(t for t in tokens if t.surface == "大丈夫")
    assert word.reading == "だいじょうぶ"
    assert word.lemma == "大丈夫"
    assert word.part_of_speech


@pytest.mark.parametrize("text,lemma", [("食べました", "食べる"), ("高かった", "高い")])
def test_inflected_base(tokenizer, text, lemma):
    token = tokenizer.tokenize(text)[0]
    assert token.orthographic_base == lemma
    assert token.lemma == lemma
    assert token.conjugation_type and token.conjugation_form


@pytest.mark.parametrize("text", ["", "  \n\t"])
def test_empty(tokenizer, text):
    assert tokenizer.tokenize(text) == []


def test_unknown_and_punctuation(tokenizer):
    tokens = tokenizer.tokenize("YomiScan。")
    assert tokens[0].surface == "YomiScan"
    assert tokens[0].lemma is None
    assert tokens[0].reading is None
    assert tokens[-1].surface == "。"
    assert tokens[-1].reading is None
