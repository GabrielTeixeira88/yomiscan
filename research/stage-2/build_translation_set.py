"""Stage 2 spike: real-line translation set from the corpus references (kept local, never committed).

    uv run --frozen python research/stage-2/build_translation_set.py samples/vision/pages.json [--count 100]
Writes .cache/stage2/translation-real.jsonl in the benchmark_translation dataset format. Lines are
dialogue/narration references with at least 4 Japanese characters, spread evenly over the corpus.
"""

import argparse
import json
import re
from pathlib import Path

JAPANESE = re.compile(r"[぀-ヿ㐀-鿿]")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("corpus", type=Path)
    parser.add_argument("--count", type=int, default=100)
    parser.add_argument("--output", type=Path, default=Path(".cache/stage2/translation-real.jsonl"))
    args = parser.parse_args()
    eligible = []
    for page in json.loads(args.corpus.read_text(encoding="utf-8"))["pages"]:
        for region in page["regions"]:
            text = region["text"]
            if region["category"] in ("dialogue", "narration") and text and len(JAPANESE.findall(text)) >= 4:
                eligible.append({"id": f"{page['id']}-{region['id']}", "category": f"{region['category']}-{page['split']}",
                                 "texts": [text]})
    step = len(eligible) / min(args.count, len(eligible))
    chosen = [eligible[int(i * step)] for i in range(min(args.count, len(eligible)))]
    args.output.write_text("".join(json.dumps(c, ensure_ascii=False) + "\n" for c in chosen), encoding="utf-8")
    print(f"{len(chosen)} of {len(eligible)} eligible lines -> {args.output}")


if __name__ == "__main__":
    main()
