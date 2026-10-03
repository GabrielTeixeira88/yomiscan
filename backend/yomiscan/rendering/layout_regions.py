"""Estimate enclosed plain interiors, independently of the pixels being erased.

No contour is painted white. A connected background component only constrains where
English may be placed; glyph masks remain the sole input to inpainting.
"""

from dataclasses import dataclass
import cv2
import numpy as np
from PIL import Image
from yomiscan.detection import BoundingBox
from .masks import TextMask, safe_text_area
from .base import TypesettingError


@dataclass(frozen=True)
class LayoutRegion:
    bbox: BoundingBox
    kind: str  # bubble / narration_box / conservative
    enclosed: bool = False


def largest_rectangle(allowed: np.ndarray, *, prefer_wide: bool = False) -> BoundingBox | None:
    """Largest axis-aligned rectangle wholly inside a binary interior, O(width*height)."""
    heights = [0] * allowed.shape[1]
    best, area = None, 0
    for y, row in enumerate(allowed):
        stack: list[tuple[int, int]] = []
        for x in range(len(heights) + 1):
            if x < len(heights):
                heights[x] = heights[x] + 1 if row[x] else 0
            height = heights[x] if x < len(heights) else 0
            start = x
            while stack and stack[-1][1] > height:
                left, previous = stack.pop()
                size = (x-left) * (min(previous, (x-left)*1.5) if prefer_wide else previous)
                if size > area:
                    best, area = BoundingBox(left, y+1-previous, x, y+1), size
                start = left
            if not stack or stack[-1][1] < height:
                stack.append((start, height))
    return best


def estimate_layout_region(image: Image.Image, box: BoundingBox, mask: TextMask,
                           obstacles: list[BoundingBox], *, margin: int = 2) -> LayoutRegion:
    if margin < 0:
        raise ValueError("Layout margin must be nonnegative")
    try:
        return _estimate_layout_region(image, box, mask, obstacles, margin=margin)
    except cv2.error as exc:
        raise TypesettingError("OpenCV could not estimate a safe text interior") from exc


def _estimate_layout_region(image: Image.Image, box: BoundingBox, mask: TextMask,
                            obstacles: list[BoundingBox], *, margin: int) -> LayoutRegion:
    """Flood through plain background and provisional glyph holes, never through outlines.

    Open components (including page margins), implausibly large interiors and components
    containing only some of the glyph mask fall back to the bounded strip expansion.
    """
    box = box.clipped(*image.size)
    fallback = LayoutRegion(safe_text_area(image, box, mask.background, obstacles), "conservative")
    # Short utterances can occupy a small fraction of their containing bubble.
    # Search far enough to see an enclosing boundary, still within a bounded ROI.
    padding = min(384, max(256, 2 * min(box.width, box.height)))
    roi = box.clipped(*image.size, padding=padding)
    pixels = np.asarray(image.crop(roi.coordinates()).convert("RGB"))
    difference = np.abs(pixels.astype(np.int16)-np.array(mask.background)).max(axis=2)
    glyphs = Image.new("L", (roi.width, roi.height))
    glyphs.paste(mask.final, (mask.crop_box.left-roi.left, mask.crop_box.top-roi.top))
    ink = np.asarray(glyphs) > 0
    if not np.any(ink):
        return fallback
    passable = ((difference <= 20) | ink).astype(np.uint8)
    count, labels, stats, _ = cv2.connectedComponentsWithStats(passable, connectivity=4)
    votes = np.bincount(labels[ink], minlength=count)
    votes[0] = 0
    label = int(votes.argmax())
    if not label or votes[label] < .98 * np.count_nonzero(ink):
        return fallback
    x, y, width, height, area = (int(v) for v in stats[label])
    if x == 0 or y == 0 or x+width == roi.width or y+height == roi.height:
        return fallback
    if not .3 * box.width * box.height <= area <= 20 * box.width * box.height:
        return fallback
    interior = (labels == label).astype(np.uint8)
    # Tiny isolated paper/compression specks must not cut a whole narration box in half.
    # Fill only small enclosed holes in the layout map, never in the erasure mask.
    hole_count, holes, hole_stats, _ = cv2.connectedComponentsWithStats(1-interior, connectivity=8)
    for hole in range(1, hole_count):
        hx, hy, hw, hh, ha = (int(v) for v in hole_stats[hole])
        if ha <= 12 and hx > 0 and hy > 0 and hx+hw < roi.width and hy+hh < roi.height:
            interior[holes == hole] = 1
    # Keep all unmasked marks as obstacles. Never fill their holes by contour bounding box.
    interior = cv2.erode(interior, np.ones((2*margin+1, 2*margin+1), np.uint8))
    for other in obstacles:
        other = other.clipped(*image.size)
        left, top = max(0, other.left-roi.left), max(0, other.top-roi.top)
        right, bottom = min(roi.width, other.right-roi.left), min(roi.height, other.bottom-roi.top)
        if right > left and bottom > top:
            interior[top:bottom, left:right] = 0
    kind = "narration_box" if area / (width*height) > .96 else "bubble"
    rectangle = largest_rectangle(interior[y:y+height, x:x+width], prefer_wide=kind == "bubble")
    if rectangle is None or min(rectangle.width, rectangle.height) < 12:
        return fallback
    result = BoundingBox(roi.left+x+rectangle.left, roi.top+y+rectangle.top,
                         roi.left+x+rectangle.right, roi.top+y+rectangle.bottom)
    # An irregular white strip over artwork can be connected yet yield a tiny
    # rectangle far from most source glyphs. Never replace a usable fallback with it.
    if result.width*result.height < fallback.bbox.width*fallback.bbox.height*.75:
        return fallback
    return LayoutRegion(result, kind, True)
