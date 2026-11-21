"""Bounded opt-in experiments: raw replies stay local; human semantic scores stay blank."""

import argparse
from collections import Counter
from dataclasses import asdict
import hashlib
import json
import os
from pathlib import Path
from statistics import median
import subprocess
from time import perf_counter

from .benchmark import read_dataset, memory_snapshot, write_ratings
from .factory import create_translation_engine, ENGINE_NAMES
from .options import capabilities
from .structured import PageTranslationRequest, TranslationSegment
from .base import TranslationError, TranslationInitializationError, TranslationContext
from ..cache_identity import component_identity, versions


def structural_observations(responses: list[dict], expected_groups: list[list[str]]) -> dict[str, int]:
    """Independent benchmark counters, including failures the adapter rejected."""
    totals: Counter = Counter()
    for response, expected in zip(responses, expected_groups):
        totals["responses"] += 1
        try:
            choice = response["choices"][0]
            finish = choice["finish_reason"]
            totals["truncation"] += finish == "length"
            totals["failed_termination"] += finish != "stop"
            pairs = json.loads(choice["message"]["content"], object_pairs_hook=lambda items: items)
            if not isinstance(pairs, list) or any(not isinstance(p, tuple) or len(p) != 2 for p in pairs):
                raise ValueError("Not an ID object")
            keys = [key for key, _ in pairs]
            totals["missing_ids"] += len(set(expected)-set(keys))
            totals["extra_ids"] += len(set(keys)-set(expected))
            totals["duplicated_ids"] += len(keys)-len(set(keys))
            totals["wrong_count"] += len(keys) != len(expected)
            totals["untranslated_ids"] += sum(not isinstance(value, str) or not value.strip() for _, value in pairs)
        except (ValueError, KeyError, IndexError, TypeError):
            totals["invalid_format"] += 1
    return dict(totals)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--engine", required=True, choices=ENGINE_NAMES)
    parser.add_argument("--dataset", type=Path, default=Path("benchmarks/manga-dialogue.jsonl"))
    parser.add_argument("--case", action="append", dest="case_ids")
    parser.add_argument("--limit", type=int, default=6)
    parser.add_argument("--targets", default="en")
    parser.add_argument("--modes", default="sentences,structured-line,structured-page,structured-panel")
    parser.add_argument("--contexts", default="none")
    parser.add_argument("--glossary", action="store_true")
    parser.add_argument("--device", choices=("cpu", "cuda", "auto"), default="cpu")
    parser.add_argument("--local-manifest", type=Path)
    parser.add_argument("--llama-server", type=Path)
    parser.add_argument("--timeout", type=int, default=90)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    ratings = args.output.with_suffix(".ratings.csv")
    protected = {p.resolve() for p in (args.dataset, args.local_manifest, args.llama_server) if p is not None}
    if args.output.suffix != ".json" or any(p.exists() or p.resolve() in protected for p in (args.output, ratings)):
        parser.error("Choose new JSON/ratings paths separate from all inputs")
    if not 1 <= args.limit <= 32 or not 1 <= args.timeout <= 300:
        parser.error("Use 1–32 cases and timeout 1–300 seconds")
    modes, contexts, targets = args.modes.split(","), args.contexts.split(","), args.targets.split(",")
    if set(modes)-{"sentences", "structured-line", "structured-page", "structured-panel"} or set(contexts)-{"none", "neighbor", "panel", "page"} or set(targets)-{"en", "pt-BR", "es"}:
        parser.error("Unknown experimental mode/context/target")
    cases = read_dataset(args.dataset)
    if args.case_ids:
        selected = set(args.case_ids)
        if selected-{case.id for case in cases}:
            parser.error("Unknown case ID")
        cases = [case for case in cases if case.id in selected]
    cases = cases[:args.limit]
    os.environ["HF_HUB_OFFLINE"] = os.environ["TRANSFORMERS_OFFLINE"] = "1"
    if args.local_manifest:
        if args.local_manifest.stat().st_size > 4096:
            parser.error("Local artifact manifest exceeds 4 KiB")
        manifest = json.loads(args.local_manifest.read_text(encoding="utf-8"))
        permitted = {"YOMISCAN_HY_MT2_GGUF", "YOMISCAN_QWEN25_GGUF", "YOMISCAN_QWEN25_LORA"}
        if not isinstance(manifest, dict) or set(manifest)-permitted or any(not isinstance(v, str) for v in manifest.values()):
            parser.error("Manifest accepts only existing local manga artifact paths")
        os.environ.update(manifest)
    if args.llama_server:
        os.environ["YOMISCAN_LLAMA_SERVER"] = str(args.llama_server.resolve())
    report = {"engine": args.engine, "device": args.device, "dataset_sha256": hashlib.sha256(args.dataset.read_bytes()).hexdigest(),
              "case_ids": [c.id for c in cases], "versions": versions("torch", "transformers", "pillow"),
              "semantic_review": "Unscored. Blank existing review sheets require qualified human review.", "runs": [],
              "memory_before": memory_snapshot()}
    engine = None
    rating_reports = []
    try:
        start = perf_counter()
        engine = create_translation_engine(args.engine, device=args.device)
        runtime = getattr(engine, "runtime", None)
        if runtime is not None:
            runtime.timeout = args.timeout
        load = getattr(engine, "load", None)
        if callable(load): load()
        runtime = getattr(engine, "runtime", None)
        if runtime is not None:
            runtime.timeout = args.timeout
            runtime.record_debug = True
            report["runtime_version"] = subprocess.run([str(runtime.executable), "--version"], capture_output=True,
                text=True, timeout=15, creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0).stderr[-1000:]
        report["initialization_ms"] = (perf_counter()-start)*1000
        report["effective_identity"] = component_identity(engine)
        report["memory_loaded"] = memory_snapshot()
        support = capabilities(engine)
        for target in targets:
            for mode in modes:
                for context in contexts:
                    label = f"{args.engine}/{target}/{mode}/{context}/glossary-{args.glossary}"
                    run = {"label": label, "target": target, "mode": mode, "context": context, "rows": []}
                    times, structural = [], Counter()
                    ratings_report = {"engine": label, "rows": []}
                    for case in cases:
                        row = {"id": case.id, "category": case.category, "source_count": len(case.texts), "references":
                               list(case.references) if target == "en" else [], "notes": case.notes, "status": "unsupported"}
                        if target not in support.targets or (mode != "sentences" and not support.structured) or (context != "none" and (mode == "sentences" or not support.bounded_context)):
                            row["error_code"] = "unsupported_combination";run["rows"].append(row);continue
                        start = perf_counter()
                        groups = []
                        if runtime is not None: runtime.debug_responses = []
                        try:
                            if mode == "sentences":
                                if args.glossary and support.glossary_hints and case.glossary:
                                    results = engine.translate_many(case.texts, context=TranslationContext(glossary=case.glossary))
                                elif target != "en" and hasattr(type(engine), "translate_many_to"):
                                    results = engine.translate_many_to(case.texts, target)
                                else:
                                    results = engine.translate_many(case.texts)
                                groups = []
                            else:
                                segments = tuple(TranslationSegment(f"B{i:03d}", text, (i-1)//2+1) for i, text in enumerate(case.texts, 1))
                                extras = tuple(TranslationSegment(f"B{900000+i:06d}", text) for i, text in enumerate((*case.previous, *case.following)))
                                request = PageTranslationRequest(segments, target, mode, context,
                                    tuple((case.glossary or {}).items()) if args.glossary else (), extras)
                                from .structured import request_groups
                                groups = [[s.id for s in group] for group in request_groups(request)]
                                results = engine.translate_page(request)
                                row["panel_source"] = "synthetic adjacent pairs; not real panel annotations"
                            if len(results) != len(case.texts) or [r.source_text for r in results] != list(case.texts):
                                raise TranslationError("Output count/source identity mismatch")
                            row.update(status="ok", runs=[[asdict(result) for result in results]])
                        except (TranslationError, ValueError) as exc:
                            row.update(status="failed", error_code=getattr(exc, "code", "translation_error"), error=str(exc)[:500])
                        row["wall_ms"] = (perf_counter()-start)*1000
                        times.append(row["wall_ms"])
                        if runtime is not None:
                            row["raw_runtime_responses"] = list(runtime.debug_responses)
                            if mode != "sentences":
                                observed = structural_observations(runtime.debug_responses, groups)
                                structural.update(observed);row["structural"] = observed
                        run["rows"].append(row);ratings_report["rows"].append(row)
                        print(json.dumps({"run": label, "case": case.id, "status": row["status"],
                                          "error_code": row.get("error_code"), "wall_ms": round(row["wall_ms"], 1)}), flush=True)
                    run["status_counts"] = dict(Counter(row["status"] for row in run["rows"]))
                    run["structural"] = dict(structural)
                    run["median_wall_ms"] = median(times) if times else None
                    report["runs"].append(run);rating_reports.append(ratings_report)
        report["memory_after"] = memory_snapshot()
    except (TranslationInitializationError, OSError, ValueError) as exc:
        report["unavailable"] = str(exc)[:1000]
        print("Selected experiment unavailable; defaults unchanged.", flush=True)
    finally:
        if engine is not None:
            close = getattr(engine, "close", None)
            if callable(close): close()
    encoded = json.dumps(report, ensure_ascii=False, indent=2)
    if len(encoded.encode()) > 32*1024*1024:
        raise ValueError("Raw benchmark exceeds 32 MiB; select fewer cases")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(encoded, encoding="utf-8")
    write_ratings(ratings, rating_reports)
    return 1 if report.get("unavailable") or any(
        row["status"] == "failed" for run in report["runs"] for row in run["rows"]) else 0


if __name__ == "__main__":
    raise SystemExit(main())
