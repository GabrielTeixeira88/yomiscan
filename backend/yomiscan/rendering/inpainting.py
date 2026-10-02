"""CPU, weight-free local inpainting; writes only masked pixels."""

import cv2
import numpy as np
from PIL import Image
from .base import InpaintingError


class OpenCVInpaintingEngine:
    def __init__(self, radius: float = 3.0) -> None:
        if radius <= 0:
            raise ValueError("Inpainting radius must be positive")
        self.radius = radius

    def inpaint(self, image: Image.Image, mask: Image.Image) -> Image.Image:
        if mask.size != image.size or mask.mode != "L":
            raise ValueError("Mask must be L mode and match the crop dimensions")
        try:
            pixels = np.array(image.convert("RGB"))
            selected = np.array(mask)
            # Avoid Telea's gray smudges on thick glyphs in demonstrably flat bubbles.
            ring = cv2.dilate(selected, np.ones((7, 7), np.uint8)) > 0
            ring &= selected == 0
            samples = pixels[ring]
            background = np.median(samples, axis=0) if len(samples) else None
            uniform = background is not None and np.percentile(np.abs(samples-background).max(axis=1), 98) <= 12
            if uniform:
                cleaned = pixels.copy()
                cleaned[selected > 0] = background.astype(np.uint8)
            else:
                cleaned = cv2.inpaint(pixels, selected, self.radius, cv2.INPAINT_TELEA)
            # Preserve unmasked pixels exactly, irrespective of library behavior.
            pixels[selected > 0] = cleaned[selected > 0]
            return Image.fromarray(pixels)
        except cv2.error as exc:
            raise InpaintingError("OpenCV could not reconstruct this text region") from exc
