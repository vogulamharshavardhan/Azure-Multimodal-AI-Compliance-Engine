# API reference

Base URL: `http://127.0.0.1:8000`. Interactive docs: `/docs`. The checked-in `openapi.json` is a reference; compare against live `/openapi.json` if schema drift occurs.

## Submit an audit

`POST /audit/jobs` with headers `Content-Type: application/json` and `X-API-Key: <configured key>`.

```json
{
  "video_url": "https://www.youtube.com/watch?v=F1Lt8isKPlk",
  "commercial_relationship": "PAID_SPONSORSHIP",
  "youtube_placement": "ORGANIC_UPLOAD",
  "ad_format": "UNKNOWN",
  "jurisdiction": "US"
}
```

Context is supplied by requester, not inferred legal fact. Only HTTPS YouTube hosts are accepted. Relationship: UNKNOWN, NONE, PAID_SPONSORSHIP, GIFTED, AFFILIATE, OTHER_MATERIAL_CONNECTION. Placement: UNKNOWN, ORGANIC_UPLOAD, PAID_AD. Format: UNKNOWN, SKIPPABLE_IN_STREAM, NON_SKIPPABLE_IN_STREAM, BUMPER, IN_FEED, SHORTS, MASTHEAD. Jurisdiction is a string; the FTC disclosure path supports US scope. Use UNKNOWN rather than guessing.

Use the CLI to avoid embedding keys in shell history:

```cmd
uv run python submit_audit.py "https://www.youtube.com/watch?v=F1Lt8isKPlk" --relationship PAID_SPONSORSHIP --placement ORGANIC_UPLOAD --ad-format UNKNOWN --jurisdiction US
uv run python check_audit.py
```

## Poll result

`GET /audit/jobs/{job_id}` with the API key. Job envelope includes ID, status, stage, timestamps, result and error. Execution states include QUEUED, PROCESSING, COMPLETED and FAILED. The dashboard can resume a job ID. `POST /audit` is a synchronous compatibility endpoint. Health endpoints `/health` and `/health/ready` support basic checks; `/health/config` is authenticated.

## Result interpretation

| Field | Meaning |
|---|---|
| `final_status` | Conservative public screening decision |
| `policy_assessments` | Domain applicability and context basis |
| `requirement_assessments` | Individual scope, evaluation status, reasoning, evidence and policy references |
| `audit_diagnostics` | Supplied/omitted evidence, retained/rejected references and contradictions |
| `policy_coverage_verified` | Whether complete policy coverage is verified; false in recorded audits |
| `stage_events`, `elapsed_seconds` | Processing progress and latency |
| `extraction_cache_status` | Extraction cache outcome, separate from model prompt caching |

`APPLICABLE / INSUFFICIENT_EVIDENCE` means a rule applies but cannot be resolved. `GROUNDED` citation status indicates source provenance, not verified legal correctness. `verified: true` on evidence refers to catalog resolution, not independent verification of the original video. A completed audit can legitimately return REVIEW_REQUIRED. Zero rejected IDs does not imply that IDs were submitted.
