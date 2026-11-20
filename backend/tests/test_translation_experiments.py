import json

from yomiscan.translation.experiments import structural_observations
from yomiscan.ordering_benchmark import synthetic_layouts, measure


def test_benchmark_counts_rejected_raw_replies_independently_of_adapter():
    def response(text, finish="stop"):
        return {"choices": [{"finish_reason": finish, "message": {"content": text}}]}
    rows = [response('{"B001":"one","B001":"duplicate","B009":"extra"}'), response('{', "length"),
            response('{"B001":null,"B002":"two"}')]
    counts = structural_observations(rows, [["B001", "B002"]]*3)
    assert counts["responses"] == 3
    assert counts["missing_ids"] == counts["extra_ids"] == counts["duplicated_ids"] == 1
    assert counts["truncation"] == counts["failed_termination"] == counts["invalid_format"] == 1
    assert counts["untranslated_ids"] == 1


def test_independent_layout_corpus_scores_truth_and_keeps_ambiguity_unscored():
    rows = [measure(*layout) for layout in synthetic_layouts()]
    assert len(rows) == 8
    for row in rows:
        assert all(r["integrity"] and r["deterministic"] for r in row["results"])
        if row["ambiguous"]:
            assert row["results"][1]["fallback"] and row["results"][1]["exact"] is None
        else:
            assert row["results"][1]["exact"] is True
    json.dumps(rows)  # The aggregate contains only geometry/metrics, no page bytes.
