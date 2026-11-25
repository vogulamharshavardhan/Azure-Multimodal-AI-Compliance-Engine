# Brand Guardian Evaluation Report

- Cases: **4**
- Decision accuracy: **1.0**
- Decision macro F1 (present classes): **1.0**
- False PASS count: **0 / 4 gold non-PASS cases**
- False PASS rate: **0.0**

## Decision confusion matrix

| Gold / Predicted | PASS | FAIL | REVIEW_REQUIRED | NOT_APPLICABLE |
|---|---:|---:|---:|---:|
| PASS | 0 | 0 | 0 | 0 |
| FAIL | 0 | 1 | 0 | 0 |
| REVIEW_REQUIRED | 0 | 0 | 2 | 0 |
| NOT_APPLICABLE | 0 | 0 | 0 | 1 |

## Per-class metrics

| Decision | Precision | Recall | F1 | Support |
|---|---:|---:|---:|---:|
| PASS | 0.0000 | 0.0000 | 0.0000 | 0 |
| FAIL | 1.0000 | 1.0000 | 1.0000 | 1 |
| REVIEW_REQUIRED | 1.0000 | 1.0000 | 1.0000 | 2 |
| NOT_APPLICABLE | 1.0000 | 1.0000 | 1.0000 | 1 |

## Applicability

```json
{
  "count": 0,
  "note": "No aligned labels supplied."
}
```

## Requirement Status

```json
{
  "count": 0,
  "note": "No aligned labels supplied."
}
```

## Retrieval

```json
{
  "evaluated_cases": 0,
  "note": "No relevant_chunk_ids supplied."
}
```

## Evidence Grounding

```json
{
  "evaluated_cases": 0,
  "f1": 0.0,
  "false_negative": 0,
  "false_positive": 0,
  "precision": 0.0,
  "recall": 0.0,
  "true_positive": 0
}
```

## Citations

```json
{
  "evaluated_cases": 0,
  "f1": 0.0,
  "false_negative": 0,
  "false_positive": 0,
  "precision": 0.0,
  "recall": 0.0,
  "true_positive": 0
}
```

## Calibration

```json
{
  "evaluated_cases": 0,
  "note": "No decision_probabilities supplied."
}
```

## Limitations

- Metrics are only as reliable as the human-reviewed gold labels.
- Missing optional labels are excluded from that metric, not counted as correct.
- A zero false-PASS count on a finite benchmark does not prove zero real-world risk.
- Review thresholds must be calibrated on representative, independently labelled data.
