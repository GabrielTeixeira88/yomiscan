"""Independent experimental geometry policy; no production selection or default change."""

from ..detection import TextRegion


def suppress_regions(regions: list[TextRegion]) -> list[TextRegion]:
    # Prefer outer coverage, then confidence. Never merge boxes or cross text classes.
    ordered = sorted(regions, key=lambda r: (-r.bbox.width*r.bbox.height, -(r.confidence or 0), r.id))
    retained = []
    for candidate in ordered:
        a = candidate.bbox
        duplicate = False
        for other in retained:
            if not candidate.metadata.get("class") or candidate.metadata.get("class") != other.metadata.get("class"):
                continue
            b = other.bbox
            intersection = max(0, min(a.right, b.right)-max(a.left, b.left)) * max(0, min(a.bottom, b.bottom)-max(a.top, b.top))
            area_a, area_b = a.width*a.height, b.width*b.height
            if intersection / (area_a+area_b-intersection) >= .8 or intersection / min(area_a, area_b) >= .9:
                duplicate = True
                break
        if not duplicate:
            retained.append(candidate)
    return sorted(retained, key=lambda r: (r.bbox.top, -r.bbox.right, r.id))
