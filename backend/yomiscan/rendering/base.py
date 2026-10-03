"""Single-page rendering contracts; analysis and rendering remain separate."""

from dataclasses import dataclass, field
from typing import Protocol
from PIL import Image
from yomiscan.page import PageAnalysisResult


class InpaintingError(RuntimeError):
    pass


class TypesettingError(RuntimeError):
    pass


class MaskGenerationError(RuntimeError):
    pass


@dataclass(frozen=True)
class BlockRenderStatus:
    block_id: int
    status: str
    reason: str | None = None
    font_size: int | None = None


@dataclass(frozen=True)
class RenderProcessing:
    mask_ms: float
    inpainting_ms: float
    typesetting_ms: float
    total_ms: float


@dataclass
class PageRenderResult:
    rendered_image: Image.Image
    blocks: tuple[BlockRenderStatus, ...]
    processing: RenderProcessing
    analysis_processing: dict[str, float] = field(default_factory=dict)
    debug_images: dict[str, Image.Image] = field(default_factory=dict)
    diagnostics: dict[str, object] = field(default_factory=dict)

    @property
    def blocks_rendered(self) -> int:
        return sum(b.status == "rendered" for b in self.blocks)

    @property
    def blocks_skipped(self) -> int:
        return len(self.blocks) - self.blocks_rendered

    def metadata(self) -> dict[str, object]:
        from dataclasses import asdict
        return {"blocks_detected": len(self.blocks), "blocks_rendered": self.blocks_rendered,
                "blocks_skipped": self.blocks_skipped, "blocks": [asdict(b) for b in self.blocks],
                "processing": asdict(self.processing), "analysis_processing": self.analysis_processing,
                "diagnostics": self.diagnostics, "coverage": self.diagnostics.get("coverage", {})}


class InpaintingEngine(Protocol):
    def inpaint(self, image: Image.Image, mask: Image.Image) -> Image.Image: ...


class PageRenderer(Protocol):
    def render(self, image: Image.Image, analysis: PageAnalysisResult, *,
               debug: bool = False) -> PageRenderResult: ...
