"""Explainable rendering categories and stage outcomes, not a semantic classifier."""

import re
from collections import Counter
from .layout_regions import LayoutRegion

CATEGORIES = ("bubble", "narration", "artwork_text", "sfx", "unknown")


def classify_text(category: str, text: str, detector_classes: set[str],
                  layout: LayoutRegion | None = None) -> tuple[str, str]:
    if category in ("sfx", "possible_sfx"):
        return "sfx", "Explicit sound-effect category"
    if layout and layout.enclosed:
        return ("narration", "Enclosed rectangular interior") if layout.kind == "narration_box" else ("bubble", "Enclosed bubble interior")
    if category in ("dialogue", "bubble") or "text_bubble" in detector_classes:
        return "bubble", "Bubble detector/category (interior still requires safety checks)"
    if category == "narration":
        return "narration", "Explicit narration category"
    # Never classify short dialogue by length alone. Restrict to a tiny sound lexicon
    # on detector-labelled free text; normal bubble interjections remain dialogue.
    compact = re.sub(r"[\s！!。…・ー〜～]", "", text)
    if "text_free" in detector_classes and compact in {"ドン", "ザッ", "ゴゴ", "ゴゴゴ", "ゴゴゴゴ", "ドドド", "バン", "ガン"}:
        return "sfx", "Likely SFX: free-text detection and explicit sound pattern"
    if category == "artwork_text" or "text_free" in detector_classes:
        return "artwork_text", "Unboxed text; includes signage and page-margin text"
    return "unknown", "Insufficient category evidence"


def failure_stage(detail: dict, reason: str | None) -> str:
    if detail.get("render") == "rendered":
        return "rendered"
    if detail.get("ocr") != "success":
        return "ocr_failed"
    if detail.get("analysis_status") == "filtered":
        return "ocr_filtered"
    if detail.get("translation") != "success":
        return "translation_or_analysis_failed"
    if reason == "Sound effects preserved":
        return "likely_sfx"
    if reason and ("Overlapping" in reason or "too close" in reason):
        return "geometry_conflict"
    if detail.get("mask") == "error":
        return "mask_failed"
    if detail.get("mask") == "unsafe":
        if reason and ("foreground text" in reason or "outline" in reason):
            return "inseparable_mask"
        return "unsafe_background"
    if detail.get("layout") == "error":
        return "no_layout_region"
    if detail.get("typesetting") == "overflow":
        return "overflow"
    if detail.get("inpainting") == "error":
        return "inpainting_failed"
    if detail.get("typesetting") == "error":
        return "typesetting_failed"
    return "invalid_geometry_or_unsupported"


def coverage_metrics(details: dict[int, dict], filtered: dict[int, str]) -> dict:
    metrics = {"total_text_blocks": len(details), "filtered_before_grouping": len(filtered),
               "not_detected_estimate": None}
    for category in CATEGORIES:
        items = [d for d in details.values() if d["category"] == category]
        metrics[category + "_detected"] = len(items)
        metrics[category + "_rendered"] = sum(d["render"] == "rendered" for d in items)
        metrics[category + "_preserved"] = sum(d["render"] != "rendered" for d in items)
    metrics["skip_reasons"] = dict(Counter(d["reason_code"] for d in details.values() if d["render"] != "rendered"))
    return metrics
