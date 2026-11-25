"""Compare the Torch-free OPUS-MT translator (Stage 5b) with the Torch translator, line by line.

    uv run --extra vision python scripts/compare_torch_free_translation.py

Lines: benchmarks/manga-dialogue.jsonl plus, when present, the local-only Stage 2 set
(.cache/stage2/translation-real.jsonl; real corpus lines, never committed). Each line is translated
alone by both engines. Prints counts and timings; translations only with --show-differences
(keep that output out of Git).
"""

import argparse
import json
from pathlib import Path
from statistics import median
import sys
from time import perf_counter

from yomiscan.translation.factory import create_translation_engine

ROOT = Path(__file__).resolve().parents[1]
SETS = (ROOT / "benchmarks" / "manga-dialogue.jsonl", ROOT / ".cache" / "stage2" / "translation-real.jsonl")


def lines(paths) -> list[str]:
    found = []
    for path in paths:
        if path.is_file():
            for row in path.read_text(encoding="utf-8").splitlines():
                if row.strip():
                    found.extend(json.loads(row)["texts"])
    return found


def run(engine, texts) -> tuple[list[str], list[float]]:
    outputs, times = [], []
    for text in texts:
        start = perf_counter()
        outputs.append(engine.translate(text).translated_text)
        times.append((perf_counter() - start) * 1000)
    return outputs, times


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--show-differences", action="store_true")
    arguments = parser.parse_args(argv)
    texts = lines(SETS)
    report: dict[str, object] = {"lines": len(texts), "sets": [p.name for p in SETS if p.is_file()]}
    results = {}
    for name in ("current", "opus-pinned"):
        start = perf_counter()
        engine = create_translation_engine(name, device="cpu")
        load = perf_counter() - start
        run(engine, texts[:1])  # warm up outside the timing
        outputs, times = run(engine, texts)
        results[name] = outputs
        report[name] = {"load_s": round(load, 2), "median_ms": round(median(times)), "p95_ms": round(sorted(times)[int(.95 * (len(times) - 1))])}
    differing = [i for i, (a, b) in enumerate(zip(results["current"], results["opus-pinned"])) if a != b]
    report["identical"] = len(texts) - len(differing)
    report["differences"] = [{"line": i, **({"torch": results["current"][i], "torch_free": results["opus-pinned"][i]}
                                            if arguments.show_differences else {})} for i in differing]
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    print(json.dumps(report, indent=1, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
