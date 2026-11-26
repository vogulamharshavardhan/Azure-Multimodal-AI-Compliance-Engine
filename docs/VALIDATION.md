# Validation and observed results

## Regression evidence

On Windows, Python 3.14.3, `uv run pytest -v` collected 105 tests: all passed in 72.93 s with 18 dependency deprecation warnings (17 LangSmith-related and one langchain-community warning). `uv run python -m backend.evaluation.smoke_v21` returned 4/4 synthetic decision guard cases passed. The five V2.2 tests cover late disclosure candidate preservation, policy ID provenance/domain isolation, applicability preservation when citations are missing, conservative absence handling and recovery of raw OCR candidates. Test success is not measured AI accuracy.

## Live audit comparison

Same 304.9-second US sponsorship test scenario, requester-provided paid sponsorship and organic upload context.

| Metric | V2.1 Nov 25 | V2.2 Nov 25 | V2.2 Nov 26 |
|---|---:|---:|---:|
| Elapsed (s) | 696.016 | 498.671 | 508.931 |
| Retrieved passages | 8 (worker log) | 8 | 8 |
| Retained citation locations | 0 | 4 | 5 |
| Identified requirements | 3 | 2 | 3 |
| Applicable | 0 | 2 | 3 |
| Uncertain | 3 | 0 | 0 |
| Insufficient evidence | 0 | 2 | 3 |
| Not evaluated | 3 | 0 | 0 |
| Conclusive | 0 | 0 | 0 |
| Supplied / total evidence segments | not reported | 102/241 | 102/241 |
| Omitted disclosure candidates | not reported | 0 of 6 | 0 of 6 |
| Rejected policy refs | not reported | 0 | 0 |
| Final decision | REVIEW_REQUIRED | REVIEW_REQUIRED | REVIEW_REQUIRED |

V2.2 first run returned timestamped OCR records for sponsorship text. The latest run did not retain any requirement-level supporting evidence, despite global candidate preservation and grounded policy references. Both V2.2 runs used an unreviewed registry, unverified coverage and disabled extraction cache. Requirement count and IDs changed. Do not present these observations as a controlled model-quality experiment or proof of compliance.

## Observability evidence

- LangSmith trace waterfall for first V2.2 run: root 498.65 s, indexer 370.16 s, OCR classifier 72.97 s. A child model call displayed Grok deployment, 94% prompt-cache hit rate, 5.739K total tokens. This cache metric is not Redis extraction caching.
- Redis Insight: before submission zero stream entries; during processing one stream entry and one pending message; after processing zero entries and zero pending. Final JSON for matching job reported COMPLETED. Source code uses XACK and XDEL after terminal persistence.
- Redis Slow Log showed HGETALL, EVAL and XADD; threshold was 10 ms. This is a diagnostic observation, not a throughput/load test.

## Future evaluation protocol

Use `backend/evaluation/record.schema.json` and the evaluation README to build a human-reviewed dataset. Label applicability, requirement outcomes, relevant policy passages, supporting video evidence and final screening outcomes. Include ambiguous, missing-disclosure and adequately disclosed cases, multiple durations and relevant jurisdictions. Measure false-PASS rate, requirement coverage, retrieval recall, evidence grounding and latency/cost separately. Record model, corpus and run configuration; repeat on a held-out set. No such independent benchmark has yet been completed.

## Azure Application Insights validation (Nov 26, 2026)

Live Application Map telemetry and dependency drill-down were observed. Azure Video Indexer (77 calls), LangSmith (64) and Azure AI Search (12) each reported 0% failures in the inspected window. The Azure AI endpoint reported 22% of 59 calls and metadata endpoint 100% of 6 calls. Failure codes and causes remain unverified. See the README for the full table and diagnostic KQL. No SLA or production health guarantee is claimed.
