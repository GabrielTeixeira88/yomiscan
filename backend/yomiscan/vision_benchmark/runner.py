"""Runs selected real engines; inference is opt-in through dedicated scripts only."""

from contextlib import contextmanager
from collections.abc import Callable
from dataclasses import asdict
import json
from pathlib import Path
from time import perf_counter
from typing import Any, Iterator
import unicodedata
from PIL import Image

from ..analysis import TextAnalyzer
from ..detection import BoundingBox, TextRegion, TextDetector
from ..ocr import OCREngine, OCRRecognitionError
from .corpus import PageCase
from .metrics import coverage, detection_metrics, transcription_metrics, latency_summary, confidence_calibration
from .runtime import environment, MemoryMeasurement
from .suppression import suppress_regions


def normalize_reference(text: str) -> str:
    return "".join(unicodedata.normalize("NFKC", text).split())


@contextmanager
def pipeline_resources(threads: int) -> Iterator[tuple[OCREngine, TextAnalyzer]]:
    import torch
    from ..analysis import TextAnalyzer
    from ..dictionary import SQLiteDictionary
    from ..nlp import FugashiTokenizer
    from ..ocr.factory import create_ocr_engine
    from ..translation.factory import create_translation_engine
    torch.set_num_threads(threads)
    with SQLiteDictionary(Path("data/jmdict.sqlite3")) as dictionary:
        ocr = translator = None
        try:
            ocr = create_ocr_engine("current", device="cpu", threads=threads, pinned=True)
            translator = create_translation_engine("current", device="cpu")
            yield ocr, TextAnalyzer(FugashiTokenizer(), dictionary, translator)
        finally:
            for component in (ocr, translator):
                close = getattr(component, "close", None)
                if close is not None:
                    close()


def pipeline_page(image: Image.Image, regions: list[TextRegion], case: PageCase, ocr: OCREngine, analyzer: TextAnalyzer) -> dict[str, Any]:
    from ..page import PageAnalysisService
    from ..rendering import ConservativePageRenderer
    from ..rendering.service import PageTranslationRenderService
    from ..diagnostics import page_snapshot
    class RecordedDetector:
        def detect(self, image: Image.Image) -> list[TextRegion]:
            return regions
    service = PageTranslationRenderService(PageAnalysisService(RecordedDetector(), ocr, analyzer), ConservativePageRenderer())
    result = service.translate_and_render_page(image)
    snapshot = page_snapshot(image, result, input_sha256=case.sha256)
    outcomes = {}
    for target in case.regions or []:
        if target["category"] != "dialogue":
            continue
        detected = any(coverage(r.bbox, target["bbox"]) >= .5 for r in regions)
        matching = [b for b in snapshot["blocks"] if coverage(BoundingBox(**b["bbox"]), target["bbox"]) >= .5]
        if not detected:
            outcome = "not_detected"
        elif not matching:
            outcome = "detected_but_filtered"
        else:
            block = max(matching, key=lambda b: coverage(BoundingBox(**b["bbox"]), target["bbox"]))
            merged = sum(coverage(BoundingBox(**block["bbox"]), g["bbox"]) >= .5 for g in case.regions or [] if g["category"] == "dialogue") > 1
            if merged:
                outcome = "incorrectly_grouped"
            elif block["ocr"]["status"] != "success":
                outcome = "ocr_failed_or_filtered"
            elif block["translation"]["status"] != "success":
                outcome = "translation_failed"
            else:
                outcome = "rendered" if block["render"]["status"] == "rendered" else "translation_succeeded_render_preserved"
        outcomes[target["id"]] = outcome
    # This local JSON contains text; the shareable Markdown report only cites aggregate results.
    return {"snapshot": snapshot, "dialogue_outcomes": outcomes,
            "ocr_success": sum(b["ocr"]["status"] == "success" for b in snapshot["blocks"]),
            "translation_available": sum(b["translation"]["status"] == "success" for b in snapshot["blocks"])}


