"""Dedicated opt-in benchmark entry points, separate from application startup and CI."""

import argparse
import json
from pathlib import Path
import sys
from typing import Any

from ..detection import DetectionError, DetectionInitializationError
from ..detection.factory import DETECTOR_NAMES, create_detector
from ..ocr import OCRInitializationError
from ..ocr.factory import OCR_NAMES, create_ocr_engine
from ..vision_models import file_hash, model_directory, MODELS
from .corpus import load_corpus
from .runner import evaluate_detection, evaluate_ocr, ocr_crops


def artifact_metadata(kind: str, engine: str) -> list[dict[str, Any]]:
    if kind == "detection" and engine == "current":
        from huggingface_hub import hf_hub_download
        from ..detection.rtdetr import MODEL_ID, MODEL_REVISION
        files = [Path(hf_hub_download(MODEL_ID, "model.safetensors", revision=MODEL_REVISION, local_files_only=True))]
    else:
        name = "detector" if kind == "detection" else "ocr-onnx" if "onnx" in engine else "ocr-original" if engine in ("current", "original-rgb") else "ocr-2025"
        folder = model_directory(name)
        files = [folder / name for name in MODELS[name].files if name.endswith((".onnx", ".safetensors", ".bin"))]
    return [{"file": path.name, "bytes": path.stat().st_size, "sha256": file_hash(path)} for path in files]


def main(kind: str, argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=f"Opt-in local {kind} benchmark; raw outputs contain private text")
    parser.add_argument("dataset", type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--engine", choices=DETECTOR_NAMES if kind == "detection" else OCR_NAMES, default="current")
    parser.add_argument("--device", choices=("cpu", "cuda"), default="cpu")
    parser.add_argument("--threads", type=int, default=4)
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--warmup", type=int, default=1)
    parser.add_argument("--split", choices=("tune", "held_out", "control"))
    if kind == "detection":
        parser.add_argument("--bubble-threshold", type=float, default=.5)
        parser.add_argument("--free-threshold", type=float, default=.5)
        parser.add_argument("--suppression", choices=("none", "coverage"), default="none")
        parser.add_argument("--pipeline", action="store_true", help="Also run original OCR, OPUS/JMdict and conservative renderer once per page")
    else:
        parser.add_argument("--detector-results", type=Path, help="Use the actual grouped/padded crops of a detection --pipeline report")
    args = parser.parse_args(argv)
    if args.repeats < 1 or args.warmup < 1 or args.threads < 1:
        parser.error("Repeats, warmup and threads must be positive")
    cases = load_corpus(args.dataset, split=args.split)
    protected = {args.dataset.resolve(), *(c.image for c in cases)}
    if getattr(args, "detector_results", None) is not None:
        protected.add(args.detector_results.resolve())
    if args.output.resolve() in protected:
        parser.error("Benchmark output must not overwrite any input image, corpus or detector report")
    try:
        if kind == "detection":
            report = evaluate_detection(cases, lambda: create_detector(args.engine, device=args.device,
                bubble_threshold=args.bubble_threshold, free_threshold=args.free_threshold, threads=args.threads),
                repeats=args.repeats, warmup=args.warmup, pipeline=args.pipeline, threads=args.threads, suppression=args.suppression)
            report["configuration"] = {"bubble_threshold": args.bubble_threshold, "free_threshold": args.free_threshold,
                                       "suppression": args.suppression, "pipeline": args.pipeline}
        else:
            report = evaluate_ocr(ocr_crops(cases, args.detector_results), lambda: create_ocr_engine(args.engine,
                device=args.device, threads=args.threads, pinned=True), repeats=args.repeats, warmup=args.warmup)
            report["crop_source"] = "production_detector" if args.detector_results else "annotated_ground_truth"
            if args.engine == "current":
                baseline = MODELS["ocr-original"]
                report["model"].update(engine="manga-ocr", model=baseline.repository, revision=baseline.revision,
                    preprocessing="grayscale", decoding="published", max_tokens=299)
        report["artifacts"] = artifact_metadata(kind, args.engine)
    except (DetectionInitializationError, OCRInitializationError, DetectionError) as exc:
        report = {"status": "unavailable", "error": str(exc)}
    report.update(kind=kind, engine=args.engine, device=args.device, threads=args.threads, dataset_sha256=file_hash(args.dataset),
        dataset_pages=len(cases), dataset_ids=[c.id for c in cases],
        measurement_scope="new process/model objects with cached artifacts; no download time or claim of OS cold-cache timing")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
    print(f"{kind} / {args.engine}: {report['status']} → {args.output}")
    return 3 if report["status"] == "unavailable" else 0
