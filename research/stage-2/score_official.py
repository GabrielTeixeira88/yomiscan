"""Stage 2 spike (informational): translation engines against owner-supplied official English.

    uv run --frozen --with sacrebleu==2.5.1 python research/stage-2/score_official.py [--show]

Official localizations rephrase freely, so chrF/BLEU are a rough signal only; meaning errors
need human (or clearly labelled assistant) review. Prints aggregates; --show prints every line
side by side for that review. Inputs stay under ignored .cache/stage2/.
"""

import argparse
import csv
import json
import sys
from pathlib import Path

import sacrebleu

ROOT = Path(".cache/stage2")


def engine_outputs() -> dict[str, dict[str, str]]:
    outputs: dict[str, dict[str, str]] = {}
    for engine, name in (("opus (python, beam 6)", "translate-opus.ratings.csv"), ("hy-mt2-manga", "translate-hy.ratings.csv")):
        with (ROOT / name).open(encoding="utf-8", newline="") as handle:
            outputs[engine] = {row["case_id"]: row["translation"] for row in csv.DictReader(handle)}
    for engine, name in (("opus (browser, q8 greedy)", "opus-browser-wasm-q8.json"), ("chrome-translator", "chrome-translator.json")):
        outputs[engine] = {row["id"]: row["output"] for row in json.loads((ROOT / name).read_text(encoding="utf-8"))["rows"]}
    return outputs


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser()
    parser.add_argument("--show", action="store_true")
    args = parser.parse_args()
    official = {row["id"]: row["official"] for row in map(json.loads, (ROOT / "official.jsonl").read_text(encoding="utf-8").splitlines()) if row}
    ids = sorted(official)
    outputs = engine_outputs()
    references = [[official[i] for i in ids]]
    print(f"{len(ids)} lines with an official translation")
    for engine, rows in outputs.items():
        hypotheses = [rows[i] for i in ids]
        chrf = sacrebleu.corpus_chrf(hypotheses, references, word_order=2).score
        bleu = sacrebleu.corpus_bleu(hypotheses, references).score
        print(f"  {engine:28s} chrF++ {chrf:5.1f}   BLEU {bleu:5.1f}")
    if args.show:
        sources = {json.loads(l)["id"]: json.loads(l)["texts"][0] for l in (ROOT / "translation-real.jsonl").read_text(encoding="utf-8").splitlines() if l}
        for i in ids:
            print(f"\n{i}  {sources[i]}\n  OFFICIAL  {official[i]}")
            for engine, rows in outputs.items():
                print(f"  {engine[:9]:9s} {rows[i]}")


if __name__ == "__main__":
    main()
