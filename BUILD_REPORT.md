# Upgrade build report

## Delivered
- Preserved original FastAPI, LangGraph, Azure, Redis, Docker, evaluation and CI architecture, with the existing dependency lock.
- Removed the uploaded `.env` and stale job file from the distributable archive. Added local audit artifacts to Git ignore.
- Replaced hardcoded submission/polling inputs with reusable CLI and dashboard, and exposed stage progress through queued job status.
- Added explicit ad format and jurisdiction context, shared public report mapping, required-input hints and local policy corpus fingerprint.
- Tightened retrieval scope by source family and bound citations to a single retrieved source/page/quote block; allowed non-PDF page references.
- Added a conservative public decision boundary: raw screening PASS is not regulatory clearance. Final PASS stays disabled pending independent approval of comprehensive policy coverage.
- Added draft policy inventory, standalone deterministic numeric-check helper, synthetic offline demo, and nine new regression tests.

## Verification actually performed
- Python 3.13.5 local runtime: source compilation passed for backend and entrypoints.
- `python -m pytest -q tests/test_screening_upgrade.py tests/test_evaluation_metrics.py tests/test_tracing_config.py`: **18 passed** (nine new tests and nine existing tests).
- `python demo_offline.py`: ran four synthetic report scenarios successfully. This is not an LLM benchmark.
- `uv sync --frozen --offline --no-python-downloads`: blocked; the pinned Python 3.14.3 interpreter was not available.
- Full test collection attempted using the available Python: blocked by 13 collection errors due to unavailable Azure, LangChain, LangGraph, Redis and yt-dlp packages. No cloud services or Docker containers were started. The UI was not run interactively.

## Important decisions and limits
The supplied policy corpus is not independently verified as complete or current; this build does not add unverified policy thresholds. The draft registry and numeric checks are not integrated as a complete regulatory rule engine. Numeric checks must use verified original campaign assets rather than downloaded/transcoded YouTube copies. Retrieval scope filtering is client-side, not an Azure index filter. Job progress is at graph-node boundaries. Advanced queue retries, idempotency, fencing, checkpointing, and dead-letter handling remain future work. No production readiness or model accuracy claim is made. The original `openapi.json` is a pre-existing snapshot; the authoritative updated API schema is generated at runtime at `/openapi.json` (see `/docs`). The original dependency pins and Docker build are not validated here. Configure credentials locally and execute the full test suite and end-to-end cloud audit before deployment.
