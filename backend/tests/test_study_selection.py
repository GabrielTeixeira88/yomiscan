"""Study selections read every detected text block; no model weights are loaded."""

from unittest.mock import Mock

from PIL import Image
import pytest

from yomiscan.analysis import TextAnalyzer
from yomiscan.api.models import ImageAnalysisResponse
from yomiscan.detection import BoundingBox, DetectionError, TextRegion
from yomiscan.ocr import OCRRecognitionError, OCRResult
from yomiscan.service import ImageAnalysisService, study_detection_setting
from yomiscan.translation import TranslationResult


def block(region_id: int, box: tuple[int, int, int, int]) -> TextRegion:
    return TextRegion(region_id, BoundingBox(*box), .9, metadata={"class": "text_bubble", "granularity": "block"})


def make_service(regions, *, texts=None, detection="auto", detector=True):
    """A service with fake engines. OCR returns texts by crop width, or the whole-selection text."""
    detector_engine = Mock()
    detector_engine.detect.return_value = regions
    by_width = texts or {}
    ocr = Mock()
    ocr.recognize.side_effect = lambda image: OCRResult(by_width.get(image.width, "全体"), "fake-ocr", 2.0)
    tokenizer, dictionary, translator = Mock(), Mock(), Mock()
    tokenizer.tokenize.return_value = []
    translator.translate.side_effect = lambda text: TranslationResult(text, f"EN:{text}", "fake", "fake", 5)
    translator.translate_many.side_effect = lambda values: [
        TranslationResult(text, f"EN:{text}", "fake", "fake", 7) for text in values]
    service = ImageAnalysisService(ocr, TextAnalyzer(tokenizer, dictionary, translator),
                                   detector=detector_engine if detector else None, study_detection=detection)
    return service, detector_engine, ocr, translator


SELECTION = Image.new("RGB", (200, 100), "white")
# Right bubble is read first (manga order); crop widths identify which block was OCR'd.
TWO_BUBBLES = [block(1, (10, 10, 50, 90)), block(2, (120, 10, 180, 90))]


def test_two_detected_blocks_are_read_separately_in_reading_order():
    service, _, ocr, translator = make_service(TWO_BUBBLES, texts={48: "左よ", 68: "右だ"})
    result = service.analyze_image(SELECTION)
    assert result.ocr.text == "右だ\n左よ"
    assert [call.args[0].width for call in ocr.recognize.call_args_list] == [68, 48]
    translator.translate_many.assert_called_once_with(["右だ", "左よ"])
    assert result.analysis.translation.translated_text == "EN:右だ\nEN:左よ"
    assert result.analysis.translation.metadata["segments"] == 2
    assert result.ocr.metadata["study_ocr"] == {"mode": "blocks", "blocks": 2}
    response = ImageAnalysisResponse.from_result(result, 10)
    assert response.provenance["study_ocr"] == {"mode": "blocks", "blocks": 2}
    assert response.original_text == "右だ\n左よ"


def test_single_detected_block_keeps_whole_selection_reading():
    service, _, ocr, _ = make_service([block(1, (10, 10, 50, 90))])
    result = service.analyze_image(SELECTION)
    ocr.recognize.assert_called_once()
    assert ocr.recognize.call_args.args[0].size == SELECTION.size
    assert result.ocr.text == "全体"
    assert result.ocr.metadata["study_ocr"] == {"mode": "selection", "blocks": 1}


def test_disabled_detection_never_calls_the_detector():
    service, detector, _, _ = make_service(TWO_BUBBLES, detection="off")
    result = service.analyze_image(SELECTION)
    detector.detect.assert_not_called()
    assert result.ocr.metadata["study_ocr"] == {"mode": "selection", "blocks": 0, "reason": "disabled"}


def test_unprepared_detector_falls_back_once_without_retrying(monkeypatch):
    from yomiscan import readiness
    calls = []
    def unavailable(environment, kinds=()):
        calls.append(kinds)
        raise readiness.SetupUnavailable("missing_detection")
    monkeypatch.setattr(readiness, "require_local_models", unavailable)
    service, _, ocr, _ = make_service(TWO_BUBBLES, detector=False)
    first = service.analyze_image(SELECTION)
    second = service.analyze_image(SELECTION)
    assert calls == [("detection",)]
    assert first.ocr.metadata["study_ocr"]["reason"] == "detector_unavailable"
    assert second.ocr.text == "全体"
    assert ocr.recognize.call_count == 2


def test_detection_failure_reads_the_whole_selection():
    service, detector, _, _ = make_service(TWO_BUBBLES)
    detector.detect.side_effect = DetectionError("boom")
    result = service.analyze_image(SELECTION)
    assert result.ocr.text == "全体"
    assert result.ocr.metadata["study_ocr"]["reason"] == "detection_failed"


def test_non_japanese_blocks_fall_back_to_the_whole_selection():
    service, _, _, _ = make_service(TWO_BUBBLES, texts={48: "ABC", 68: "123"})
    result = service.analyze_image(SELECTION)
    assert result.ocr.text == "全体"
    assert result.ocr.metadata["study_ocr"] == {"mode": "selection", "blocks": 2, "reason": "no_japanese_blocks"}


def test_one_failed_block_keeps_the_readable_block():
    service, _, ocr, _ = make_service(TWO_BUBBLES)
    def recognize(image):
        if image.width == 68:
            raise OCRRecognitionError("private detail")
        return OCRResult("左よ", "fake-ocr", 2.0)
    ocr.recognize.side_effect = recognize
    result = service.analyze_image(SELECTION)
    assert result.ocr.text == "左よ"
    assert result.ocr.metadata["study_ocr"] == {"mode": "blocks", "blocks": 1}


@pytest.mark.parametrize("value,expected", [(None, "auto"), ("auto", "auto"), ("off", "off")])
def test_study_detection_setting(value, expected):
    environment = {} if value is None else {"YOMISCAN_STUDY_DETECTION": value}
    assert study_detection_setting(environment) == expected


def test_study_detection_setting_rejects_unknown_values():
    with pytest.raises(ValueError):
        study_detection_setting({"YOMISCAN_STUDY_DETECTION": "always"})
    with pytest.raises(ValueError):
        make_service([], detection="always")
