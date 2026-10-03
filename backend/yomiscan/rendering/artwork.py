"""Conservative recovery of dark glyphs with light edging over artwork.

This is not general text segmentation. Every substantial dark component inside the
text box must be isolated and surrounded by light pixels; otherwise preserve it.
Only selected strokes are erased, never the background rectangle or white halo.
"""

import cv2
import numpy as np
from PIL import Image
from yomiscan.detection import BoundingBox
from .masks import TextMask
from .base import MaskGenerationError


def edged_text_mask(image: Image.Image, box: BoundingBox, *, padding: int = 12) -> TextMask | None:
    try:
        return _edged_text_mask(image, box, padding)
    except cv2.error as exc:
        raise MaskGenerationError("Could not separate light-edged artwork text") from exc


def _edged_text_mask(image: Image.Image, box: BoundingBox, padding: int) -> TextMask | None:
    roi = box.clipped(*image.size, padding=padding)
    gray = np.asarray(image.crop(roi.coordinates()).convert("L"))
    x0, y0, x1, y1 = box.left-roi.left, box.top-roi.top, box.right-roi.left, box.bottom-roi.top
    dark = (gray < 160).astype(np.uint8)
    count, labels, stats, _ = cv2.connectedComponentsWithStats(dark, connectivity=8)
    raw = np.zeros_like(dark)
    # Adjacent strokes, furigana and enclosed counters are not background evidence.
    all_ink = cv2.dilate(dark, np.ones((3, 3), np.uint8))
    target = np.zeros_like(dark); target[y0:y1, x0:x1] = 1
    rejected = 0
    for label in range(1, count):
        x, y, w, h, area = map(int, stats[label])
        component = (labels == label).astype(np.uint8)
        inside = int(np.count_nonzero(component & target))
        if not inside or area < 2:
            continue
        # The surrounding ring excludes JPEG antialiasing immediately on the stroke.
        outer = cv2.dilate(component, np.ones((7, 7), np.uint8))
        inner = cv2.dilate(component, np.ones((3, 3), np.uint8))
        ring = (outer > 0) & (inner == 0) & (all_ink == 0)
        isolated = x > 0 and y > 0 and x+w < gray.shape[1] and y+h < gray.shape[0]
        contained = inside >= .98*area
        light = bool(np.any(ring) and np.mean(gray[ring] >= 210) >= .85)
        if isolated and contained and light:
            raw[component > 0] = 255
        else:
            rejected += inside
    total = int(np.count_nonzero(dark & target))
    if not total or rejected > max(2, total*.01) or np.count_nonzero(raw) < 8:
        return None
    final = cv2.dilate(raw, np.ones((3, 3), np.uint8))
    return TextMask(roi, Image.fromarray(raw), Image.fromarray(final), (255, 255, 255), True,
                    foreground_complete=True, background_uniform=False)
