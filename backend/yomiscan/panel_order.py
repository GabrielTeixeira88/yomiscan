"""Optional bounded white-gutter XY cuts; ambiguous geometry keeps the band order."""

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol
import numpy as np
from PIL import Image

from .detection import BoundingBox, TextRegion
from .page_layout import RegionGroup, reading_order


class BlockGeometry(Protocol):
    id: int
    bbox: BoundingBox


@dataclass(frozen=True)
class PageOrder:
    block_ids: tuple[int, ...]
    panel_by_block: dict[int, int]
    panels: tuple[BoundingBox, ...]
    strategy: str
    fallback_reason: str | None = None


def band_ids(blocks: Sequence[BlockGeometry]) -> tuple[int, ...]:
    groups = [RegionGroup((TextRegion(b.id, b.bbox),), b.bbox) for b in blocks]
    return tuple(g.regions[0].id for g in reading_order(groups))


def page_order(image: Image.Image, blocks: Sequence[BlockGeometry], strategy: str = "bands") -> PageOrder:
    if strategy not in ("bands", "panels"):
        raise ValueError("Unknown page-order strategy")
    ids = band_ids(blocks)
    if len(ids) != len(set(ids)):
        raise ValueError("Page block IDs must be unique")
    def fallback(reason: str | None) -> PageOrder:
        return PageOrder(ids, {identifier: 1 for identifier in ids}, (BoundingBox(0, 0, *image.size),), "bands", reason)
    if strategy == "bands" or len(blocks) < 2:
        return fallback(None if strategy == "bands" else "insufficient_blocks")
    # Bound image work independently of page megapixels. Color is not semantic context.
    ratio = min(1.0, 640/max(image.size))
    size = (max(1, round(image.width*ratio)), max(1, round(image.height*ratio)))
    pixels = np.asarray(image.convert("L").resize(size, Image.Resampling.BOX))
    ink = pixels < 235
    if np.mean(ink) < .03:
        return fallback("insufficient_panel_evidence")
    ys, xs = np.where(ink)
    if not len(xs):
        return fallback("blank_page")
    root = (int(xs.min()), int(ys.min()), int(xs.max())+1, int(ys.max())+1)
    scaled = {b.id: (b.bbox.left*ratio, b.bbox.top*ratio, b.bbox.right*ratio, b.bbox.bottom*ratio) for b in blocks}
    leaves: list[tuple[tuple[int, int, int, int], tuple[int, ...]]] = []

    def runs(values: np.ndarray) -> list[tuple[int, int]]:
        padded = np.r_[False, values, False].astype(np.int8)
        changes = np.diff(padded)
        return list(zip(np.where(changes == 1)[0].tolist(), np.where(changes == -1)[0].tolist(), strict=True))

    def split(box: tuple[int, int, int, int], members: tuple[int, ...], depth: int) -> None:
        left, top, right, bottom = box
        if depth >= 8 or len(members) < 2 or min(right-left, bottom-top) < 16:
            leaves.append((box, members)); return
        region = ink[top:bottom, left:right]
        candidates = []
        for axis, paper in (("y", np.mean(region, axis=1) <= .002), ("x", np.mean(region, axis=0) <= .002)):
            extent = bottom-top if axis == "y" else right-left
            offset = top if axis == "y" else left
            for start, end in runs(paper):
                if start <= 2 or end >= extent-2 or end-start < max(3, round(extent*.012)):
                    continue
                cut = offset+(start+end)/2
                before, after = [], []
                for identifier in members:
                    bounds = scaled[identifier]
                    low, high = (bounds[1], bounds[3]) if axis == "y" else (bounds[0], bounds[2])
                    if high <= cut: before.append(identifier)
                    elif low >= cut: after.append(identifier)
                    else: break  # Never split a text block or silently choose its center.
                else:
                    if before and after:
                        candidates.append(((end-start)/extent, axis == "y", axis, int(round(cut)), tuple(before), tuple(after)))
        if not candidates:
            leaves.append((box, members)); return
        _, _, axis, cut, before, after = max(candidates)
        if axis == "y":
            split((left, top, right, cut), before, depth+1)
            split((left, cut, right, bottom), after, depth+1)
        else:
            split((cut, top, right, bottom), after, depth+1)  # Manga columns: right first.
            split((left, top, cut, bottom), before, depth+1)
    split(root, ids, 0)
    if len(leaves) < 2:
        return fallback("no_unambiguous_white_gutter")
    by_id = {b.id: b for b in blocks}
    ordered, panels, mapping = [], [], {}
    for index, (box, members) in enumerate(leaves, 1):
        panels.append(BoundingBox(*(round(v/ratio) for v in box)).clipped(*image.size))
        for identifier in band_ids([by_id[i] for i in members]):
            ordered.append(identifier); mapping[identifier] = index
    if len(ordered) != len(ids) or set(ordered) != set(ids):
        return fallback("partition_integrity_failed")
    return PageOrder(tuple(ordered), mapping, tuple(panels), "panels")
