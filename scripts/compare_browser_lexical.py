"""Check the browser lexical engine against the backend, token for token (Stage 5a).

    cd extension; node build.mjs --test; node .test/lexical-parity.mjs; cd ..
    uv run --frozen python scripts/compare_browser_lexical.py [--dictionary data/jmdict.sqlite3]

Replays the browser's own lindera tokens through the unchanged Python TextAnalyzer and
requires identical lookup forms, ranked entry IDs, inflection labels, units and grammar
notes. Then scores the lexical golden set with those tokens (the browser engine's score)
next to fugashi + UniDic-lite (the backend's score). Exit status 1 on any difference.
"""

import argparse
import json
from pathlib import Path
import sys

from yomiscan.analysis import TextAnalyzer
from yomiscan.dictionary import SQLiteDictionary
from yomiscan.lexical_evaluation import evaluate, load_cases
from yomiscan.nlp import FugashiTokenizer, JapaneseToken


class ReplayTokenizer:
    def __init__(self, sentences: dict[str, dict]) -> None:
        self.sentences = sentences

    def tokenize(self, text: str) -> list[JapaneseToken]:
        return [JapaneseToken(**token) for token in self.sentences[text]["tokens"]]


def python_view(result) -> dict:
    return {"tokens": [{"lookup_form": t.lookup_form, "entry_ids": list(t.entry_ids), "inflection": list(t.inflection)} for t in result.tokens],
            "units": [{"start": u.start, "end": u.end, "surface": u.surface, "lookup_form": u.lookup_form, "entry_ids": list(u.entry_ids)}
                      for u in result.units],
            "grammar": [{"pattern": g.pattern, "start": g.start, "end": g.end} for g in result.grammar]}


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--dictionary", type=Path, default=Path("data/jmdict.sqlite3"))
    parser.add_argument("--browser", type=Path, default=Path(".cache/stage5a/lexical-browser.json"))
    parser.add_argument("--golden", type=Path, default=Path("benchmarks/lexical-golden.jsonl"))
    args = parser.parse_args()
    browser = json.loads(args.browser.read_text(encoding="utf-8"))
    replay = ReplayTokenizer(browser["sentences"])
    differences = 0
    with SQLiteDictionary(args.dictionary) as dictionary:
        analyzer = TextAnalyzer(replay, dictionary)
        for text, item in browser["sentences"].items():
            expected = python_view(analyzer.analyze(text))
            if expected != item["analysis"]:
                differences += 1
                for part in ("tokens", "units", "grammar"):
                    if expected[part] != item["analysis"][part]:
                        print(f"DIFF {part}: {text}\n  python  {expected[part]}\n  browser {item['analysis'][part]}")
        print(f"{len(browser['sentences']) - differences} / {len(browser['sentences'])} sentences identical "
              f"({browser['tokenizer']}, {browser['ms']:.0f} ms in Node)")
        cases = load_cases(args.golden)
        for name, tokenizer in ((browser["tokenizer"] + " (browser engine)", replay), ("fugashi + UniDic-lite (backend)", FugashiTokenizer())):
            print(name, json.dumps(evaluate(TextAnalyzer(tokenizer, dictionary), cases).summary()))
    return 1 if differences else 0


if __name__ == "__main__":
    raise SystemExit(main())
