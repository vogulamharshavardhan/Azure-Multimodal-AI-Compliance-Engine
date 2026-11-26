# Setup, deployment and operations

## Environment configuration

Copy `.env.example` to `.env` only for a fresh setup. Fill placeholders locally; do not share values.

| Group | Variables (representative) |
|---|---|
| Application | `APP_ENV`, `API_KEY`, `LOG_LEVEL`, `MAX_QUEUED_AUDITS`, `MAX_CONCURRENT_AUDITS` |
| Redis | `REDIS_PASSWORD`, `REDIS_URL` (Compose overrides API/worker URL) |
| Azure storage | `AZURE_STORAGE_CONNECTION_STRING`, `AZURE_STORAGE_CONTAINER_NAME` |
| Video Indexer | `AZURE_VI_NAME`, `AZURE_VI_ACCOUNT_ID`, `AZURE_VI_LOCATION`, `AZURE_SUBSCRIPTION_ID`, `AZURE_RESOURCE_GROUP`; Azure identity settings as needed |
| Foundry | `AZURE_AI_FOUNDRY_ENDPOINT`, `AZURE_AI_FOUNDRY_API_KEY`, `GROK_DEPLOYMENT_NAME` |
| Embeddings | `AZURE_OPENAI_EMBEDDING_ENDPOINT`, `AZURE_OPENAI_EMBEDDING_API_KEY`, `AZURE_OPENAI_EMBEDDING_DEPLOYMENT`, `AZURE_OPENAI_EMBEDDING_API_VERSION` |
| Search | `AZURE_SEARCH_ENDPOINT`, `AZURE_SEARCH_API_KEY`, `AZURE_SEARCH_INDEX_NAME`, `MIN_POLICY_RELEVANCE_SCORE` |
| Tracing | `LANGSMITH_TRACING`, `LANGSMITH_API_KEY`, `LANGSMITH_PROJECT`, `LANGSMITH_ENDPOINT` |
| Telemetry | `APPLICATIONINSIGHTS_CONNECTION_STRING` (optional) |
| Performance | `EXTRACTION_CACHE_TTL_SECONDS`, `OCR_BATCH_CONCURRENCY` |

Use the complete template in the source for remaining settings. Review policy sources before indexing into a dedicated index. See [policy sources](POLICY_SOURCES.md).

## Start and inspect (Windows CMD)

```cmd
docker compose up -d --build
docker compose ps
curl http://127.0.0.1:8000/health/ready
docker compose logs -f --tail=50 brand-guardian-worker
```

Use another terminal for `uv run streamlit run dashboard.py --server.address 127.0.0.1`. Stop log following with Ctrl+C; this does not stop containers. Avoid `docker compose down -v`, which removes volumes. Build only when code/image changes; for worker-only environment changes after jobs finish, `docker compose up -d --no-build --force-recreate brand-guardian-worker`.

## LangSmith

Configure tracing through the environment and inspect project `brand-guardian-prod` (observed local project name). Open a root run, expand `indexer`, `ocr_classifier`, `policy_applicability`, `auditor` as available. Inspect model child runs for timing, identity and tokens. The observed `ChatOpenAI` wrapper reported Grok deployment `grok-4-20-reasoning`. A green trace is technical execution success, not legal clearance. Mask prompts, account identifiers and private data.

## Redis Insight

The demonstrated Docker network is `brandguardian_default`; confirm your own network with `docker network ls` before installation.

```cmd
docker run -d --name redisinsight --network brandguardian_default -p 127.0.0.1:5540:5540 -v redisinsight:/data redis/redisinsight:latest
```

If already installed, do not recreate; use `docker start redisinsight` only if stopped. Open http://127.0.0.1:5540. Connect to host `redis` or `brandguardian-redis-1`, port 6379, user `default`, existing Redis password, database 0, non-TLS for this local topology. Keep credentials private. Redis is not exposed on the host in the demonstrated Compose setup.

Browse → `brand_guardian:audit_jobs` → Consumer Groups. Observe pending messages before/during/after a permitted test. Registered consumer count is not active worker count. Analyze → Slow Log shows commands exceeding configured threshold, not necessarily faults. Never delete keys or create groups for a monitoring demonstration.

Read-only commands in Redis Insight CLI:

