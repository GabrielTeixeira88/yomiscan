from dataclasses import dataclass
from PIL import Image, ImageDraw
import pytest

from yomiscan.detection import BoundingBox
from yomiscan.panel_order import page_order


@dataclass(frozen=True)
class Block:
    id: int
    bbox: BoundingBox


def fixture():
    image = Image.new("RGB", (400, 400), "white")
    draw = ImageDraw.Draw(image)
    # One tall right panel, two stacked left panels: band sorting interleaves panels.
    for box in ((215, 10, 390, 390), (10, 10, 190, 185), (10, 215, 190, 390)):
        draw.rectangle(box, outline="black", width=8)
    blocks = [Block(1, BoundingBox(300, 30, 350, 60)), Block(2, BoundingBox(300, 300, 350, 330)),
              Block(3, BoundingBox(60, 50, 100, 80)), Block(4, BoundingBox(60, 260, 100, 300))]
    return image, blocks


def test_labeled_geometry_order_is_independent_of_translation_and_preserves_ids():
    image, blocks = fixture()
    assert page_order(image, blocks).block_ids == (1, 3, 4, 2)
    result = page_order(image, blocks, "panels")
    assert result.block_ids == (1, 2, 3, 4)
    assert result.panel_by_block[1] == result.panel_by_block[2]
    assert result.panel_by_block[3] != result.panel_by_block[4]
    assert result.strategy == "panels"
    assert result == page_order(image, list(reversed(blocks)), "panels")


@pytest.mark.parametrize("kind", ["blank", "borderless", "dark", "diagonal"])
def test_ambiguous_layouts_fall_back_without_text_loss(kind):
    image, blocks = fixture()
    if kind in ("blank", "borderless"):
        image = Image.new("RGB", image.size, "white")
    elif kind == "dark":
        image = Image.new("RGB", image.size, "black")
    else:
        draw = ImageDraw.Draw(image)
        draw.line((0, 0, 400, 400), fill="black", width=35)
        draw.line((400, 0, 0, 400), fill="black", width=35)
    result = page_order(image, blocks, "panels")
    assert sorted(result.block_ids) == [1, 2, 3, 4]
    assert len(set(result.block_ids)) == 4
    if kind != "diagonal":
        assert result.strategy == "bands" and result.fallback_reason


def test_blocks_crossing_gutters_are_never_split_dropped_or_duplicated():
    image, blocks = fixture()
    blocks.append(Block(9, BoundingBox(180, 180, 240, 240)))
    result = page_order(image, blocks, "panels")
    assert sorted(result.block_ids) == [1, 2, 3, 4, 9]
    assert result.strategy == "bands"
    with pytest.raises(ValueError, match="unique"):
        page_order(image, [blocks[0], blocks[0]], "panels")
