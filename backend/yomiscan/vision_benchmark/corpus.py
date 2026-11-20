"""Versioned local annotation format. References are never inferred from OCR output."""

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any
from ..vision_models import file_hash


@dataclass(frozen=True)
class PageCase:
    id: str
    image: Path
    sha256: str
    split: str
    regions: list[dict[str, Any]] | None
    exhaustive: bool


def load_corpus(path: Path, *, split: str | None = None) -> list[PageCase]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("schema_version") != 1 or not isinstance(data.get("pages"), list):
        raise ValueError("Vision corpus must have schema_version 1 and pages[]")
    cases, seen = [], set()
    for entry in data["pages"]:
        identity = entry["id"]
        if not isinstance(identity, str) or not identity or identity in seen:
            raise ValueError("Page IDs must be unique nonempty strings")
        seen.add(identity)
        if split is not None and entry["split"] != split:
            continue
        image = (path.parent / entry["image"]).resolve()
        digest = file_hash(image)
        if digest != entry["sha256"]:
            raise ValueError(f"Image fingerprint mismatch for {identity}; recheck annotations")
        regions = entry.get("regions")
        ids = set()
        if regions is not None:
            for region in regions:
                box = region["bbox"]
                if (region["id"] in ids or len(box) != 4 or any(type(n) is not int for n in box)
                    or box[0] < 0 or box[1] < 0 or box[2] <= box[0] or box[3] <= box[1]
                    or region["category"] not in ("dialogue", "narration", "artwork", "sfx", "control")
                    or region.get("text") is not None and not isinstance(region["text"], str)):
                    raise ValueError(f"Invalid region annotation for {identity}")
                ids.add(region["id"])
        cases.append(PageCase(identity, image, digest, entry["split"], regions, entry.get("annotations_complete", False)))
    if not cases:
        raise ValueError("No pages in the selected corpus split")
    return cases
