"""Explicit geometric proxies and character alignment, not inferred human accuracy."""

from math import ceil, sqrt
from statistics import median, mean
from typing import Any
from ..detection import BoundingBox, TextRegion
from ..page_layout import group_regions


def coverage(box: BoundingBox, target: list[int]) -> float:
    left, top, right, bottom = target
    intersection = max(0, min(box.right, right) - max(box.left, left)) * max(0, min(box.bottom, bottom) - max(box.top, top))
    return intersection / ((right - left) * (bottom - top))


def detection_metrics(predictions: list[TextRegion], truth: list[dict[str, Any]] | None,
                      size: tuple[int, int], *, exhaustive: bool = False) -> dict[str, Any]:
    result: dict[str, Any] = {"detected_regions": len(predictions), "annotation_available": truth is not None}
    if truth is None:
        return result | {key: None for key in ("dialogue_regions", "dialogue_found", "missed_dialogue", "false_positive_predictions",
            "merged_predictions", "duplicate_predictions", "crop_complete_dialogue", "grouped_merges", "split_candidates")}
    associations = [[i for i, target in enumerate(truth) if coverage(region.bbox, target["bbox"]) >= .5] for region in predictions]
    dialogue = [i for i, target in enumerate(truth) if target["category"] == "dialogue"]
    found = {i for linked in associations for i in linked}
    duplicates: set[int] = set()
    for i in range(len(truth)):
        matches = [index for index, linked in enumerate(associations) if i in linked]
        duplicates.update(matches[1:])
    groups = group_regions(predictions)
    completeness = {truth[i]["id"]: max((coverage(g.bbox.clipped(*size, padding=4), truth[i]["bbox"]) for g in groups), default=0)
                    for i in dialogue}
    return result | {"dialogue_regions": len(dialogue), "dialogue_found": len(set(dialogue) & found),
        "missed_dialogue": len(set(dialogue) - found),
        "false_positive_predictions": sum(not linked for linked in associations) if exhaustive else None,
        "unmatched_predictions": sum(not linked for linked in associations),
        "merged_predictions": sum(len(set(linked) & set(dialogue)) > 1 for linked in associations),
        "duplicate_predictions": len(duplicates),
        "grouped_merges": sum(sum(coverage(group.bbox, truth[i]["bbox"]) >= .5 for i in dialogue) > 1 for group in groups),
        "crop_complete_dialogue": sum(value >= .95 for value in completeness.values()), "crop_completeness": completeness,
        "split_candidates": sum(sum(coverage(p.bbox, truth[i]["bbox"]) >= .1 for p in predictions) > 1 and
            max((coverage(p.bbox, truth[i]["bbox"]) for p in predictions), default=0) < .9 for i in dialogue)}


def transcription_metrics(reference: str | None, hypothesis: str) -> dict[str, Any] | None:
    if reference is None:
        return None
    costs = [list(range(len(hypothesis) + 1))]
    for i, ref in enumerate(reference, 1):
        row = [i]
        for j, actual in enumerate(hypothesis, 1):
            row.append(min(costs[-1][j] + 1, row[-1] + 1, costs[-1][j-1] + (ref != actual)))
        costs.append(row)
    i, j = len(reference), len(hypothesis)
    substitutions = deletions = insertions = 0
    while i or j:
        if i and j and costs[i][j] == costs[i-1][j-1] + (reference[i-1] != hypothesis[j-1]):
            substitutions += reference[i-1] != hypothesis[j-1]; i -= 1; j -= 1
        elif i and costs[i][j] == costs[i-1][j] + 1:
            deletions += 1; i -= 1
        else:
            insertions += 1; j -= 1
    return {"reference_characters": len(reference), "substitutions": substitutions, "deletions": deletions,
            "insertions": insertions, "cer": costs[-1][-1] / len(reference) if reference else None,
            "exact": reference == hypothesis}


def latency_summary(values: list[float]) -> dict[str, Any]:
    ordered = sorted(values)
    return {"samples": len(values), "median_ms": median(values) if values else None,
            "p95_ms": ordered[ceil(.95 * len(ordered))-1] if ordered else None, "p95_method": "nearest_rank"}


def confidence_calibration(rows: list[dict[str, Any]]) -> dict[str, Any]:
    available = [r for r in rows if r.get("confidence") is not None and r.get("normalized") is not None]
    table = []
    for threshold in (.5, .75, .85, .95, .99):
        wrong = [r for r in available if not r["normalized"]["exact"]]
        flagged = [r for r in available if r["confidence"] < threshold]
        detected = [r for r in flagged if not r["normalized"]["exact"]]
        table.append({"threshold": threshold, "flagged": len(flagged), "errors_flagged": len(detected),
            "incorrect_high_confidence": len(wrong) - len(detected), "correct_low_confidence": len(flagged) - len(detected),
            "precision": len(detected) / len(flagged) if flagged else None,
            "recall": len(detected) / len(wrong) if wrong else None})
    paired = [r for r in available if r["normalized"]["cer"] is not None]
    correlation = None
    if len(paired) >= 3:
        xs, ys = [r["confidence"] for r in paired], [r["normalized"]["cer"] for r in paired]
        mx, my = mean(xs), mean(ys)
        denominator = sqrt(sum((x-mx)**2 for x in xs) * sum((y-my)**2 for y in ys))
        if denominator:
            correlation = sum((x-mx)*(y-my) for x, y in zip(xs, ys, strict=True)) / denominator
    return {"reads_with_confidence_and_truth": len(available), "confidence_cer_pearson_r": correlation, "thresholds": table,
            "short_reads": sum(r["normalized"]["reference_characters"] <= 5 for r in available),
            "mixed_script_reads": sum("mixed_script" in r.get("tags", []) for r in available),
            "policy": "diagnostic_only; exploratory counts, no automatic rejection or calibrated probability claim"}
