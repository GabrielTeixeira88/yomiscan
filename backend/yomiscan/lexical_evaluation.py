"""Score lexical analysis against a hand-written golden set (benchmarks/lexical-golden.jsonl).

A case names a token by its surface in a sentence and the correct top-ranked meaning:
the best entry's spelling, its first sense's part of speech, or a gloss substring among
the senses the Study popup shows unfolded (the first three). Expectations describe the
correct answer, not current output, so failures are real defects.

`units` are multi-token meaning units (しょうがない, かもしれない). Token-level analysis
cannot produce them yet; they are reported as pending until longest-match lookup exists.
"""

from collections.abc import Iterable
from dataclasses import dataclass, field
import json
from pathlib import Path

from .analysis import TextAnalysisResult, TextAnalyzer
from .dictionary import DictionaryEntry

VISIBLE_SENSES = 3


@dataclass(frozen=True)
class Expectation:
    surface: str
    spelling: str | None = None
    pos: str | None = None
    gloss: str | None = None


@dataclass(frozen=True)
class GoldenCase:
    id: str
    text: str
    expect: tuple[Expectation, ...] = ()
    units: tuple[dict[str, str], ...] = ()


@dataclass(frozen=True)
class Outcome:
    case: str
    surface: str
    status: str  # "pass", "fail", "missing_token" or "pending_unit"
    detail: str = ""


@dataclass
class Report:
    outcomes: list[Outcome] = field(default_factory=list)

    def count(self, status: str) -> int:
        return sum(outcome.status == status for outcome in self.outcomes)

    @property
    def scored(self) -> int:
        return self.count("pass") + self.count("fail") + self.count("missing_token")

    @property
    def pass_rate(self) -> float:
        return self.count("pass") / self.scored if self.scored else 0.0

    def summary(self) -> dict[str, object]:
        return {"scored": self.scored, "pass": self.count("pass"), "fail": self.count("fail"),
                "missing_token": self.count("missing_token"), "pending_units": self.count("pending_unit"),
                "pass_rate": round(self.pass_rate, 4)}


def load_cases(path: Path) -> list[GoldenCase]:
    cases = []
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            data = json.loads(line)
            expectations = tuple(Expectation(**item) for item in data.get("expect", ()))
            units = tuple(dict(item) for item in data.get("units", ()))
            case = GoldenCase(data["id"], data["text"], expectations, units)
        except (json.JSONDecodeError, KeyError, TypeError) as exc:
            raise ValueError(f"{path}:{number}: invalid golden case: {exc}") from exc
        if not case.expect and not case.units:
            raise ValueError(f"{path}:{number}: case {case.id} has no expectations")
        cases.append(case)
    if len({case.id for case in cases}) != len(cases):
        raise ValueError(f"{path}: duplicate case IDs")
    return cases


def check(expectation: Expectation, top: DictionaryEntry | None) -> str:
    """Empty string when the top entry satisfies every given field, else the reason."""
    if top is None:
        return "no dictionary entry"
    problems = []
    forms = set(top.spellings) | {reading.text for reading in top.readings}
    if expectation.spelling and expectation.spelling not in forms:
        problems.append(f"top entry {sorted(forms)[:3]} lacks {expectation.spelling}")
    first_pos = top.senses[0].parts_of_speech if top.senses else ()
    if expectation.pos and not any(expectation.pos.lower() in label.lower() for label in first_pos):
        problems.append(f"first-sense POS {list(first_pos)} lacks {expectation.pos}")
    glosses = [gloss for sense in top.senses[:VISIBLE_SENSES] for gloss in sense.glosses]
    if expectation.gloss and not any(expectation.gloss.lower() in gloss.lower() for gloss in glosses):
        problems.append(f"visible glosses {glosses[:4]} lack {expectation.gloss}")
    return "; ".join(problems)


def evaluate_result(case: GoldenCase, result: TextAnalysisResult) -> list[Outcome]:
    outcomes = []
    for expectation in case.expect:
        token = next((item for item in result.tokens if item.token.surface == expectation.surface), None)
        if token is None:
            surfaces = [item.token.surface for item in result.tokens]
            outcomes.append(Outcome(case.id, expectation.surface, "missing_token", f"tokens {surfaces}"))
            continue
        top = result.dictionary_entries[token.entry_ids[0]] if token.entry_ids else None
        problem = check(expectation, top)
        outcomes.append(Outcome(case.id, expectation.surface, "fail" if problem else "pass", problem))
    outcomes.extend(Outcome(case.id, unit["text"], "pending_unit", "multi-token unit; needs longest-match lookup")
                    for unit in case.units)
    return outcomes


def evaluate(analyzer: TextAnalyzer, cases: Iterable[GoldenCase]) -> Report:
    report = Report()
    for case in cases:
        report.outcomes.extend(evaluate_result(case, analyzer.analyze(case.text)))
    return report


def main(argv: list[str] | None = None) -> int:
    import argparse
    parser = argparse.ArgumentParser(description="Score dictionary candidate ranking against the lexical golden set (local JMdict, no models)")
    parser.add_argument("--dictionary", type=Path, default=Path("data/jmdict.sqlite3"))
    parser.add_argument("--dataset", type=Path, default=Path("benchmarks/lexical-golden.jsonl"))
    parser.add_argument("--output", type=Path, help="Write per-expectation outcomes as JSON")
    parser.add_argument("--min-pass-rate", type=float, default=0.0, help="Exit 1 below this scored pass rate (0-1)")
    args = parser.parse_args(argv)
    from .dictionary import SQLiteDictionary
    from .nlp import FugashiTokenizer
    cases = load_cases(args.dataset)
    with SQLiteDictionary(args.dictionary) as dictionary:
        report = evaluate(TextAnalyzer(FugashiTokenizer(), dictionary), cases)
        schema = dictionary.schema_version
    for outcome in report.outcomes:
        if outcome.status in ("fail", "missing_token"):
            print(f"{outcome.status.upper():14} {outcome.case} {outcome.surface}: {outcome.detail}")
    summary = {**report.summary(), "cases": len(cases), "dictionary_schema": schema}
    print(json.dumps(summary, ensure_ascii=False))
    if args.output:
        args.output.write_text(json.dumps({"summary": summary, "outcomes": [vars(o) for o in report.outcomes]},
                                          ensure_ascii=False, indent=2), encoding="utf-8")
    return 0 if report.pass_rate >= args.min_pass_rate else 1
