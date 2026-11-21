"""Reader typography settings affect rendering only."""

from dataclasses import dataclass
import math


@dataclass(frozen=True)
class RenderSettings:
    font_scale: float = 1.0

    def __post_init__(self) -> None:
        if isinstance(self.font_scale, bool) or not isinstance(self.font_scale, (int, float)) or not math.isfinite(self.font_scale) or not .75 <= self.font_scale <= 1.5:
            raise ValueError("Font scale must be a finite number between 0.75 and 1.50")
