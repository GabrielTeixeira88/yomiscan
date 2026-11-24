"""Stage 2 spike: corpus pages as Pillow-decoded RGB PNGs (and original bytes) for the JS detector.

    uv run --frozen --extra vision python research/stage-2/dump_pages.py samples/vision/pages.json
Writes .cache/stage2/pages/<id>.png, <id><original suffix> and pages.json (id, split, files, size).
"""

import json
import shutil
import sys
from pathlib import Path

from PIL import Image

corpus = Path(sys.argv[1])
out = Path(".cache/stage2/pages")
out.mkdir(parents=True, exist_ok=True)
rows = []
for page in json.loads(corpus.read_text(encoding="utf-8"))["pages"]:
    source = corpus.parent / page["image"]
    with Image.open(source) as image:
        rgb = image.convert("RGB")
    rgb.save(out / f"{page['id']}.png")
    original = f"{page['id']}{source.suffix.lower()}"
    shutil.copyfile(source, out / original)
    rows.append({"id": page["id"], "split": page["split"], "png": f"{page['id']}.png", "original": original,
                 "width": rgb.width, "height": rgb.height})
(out / "pages.json").write_text(json.dumps(rows, indent=1), encoding="utf-8")
print(len(rows), "pages ->", out)
