# Brand Guardian evaluation

This is an offline, deterministic benchmark evaluator. It compares saved pipeline
outputs with independently human-reviewed gold labels. It does not call Grok,
Azure, or any external evaluator and does not create labels.

## Run

Create a JSON Lines dataset in the schema described in `record.schema.json`, then:

```cmd
uv run python -m backend.evaluation.evaluate --dataset path\to\benchmark.jsonl
```

Reports are written to `backend/evaluation/reports/evaluation.json` and
`evaluation.md`. Do not commit sensitive video content, transcripts, API keys,
SAS URLs, or personally identifying data in benchmark files.

## Record contract

Each JSONL line is one case:

- `case_id`: stable unique case identifier.
- `expected`: human-reviewed gold assessment.
- `predicted`: output from the exact pipeline version being evaluated.

Required in both assessments:
- `decision`: `PASS`, `FAIL`, `REVIEW_REQUIRED`, or `NOT_APPLICABLE`.

Optional aligned labels:
- `applicability`: domain name to `APPLICABLE`, `NOT_APPLICABLE`, or `UNCERTAIN`.
- `requirement_statuses`: requirement ID to `COMPLIANT`, `NON_COMPLIANT`,
  `INSUFFICIENT_EVIDENCE`, or `NOT_EVALUATED`.

Optional retrieval/evidence labels:
- `expected.relevant_chunk_ids`: gold relevant policy chunk IDs, ordered only
  when the benchmark protocol explicitly defines an ideal ranking.
- `predicted.relevant_chunk_ids`: retrieved chunk IDs in actual rank order.
- `expected.supported_claim_ids`: claims that the cited source evidence truly supports.
- `predicted.grounded_claim_ids`: claims the pipeline asserts are grounded.
- `expected.valid_citation_ids`: citations adjudicated as valid.
- `predicted.citation_ids`: citations emitted by the pipeline.

Optional calibration:
- `predicted.decision_probabilities`: probability distribution across all four
  decision classes. Values must sum to approximately 1.

See `record.schema.json` for the machine-readable schema.

## Metrics

The report includes:
- Decision accuracy, per-class precision/recall/F1, macro F1, and confusion matrix.
- False-PASS count and rate among all gold non-PASS cases. This is deliberately
  conservative: PASS predicted for gold FAIL, REVIEW_REQUIRED, or NOT_APPLICABLE
  is counted as a false PASS.
- Applicability and requirement-status classification metrics over aligned labels.
- Retrieval Precision@K, Recall@K, nDCG@K, and MRR when gold relevant chunk IDs exist.
- Evidence grounding and citation precision/recall/F1 using adjudicated ID sets.
- Multiclass Brier score and expected calibration error when probability outputs exist.

Missing optional labels are excluded from that metric, not treated as correct.
The report records this limitation.

## Gold dataset protocol (required before reporting model quality)

1. Define the target population and supported policy jurisdictions / ad formats.
2. Sample representative videos across paid sponsorship, gifted products,
   affiliate links, organic uploads, paid-ad creatives, ambiguous cases,
   languages, video lengths, disclosure placements, and OCR quality.
3. Have two qualified reviewers independently label applicability, each
   applicable requirement, evidence spans, policy passages, citations, and final
   decision. Adjudicate disagreements before the records enter the gold set.
4. Keep a creator/channel-level and time-based holdout. Do not split clips from
   the same source video across train/tuning and test partitions.
5. Version the policy corpus, prompts, model deployment, code commit, and
   annotation guide alongside each benchmark run.
6. Report sample counts and confidence intervals with metrics. Review class
   imbalance. Do not infer production safety from a small test set.

## Release gates

Do not hard-code a universal accuracy threshold before the first representative
gold benchmark exists. Establish thresholds with compliance owners. At minimum:
- No false PASS in the release test set, with its denominator and confidence
  interval shown. This is a release gate, not proof of zero population risk.
- FAIL precision must be high enough to avoid unsupported allegations.
- REVIEW_REQUIRED must remain available when scope or evidence is uncertain.
- NOT_APPLICABLE must never be counted as PASS.
- No requirement may be marked compliant solely because evidence is missing.
- Re-run the same frozen benchmark after changes to prompts, model deployment,
  policy corpus, retrieval settings, or decision logic.

## Important limitations

This evaluator measures agreement with the gold labels, not legal correctness.
It does not automatically execute the video pipeline or generate human labels.
The `predicted` assessment must come from an actual saved pipeline run. Scores
must not be reported until a sufficiently representative, adjudicated dataset
has been created and evaluated.
