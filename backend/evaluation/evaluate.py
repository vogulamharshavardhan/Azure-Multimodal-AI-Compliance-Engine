"""Offline, deterministic evaluation for Brand Guardian.

The evaluator compares pipeline predictions with human-reviewed gold labels.
It does not call an LLM and never invents benchmark labels.
"""
from __future__ import annotations

import argparse
import json
import math
import statistics
import sys
from collections import Counter
from pathlib import Path
from typing import Any

DECISIONS = ("PASS", "FAIL", "REVIEW_REQUIRED", "NOT_APPLICABLE")
APPLICABILITY = ("APPLICABLE", "NOT_APPLICABLE", "UNCERTAIN")
REQUIREMENT_STATUSES = (
    "COMPLIANT", "NON_COMPLIANT", "INSUFFICIENT_EVIDENCE", "NOT_EVALUATED"
)


class EvaluationDataError(ValueError):
    """Raised when a benchmark record is malformed or ambiguous."""


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    seen: set[str] = set()
    with path.open("r", encoding="utf-8") as handle:
        for line_number, raw in enumerate(handle, start=1):
            if not raw.strip() or raw.lstrip().startswith("#"):
                continue
            try:
                row = json.loads(raw)
            except json.JSONDecodeError as exc:
                raise EvaluationDataError(
                    f"{path}:{line_number}: invalid JSON: {exc.msg}"
                ) from exc
            if not isinstance(row, dict):
                raise EvaluationDataError(
                    f"{path}:{line_number}: each JSONL row must be an object"
                )
            case_id = row.get("case_id")
            if not isinstance(case_id, str) or not case_id.strip():
                raise EvaluationDataError(
                    f"{path}:{line_number}: case_id must be a non-empty string"
                )
            if case_id in seen:
                raise EvaluationDataError(
                    f"{path}:{line_number}: duplicate case_id {case_id!r}"
                )
            seen.add(case_id)
            _validate_record(row, path, line_number)
            records.append(row)
    if not records:
        raise EvaluationDataError("The benchmark dataset contains no records.")
    return records


def _validate_record(row: dict[str, Any], path: Path, line: int) -> None:
    expected = row.get("expected")
    predicted = row.get("predicted")
    if not isinstance(expected, dict) or not isinstance(predicted, dict):
        raise EvaluationDataError(
            f"{path}:{line}: expected and predicted objects are required"
        )
    for section_name, section in (("expected", expected), ("predicted", predicted)):
        decision = section.get("decision")
        if decision not in DECISIONS:
            raise EvaluationDataError(
                f"{path}:{line}: {section_name}.decision must be one of {DECISIONS}"
            )
        for key in ("applicability", "requirement_statuses"):
            value = section.get(key, {})
            if not isinstance(value, dict):
                raise EvaluationDataError(
                    f"{path}:{line}: {section_name}.{key} must be an object"
                )
        for domain, label in section.get("applicability", {}).items():
            if label not in APPLICABILITY:
                raise EvaluationDataError(
                    f"{path}:{line}: invalid applicability label for {domain}: {label}"
                )
        for requirement_id, label in section.get("requirement_statuses", {}).items():
            if label not in REQUIREMENT_STATUSES:
                raise EvaluationDataError(
                    f"{path}:{line}: invalid requirement status for {requirement_id}: {label}"
                )
        for key in (
            "relevant_chunk_ids", "grounded_claim_ids", "citation_ids",
        ):
            value = section.get(key, [])
            if not isinstance(value, list) or any(not isinstance(x, str) for x in value):
                raise EvaluationDataError(
                    f"{path}:{line}: {section_name}.{key} must be a list of strings"
                )
    probabilities = predicted.get("decision_probabilities")
    if probabilities is not None:
        if not isinstance(probabilities, dict):
            raise EvaluationDataError(
                f"{path}:{line}: decision_probabilities must be an object"
            )
        if set(probabilities) - set(DECISIONS):
            raise EvaluationDataError(
                f"{path}:{line}: decision_probabilities contains unknown labels"
            )
        values = [float(value) for value in probabilities.values()]
        if any(not math.isfinite(value) or value < 0 or value > 1 for value in values):
            raise EvaluationDataError(
                f"{path}:{line}: probabilities must be finite values in [0, 1]"
            )
        if values and not math.isclose(sum(values), 1.0, abs_tol=0.02):
            raise EvaluationDataError(
                f"{path}:{line}: decision probabilities must sum to 1 (±0.02)"
            )


