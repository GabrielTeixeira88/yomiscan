from contextlib import contextmanager
from io import BytesIO
from unittest.mock import Mock

from fastapi.testclient import TestClient
from PIL import Image
import pytest

from yomiscan.analysis import TextAnalyzer
from yomiscan.api.main import create_app
from yomiscan.detection import BoundingBox as Box, TextRegion, DetectionError, DetectionInitializationError
from yomiscan.detection.rtdetr import decode_regions
from yomiscan.japanese import contains_japanese, is_japanese_punctuation
from yomiscan.ocr import OCRResult, OCRRecognitionError
from yomiscan.page import PageAnalysisService, PageConfig
from yomiscan.page_layout import group_regions, reading_order
from yomiscan.service import ImageAnalysisService
from yomiscan.translation import TranslationResult, TranslationError
from yomiscan.page_cli import main, draw_regions


def region(i, box, orientation="unknown", granularity="block"):
    return TextRegion(i, Box(*box), .9, orientation, metadata={"granularity": granularity})


@pytest.mark.parametrize("text,expected", [
    ("123 大丈夫!?", True), ("ﾄﾞﾝ", True), ("ゴゴゴ", True), ("あ", True),
    ("𠮷", True), ("ABC 123", False), ("！？…", False), ("", False),
])
def test_japanese_validation(text, expected):
    assert contains_japanese(text) is expected
    assert is_japanese_punctuation("。")
    assert not is_japanese_punctuation("A")


def test_detector_decode_maps_clips_filters_and_orders():
    found = decode_regions([[90, 10, 110, 30], [-2, 10, 20, 30], [0, 0, 100, 100],
                            [200, 0, 300, 20], [float("nan"), 0, 3, 4]],
                           [.8, .7, .99, .9, .9], [2, 1, 0, 1, 1], (100, 100))
    assert [r.bbox for r in found] == [Box(90, 10, 100, 30), Box(0, 10, 20, 30)]
    assert [r.id for r in found] == [1, 2]


def test_grouping_only_close_aligned_lines_and_stable_reading_order():
    a, b = region(1, (80, 0, 90, 100), "vertical", "line"), region(2, (66, 0, 76, 100), "vertical", "line")
    distant = region(3, (20, 0, 30, 100), "vertical", "line")
    groups = reading_order(group_regions([distant, b, a]))
    assert [len(g.regions) for g in groups] == [2, 1]
    assert groups[0].bbox == Box(66, 0, 90, 100)
    assert len(group_regions([region(1, (80, 0, 90, 100)), region(2, (66, 0, 76, 100))])) == 2
    horizontal = [region(4, (0, 200, 100, 210), "horizontal", "line"),
                  region(5, (0, 214, 100, 224), "horizontal", "line")]
    assert len(group_regions(horizontal)) == 1


def resources(regions):
    detector, ocr, tokenizer, dictionary, translator = (Mock() for _ in range(5))
    detector.detect.return_value = regions
    ocr.recognize.return_value = OCRResult("大丈夫", "fake", 1)
    tokenizer.tokenize.return_value = []
    translator.translate_many.side_effect = lambda texts: [TranslationResult(t, "Okay", "fake", "fake", 5) for t in texts]
    analyzer = TextAnalyzer(tokenizer, dictionary, translator)
    return detector, ocr, translator, analyzer


def test_page_clipping_padding_filtering_batching_and_failure_isolation():
    detector, ocr, translator, analyzer = resources([
        region(3, (1, 60, 40, 98)), region(2, (0, 0, 20, 40)),
        region(1, (70, 0, 105, 40)), region(4, (0, 0, 1, 1)),
    ])
    sizes = []
    def recognize(image):
        sizes.append(image.size)
        if len(sizes) == 2:
            raise OCRRecognitionError("private path")
        return OCRResult("大丈夫", "fake", 1)
    ocr.recognize.side_effect = recognize
    result = PageAnalysisService(detector, ocr, analyzer).analyze_page(Image.new("RGB", (100, 100)))
    assert sizes[0] == (34, 44)
    assert [b.region_ids for b in result.text_blocks] == [(1,), (2,), (3,)]
    assert [b.status for b in result.text_blocks] == ["success", "error", "success"]
    assert "private" not in result.text_blocks[1].error_message
    assert 4 in result.filtered_regions
    translator.translate_many.assert_called_once_with(["大丈夫", "大丈夫"])
    translator.translate.assert_not_called()


