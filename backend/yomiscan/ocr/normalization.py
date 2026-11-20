"""Match the established manga-ocr text convention without importing a neural runtime."""

import re
import jaconv


def normalize_recognition(text: str) -> str:
    compact = "".join(text.split()).replace("…", "...")
    compact = re.sub(r"[・.]{2,}", lambda match: "." * len(match.group()), compact)
    return jaconv.h2z(compact, ascii=True, digit=True)