def evaluate_detection(cases: list[PageCase], factory: Callable[[], TextDetector], *, repeats: int = 3, warmup: int = 1,
                       pipeline: bool = False, threads: int = 4, suppression: str = "none") -> dict[str, Any]:
    memory = MemoryMeasurement(); memory.start()
    engine = None
    try:
        start = perf_counter(); engine = factory(); load_ms = (perf_counter()-start)*1000
        describe = getattr(engine, "diagnostic_metadata", None)
        report: dict[str, Any] = {"schema_version": 1, "environment": environment(), "load_ms": load_ms,
            "model": describe() if callable(describe) else {}, "memory_detector_loaded": memory.snapshot(),
            "repeats": repeats, "warmup": warmup, "threads": threads, "suppression": suppression, "pages": []}
        durations = []
        for case in cases:
            with Image.open(case.image) as source:
                image = source.convert("RGB")
            if case.regions is not None and any(r["bbox"][2] > image.width or r["bbox"][3] > image.height for r in case.regions):
                raise ValueError(f"Annotation exceeds image bounds: {case.id}")
            warm = []
            first_ms = None
            regions = []
            for i in range(warmup+repeats):
                start = perf_counter(); raw = engine.detect(image)
                regions = suppress_regions(raw) if suppression == "coverage" else raw
                elapsed = (perf_counter()-start)*1000
                if i == 0:
                    first_ms = elapsed
                if i >= warmup:
                    warm.append(elapsed); durations.append(elapsed)
            row = {"id": case.id, "sha256": case.sha256, "split": case.split, "width": image.width, "height": image.height,
                "first_ms": first_ms, "warm_ms": warm, "raw_count_before_suppression": len(raw),
                "regions": [asdict(r) for r in regions], "metrics": detection_metrics(regions, case.regions, image.size, exhaustive=case.exhaustive)}
            report["pages"].append(row)
            image.close()
        report["latency"] = latency_summary(durations)
        if pipeline:
            with pipeline_resources(threads) as (ocr, analyzer):
                for case, row in zip(cases, report["pages"], strict=True):
                    with Image.open(case.image) as source:
                        image = source.convert("RGB")
                    regions = [TextRegion(r["id"], BoundingBox(**r["bbox"]), r["confidence"], r["orientation"], metadata=r["metadata"]) for r in row["regions"]]
                    row["pipeline"] = pipeline_page(image, regions, case, ocr, analyzer)
                    image.close()
        report["memory_end"] = memory.snapshot()
        report["status"] = "completed"
        return report
    finally:
        close = getattr(engine, "close", None)
        if close is not None:
            close()
        memory.close()


def ocr_crops(cases: list[PageCase], detector_results: Path | None = None) -> list[dict[str, Any]]:
    detections = json.loads(detector_results.read_text(encoding="utf-8")) if detector_results else None
    crops = []
    for case in cases:
        with Image.open(case.image) as source:
            image = source.convert("RGB")
        regions = case.regions or []
        if detections is not None:
            row = next((r for r in detections["pages"] if r["id"] == case.id), None)
            if row is None or row["sha256"] != case.sha256:
                raise ValueError(f"Detector result missing or stale for {case.id}")
            blocks = row["pipeline"]["snapshot"]["blocks"]
            boxes = [(str(b["id"]), BoundingBox(**b["bbox"]).clipped(*image.size, padding=4)) for b in blocks]
        else:
            boxes = [(r["id"], BoundingBox(*r["bbox"])) for r in regions if r.get("text") is not None]
        for identity, box in boxes:
            linked = [r for r in regions if coverage(box, r["bbox"]) >= .5]
            truth = linked[0] if len(linked) == 1 else None
            reference = truth.get("text") if truth else None
            if detections is not None and truth and coverage(box, truth["bbox"]) < .95:
                reference = None # Incomplete crop cannot be scored against a complete transcription.
            crops.append({"id": f"{case.id}/{identity}", "split": case.split, "image": image.crop(box.coordinates()),
                "reference": reference, "tags": truth.get("tags", []) if truth else [],
                "category": truth["category"] if truth else "unmatched_or_merged", "bbox": list(box.coordinates())})
        image.close()
    if not crops:
        raise ValueError("No annotated OCR crops; supply known text or detector results")
    return crops


def evaluate_ocr(crops: list[dict[str, Any]], factory: Callable[[], OCREngine], *, repeats: int = 3, warmup: int = 1) -> dict[str, Any]:
    memory = MemoryMeasurement(); memory.start()
    engine = None
    try:
        start = perf_counter(); engine = factory(); load_ms = (perf_counter()-start)*1000
        report: dict[str, Any] = {"schema_version": 1, "environment": environment(), "load_ms": load_ms,
            "memory_loaded": memory.snapshot(), "repeats": repeats, "warmup": warmup, "rows": []}
        warm_times = []
        for crop in crops:
            row = {key: value for key, value in crop.items() if key != "image"}
            elapsed_runs, outputs = [], []
            try:
                for i in range(warmup+repeats):
                    start = perf_counter(); result = engine.recognize(crop["image"])
                    elapsed = (perf_counter()-start)*1000
                    if i >= warmup:
                        elapsed_runs.append(elapsed); warm_times.append(elapsed); outputs.append(result.text)
                row.update(status="success", output=outputs[0], run_outputs=outputs, warm_ms=elapsed_runs,
                    confidence=result.metadata.get("confidence"), confidence_method=result.metadata.get("confidence_method"),
                    termination=result.metadata.get("termination"), metadata=result.metadata)
            except OCRRecognitionError as exc:
                row.update(status="error", output="", error_code="token_limit" if "token_limit" in str(exc) else "recognition_failed",
                           error=str(exc), confidence=None, warm_ms=elapsed_runs)
            row["strict"] = transcription_metrics(crop["reference"], row["output"])
            row["normalized"] = transcription_metrics(normalize_reference(crop["reference"]) if crop["reference"] is not None else None,
                                                       normalize_reference(row["output"]))
            report["rows"].append(row)
        report["latency"] = latency_summary(warm_times)
        report["calibration"] = confidence_calibration(report["rows"])
        describe = getattr(engine, "diagnostic_metadata", None)
        report["model"] = describe() if callable(describe) else {"model": None, "revision": None}
        report["memory_end"] = memory.snapshot()
        report["status"] = "completed"
        return report
    finally:
        close = getattr(engine, "close", None)
        if close is not None:
            close()
        for crop in crops:
            crop["image"].close()
        memory.close()