def test_non_japanese_and_empty_page_do_not_translate():
    detector, ocr, translator, analyzer = resources([region(1, (0, 0, 20, 40))])
    ocr.recognize.return_value = OCRResult("123!?", "fake", 1)
    service = PageAnalysisService(detector, ocr, analyzer)
    assert service.analyze_page(Image.new("RGB", (100, 100))).text_blocks[0].status == "filtered"
    detector.detect.return_value = []
    assert service.analyze_page(Image.new("RGB", (100, 100))).text_blocks == ()
    translator.translate_many.assert_not_called()


def test_failed_translation_batch_retries_individually():
    _, _, translator, analyzer = resources([])
    translator.translate_many.side_effect = TranslationError("batch failed")
    translator.translate.side_effect = [TranslationResult("あ", "Ah", "fake", "fake", 1), TranslationError("bad block")]
    results = analyzer.analyze_many(["あ", "い"])
    assert results[0].translation.translated_text == "Ah"
    assert isinstance(results[1], TranslationError)


@pytest.fixture
def page_api():
    detector, ocr, translator, analyzer = resources([region(1, (0, 0, 10, 10))])
    @contextmanager
    def factory():
        yield ImageAnalysisService(ocr, analyzer, detector=detector)
    with TestClient(create_app(factory), base_url="http://127.0.0.1",
                    headers={"X-YomiScan-Client": "study-extension-v1"}) as client:
        yield client, detector, ocr


def upload(client, data=None):
    if data is None:
        buffer = BytesIO()
        Image.new("RGB", (50, 50)).save(buffer, format="PNG")
        data = buffer.getvalue()
    return client.post("/api/v1/analyze-page", files={"file": ("page.png", data)})


def test_page_api_serialization_reuse_and_no_regions(page_api):
    client, detector, _ = page_api
    for _ in range(2):
        response = upload(client)
        assert response.status_code == 200
        data = response.json()
        assert data["width"] == 50
        assert data["regions_detected"] == 1
        assert data["text_blocks"][0]["translation"] == "Okay"
        assert data["text_blocks"][0]["bbox"]["right"] == 10
        assert "regions" not in data
    assert detector.detect.call_count == 2
    detector.detect.return_value = []
    assert upload(client).json()["text_blocks"] == []


@pytest.mark.parametrize("data", [b"", b"garbage"])
def test_page_api_invalid(page_api, data):
    client, detector, _ = page_api
    assert upload(client, data).status_code == 400
    detector.detect.assert_not_called()


@pytest.mark.parametrize("error,status", [(DetectionError("secret"), 500), (DetectionInitializationError("secret"), 503)])
def test_page_api_detector_failure(page_api, error, status):
    client, detector, _ = page_api
    detector.detect.side_effect = error
    response = upload(client)
    assert response.status_code == status
    assert "secret" not in response.text
    assert client.get("/health").status_code == 200


def test_page_api_ocr_failure_is_a_block_error(page_api):
    client, _, ocr = page_api
    ocr.recognize.side_effect = OCRRecognitionError("secret")
    response = upload(client)
    assert response.status_code == 200
    assert response.json()["text_blocks"][0]["status"] == "error"
    assert "secret" not in response.text


def test_page_api_order_is_independent_of_detector_input_order(page_api):
    client, detector, _ = page_api
    boxes = [region(2, (0, 0, 10, 20)), region(1, (30, 0, 45, 20))]
    detector.detect.return_value = boxes
    first = upload(client).json()["text_blocks"]
    detector.detect.return_value = boxes[::-1]
    second = upload(client).json()["text_blocks"]
    assert first == second
    assert [block["region_ids"] for block in first] == [[1], [2]]


def test_debug_does_not_modify_input_and_cli_refuses_overwrite(tmp_path):
    source = tmp_path / "source.png"
    image = Image.new("RGB", (50, 50), "white")
    image.save(source)
    before = source.read_bytes()
    output = tmp_path / "debug.png"
    draw_regions(image, [region(1, (5, 5, 40, 40))], output)
    assert output.exists() and source.read_bytes() == before
    with pytest.raises(SystemExit):
        main([str(source), "--output", str(source)], detection_only=True)
    assert main([str(tmp_path / "missing"), "--output", str(output)], detection_only=True) == 2


def test_config_rejects_invalid_sizes():
    with pytest.raises(ValueError):
        PageConfig(padding=-1)
