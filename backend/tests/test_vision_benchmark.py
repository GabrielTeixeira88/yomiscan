from PIL import Image
from yomiscan.detection import BoundingBox, TextRegion


def test_detection_evaluation_separates_misses_merges_duplicates_and_crop_coverage():
    from yomiscan.vision_benchmark.metrics import detection_metrics
    truth = [{"id": "one", "bbox": [10, 10, 30, 40], "category": "dialogue"},
             {"id": "two", "bbox": [60, 10, 80, 40], "category": "dialogue"},
             {"id": "miss", "bbox": [10, 70, 30, 90], "category": "dialogue"}]
    predictions = [TextRegion(1, BoundingBox(9, 9, 81, 41)),
                   TextRegion(2, BoundingBox(10, 10, 30, 40)),
                   TextRegion(3, BoundingBox(90, 80, 99, 99))]
    result = detection_metrics(predictions, truth, (100, 100), exhaustive=True)
    assert result["dialogue_found"] == 2
    assert result["missed_dialogue"] == 1
    assert result["merged_predictions"] == 1
    assert result["duplicate_predictions"] == 1
    assert result["false_positive_predictions"] == 1


def test_ocr_metrics_count_omissions_insertions_and_do_not_turn_missing_truth_into_accuracy():
    from yomiscan.vision_benchmark.metrics import transcription_metrics
    result = transcription_metrics("猫がいる", "猫いるよ")
    assert result["reference_characters"] == 4
    assert result["deletions"] == 1
    assert result["insertions"] == 1
    assert result["cer"] == .5
    assert result["exact"] is False
    assert transcription_metrics(None, "猫") is None


def test_summary_keeps_failed_reads_in_error_rate_and_does_not_claim_unlabelled_accuracy():
    from yomiscan.vision_benchmark.summary import summarize
    report = {"kind": "ocr", "engine": "fake", "status": "completed", "rows": [
        {"split": "held_out", "status": "success", "strict": {"reference_characters": 2, "substitutions": 0,
          "deletions": 0, "insertions": 0, "exact": True}, "normalized": {"reference_characters": 2,
          "substitutions": 0, "deletions": 0, "insertions": 0, "exact": True}, "output": "猫犬"},
        {"split": "held_out", "status": "error", "strict": {"reference_characters": 2, "substitutions": 0,
          "deletions": 2, "insertions": 0, "exact": False}, "normalized": {"reference_characters": 2,
          "substitutions": 0, "deletions": 2, "insertions": 0, "exact": False}, "output": ""},
        {"split": "held_out", "status": "success", "strict": None, "normalized": None, "output": "unknown"}]}
    summary = summarize(report)
    assert summary["accuracy"]["normalized"]["cer"] == .5
    assert summary["accuracy"]["normalized"]["exact_rate"] == .5
    assert summary["accuracy"]["normalized"]["valid_references"] == 2
    assert summary["failed_reads"] == 1


def test_experimental_suppression_preserves_unknown_classes_and_never_joins_neighbors():
    from yomiscan.vision_benchmark.suppression import suppress_regions
    unknown = [TextRegion(1, BoundingBox(0, 0, 30, 50)), TextRegion(2, BoundingBox(0, 0, 30, 50))]
    neighbors = [TextRegion(3, BoundingBox(40, 0, 60, 50), metadata={"class": "text_bubble"}),
                 TextRegion(4, BoundingBox(65, 0, 85, 50), metadata={"class": "text_bubble"})]
    assert len(suppress_regions(unknown + neighbors)) == 4


def test_detection_runner_accepts_the_existing_detector_protocol_and_serializes_results(tmp_path):
    import json
    from yomiscan.vision_benchmark.corpus import PageCase
    from yomiscan.vision_benchmark.runner import evaluate_detection
    source = tmp_path / "page.png"
    Image.new("RGB", (100, 100), "white").save(source)
    class Detector:
        def detect(self, image):
            return [TextRegion(1, BoundingBox(10, 10, 30, 40))]
    case = PageCase("synthetic", source, "fixture", "held_out", [
        {"id": "dialogue", "bbox": [10, 10, 30, 40], "category": "dialogue"}], True)
    report = evaluate_detection([case], Detector, repeats=1)
    assert report["pages"][0]["metrics"]["dialogue_found"] == 1
    assert report["latency"]["samples"] == 1
    assert json.loads(json.dumps(report))["model"] == {}


def test_ocr_runner_exposes_confident_errors_and_correct_low_confidence_without_filtering():
    from yomiscan.ocr import OCRResult
    from yomiscan.vision_benchmark.runner import evaluate_ocr
    class OCR:
        def recognize(self, image):
            return OCRResult("犬", "fixture", 1, {"confidence": .99 if image.getpixel((0, 0))[0] == 0 else .2})
    crops = [{"id": "wrong", "image": Image.new("RGB", (2, 2), "black"), "reference": "猫", "split": "held_out"},
             {"id": "correct", "image": Image.new("RGB", (2, 2), "white"), "reference": "犬", "split": "held_out"}]
    report = evaluate_ocr(crops, OCR, repeats=1)
    threshold = next(r for r in report["calibration"]["thresholds"] if r["threshold"] == .85)
    assert threshold["incorrect_high_confidence"] == 1
    assert threshold["correct_low_confidence"] == 1
    assert threshold["precision"] == threshold["recall"] == 0
    assert all(r["status"] == "success" for r in report["rows"])
    assert report["model"]["revision"] is None


def test_corpus_fingerprint_prevents_scoring_annotations_for_replaced_pixels(tmp_path):
    import json
    import pytest
    from hashlib import sha256
    from yomiscan.vision_benchmark.corpus import load_corpus
    source = tmp_path / "page.png"
    Image.new("RGB", (20, 20), "white").save(source)
    manifest = tmp_path / "corpus.json"
    manifest.write_text(json.dumps({"schema_version": 1, "pages": [{"id": "one", "image": "page.png",
        "sha256": sha256(source.read_bytes()).hexdigest(), "split": "held_out", "regions": None}]}), encoding="utf-8")
    assert load_corpus(manifest)[0].regions is None
    Image.new("RGB", (20, 20), "black").save(source)
    with pytest.raises(ValueError, match="fingerprint"):
        load_corpus(manifest)
