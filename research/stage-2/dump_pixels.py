"""Stage 2 spike: reference pixel_values from manga-ocr's own processor, for the JS port check.

    uv run --frozen --extra vision python research/stage-2/dump_pixels.py [count]
Writes .cache/stage2/pixels/NNN.f32 (raw float32, 3x224x224) for the first crops.
"""

import sys
from pathlib import Path

import numpy as np
from PIL import Image
from transformers import ViTImageProcessor

from yomiscan.vision_models import model_directory

crops, out = Path(".cache/stage2/crops"), Path(".cache/stage2/pixels")
out.mkdir(parents=True, exist_ok=True)
processor = ViTImageProcessor.from_pretrained(model_directory("ocr-original"))
count = int(sys.argv[1]) if len(sys.argv) > 1 else 20
for path in sorted(crops.glob("*.png"))[:count]:
    image = Image.open(path).convert("L").convert("RGB")  # exactly MangaOcr.__call__
    pixels = processor(image, return_tensors="np").pixel_values[0].astype(np.float32)
    (out / f"{path.stem}.f32").write_bytes(pixels.tobytes())
print(count, "pixel arrays ->", out)
