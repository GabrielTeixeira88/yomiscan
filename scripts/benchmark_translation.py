"""Opt-in real-model evaluation; never collected by pytest. May download weights."""

import argparse
import json
import platform
import sys
from time import perf_counter

from yomiscan.translation import MarianTranslationEngine

TEXTS = [
    "でも大丈夫", "今日は学校に行かなかった。", "何をしているんだ？",
    "そんなこと言ってないぞ。", "本当に大丈夫なの？", "彼女は昨日東京に行った。",
    "これはどういう意味ですか？", "行かなきゃ。", "うそだろ！",
    "別にあんたのためじゃないんだからね。", "でも\n大丈夫",
]


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--device", choices=("auto", "cpu", "cuda"), default="cpu")
    args = parser.parse_args()
    start = perf_counter()
    engine = MarianTranslationEngine(device=args.device)
    initialization_ms = (perf_counter() - start) * 1000
    singles = [engine.translate(text) for text in TEXTS]
    start = perf_counter()
    batch = engine.translate_many(TEXTS)
    batch_ms = (perf_counter() - start) * 1000
    print(json.dumps({
        "python": platform.python_version(), "platform": platform.platform(),
        "device": engine.device, "model": singles[0].model,
        "revision": singles[0].metadata["revision"], "initialization_ms": initialization_ms,
        "batch_size": engine.batch_size, "batch_total_ms": batch_ms,
        "sentences": [{"source": result.source_text, "translation": result.translated_text,
                       "ms": result.processing_time_ms, "batched_translation": batched.translated_text}
                      for result, batched in zip(singles, batch, strict=True)],
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
