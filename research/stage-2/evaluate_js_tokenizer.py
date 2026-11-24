"""Stage 2 spike (informational): lexical golden set with a JavaScript tokenizer's output.

    node research/stage-2/browser/tokenize-golden.mjs   (run from research/stage-2/browser)
    uv run --frozen python research/stage-2/evaluate_js_tokenizer.py [--dictionary data/jmdict.sqlite3]

Replays the precomputed tokens through the unchanged TextAnalyzer/JMdict ranking and compares
with fugashi + UniDic-lite on the same dictionary.
"""

import argparse
import json
from pathlib import Path

from yomiscan.analysis import TextAnalyzer
from yomiscan.dictionary import SQLiteDictionary
from yomiscan.japanese import hiragana
from yomiscan.lexical_evaluation import evaluate, load_cases
from yomiscan.nlp import FugashiTokenizer, JapaneseToken


class ReplayTokenizer:
    def __init__(self, sentences: dict[str, list[dict]]) -> None:
        self.sentences = sentences

    def tokenize(self, text: str) -> list[JapaneseToken]:
        tokens = []
        for t in self.sentences[text]:
            reading = hiragana(t["reading"]) if t["reading"] else None
            base = hiragana(t["lemma_reading"]) if t["lemma_reading"] else None
            tokens.append(JapaneseToken(**{**t, "reading": reading, "lemma_reading": base}))
        return tokens


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dictionary", type=Path, default=Path("data/jmdict.sqlite3"))
    parser.add_argument("--tokens", type=Path, default=Path(".cache/stage2/lindera-golden.json"))
    args = parser.parse_args()
    cases = load_cases(Path("benchmarks/lexical-golden.jsonl"))
    replay = json.loads(args.tokens.read_text(encoding="utf-8"))
    with SQLiteDictionary(args.dictionary) as dictionary:
        for name, tokenizer in (("fugashi + UniDic-lite", FugashiTokenizer()), (replay["tokenizer"], ReplayTokenizer(replay["sentences"]))):
            report = evaluate(TextAnalyzer(tokenizer, dictionary), cases)
            print(name, json.dumps(report.summary()))
            if name != "fugashi + UniDic-lite":
                for outcome in report.outcomes:
                    if outcome.status in ("fail", "missing_token"):
                        print("  ", outcome.status, outcome.case_id if hasattr(outcome, "case_id") else "", outcome.detail[:120])


if __name__ == "__main__":
    main()
