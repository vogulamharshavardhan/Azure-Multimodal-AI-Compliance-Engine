# Demonstration and screenshot guide

## Four-minute walkthrough

0:00–0:30: Explain the problem: manual review of sponsorship disclosures is time-consuming and evidence must be traceable.

0:30–1:15: Show architecture: FastAPI → Redis Streams → worker/LangGraph → Video Indexer/Grok/RAG → grounded report.

1:15–2:00: Show dashboard submission and context. Open a previously completed audit by job ID; disclose that it is a saved result.

2:00–2:45: Expand requirement findings, citations, grounding diagnostics and stage timings. Explain REVIEW_REQUIRED, not a compliance approval.

2:45–3:30: Show LangSmith waterfall and model token monitoring; show Redis Insight pending 1 → 0 and matching completed result.

3:30–4:00: Show 105 tests and 4 synthetic checks. Explain remaining limitations and unverified model accuracy.

## Screenshot placement

Create `docs/screenshots/` in your repository. Save your own sanitized captures using these names. This pack includes the actual dashboard and completed Redis captures (identifiers masked) and a narrated walkthrough at `docs/demo.mp4`. Other screenshots listed below are optional and should be added only from your own sanitized captures.

| Filename | Capture |
|---|---|
| `dashboard.png` | Submission and completed screening report |
| `grounding_diagnostics.png` | Candidate counts, citations and stage details |
| `langsmith_traces.png` | Trace overview |
| `langgraph_workflow.png` | Expanded execution waterfall |
| `grok_token_usage.png` | Model identity and token breakdown |
| `redis_database.png` | Namespace, job hashes, stream |
| `redis_slow_log.png` | XADD/EVAL/HGETALL with sensitive identifiers masked |
| `redis_job_processing.png` | One pending message |
| `redis_job_completed.png` | Zero pending messages |
| `test_results.png` | 105 passing tests |

After saving the images, add Markdown links or image embeds to the README, e.g. `![Redis job processing](docs/screenshots/redis_job_processing.png)`. Verify the exact path first. Do not show keys, private prompt data, SAS URLs, job IDs or account identifiers. Do not publish raw JSON unless reviewed and sanitized.

## Azure Application Insights

Show the bundled sanitized `docs/screenshots/azure_application_map.png` after the Redis demonstration. Explain the three observability layers and the difference between successful telemetry ingestion and dependency health. The narrated video predates this verification; use the screenshot as a separate updated exhibit.
