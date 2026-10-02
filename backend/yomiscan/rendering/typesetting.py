"""Measured, centered English layout using Pillow's redistributable Aileron subset."""

from dataclasses import dataclass
from typing import Protocol
import unicodedata
from PIL import Image, ImageDraw, ImageFont
from yomiscan.detection import BoundingBox
from .base import TypesettingError


@dataclass(frozen=True)
class TextLayout:
    text: str
    region: BoundingBox
    font_size: int
    position: tuple[float, float]
    spacing: int
    ink_bounds: tuple[float, float, float, float]


class Typesetter(Protocol):
    def layout_text(self, text: str, region: BoundingBox) -> TextLayout | None: ...
    def draw_text(self, image: Image.Image, layout: TextLayout, *, fill: tuple[int, int, int]) -> None: ...


def wrap_text(text: str, font: ImageFont.FreeTypeFont, width: int) -> str | None:
    words = text.split()
    if any(font.getlength(word) > width for word in words):
        return None
    # Measured dynamic programming: prefer few lines, then balanced line lengths.
    # Penalizing the last line too avoids a tiny orphan under several full lines.
    costs = [float("inf")] * (len(words)+1)
    breaks = [0] * len(words)
    costs[-1] = 0
    for start in range(len(words)-1, -1, -1):
        for end in range(start+1, len(words)+1):
            length = font.getlength(" ".join(words[start:end]))
            if length > width:
                break
            score = 2*width*width + (width-length)**2 + costs[end]
            if score < costs[start]:
                costs[start], breaks[start] = score, end
    lines, index = [], 0
    while index < len(words):
        end = breaks[index]
        lines.append(" ".join(words[index:end]))
        index = end
    return "\n".join(lines)


class PillowTypesetter:
    def __init__(self, *, minimum_size: int = 14, maximum_size: int = 30,
                 preferred_size: int = 26, margin: int = 3) -> None:
        if not 1 <= minimum_size <= maximum_size <= 128 or margin < 0:
            raise ValueError("Invalid font-size bounds or margin")
        self.minimum_size, self.maximum_size, self.margin = minimum_size, maximum_size, margin
        if not 1 <= preferred_size <= 128:
            raise ValueError("Invalid preferred font size")
        self.preferred_size = max(minimum_size, min(preferred_size, maximum_size))
        self._fonts: dict[int, ImageFont.FreeTypeFont] = {}

    def font(self, size: int) -> ImageFont.FreeTypeFont:
        if size not in self._fonts:
            try:
                font = ImageFont.load_default(size=size)
                if not isinstance(font, ImageFont.FreeTypeFont):
                    raise OSError("Pillow FreeType support is required")
                self._fonts[size] = font
            except OSError as exc:
                raise TypesettingError("Could not load Pillow's bundled Aileron font; reinstall Pillow with FreeType") from exc
        return self._fonts[size]

    def layout_text(self, text: str, region: BoundingBox) -> TextLayout | None:
        # Typographic punctuation has ASCII equivalents; do not discard unsupported words.
        normalized = unicodedata.normalize("NFKC", text).translate(str.maketrans({
            "’": "'", "‘": "'", "“": '"', "”": '"', "–": "-", "—": "-", "…": "...",
        }))
        normalized = " ".join(normalized.split())
        if not normalized or len(normalized) > 4000:
            return None
        probe = self.font(self.minimum_size)
        missing = bytes(probe.getmask("\ufffd"))
        if any(bytes(probe.getmask(c)) == missing for c in set(normalized) if not c.isspace()):
            raise TypesettingError("Translation contains characters absent from the bundled English font")
        width, height = region.width - 2*self.margin, region.height - 2*self.margin
        if min(width, height) <= 0:
            return None
        measure = ImageDraw.Draw(Image.new("L", (1, 1)))
        candidates: list[tuple[float, TextLayout]] = []
        for size in range(self.preferred_size, self.minimum_size-1, -1):
            font = self.font(size)
            wrapped = wrap_text(normalized, font, width)
            if wrapped is None:
                continue
            spacing = max(2, round(size * .18))
            bounds = measure.multiline_textbbox((0, 0), wrapped, font=font, spacing=spacing, align="center")
            bw, bh = bounds[2]-bounds[0], bounds[3]-bounds[1]
            if bw <= width and bh <= height:
                left, top = region.left+(region.width-bw)/2, region.top+(region.height-bh)/2
                layout = TextLayout(wrapped, region, size, (left-bounds[0], top-bounds[1]), spacing,
                                    (left, top, left+bw, top+bh))
                # A small size reduction is worthwhile when it removes an awkward short line.
                score = 2*(self.preferred_size-size)/self.preferred_size + .22*len(wrapped.splitlines())
                candidates.append((score, layout))
        return min(candidates, key=lambda candidate: candidate[0])[1] if candidates else None

    def draw_text(self, image: Image.Image, layout: TextLayout, *, fill: tuple[int, int, int]) -> None:
        try:
            ImageDraw.Draw(image).multiline_text(layout.position, layout.text, font=self.font(layout.font_size),
                                                fill=fill, spacing=layout.spacing, align="center")
        except (OSError, ValueError) as exc:
            raise TypesettingError("Pillow could not draw the fitted translation") from exc
