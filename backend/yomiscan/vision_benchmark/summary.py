"""Summarize private benchmark JSON without copying images, URLs or transcriptions."""

from collections import Counter
from glob import glob
import json
from pathlib import Path
from typing import Any


def accuracy(rows: list[dict[str, Any]], field: str) -> dict[str, Any]:
    scored = [r[field] for r in rows if r.get(field) is not None]
    total = sum(r["reference_characters"] for r in scored)
    counts = {key: sum(r[key] for r in scored) for key in ("substitutions", "deletions", "insertions")}
    return {"valid_references": len(scored), "reference_characters": total, **counts,
            "cer": sum(counts.values()) / total if total else None,
            "exact_matches": sum(r["exact"] for r in scored),
            "exact_rate": sum(r["exact"] for r in scored) / len(scored) if scored else None}


def detection_totals(pages: list[dict[str, Any]]) -> dict[str, Any]:
    keys = ("detected_regions", "dialogue_regions", "dialogue_found", "missed_dialogue", "false_positive_predictions",
            "merged_predictions", "duplicate_predictions", "crop_complete_dialogue", "grouped_merges", "split_candidates")
    totals = {key: sum(p["metrics"][key] for p in pages) if pages and all(p["metrics"].get(key) is not None for p in pages) else None
              for key in keys}
    outcomes = Counter(outcome for page in pages for outcome in page.get("pipeline", {}).get("dialogue_outcomes", {}).values())
    counts = [p["pipeline"]["snapshot"]["counts"] for p in pages if "pipeline" in p]
    totals["rendered_blocks"] = sum(c["rendered"] for c in counts) if counts else None
    totals["preserved_blocks"] = sum(c["preserved"] for c in counts) if counts else None
    totals["dialogue_outcomes"] = dict(outcomes) if outcomes else None
    totals["ocr_success"] = sum(p["pipeline"]["ocr_success"] for p in pages if "pipeline" in p) if counts else None
    totals["translation_available"] = sum(p["pipeline"]["translation_available"] for p in pages if "pipeline" in p) if counts else None
    return totals


def summarize(report: dict[str, Any]) -> dict[str, Any]:
    result = {key: report.get(key) for key in ("kind", "engine", "status", "configuration", "crop_source", "load_ms",
        "latency", "memory_detector_loaded", "memory_loaded", "memory_end", "artifacts", "model", "environment", "dataset_sha256")}
    if report["status"] != "completed":
        return result | {"failure": "Model unavailable; inspect the private raw report for local error details."}
    if report["kind"] == "detection":
        pages = report["pages"]
        result["totals"] = detection_totals(pages)
        result["by_split"] = {split: detection_totals([p for p in pages if p["split"] == split]) for split in {p["split"] for p in pages}}
    else:
        rows = report["rows"]
        unknown_termination = sum(r["status"] == "success" and r.get("termination") is None for r in rows)
        observed_limits = sum(r.get("error_code") == "token_limit" for r in rows)
        result.update(reads=len(rows), failed_reads=sum(r["status"] == "error" for r in rows),
            truncations=observed_limits if not unknown_termination else None, observed_token_limit_errors=observed_limits,
            termination_unavailable_reads=unknown_termination,
            blank_reads=sum(r["status"] == "success" and not r["output"] for r in rows),
            hallucinated_characters_on_blank_reference=sum(len(r["output"]) for r in rows if r.get("reference") == ""),
            accuracy={field: accuracy(rows, field) for field in ("strict", "normalized")}, calibration=report.get("calibration"))
        result["by_split"] = {split: accuracy([r for r in rows if r["split"] == split], "normalized") for split in {r["split"] for r in rows}}
        tags = {tag for row in rows for tag in row.get("tags", [])}
        result["by_tag"] = {tag: accuracy([r for r in rows if tag in r.get("tags", [])], "normalized") for tag in sorted(tags)}
    return result


def markdown(results: list[dict[str, Any]]) -> str:
    lines = ["# Local vision benchmark summary", "", "Aggregate measurements only. See provenance, corpus annotations and decision notes before drawing conclusions.", "",
             "| Run | Engine | Status | Load ms | Warm median ms | Warm p95 ms | Quality |", "|---|---|---|---:|---:|---:|---|"]
    for row in results:
        timing = row.get("latency") or {}
        if row.get("totals"):
            totals = row["totals"]
            quality = f"dialogue {totals['dialogue_found']}/{totals['dialogue_regions']}; FP {totals['false_positive_predictions']}; merges {totals['merged_predictions']}; rendered {totals['rendered_blocks']}"
        elif row.get("accuracy"):
            a = row["accuracy"]["normalized"]
            quality = f"CER {a['cer']}; exact {a['exact_matches']}/{a['valid_references']}; failed {row['failed_reads']}"
        else:
            quality = "unavailable"
        def duration(value: object) -> str:
            return f"{value:.1f}" if isinstance(value, (float, int)) else "unavailable"
        lines.append(f"| {row['run']} | {row['engine']} | {row['status']} | {duration(row.get('load_ms'))} | {duration(timing.get('median_ms'))} | {duration(timing.get('p95_ms'))} | {quality} |")
    return "\n".join(lines) + "\n"


def main() -> int:
    import argparse
    parser = argparse.ArgumentParser(description="Aggregate local vision runs; output contains no source text/images")
    parser.add_argument("reports", nargs="+")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    files = sorted({Path(path).resolve() for pattern in args.reports for path in glob(pattern)})
    results = []
    for path in files:
        report = json.loads(path.read_text(encoding="utf-8"))
        if report.get("kind") not in ("ocr", "detection"):
            continue
        if path == args.output.resolve():
            parser.error("Summary output must not overwrite an input report")
        results.append(summarize(report) | {"run": path.stem})
    if not results:
        parser.error("No benchmark reports matched")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(results, ensure_ascii=False, indent=2) if args.output.suffix == ".json" else markdown(results), encoding="utf-8")
    return 0