def _classification_metrics(
    y_true: list[str], y_pred: list[str], labels: tuple[str, ...]
) -> dict[str, Any]:
    matrix = {actual: {pred: 0 for pred in labels} for actual in labels}
    for actual, predicted in zip(y_true, y_pred):
        if actual in matrix and predicted in matrix[actual]:
            matrix[actual][predicted] += 1

    per_class: dict[str, dict[str, float | int]] = {}
    f1_values: list[float] = []
    for label in labels:
        tp = matrix[label][label]
        fp = sum(matrix[other][label] for other in labels if other != label)
        fn = sum(matrix[label][other] for other in labels if other != label)
        support = sum(matrix[label].values())
        precision = tp / (tp + fp) if tp + fp else 0.0
        recall = tp / (tp + fn) if tp + fn else 0.0
        f1 = (
            2 * precision * recall / (precision + recall)
            if precision + recall else 0.0
        )
        per_class[label] = {
            "precision": round(precision, 6),
            "recall": round(recall, 6),
            "f1": round(f1, 6),
            "support": support,
        }
        if support:
            f1_values.append(f1)

    total = len(y_true)
    correct = sum(matrix[label][label] for label in labels)
    return {
        "count": total,
        "accuracy": round(correct / total, 6) if total else None,
        "macro_f1_present_classes": (
            round(statistics.mean(f1_values), 6) if f1_values else None
        ),
        "per_class": per_class,
        "confusion_matrix": matrix,
    }


def _mapping_metrics(
    rows: list[dict[str, Any]], section: str, labels: tuple[str, ...]
) -> dict[str, Any]:
    pairs: list[tuple[str, str]] = []
    for row in rows:
        expected = row["expected"].get(section, {})
        predicted = row["predicted"].get(section, {})
        for key in sorted(set(expected) & set(predicted)):
            pairs.append((expected[key], predicted[key]))
    if not pairs:
        return {"count": 0, "note": "No aligned labels supplied."}
    return _classification_metrics(
        [pair[0] for pair in pairs], [pair[1] for pair in pairs], labels
    )


def _set_metrics(
    rows: list[dict[str, Any]], expected_key: str, predicted_key: str
) -> dict[str, Any]:
    tp = fp = fn = 0
    evaluated = 0
    for row in rows:
        expected = set(row["expected"].get(expected_key, []))
        predicted = set(row["predicted"].get(predicted_key, []))
        if not expected and not predicted:
            continue
        evaluated += 1
        tp += len(expected & predicted)
        fp += len(predicted - expected)
        fn += len(expected - predicted)
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return {
        "evaluated_cases": evaluated,
        "true_positive": tp,
        "false_positive": fp,
        "false_negative": fn,
        "precision": round(precision, 6),
        "recall": round(recall, 6),
        "f1": round(f1, 6),
    }


def _retrieval_metrics(rows: list[dict[str, Any]], k_values=(1, 3, 5, 10)) -> dict[str, Any]:
    cases = []
    for row in rows:
        expected = row["expected"].get("relevant_chunk_ids", [])
        predicted = row["predicted"].get("relevant_chunk_ids", [])
        if expected:
            cases.append((set(expected), predicted))
    if not cases:
        return {"evaluated_cases": 0, "note": "No relevant_chunk_ids supplied."}

    output: dict[str, Any] = {"evaluated_cases": len(cases), "by_k": {}}
    reciprocal_ranks: list[float] = []
    for relevant, ranked in cases:
        rank = next((i for i, chunk in enumerate(ranked, 1) if chunk in relevant), None)
        reciprocal_ranks.append(1 / rank if rank else 0.0)

    for k in k_values:
        precisions, recalls, ndcgs = [], [], []
        for relevant, ranked in cases:
            top = ranked[:k]
            hits = sum(1 for chunk in top if chunk in relevant)
            precisions.append(hits / k)
            recalls.append(hits / len(relevant))
            dcg = sum(
                1 / math.log2(index + 1)
                for index, chunk in enumerate(top, 1)
                if chunk in relevant
            )
            ideal_hits = min(len(relevant), k)
            idcg = sum(1 / math.log2(index + 1) for index in range(1, ideal_hits + 1))
            ndcgs.append(dcg / idcg if idcg else 0.0)
        output["by_k"][str(k)] = {
            "precision_at_k": round(statistics.mean(precisions), 6),
            "recall_at_k": round(statistics.mean(recalls), 6),
            "ndcg_at_k": round(statistics.mean(ndcgs), 6),
        }
    output["mrr"] = round(statistics.mean(reciprocal_ranks), 6)
    return output


