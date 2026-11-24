"""Stage 2 spike: write the production detector crops (same as the reference OCR arm) as PNGs.

    uv run --frozen --extra vision python research/stage-2/dump_crops.py samples/vision/pages.json \
        reports/stage2-detect-current-pipeline.json reports/stage2-ocr-reference.json

Output (ignored): .cache/stage2/crops/NNN.png and crops.json with id, split, category,
reference text and the reference arm's output for each crop, in the reference report's order.
"""

import argparse
import json
from pathlib import Path

from yomiscan.vision_benchmark.corpus import load_corpus
from yomiscan.vision_benchmark.runner import ocr_crops


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("corpus", type=Path)
    parser.add_argument("detections", type=Path)
    parser.add_argument("reference", type=Path)
    parser.add_argument("--output", type=Path, default=Path(".cache/stage2/crops"))
    args = parser.parse_args()
    crops = ocr_crops(load_corpus(args.corpus), args.detections)
    reference = {row["id"]: row for row in json.loads(args.reference.read_text(encoding="utf-8"))["rows"]}
    if [crop["id"] for crop in crops] != list(reference):
        raise SystemExit("Crop order differs from the reference report; regenerate both from the same detections")
    args.output.mkdir(parents=True, exist_ok=True)
    rows = []
    for index, crop in enumerate(crops):
        name = f"{index:03d}.png"
        crop["image"].save(args.output / name)
        rows.append({"file": name, "id": crop["id"], "split": crop["split"], "category": crop["category"],
                     "reference": crop["reference"], "reference_output": reference[crop["id"]]["output"]})
    (args.output / "crops.json").write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")
    print(len(rows), "crops ->", args.output)


if __name__ == "__main__":
    main()
