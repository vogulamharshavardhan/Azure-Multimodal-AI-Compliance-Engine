import json

import pytest

from backend.evaluation.evaluate import (
    EvaluationDataError,
    _load_jsonl,
    evaluate_records,
    render_markdown,
)


def _record(case_id, expected, predicted):
    return {
        "case_id": case_id,
        "expected": expected,
        "predicted": predicted,
    }


def test_decision_metrics_include_false_pass_rate():
    rows = [
        _record("1", {"decision": "FAIL"}, {"decision": "PASS"}),
        _record("2", {"decision": "PASS"}, {"decision": "PASS"}),
        _record("3", {"decision": "REVIEW_REQUIRED"}, {"decision": "REVIEW_REQUIRED"}),
        _record("4", {"decision": "NOT_APPLICABLE"}, {"decision": "NOT_APPLICABLE"}),
    ]
    report = evaluate_records(rows)
    assert report["dataset"]["cases"] == 4
    assert report["decision"]["false_pass_count"] == 1
    assert report["decision"]["false_pass_rate_among_gold_non_pass"] == pytest.approx(1 / 3)
    assert report["decision"]["accuracy"] == 0.75


def test_applicability_requirement_retrieval_grounding_and_citations():
    rows = [
        _record(
            "case-a",
            {
                "decision": "FAIL",
                "applicability": {"ADVERTISING_DISCLOSURES": "APPLICABLE"},
                "requirement_statuses": {"DISC-01": "NON_COMPLIANT"},
                "relevant_chunk_ids": ["p1", "p2"],
                "supported_claim_ids": ["claim-1", "claim-2"],
                "valid_citation_ids": ["cite-1"],
            },
            {
                "decision": "FAIL",
                "applicability": {"ADVERTISING_DISCLOSURES": "APPLICABLE"},
                "requirement_statuses": {"DISC-01": "NON_COMPLIANT"},
                "relevant_chunk_ids": ["p1", "wrong"],
                "grounded_claim_ids": ["claim-1", "hallucinated"],
                "citation_ids": ["cite-1", "bad-cite"],
            },
        )
    ]
    report = evaluate_records(rows)
    assert report["applicability"]["accuracy"] == 1.0
    assert report["requirement_status"]["accuracy"] == 1.0
    assert report["retrieval"]["mrr"] == 1.0
    assert report["evidence_grounding"]["precision"] == 0.5
    assert report["evidence_grounding"]["recall"] == 0.5
    assert report["citations"]["precision"] == 0.5
    assert report["citations"]["recall"] == 1.0


def test_calibration_metrics_are_computed_when_probabilities_exist():
    rows = [
        _record(
            "case-a",
            {"decision": "PASS"},
            {
                "decision": "PASS",
                "decision_probabilities": {
                    "PASS": 0.8,
                    "FAIL": 0.05,
                    "REVIEW_REQUIRED": 0.1,
                    "NOT_APPLICABLE": 0.05,
                },
            },
        )
    ]
    calibration = evaluate_records(rows)["calibration"]
    assert calibration["evaluated_cases"] == 1
    assert calibration["multiclass_brier_score"] >= 0
    assert calibration["expected_calibration_error"] == pytest.approx(0.2)


def test_duplicate_case_ids_are_rejected(tmp_path):
    path = tmp_path / "duplicate.jsonl"
    row = _record("same", {"decision": "PASS"}, {"decision": "PASS"})
    path.write_text(json.dumps(row) + "\n" + json.dumps(row) + "\n", encoding="utf-8")
    with pytest.raises(EvaluationDataError, match="duplicate case_id"):
        _load_jsonl(path)


def test_invalid_decision_is_rejected(tmp_path):
    path = tmp_path / "invalid.jsonl"
    row = _record("bad", {"decision": "MAYBE"}, {"decision": "PASS"})
    path.write_text(json.dumps(row) + "\n", encoding="utf-8")
    with pytest.raises(EvaluationDataError, match="expected.decision"):
        _load_jsonl(path)


def test_markdown_report_contains_confusion_matrix_and_limitations():
    rows = [
        _record("case-a", {"decision": "PASS"}, {"decision": "PASS"})
    ]
    markdown = render_markdown(evaluate_records(rows))
    assert "Decision confusion matrix" in markdown
    assert "zero real-world risk" in markdown
