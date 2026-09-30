from io import BytesIO
import warnings

from PIL import Image, ImageOps, UnidentifiedImageError

MAX_FILE_BYTES = 10 * 1024 * 1024
MAX_PIXELS = 12_000_000


def decode_image(data: bytes) -> Image.Image:
    if not data:
        raise ValueError("The uploaded image is empty.")
    if len(data) > MAX_FILE_BYTES:
        raise ValueError("Image exceeds the 10 MiB upload limit.")
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(BytesIO(data)) as source:
                if source.format not in ("PNG", "JPEG", "WEBP"):
                    raise ValueError("Use a PNG, JPEG, or WebP image.")
                if source.width * source.height > MAX_PIXELS:
                    raise ValueError("Image exceeds 12 megapixels; select a smaller region.")
                if getattr(source, "n_frames", 1) != 1:
                    raise ValueError("Animated images are not supported; upload a still crop.")
                source.load()
                return ImageOps.exif_transpose(source).convert("RGB")
    except (OSError, UnidentifiedImageError, Image.DecompressionBombError,
            Image.DecompressionBombWarning) as exc:
        raise ValueError("Cannot decode image; use a valid PNG, JPEG, or WebP crop.") from exc
