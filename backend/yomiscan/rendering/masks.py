"""Conservative connected-component masks for uniform light/dark backgrounds.

This is not learned text segmentation: uncertain background/artwork is rejected.
Coordinates of returned masks are local to crop_box, never detector-scaled pixels.
"""

from dataclasses import dataclass
import cv2
import numpy as np
from PIL import Image
from yomiscan.detection import BoundingBox
from .base import MaskGenerationError


@dataclass(frozen=True)
class MaskConfig:
    text_padding: int = 4
    context_padding: int = 12
    dilation: int = 1
    contrast: int = 25
    minimum_background_fraction: float = .65

    def __post_init__(self) -> None:
        if min(self.text_padding, self.dilation) < 0 or self.context_padding <= self.text_padding + self.dilation:
            raise ValueError("Mask context must exceed nonnegative text padding + dilation")
        if not 1 <= self.contrast <= 255 or not 0 < self.minimum_background_fraction <= 1:
            raise ValueError("Invalid mask contrast/background fraction")


@dataclass
class TextMask:
    crop_box: BoundingBox
    raw: Image.Image
    final: Image.Image
    background: tuple[int, int, int]
    safe: bool
    reason: str | None = None
    foreground_complete: bool = False
    background_uniform: bool = False


def intersects(a: BoundingBox, b: BoundingBox) -> bool:
    return max(a.left, b.left) < min(a.right, b.right) and max(a.top, b.top) < min(a.bottom, b.bottom)


class UniformBackgroundMaskGenerator:
    def __init__(self, config: MaskConfig = MaskConfig()) -> None:
        self.config = config

    def generate(self, image: Image.Image, box: BoundingBox) -> TextMask:
        try:
            return self._generate(image, box)
        except cv2.error as exc:
            raise MaskGenerationError("OpenCV could not separate the foreground text") from exc

    def _generate(self, image: Image.Image, box: BoundingBox) -> TextMask:
        box = box.clipped(*image.size)
        if min(box.width, box.height) < 3:
            raise ValueError("Text box is too small or outside the image")
        context = box.clipped(*image.size, padding=self.config.context_padding)
        target = box.clipped(*image.size, padding=self.config.text_padding)
        pixels = np.array(image.crop(context.coordinates()).convert("RGB"))
        gray = cv2.cvtColor(pixels, cv2.COLOR_RGB2GRAY)
        x0, y0 = target.left-context.left, target.top-context.top
        x1, y1 = target.right-context.left, target.bottom-context.top
        inner = gray[y0:y1, x0:x1]
        mode = int(np.bincount((inner // 8).ravel(), minlength=32).argmax())
        background_pixels = pixels[y0:y1, x0:x1][inner // 8 == mode]
        background = tuple(int(v) for v in np.median(background_pixels, axis=0))
        bg_gray = int(np.median(inner[inner // 8 == mode]))
        difference = np.abs(pixels.astype(np.int16) - np.array(background, dtype=np.int16)).max(axis=2)
        foreground = (difference >= self.config.contrast).astype(np.uint8)
        count, labels, stats, _ = cv2.connectedComponentsWithStats(foreground, connectivity=8)
        raw = np.zeros(gray.shape, dtype=np.uint8)
        rejected = np.zeros_like(raw)
        for label in range(1, count):
            x, y, width, height, area = (int(v) for v in stats[label])
            if x >= x1 or y >= y1 or x+width <= x0 or y+height <= y0:
                continue
            # Connected outlines and artwork touching the context edge are never erased.
            boundary = x == 0 or y == 0 or x+width >= gray.shape[1] or y+height >= gray.shape[0]
            oversized = width > .75 * target.width and height > .75 * target.height
            outside = x < x0 or y < y0 or x+width > x1 or y+height > y1
            if boundary or oversized or outside:
                rejected[labels == label] = 255
            elif area >= 2:
                raw[labels == label] = 255
        radius = self.config.dilation
        final = cv2.dilate(raw, np.ones((2*radius+1, 2*radius+1), np.uint8)) if radius else raw.copy()
        # Never dilate onto known structural components, nor out of the target rectangle.
        allowed = np.zeros_like(raw)
        allowed[y0:y1, x0:x1] = 255
        final &= allowed
        final[rejected > 0] = 0
        tx0, ty0 = box.left-context.left, box.top-context.top
        tx1, ty1 = box.right-context.left, box.bottom-context.top
        interior = np.s_[ty0:ty1, tx0:tx1]
        ink_fraction = float(np.mean(foreground[interior] > 0))
        remaining = difference[interior][final[interior] == 0]
        reason = None
        if not np.any(raw):
            reason = "No safely separable foreground text"
        elif ink_fraction > 1-self.config.minimum_background_fraction:
            reason = "Dense foreground or textured background"
        elif np.any(rejected[interior]):
            reason = "Text area intersects an outline or connected artwork"
        elif len(remaining) == 0 or np.percentile(remaining, 98) > 14:
            reason = "Nonuniform background; artwork/screentones left unchanged"
        elif not (bg_gray >= 180 or bg_gray <= 75):
            reason = "Uncertain midtone background"
        complete = not np.any(rejected[interior])
        uniform = bool(len(remaining) and np.percentile(remaining, 98) <= 14)
        return TextMask(context, Image.fromarray(raw), Image.fromarray(final), background, reason is None, reason,
                        complete, uniform)


def safe_text_area(image: Image.Image, box: BoundingBox, background: tuple[int, int, int],
                   obstacles: list[BoundingBox], expansion: int = 12) -> BoundingBox:
    """Expand only through plain background strips; never through a neighboring block."""
    area = box.clipped(*image.size)
    pixels = np.asarray(image.convert("RGB"))
    for _ in range(expansion):
        for direction in range(4):
            candidate = [BoundingBox(area.left-1, area.top, area.right, area.bottom),
                         BoundingBox(area.left, area.top-1, area.right, area.bottom),
                         BoundingBox(area.left, area.top, area.right+1, area.bottom),
                         BoundingBox(area.left, area.top, area.right, area.bottom+1)][direction]
            candidate = candidate.clipped(*image.size)
            if any(intersects(candidate, other) for other in obstacles):
                continue
            strips = []
            if candidate.left < area.left: strips.append(pixels[area.top:area.bottom, candidate.left:area.left])
            if candidate.top < area.top: strips.append(pixels[candidate.top:area.top, area.left:area.right])
            if candidate.right > area.right: strips.append(pixels[area.top:area.bottom, area.right:candidate.right])
            if candidate.bottom > area.bottom: strips.append(pixels[area.bottom:candidate.bottom, area.left:area.right])
            if strips and all(np.max(np.abs(s.astype(np.int16)-np.array(background))) <= 14 for s in strips):
                area = candidate
    return area