def _calibration_metrics(rows: list[dict[str, Any]], bins: int = 10) -> dict[str, Any]:
    samples: list[tuple[float, int, float]] = []
    for row in rows:
        probabilities = row["predicted"].get("decision_probabilities")
        if not probabilities:
            continue
        # Missing classes are treated as zero probability.
        normalized = {label: float(probabilities.get(label, 0.0)) for label in DECISIONS}
        total = sum(normalized.values())
        if total <= 0:
            continue
        normalized = {key: value / total for key, value in normalized.items()}
        predicted_label = max(normalized, key=normalized.get)
        confidence = normalized[predicted_label]
        correct = int(predicted_label == row["expected"]["decision"])
        brier = sum(
            (normalized[label] - int(label == row["expected"]["decision"])) ** 2
            for label in DECISIONS
        )
        samples.append((confidence, correct, brier))
    if not samples:
        return {"evaluated_cases": 0, "note": "No decision_probabilities supplied."}
    ece = 0.0
    for index in range(bins):
        lower, upper = index / bins, (index + 1) / bins
        bucket = [
            sample for sample in samples
            if lower <= sample[0] < upper or (index == bins - 1 and sample[0] == 1.0)
        ]
        if bucket:
            avg_conf = statistics.mean(item[0] for item in bucket)
            avg_acc = statistics.mean(item[1] for item in bucket)
            ece += len(bucket) / len(samples) * abs(avg_conf - avg_acc)
    return {
        "evaluated_cases": len(samples),
        "multiclass_brier_score": round(statistics.mean(x[2] for x in samples), 6),
        "expected_calibration_error": round(ece, 6),
        "bins": bins,
    }



def _wilson_interval(successes: int, total: int, z: float = 1.96) -> list[float] | None:
    """95% Wilson score interval for a binomial proportion."""
    if total <= 0:
        return None
    proportion = successes / total
    denominator = 1 + (z * z / total)
    center = (proportion + z * z / (2 * total)) / denominator
    margin = (
        z * math.sqrt(
            (proportion * (1 - proportion) / total)
            + (z * z / (4 * total * total))
        ) / denominator
    )
    return [round(max(0.0, center - margin), 6), round(min(1.0, center + margin), 6)]


