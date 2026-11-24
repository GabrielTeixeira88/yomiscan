"""Stage 2 spike (informational): blind A/B/C/D rating sheet for the translation bake-off.

    uv run --frozen python research/stage-2/blind_ratings.py make
        -> .cache/stage2/blind-ratings.csv (rate this) + .cache/stage2/blind-key.json (do not open)
    uv run --frozen python research/stage-2/blind_ratings.py unblind
        -> .cache/stage2/unblinded.ratings.csv, then:
    uv run --frozen python scripts/summarize_translation_ratings.py .cache/stage2/unblinded.ratings.csv

Inputs: benchmark_translation ratings CSVs (Python OPUS, Hy-MT2), the Chrome Translator run and the
browser OPUS run (Transformers.js, 8-bit, greedy), which is what a browser-first build would show.
Candidates are shuffled per line with a fixed seed, so the label does not reveal the engine.
"""

import csv
import json
import random
import sys
from pathlib import Path

ROOT = Path(".cache/stage2")
COLUMNS = ["engine", "case_id", "line", "source", "translation", "reference", "notes", "accuracy_1_5",
           "naturalness_1_5", "tone_1_5", "context_1_5", "major_meaning_error", "overly_formal",
           "invented_meaning", "reviewer", "review_notes"]


def candidates() -> dict[str, list[dict]]:
    by_case: dict[str, list[dict]] = {}
    for engine, name in (("opus", "translate-opus.ratings.csv"), ("hy-mt2-manga", "translate-hy.ratings.csv")):
        with (ROOT / name).open(encoding="utf-8", newline="") as handle:
            for row in csv.DictReader(handle):
                by_case.setdefault(row["case_id"], []).append({**row, "engine": engine})
    for engine, name in (("chrome-translator", "chrome-translator.json"), ("opus-browser-q8-greedy", "opus-browser-wasm-q8.json")):
        for row in json.loads((ROOT / name).read_text(encoding="utf-8"))["rows"]:
            source = by_case[row["id"]][0]
            by_case[row["id"]].append({**{c: "" for c in COLUMNS}, "engine": engine, "case_id": row["id"],
                                       "line": "1", "source": source["source"], "translation": row["output"]})
    return by_case


def make() -> None:
    rng = random.Random(20261124)
    rows, key = [], {}
    for case_id, group in candidates().items():
        if len(group) != 4:
            raise SystemExit(f"{case_id}: expected 4 candidates, got {len(group)}")
        rng.shuffle(group)
        for label, candidate in zip("ABCD", group, strict=True):
            key[f"{case_id}/{label}"] = candidate["engine"]
            rows.append({**{c: "" for c in COLUMNS}, "engine": label, "case_id": case_id, "line": candidate["line"],
                         "source": candidate["source"], "translation": candidate["translation"]})
    with (ROOT / "blind-ratings.csv").open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, COLUMNS)
        writer.writeheader()
        writer.writerows(rows)
    (ROOT / "blind-key.json").write_text(json.dumps(key, indent=1), encoding="utf-8")
    print(f"{len(rows)} rows ({len(key) // 4} lines x 4) -> {ROOT / 'blind-ratings.csv'}")


def unblind() -> None:
    key = json.loads((ROOT / "blind-key.json").read_text(encoding="utf-8"))
    with (ROOT / "blind-ratings.csv").open(encoding="utf-8-sig", newline="") as handle:
        rows = [{**row, "engine": key[f"{row['case_id']}/{row['engine']}"]} for row in csv.DictReader(handle)]
    with (ROOT / "unblinded.ratings.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, COLUMNS)
        writer.writeheader()
        writer.writerows(rows)
    print(f"{len(rows)} rows -> {ROOT / 'unblinded.ratings.csv'}")


if __name__ == "__main__":
    {"make": make, "unblind": unblind}[sys.argv[1]]()
