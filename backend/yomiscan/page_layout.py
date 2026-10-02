"""Conservative geometry only; no panel understanding or language inference."""

from dataclasses import dataclass
from .detection import BoundingBox, TextRegion


@dataclass(frozen=True)
class RegionGroup:
    regions: tuple[TextRegion, ...]
    bbox: BoundingBox


def union_box(regions: tuple[TextRegion, ...]) -> BoundingBox:
    return BoundingBox(min(r.bbox.left for r in regions), min(r.bbox.top for r in regions),
                       max(r.bbox.right for r in regions), max(r.bbox.bottom for r in regions))


def nearby_lines(a: TextRegion, b: TextRegion) -> bool:
    # Block-level predictions must never be merged just because two bubbles are near.
    if any(r.metadata.get("granularity") != "line" for r in (a, b)):
        return False
    if a.orientation != b.orientation or a.orientation == "unknown":
        return False
    x, y = a.bbox, b.bbox
    if a.orientation == "vertical":
        overlap = min(x.bottom, y.bottom) - max(x.top, y.top)
        gap = max(x.left, y.left) - min(x.right, y.right)
        return (overlap >= .8 * max(x.height, y.height) and
                0 <= gap <= .6 * min(x.width, y.width) and
                max(x.width, y.width) <= 1.5 * min(x.width, y.width))
    overlap = min(x.right, y.right) - max(x.left, y.left)
    gap = max(x.top, y.top) - min(x.bottom, y.bottom)
    return (overlap >= .8 * max(x.width, y.width) and
            0 <= gap <= .6 * min(x.height, y.height) and
            max(x.height, y.height) <= 1.5 * min(x.height, y.height))


def group_regions(regions: list[TextRegion]) -> list[RegionGroup]:
    groups: list[list[TextRegion]] = []
    for region in sorted(regions, key=lambda r: (r.bbox.top, -r.bbox.right, r.id)):
        # Complete-link rule avoids chains bridging distant bubbles.
        target = next((g for g in groups if all(nearby_lines(region, r) for r in g)), None)
        if target is None:
            groups.append([region])
        else:
            target.append(region)
    return [RegionGroup(tuple(g), union_box(tuple(g))) for g in groups]


def reading_order(groups: list[RegionGroup]) -> list[RegionGroup]:
    """Top-to-bottom bands, right-to-left within each anchored band."""
    pending = sorted(groups, key=lambda g: (g.bbox.top, -g.bbox.right, g.regions[0].id))
    ordered = []
    while pending:
        anchor = pending.pop(0)
        tolerance = max(8, min(40, anchor.bbox.height * .25))
        band = [anchor]
        while pending and pending[0].bbox.top <= anchor.bbox.top + tolerance:
            band.append(pending.pop(0))
        ordered.extend(sorted(band, key=lambda g: (-g.bbox.right, g.bbox.top, g.regions[0].id)))
    return ordered
