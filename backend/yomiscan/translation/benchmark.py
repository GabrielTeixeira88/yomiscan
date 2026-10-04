"""Model-agnostic evaluation and blank human review sheets."""

from collections.abc import Callable
from dataclasses import asdict, dataclass
import csv
import gc
import json
from pathlib import Path
import platform
import os
import shutil
import subprocess
from statistics import mean
from time import perf_counter

from .base import TranslationEngine, TranslationError, TranslationInitializationError
from .factory import ENGINE_NAMES, create_translation_engine
from .manga import TranslationContext


@dataclass(frozen=True)
class EvaluationCase:
    id: str
    category: str
    texts: tuple[str, ...]
    references: tuple[str, ...] = ()
    previous: tuple[str, ...] = ()
    following: tuple[str, ...] = ()
    glossary: dict[str, str] | None = None
    notes: str = ""


def read_dataset(path: Path) -> list[EvaluationCase]:
    cases, seen = [], set()
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            item = json.loads(line)
            for key in ("texts", "references", "previous", "following"):
                if key in item and not isinstance(item[key], list):
                    raise ValueError(f"{key} must be a list")
            case = EvaluationCase(item["id"], item["category"], tuple(item["texts"]), tuple(item.get("references", [])),
                                  tuple(item.get("previous", [])), tuple(item.get("following", [])), item.get("glossary"), item.get("notes", ""))
            if not isinstance(case.id, str) or case.id in seen or not case.texts:
                raise ValueError("IDs must be unique and cases must contain source lines")
            if any(not isinstance(text, str) or not text.strip() for text in (*case.texts, *case.previous, *case.following)):
                raise ValueError("Source/context lines must be nonempty strings")
            if case.references and len(case.references) != len(case.texts):
                raise ValueError("References must align with source lines")
            if case.glossary and any(not isinstance(k, str) or not isinstance(v, str) for k, v in case.glossary.items()):
                raise ValueError("Glossary must map strings to strings")
        except (KeyError, TypeError, ValueError, AttributeError) as exc:
            raise ValueError(f"Invalid evaluation dataset line {number}: {exc}") from exc
        seen.add(case.id)
        cases.append(case)
    if not cases:
        raise ValueError("Evaluation dataset is empty")
    return cases