def evaluate_records(rows: list[dict[str, Any]]) -> dict[str, Any]:
    y_true = [row["expected"]["decision"] for row in rows]
    y_pred = [row["predicted"]["decision"] for row in rows]
    decision = _classification_metrics(y_true, y_pred, DECISIONS)
    false_pass = sum(
        1 for actual, predicted in zip(y_true, y_pred)
        if actual != "PASS" and predicted == "PASS"
    )
    non_pass = sum(1 for actual in y_true if actual != "PASS")
    false_fail = sum(
        1 for actual, predicted in zip(y_true, y_pred)
        if actual != "FAIL" and predicted == "FAIL"
    )
    non_fail = sum(1 for actual in y_true if actual != "FAIL")

    return {
        "dataset": {"cases": len(rows), "unique_case_ids": len({r["case_id"] for r in rows})},
        "decision": {
            **decision,
            "false_pass_count": false_pass,
            "false_pass_rate_95pct_wilson_ci": _wilson_interval(false_pass, non_pass),
            "accuracy_95pct_wilson_ci": _wilson_interval(
                sum(1 for actual, predicted in zip(y_true, y_pred) if actual == predicted), len(y_true)
            ),
            "false_pass_rate_among_gold_non_pass": round(false_pass / non_pass, 6) if non_pass else None,
            "false_fail_count": false_fail,
            "false_fail_rate_among_gold_non_fail": round(false_fail / non_fail, 6) if non_fail else None,
            "gold_non_pass_cases": non_pass,
            "gold_non_fail_cases": non_fail,
        },
        "applicability": _mapping_metrics(rows, "applicability", APPLICABILITY),
        "requirement_status": _mapping_metrics(rows, "requirement_statuses", REQUIREMENT_STATUSES),
        "retrieval": _retrieval_metrics(rows),
        "evidence_grounding": _set_metrics(rows, "supported_claim_ids", "grounded_claim_ids"),
        "citations": _set_metrics(rows, "valid_citation_ids", "citation_ids"),
        "calibration": _calibration_metrics(rows),
        "limitations": [
            "Metrics are only as reliable as the human-reviewed gold labels.",
            "Missing optional labels are excluded from that metric, not counted as correct.",
            "A zero false-PASS count on a finite benchmark does not prove zero real-world risk.",
            "Review thresholds must be calibrated on representative, independently labelled data.",
        ],
    }


def render_markdown(report: dict[str, Any]) -> str:
    decision = report["decision"]
    lines = [
        "# Brand Guardian Evaluation Report",
        "",
        f"- Cases: **{report['dataset']['cases']}**",
        f"- Decision accuracy: **{decision['accuracy']}**",
        f"- Decision macro F1 (present classes): **{decision['macro_f1_present_classes']}**",
        f"- False PASS count: **{decision['false_pass_count']} / {decision['gold_non_pass_cases']} gold non-PASS cases**",
        f"- False PASS rate: **{decision['false_pass_rate_among_gold_non_pass']}**",
        "",
        "## Decision confusion matrix",
        "",
        "| Gold / Predicted | " + " | ".join(DECISIONS) + " |",
        "|---|" + "---:|" * len(DECISIONS),
    ]
    for actual in DECISIONS:
        lines.append("| " + actual + " | " + " | ".join(
            str(decision["confusion_matrix"][actual][pred]) for pred in DECISIONS
        ) + " |")
    lines.extend(["", "## Per-class metrics", "", "| Decision | Precision | Recall | F1 | Support |", "|---|---:|---:|---:|---:|"])
    for label, metrics in decision["per_class"].items():
        lines.append(
            f"| {label} | {metrics['precision']:.4f} | {metrics['recall']:.4f} | "
            f"{metrics['f1']:.4f} | {metrics['support']} |"
        )
    for section in ("applicability", "requirement_status", "retrieval", "evidence_grounding", "citations", "calibration"):
        lines.extend(["", f"## {section.replace('_', ' ').title()}", "", "```json",
                      json.dumps(report[section], indent=2, sort_keys=True), "```"])
    lines.extend(["", "## Limitations", ""])
    lines.extend(f"- {item}" for item in report["limitations"])
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Evaluate Brand Guardian against human-reviewed JSONL labels.")
    parser.add_argument("--dataset", required=True, help="Path to JSONL benchmark records.")
    parser.add_argument("--output-dir", default="backend/evaluation/reports", help="Report output directory.")
    args = parser.parse_args(argv)
    try:
        records = _load_jsonl(Path(args.dataset))
        report = evaluate_records(records)
        output_dir = Path(args.output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        (output_dir / "evaluation.json").write_text(
            json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        (output_dir / "evaluation.md").write_text(
            render_markdown(report), encoding="utf-8"
        )
        print(json.dumps({
            "cases": report["dataset"]["cases"],
            "accuracy": report["decision"]["accuracy"],
            "macro_f1": report["decision"]["macro_f1_present_classes"],
            "false_pass_count": report["decision"]["false_pass_count"],
            "reports": [
                str(output_dir / "evaluation.json"),
                str(output_dir / "evaluation.md"),
            ],
        }, indent=2))
        return 0
    except (OSError, EvaluationDataError, ValueError) as exc:
        print(f"Evaluation failed: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
