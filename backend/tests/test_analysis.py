from unittest.mock import Mock

from PIL import Image

from yomiscan.analysis import TextAnalyzer, analyze_image, lookup_candidates
from yomiscan.dictionary import SQLiteDictionary
from yomiscan.nlp import FugashiTokenizer, JapaneseToken
from yomiscan.ocr import OCRResult
from yomiscan.translation import TranslationResult, TranslationError
import pytest


def test_real_tokenizer_normalized_lookup(dictionary_path):
    with SQLiteDictionary(dictionary_path) as dictionary:
        analyzer = TextAnalyzer(FugashiTokenizer(), dictionary)
        result = analyzer.analyze("食べました。高かった。猫、YomiScan")
        assert result.tokens[0].lookup_form == "食べる"
        assert result.dictionary_entries[result.tokens[0].entry_ids[0]].senses[0].glosses == ("to eat",)
        assert any(t.lookup_form == "高い" for t in result.tokens)
        assert all(not t.entry_ids for t in result.tokens if t.token.surface in ("。", "、", "YomiScan"))
        assert analyzer.analyze("").tokens == ()


def test_lookup_candidates_do_not_use_inflected_reading():
    token = JapaneseToken("食べ", "食べる", "たべ", orthographic_base="食べる", lemma_reading="たべる")
    assert lookup_candidates(token) == ("食べる", "食べ", "たべる")
    assert lookup_candidates(JapaneseToken("。", "。")) == ()
    assert lookup_candidates(JapaneseToken("アイス", "アイス-ice", orthographic_base="アイス"))[0] == "アイス"


def test_deduplicates_entries_and_queries(dictionary_path):
    with SQLiteDictionary(dictionary_path) as dictionary:
        wrapped = Mock(wraps=dictionary)
        result = TextAnalyzer(FugashiTokenizer(), wrapped).analyze("猫 猫")
        assert len(result.tokens) == 2
        assert len(result.dictionary_entries) == 1
        wrapped.lookup.assert_called_once_with("猫")


def test_combined_pipeline_with_mock_ocr(dictionary_path):
    ocr = Mock()
    ocr.recognize.return_value = OCRResult("大丈夫", "fake", 1.0)
    with SQLiteDictionary(dictionary_path) as dictionary, Image.new("RGB", (8, 8)) as image:
        result = analyze_image(image, ocr, TextAnalyzer(FugashiTokenizer(), dictionary))
        ocr.recognize.assert_called_once_with(image)
    assert result.analysis.original_text == "大丈夫"
    assert result.analysis.tokens[0].entry_ids == (4,)
    assert result.ocr.engine == "fake"


def test_translation_is_once_per_region_and_separate_from_dictionary(dictionary_path):
    translator = Mock()
    translator.translate.return_value = TranslationResult("でも大丈夫", "But it's okay.", "fake", "fake", 7)
    with SQLiteDictionary(dictionary_path) as dictionary:
        analyzer = TextAnalyzer(FugashiTokenizer(), dictionary, translator)
        result = analyzer.analyze("でも大丈夫")
        translator.translate.assert_called_once_with("でも大丈夫")
        assert result.translation.translated_text == "But it's okay."
        assert result.dictionary_entries[4].senses[0].glosses == ("okay",)
        assert result.processing_time_ms >= 0
        assert analyzer.analyze(" \n").translation is None
        translator.translate.assert_called_once()
        translator.translate.side_effect = TranslationError("failed")
        with pytest.raises(TranslationError):
            analyzer.analyze("猫")