def memory_snapshot() -> dict[str, object]:
    try:
        import psutil
    except ImportError:
        return {"rss_bytes": None, "note": "Install uv sync --extra benchmark for RSS snapshots"}
    process = psutil.Process()
    rss = 0
    for child in [process, *process.children(recursive=True)]:
        try:
            rss += child.memory_info().rss
        except psutil.NoSuchProcess:
            pass
    result = {"rss_bytes": rss, "scope": "Python plus owned children; snapshot, not peak; includes shared pages"}
    executable = shutil.which("nvidia-smi")
    if executable is None and os.name == "nt":
        candidate = Path(os.environ.get("SystemRoot", "C:/Windows")) / "System32/nvidia-smi.exe"
        executable = str(candidate) if candidate.is_file() else None
    if executable:
        try:
            gpu = subprocess.run([executable, "--query-gpu=name,memory.total,memory.used", "--format=csv,noheader,nounits"],
                                 capture_output=True, text=True, timeout=10,
                                 creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
            result["gpu_snapshot"] = gpu.stdout.strip() if gpu.returncode == 0 else "unavailable"
            result["gpu_scope"] = "Whole GPU used MiB, including other applications; snapshot, not peak"
        except (OSError, subprocess.SubprocessError) as exc:
            result["gpu_snapshot_error"] = str(exc)
    return result


def evaluate_engine(name: str, cases: list[EvaluationCase], *, device: str = "auto", mode: str = "isolated",
                    glossary: bool = False, repeats: int = 2,
                    factory: Callable[..., TranslationEngine] = create_translation_engine) -> dict[str, object]:
    if repeats < 1:
        raise ValueError("repeats must be positive")
    if mode not in ("isolated", "previous", "page"):
        raise ValueError("context mode must be isolated, previous, or page")
    report: dict[str, object] = {"engine": name, "context_mode": mode, "glossary": glossary,
                               "device_requested": device, "rows": [], "memory_before": memory_snapshot()}
    rows = []
    engine = None
    try:
        start = perf_counter()
        engine = factory(name, device=device)
        load = getattr(engine, "load", None)
        if load is not None:
            load()
        report["load_ms"] = (perf_counter() - start) * 1000
        report["memory_loaded"] = memory_snapshot()
        for case in cases:
            row = {"id": case.id, "category": case.category, "sources": list(case.texts),
                   "references": list(case.references), "notes": case.notes,
                   "previous": list(case.previous), "following": list(case.following), "glossary": case.glossary}
            if (mode != "isolated" and name in ("current", "hy-mt2-manga", "fugumt", "nllb-600m")) or (glossary and name in ("current", "fugumt", "nllb-600m")):
                row.update(status="unsupported", error="Engine does not support requested context/glossary; no silent fallback")
                rows.append(row)
                continue
            durations, runs = [], []
            try:
                for _ in range(repeats):
                    start = perf_counter()
                    if mode == "isolated":
                        results = [engine.translate(text, context=TranslationContext(glossary=case.glossary or {}))
                                   if glossary else engine.translate(text) for text in case.texts]
                    else:
                        context = TranslationContext(previous=case.previous,
                                                     following=case.following if mode == "page" else (),
                                                     glossary=(case.glossary or {}) if glossary else {})
                        if name == "qwen25-manga":
                            results = [engine.translate(text, context=TranslationContext(
                                previous=(*case.previous, *case.texts[:i]),
                                following=(*case.texts[i + 1:], *case.following) if mode == "page" else (),
                                glossary=context.glossary)) for i, text in enumerate(case.texts)]
                        else:
                            results = engine.translate_many(case.texts, context=context)
                    durations.append((perf_counter() - start) * 1000)
                    if len(results) != len(case.texts) or any(r.source_text != source for r, source in zip(results, case.texts, strict=True)):
                        raise TranslationError("Engine did not preserve source count/order")
                    runs.append([asdict(result) for result in results])
                start = perf_counter()
                batch = engine.translate_many(case.texts)
                batch_ms = (perf_counter() - start) * 1000
                if len(batch) != len(case.texts) or [r.source_text for r in batch] != list(case.texts):
                    raise TranslationError("translate_many did not preserve source count/order")
                row.update(status="ok", runs=runs, run_ms=durations, translate_many_ms=batch_ms,
                           translate_many=[asdict(result) for result in batch])
            except (TranslationError, TranslationInitializationError, ValueError) as exc:
                row.update(status="error", error=str(exc))
            rows.append(row)
        report["status"] = "completed" if all(row["status"] != "error" for row in rows) else "completed_with_errors"
        if rows and all(row["status"] == "unsupported" for row in rows):
            report["status"] = "unsupported"
        report["memory_after"] = memory_snapshot()
    except (TranslationInitializationError, TranslationError, ValueError) as exc:
        report.update(status="unavailable", error=str(exc))
    finally:
        if engine is not None:
            close = getattr(engine, "close", None)
            if close is not None:
                close()
        del engine
        gc.collect()
    report["rows"] = rows
    good = [row for row in rows if row["status"] == "ok"]
    warm = [elapsed / len(row["sources"]) for row in good for elapsed in row["run_ms"][1:]]
    report["summary"] = {"cases_ok": len(good), "cases_total": len(cases),
                         "first_case_ms": good[0]["run_ms"][0] if good else None,
                         "mean_warm_ms_per_line": mean(warm) if warm else None,
                         "warm_repeated_line_ms": (sum(sum(row["run_ms"][1:]) for row in good) /
                            sum(len(row["sources"]) * (len(row["run_ms"]) - 1) for row in good)) if warm else None,
                         "note": "Per-line page latency is amortized; batch time is not a sum of result timings"}
    return report


RATING_FIELDS = ("engine", "case_id", "line", "source", "translation", "reference", "notes",
                 "accuracy_1_5", "naturalness_1_5", "tone_1_5", "context_1_5",
                 "major_meaning_error", "overly_formal", "invented_meaning", "reviewer", "review_notes")


def write_ratings(path: Path, reports: list[dict]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=RATING_FIELDS)
        writer.writeheader()
        for report in reports:
            for row in report["rows"]:
                if row["status"] != "ok":
                    continue
                for i, result in enumerate(row["runs"][0]):
                    writer.writerow({"engine": report["engine"], "case_id": row["id"], "line": i + 1,
                                     "source": result["source_text"], "translation": result["translated_text"],
                                     "reference": row["references"][i] if row["references"] else "",
                                     "notes": row["notes"]})


def summarize_ratings(path: Path) -> dict[str, dict[str, object]]:
    """Validate manually completed CSVs; do not convert blank scores into zeroes."""
    grouped: dict[str, list[dict[str, str]]] = {}
    with path.open(encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        if not set(RATING_FIELDS).issubset(reader.fieldnames or []):
            raise ValueError("Rating CSV is missing required columns")
        for number, row in enumerate(reader, 2):
            for key in ("accuracy_1_5", "naturalness_1_5", "tone_1_5", "context_1_5"):
                if row[key] not in ("", "1", "2", "3", "4", "5"):
                    raise ValueError(f"Rating row {number}: {key} must be blank or 1–5")
            for key in ("major_meaning_error", "overly_formal", "invented_meaning"):
                if row[key].lower() not in ("", "yes", "no"):
                    raise ValueError(f"Rating row {number}: {key} must be blank, yes, or no")
            if any(row[key] for key in RATING_FIELDS[7:14]):
                grouped.setdefault(row["engine"], []).append(row)
    output = {}
    for engine, rows in grouped.items():
        summary = {"reviewed_rows": len(rows)}
        for key in ("accuracy_1_5", "naturalness_1_5", "tone_1_5", "context_1_5"):
            scores = [int(row[key]) for row in rows if row[key]]
            summary[key] = mean(scores) if scores else None
        for key in ("major_meaning_error", "overly_formal", "invented_meaning"):
            summary[key + "_yes"] = sum(row[key].lower() == "yes" for row in rows)
            summary[key + "_rated"] = sum(bool(row[key]) for row in rows)
        output[engine] = summary
    return output


def format_comparison(cases: list[EvaluationCase], reports: list[dict]) -> str:
    """Compare the same source across engines without hiding failed/unavailable runs."""
    lines = ["\nYomiScan translation comparison"]
    indexed = [(report, {row["id"]: row for row in report["rows"]}) for report in reports]
    for case in cases:
        for index, source in enumerate(case.texts):
            lines.extend((f"\n[{case.id}, line {index + 1}] SOURCE", source))
            for report, rows in indexed:
                label = report["engine"]
                row = rows.get(case.id)
                if row is None:
                    lines.append(f"{label}: {report['status']} — {report.get('error', 'No result')}")
                elif row["status"] != "ok":
                    lines.append(f"{label}: {row['status']} — {row['error']}")
                else:
                    result = row["runs"][0][index]
                    scope = result.get("metadata", {}).get("timing_scope", "inference")
                    lines.append(f"{label}: {result['translated_text']}")
                    lines.append(f"  {result['processing_time_ms']:.1f} ms ({scope}); "
                                 f"case wall time {row['run_ms'][0]:.1f} ms; "
                                 f"translate_many {row['translate_many_ms']:.1f} ms for {len(case.texts)} line(s)")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    import argparse
    import sys
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="Opt-in local manga translation benchmark")
    parser.add_argument("--engine", choices=(*ENGINE_NAMES, "all", "core"), default="current",
                        help="core compares current, fugumt, nllb-600m and hy-mt2-manga only")
    parser.add_argument("--dataset", type=Path, default=Path("benchmarks/manga-dialogue.jsonl"))
    parser.add_argument("--device", choices=("auto", "cpu", "cuda"), default="auto")
    parser.add_argument("--context-mode", choices=("isolated", "previous", "page"), default="isolated")
    parser.add_argument("--glossary", action="store_true")
    parser.add_argument("--repeats", type=int, default=2)
    parser.add_argument("--limit", type=int)
    parser.add_argument("--output", type=Path, default=Path(".cache/translation-benchmark.json"))
    args = parser.parse_args(argv)
    if args.output.resolve() == args.dataset.resolve() or args.output.with_suffix(".ratings.csv").resolve() == args.dataset.resolve():
        parser.error("Benchmark output must not overwrite the source dataset")
    try:
        cases = read_dataset(args.dataset)
        if args.limit is not None:
            if args.limit < 1:
                parser.error("--limit must be positive")
            cases = cases[:args.limit]
        if args.repeats < 1:
            parser.error("--repeats must be positive")
    except (OSError, ValueError) as exc:
        parser.error(str(exc))
    reports = []
    args.output.parent.mkdir(parents=True, exist_ok=True)
    selected = (ENGINE_NAMES if args.engine == "all" else
                ("current", "fugumt", "nllb-600m", "hy-mt2-manga") if args.engine == "core" else (args.engine,))
    for name in selected:
        print(f"Benchmarking {name}...", flush=True)
        report = evaluate_engine(name, cases, device=args.device, mode=args.context_mode, glossary=args.glossary, repeats=args.repeats)
        reports.append(report)
        print(json.dumps({k: report[k] for k in ("status", "error", "summary") if k in report}, ensure_ascii=False))
        args.output.write_text(json.dumps({"schema_version": 1, "python": platform.python_version(), "platform": platform.platform(),
                                         "dataset": str(args.dataset), "reports": reports}, ensure_ascii=False, indent=2), encoding="utf-8")
        write_ratings(args.output.with_suffix(".ratings.csv"), reports)
    print(format_comparison(cases, reports))
    return 0 if all(r["status"] == "completed" for r in reports) else 1
