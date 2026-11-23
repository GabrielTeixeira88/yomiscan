"""Golden-set evaluator mechanics on the small fixture dictionary (no JMdict download)."""

from pathlib import Path

import pytest

from yomiscan.analysis import TextAnalyzer
from yomiscan.dictionary import SQLiteDictionary
from yomiscan.lexical_evaluation import GoldenCase, Expectation, evaluate, load_cases, main
from yomiscan.nlp import FugashiTokenizer

DATASET = Path(__file__).parents[2] / "benchmarks" / "lexical-golden.jsonl"


def test_committed_golden_set_is_well_formed():
    cases = load_cases(DATASET)
    assert len(cases) >= 60
    assert all(case.expect or case.units for case in cases)
    assert sum(len(case.expect) for case in cases) >= 130


def test_pass_fail_missing_and_pending_outcomes(dictionary_path):
    cases = [GoldenCase("T1", "猫を食べた", (Expectation("猫", spelling="猫", pos="noun", gloss="cat"),
                                           Expectation("食べ", spelling="食べる"),
                                           Expectation("猫", gloss="dog"),
                                           Expectation("犬", gloss="dog")),
                        ({"text": "食べた", "gloss": "ate"},))]
    with SQLiteDictionary(dictionary_path) as dictionary:
        report = evaluate(TextAnalyzer(FugashiTokenizer(), dictionary), cases)
    assert [outcome.status for outcome in report.outcomes] == ["pass", "pass", "fail", "missing_token", "pending_unit"]
    assert "dog" in report.outcomes[2].detail
    assert report.summary() == {"scored": 4, "pass": 2, "fail": 1, "missing_token": 1, "pending_units": 1, "pass_rate": 0.5}


@pytest.mark.parametrize("line,message", [
    ('{"id": "X", "text": "猫"}', "no expectations"),
    ('{"text": "猫", "expect": [{"surface": "猫"}]}', "invalid golden case"),
    ('{"id": "X", "text": "猫", "expect": [{"surface": "猫", "unknown": 1}]}', "invalid golden case"),
])
def test_invalid_cases_are_rejected(tmp_path, line, message):
    path = tmp_path / "golden.jsonl"
    path.write_text(line + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match=message):
        load_cases(path)


def test_cli_reports_and_enforces_minimum_pass_rate(dictionary_path, tmp_path, capsys):
    dataset = tmp_path / "golden.jsonl"
    dataset.write_text('{"id": "C1", "text": "猫", "expect": [{"surface": "猫", "gloss": "cat"}]}\n'
                       '{"id": "C2", "text": "猫", "expect": [{"surface": "猫", "gloss": "dog"}]}\n', encoding="utf-8")
    output = tmp_path / "report.json"
    assert main(["--dictionary", str(dictionary_path), "--dataset", str(dataset), "--output", str(output)]) == 0
    assert main(["--dictionary", str(dictionary_path), "--dataset", str(dataset), "--min-pass-rate", "0.9"]) == 1
    assert '"pass_rate": 0.5' in capsys.readouterr().out
    assert output.exists()