```redis
XLEN brand_guardian:audit_jobs
XINFO GROUPS brand_guardian:audit_jobs
XINFO CONSUMERS brand_guardian:audit_jobs brand_guardian:audit_workers
XPENDING brand_guardian:audit_jobs brand_guardian:audit_workers
```

## Troubleshooting

| Symptom | Action |
|---|---|
| API port 8000 unavailable | Check `docker compose ps` and other containers for conflicts; avoid stopping unrelated services |
| Redis Insight cannot reach localhost | Use Compose service/container hostname on shared Docker network |
| Authentication failed | Use configured Redis password; do not reset a working service during an audit |
| Dashboard shows previous result | Paste desired job ID in Job ID (refresh or resume), click Refresh status |
| Empty stream after audit | Check stored job status; cleared pending entries alone do not prove success |
| Cache DISABLED | Check worker's non-secret environment settings; enable TTL only if acceptable |
| LLM transient connection failures | Inspect worker logs; reduce OCR concurrency if needed after jobs finish |

## Security and retention

Rotate the previously disclosed Redis credential and any other exposed keys before publication, updating all dependent services and Redis Insight together during maintenance. Avoid printing full Compose configuration or container environments because they may contain secrets. Keep `.env`, audit JSON, logs, downloaded media, policy corpus (pending rights review), caches and credential files out of Git. Scan staged files AND history before public push. Local shared-key deployment is not a multi-tenant security boundary. Review Azure storage lifecycle and trace retention; delete sensitive data according to applicable policy. No comprehensive security audit is claimed.

## Application Insights troubleshooting

### Azure Monitor / Application Insights

Brand Guardian includes configuration-dependent OpenTelemetry/Azure Monitor integration in `backend/src/api/telemetry.py`. Set `APPLICATIONINSIGHTS_CONNECTION_STRING` locally (never commit the value). The Azure portal Application Insights resource displayed live dependency telemetry and an Application Map during the November 26, 2026 review. Together with LangSmith and Redis Insight, this demonstrates three complementary observability surfaces: AI execution, job processing, and application/dependency telemetry.

**Observed Application Map — last 24 hours:**

| Dependency | Calls | Reported failure rate |
| --- | ---: | ---: |
| Azure Video Indexer | 77 | 0% |
| LangSmith API | 64 | 0% |
| Azure AI endpoint | 59 | 22% |
| Azure Monitor settings | 30 | 0% |
| YouTube | 21 | 0% |
| Microsoft authentication | 20 | 0% |
| Azure AI Search | 12 | 0% |
| Azure Instance Metadata endpoint | 6 | 100% |
| Azure Resource Management | 5 | 0% |

The displayed failure percentages are rounded portal observations, not SLAs. The grouped HTTP edge showed 294 calls and 100% in the map, which must not be interpreted as every individual dependency failing: the drill-down reports different rates. Eight reported application instances are not proof of eight concurrently running containers. The metadata address `169.254.169.254` is consistent with a local Docker environment attempting Azure metadata discovery, but the exact caller/cause is unconfirmed. The Azure AI endpoint failures need investigation; prior connection errors are a possible explanation, not a confirmed root cause. Telemetry collection is verified; dependency health and retry effectiveness are not fully validated.

<!-- Azure screenshot: ![Azure Application Insights dependency map](docs/screenshots/azure_application_map.png) -->

**Investigate dependency failures:** Azure portal → Application Insights → Application map → dependency edge → View in Logs. For the Application Insights `dependencies` schema, run:

```kusto
dependencies
| where timestamp > ago(24h)
| summarize Calls = sum(itemCount), Failed = sumif(itemCount, success == false), AvgLatencyMs = round(avg(duration), 2) by target, resultCode
| extend FailureRate = round(100.0 * Failed / Calls, 2)
| order by Failed desc
```

```kusto
dependencies
| where timestamp > ago(24h)
| where target contains "services.ai.azure" and success == false
| project timestamp, target, name, resultCode, duration
| order by timestamp desc
```

These are diagnostic examples, not queries executed for this release. If using the workspace-native `AppDependencies` table, adapt the column names to that schema. Inspect actual failure codes and correlated worker logs before changing timeouts, retry policies or credentials. Avoid exposing sensitive dependency URLs or trace payloads.

