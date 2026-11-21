"""Model-free ordering benchmark; optional local annotations stay outside Git."""

import argparse
from collections.abc import Iterator
from dataclasses import dataclass
import json
from pathlib import Path
from time import perf_counter

from PIL import Image, ImageDraw

from .detection import BoundingBox
from .panel_order import page_order


@dataclass(frozen=True)
class AnnotatedBlock:
    id: int
    bbox: BoundingBox


def synthetic_layouts() -> Iterator[tuple[str, Image.Image, list[AnnotatedBlock], list[int] | None, bool]]:
    """Original geometry with explicit truth; ambiguity has no invented ground truth."""
    boxes = {
        "tall-right": [(215, 10, 390, 390), (10, 10, 190, 185), (10, 215, 190, 390)],
        "grid": [(215, 10, 390, 185), (10, 10, 190, 185), (215, 215, 390, 390), (10, 215, 190, 390)],
        "columns": [(215, 10, 390, 390), (10, 10, 190, 390)],
        "rows": [(10, 10, 390, 185), (10, 215, 390, 390)],
    }
    tall = [AnnotatedBlock(i+1, BoundingBox(*b)) for i, b in enumerate([
        (300, 30, 350, 60), (300, 300, 350, 330), (60, 50, 100, 80), (60, 260, 100, 300)])]
    for name, panels in boxes.items():
        image = Image.new("RGB", (400, 400), "white")
        for panel in panels:
            ImageDraw.Draw(image).rectangle(panel, outline="black", width=8)
        if name in ("tall-right", "columns"):
            blocks = tall
        else:
            blocks = [AnnotatedBlock(i+1, BoundingBox(l+30, t+30, l+70, t+65)) for i, (l, t, _, _) in enumerate(panels)]
        yield name, image, blocks, [b.id for b in blocks], False
    for name, color in (("borderless", "white"), ("dark", "black")):
        yield name, Image.new("RGB", (400, 400), color), tall, None, True
    crossing = tall+[AnnotatedBlock(9, BoundingBox(180, 180, 240, 240))]
    image = Image.new("RGB", (400, 400), "white")
    for panel in boxes["tall-right"]:
        ImageDraw.Draw(image).rectangle(panel, outline="black", width=8)
    yield "crossing-gutter", image, crossing, None, True
    draw = ImageDraw.Draw(image)
    draw.line((0, 0, 400, 400), fill="black", width=35)
    draw.line((400, 0, 0, 400), fill="black", width=35)
    yield "diagonal", image, tall, None, True


def measure(name: str, image: Image.Image, blocks: list[AnnotatedBlock], expected: list[int] | None,
            ambiguous: bool) -> dict[str, object]:
    rows = []
    for strategy in ("bands", "panels"):
        start = perf_counter()
        result = page_order(image, blocks, strategy)
        elapsed = (perf_counter()-start)*1000
        identifiers = list(result.block_ids)
        pairwise = None
        if expected:
            positions = {value: index for index, value in enumerate(identifiers)}
            pairs = [(a, b) for i, a in enumerate(expected) for b in expected[i+1:]]
            pairwise = sum(positions[a] < positions[b] for a, b in pairs)/len(pairs) if pairs else 1
        rows.append({"strategy": strategy, "actual_strategy": result.strategy, "ids": identifiers,
                     "exact": identifiers == expected if expected else None, "pairwise": pairwise,
                     "integrity": len(identifiers) == len(blocks) and set(identifiers) == {b.id for b in blocks},
                     "deterministic": result == page_order(image, list(reversed(blocks)), strategy),
                     "fallback": result.fallback_reason, "wall_ms": elapsed})
    return {"id": name, "truth": expected, "ambiguous": ambiguous, "results": rows}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--annotations", type=Path, help="Local JSON array: id, image, blocks [{id,bbox}], order or null, ambiguous")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    if args.output.exists() or args.output == args.annotations:
        parser.error("Choose a new output path")
    rows = [measure(*layout) for layout in synthetic_layouts()]
    if args.annotations:
        if args.annotations.stat().st_size > 1024*1024:
            parser.error("Annotation manifest exceeds 1 MiB")
        cases = json.loads(args.annotations.read_text(encoding="utf-8"))
        if not isinstance(cases, list) or len(cases) > 100:
            parser.error("Use at most 100 annotated local pages")
        for case in cases:
            blocks = [AnnotatedBlock(b["id"], BoundingBox(*b["bbox"])) for b in case["blocks"]]
            expected = case.get("order")
            if expected is not None and (len(expected) != len(blocks) or set(expected) != {b.id for b in blocks}):
                parser.error("Annotation order must contain every block exactly once")
            with Image.open(args.annotations.parent/case["image"]) as image:
                rows.append(measure(case["id"], image, blocks, expected, case.get("ambiguous", False)))
    report = {"corpus": "8 original synthetic layouts plus explicitly supplied local annotations", "rows": rows}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps({"layouts": len(rows), "output": str(args.output)}))
    return 0
