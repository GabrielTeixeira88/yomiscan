"""Dictionary-form readings for saved words (Stage 6). The cases are shared with the browser engine."""

import json
from pathlib import Path

import pytest

from yomiscan.analysis import AnalyzedToken, TextAnalysisResult
from yomiscan.api.models import ImageAnalysisResponse
from yomiscan.dictionary import DictionaryEntry, DictionaryReading, DictionarySense
from yomiscan.headword import dictionary_reading
from yomiscan.lexical_units import LexicalUnit
from yomiscan.nlp import JapaneseToken

CASES = json.loads((Path(__file__).parent / "headword_cases.json").read_text(encoding="utf-8"))


def entry(key: str, entry_id: int = 1) -> DictionaryEntry:
    data = CASES["entries"][key]
    return DictionaryEntry(entry_id, tuple(data["spellings"]),
                           tuple(DictionaryReading(r["text"], tuple(r["spellings"]), r["no_kanji"]) for r in data["readings"]),
                           (DictionarySense(("gloss",), ("noun",)),))


@pytest.mark.parametrize("case", CASES["cases"], ids=[case["name"] for case in CASES["cases"]])
def test_shared_cases(case: dict) -> None:
    found = entry(case["entry"]) if case["entry"] else None
    assert dictionary_reading(case["form"], found, case["hints"]) == case["expected"]


def test_responses_carry_the_dictionary_reading_of_tokens_and_units() -> None:
    tabeta = JapaneseToken(surface="食べ", lemma="食べる", reading="たべ", orthographic_base="食べる", lemma_reading="たべる")
    ta = JapaneseToken(surface="た", lemma="た", reading="た")
    kamo = JapaneseToken(surface="かも", lemma="かも", reading="かも")
    entries = {1: entry("taberu", 1)}
    analysis = TextAnalysisResult(
        original_text="食べたかも",
        tokens=(AnalyzedToken(tabeta, "食べる", (1,)), AnalyzedToken(ta, None, ()), AnalyzedToken(kamo, "かも", ())),
        dictionary_entries=entries,
        units=(LexicalUnit(1, 3, "たかも", "たかも", ()),),
    )
    response = ImageAnalysisResponse.from_analysis(analysis)
    assert [t.dictionary_reading for t in response.tokens] == ["たべる", "た", "かも"]
    assert response.units[0].dictionary_reading == "たかも"
    assert "dictionary_reading" in response.model_dump()["tokens"][0]
