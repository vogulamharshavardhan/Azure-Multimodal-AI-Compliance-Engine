"""FastAPI entry point for the Brand Guardian compliance pipeline.

Run locally from the repository root:
    uv run uvicorn backend.src.api.server:app --host 127.0.0.1 --port 8000 --reload

Production requires API_KEY and should run behind a TLS-terminating gateway.
"""

from __future__ import annotations

import hmac
import logging
import os
import time
from collections import defaultdict, deque
from contextlib import asynccontextmanager
from pathlib import Path
from threading import BoundedSemaphore, Lock
from typing import Any, Literal

from dotenv import load_dotenv
from fastapi import Depends, FastAPI, Header, HTTPException, Request, status
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, ConfigDict, Field, HttpUrl, field_validator

PROJECT_ROOT = Path(__file__).resolve().parents[3]
load_dotenv(PROJECT_ROOT / ".env", override=False)

from backend.src.core.logging_config import setup_logging  # noqa: E402
from backend.src.core.exception_handlers import register_exception_handlers  # noqa: E402
from backend.src.core.exceptions import PipelineExecutionError  # noqa: E402
from backend.src.api.telemetry import setup_telemetry, shutdown_telemetry  # noqa: E402
from backend.src.api.tracing import (  # noqa: E402
    setup_langsmith_tracing,
    shutdown_langsmith_tracing,
)
from backend.src.services.audit_job_queue import AuditJobQueue  # noqa: E402

setup_logging()
logger = logging.getLogger("brand-guardian.api")

# Configure SDKs only after .env has been loaded and logging is ready.
telemetry_enabled = setup_telemetry()
langsmith_tracing_enabled = setup_langsmith_tracing()

from backend.src.graph.workflow import app as compliance_graph  # noqa: E402

APP_ENV = os.getenv("APP_ENV", "production").strip().lower()
API_KEY = os.getenv("API_KEY", "").strip()
RATE_LIMIT_PER_MINUTE = int(os.getenv("AUDIT_RATE_LIMIT_PER_MINUTE", "5"))
MAX_CONCURRENT_AUDITS = int(os.getenv("MAX_CONCURRENT_AUDITS", "2"))
_audit_slots = BoundedSemaphore(max(1, MAX_CONCURRENT_AUDITS))
_RATE_LIMIT_WINDOW_SECONDS = 60.0
_rate_limit_lock = Lock()
_request_times: dict[str, deque[float]] = defaultdict(deque)
_job_queue: AuditJobQueue | None = None
_job_queue_lock = Lock()


def get_audit_queue() -> AuditJobQueue:
    """Return the process-wide Redis queue client."""
    global _job_queue
    with _job_queue_lock:
        if _job_queue is None:
            _job_queue = AuditJobQueue()
        return _job_queue


def require_api_key(x_api_key: str | None = Header(default=None)) -> None:
    """Require a constant-time-checked API key for protected endpoints."""
    if len(API_KEY) < 32:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="API authentication is not configured with a sufficiently strong key.",
        )
    if not x_api_key or not hmac.compare_digest(x_api_key, API_KEY):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing API key.",
            headers={"WWW-Authenticate": "ApiKey"},
        )


def enforce_audit_rate_limit(request: Request) -> None:
    """Apply a per-process safety limit; enforce distributed limits at the gateway too."""
    if APP_ENV == "test":
        return
    if RATE_LIMIT_PER_MINUTE < 1:
        raise HTTPException(status_code=503, detail="Audit rate limiting is misconfigured.")
    client_host = request.client.host if request.client else "unknown"
    now = time.monotonic()
    with _rate_limit_lock:
        timestamps = _request_times[client_host]
        while timestamps and now - timestamps[0] >= _RATE_LIMIT_WINDOW_SECONDS:
            timestamps.popleft()
        if len(timestamps) >= RATE_LIMIT_PER_MINUTE:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Audit request limit exceeded. Try again later.",
                headers={"Retry-After": str(int(_RATE_LIMIT_WINDOW_SECONDS))},
            )
        timestamps.append(now)


async def audit_capacity():
    """Bound concurrent expensive audits in this API process."""
    if APP_ENV == "test":
        yield
        return
    if MAX_CONCURRENT_AUDITS < 1 or not _audit_slots.acquire(blocking=False):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Audit capacity is currently full. Retry shortly.",
            headers={"Retry-After": "30"},
        )
    try:
        yield
    finally:
        _audit_slots.release()



class AuditRequest(BaseModel):
    """Input contract for a single YouTube video compliance audit.

    Context fields are explicit requester assertions. Leave them UNKNOWN
    unless the relationship and intended placement are known.
    """

    model_config = ConfigDict(str_strip_whitespace=True)

    video_url: HttpUrl = Field(
        ...,
        description="HTTPS URL of a YouTube video to audit.",
        examples=["https://www.youtube.com/watch?v=EuyZP6_0sec"],
    )
    commercial_relationship: Literal[
        "UNKNOWN",
        "NONE",
        "PAID_SPONSORSHIP",
        "GIFTED",
        "AFFILIATE",
        "OTHER_MATERIAL_CONNECTION",
    ] = Field(
        default="UNKNOWN",
        description=(
            "Requester-confirmed commercial relationship. "
            "Use UNKNOWN if not established."
        ),
    )
    youtube_placement: Literal["UNKNOWN", "ORGANIC_UPLOAD", "PAID_AD"] = Field(
        default="UNKNOWN",
        description=(
            "Requester-confirmed placement. A normal YouTube upload "
            "is not automatically a paid ad."
        ),
    )

    ad_format: Literal["UNKNOWN", "SKIPPABLE_IN_STREAM", "NON_SKIPPABLE_IN_STREAM", "BUMPER", "IN_FEED", "SHORTS", "MASTHEAD"] = "UNKNOWN"
    jurisdiction: str = Field(default="UNKNOWN", max_length=80)

    @field_validator("video_url")
    @classmethod
    def validate_youtube_url(cls, value: HttpUrl) -> HttpUrl:
        """Reject non-HTTPS URLs and non-YouTube hosts."""
        if value.scheme != "https":
            raise ValueError("Only HTTPS YouTube URLs are accepted.")

        allowed_hosts = {
            "youtube.com",
            "www.youtube.com",
            "m.youtube.com",
            "music.youtube.com",
            "youtu.be",
            "www.youtu.be",
        }

        if value.host.lower().rstrip(".") not in allowed_hosts:
            raise ValueError("Only YouTube video URLs are accepted.")

        return value


class AuditResponse(BaseModel):
    """Stable API response contract for the audit workflow."""

    audit_context: dict[str, Any] = Field(default_factory=dict)
    screening_status: str | None = None
    policy_corpus_sha256: str | None = None
    policy_coverage_verified: bool = False
    required_user_inputs: list[str] = Field(default_factory=list)
    review_required: bool = False
    policy_registry: dict[str, Any] = Field(default_factory=dict)
    requirements_attempted: int = 0
    requirements_conclusively_evaluated: int = 0
    requirement_evaluation_status: str | None = None
    video_id: str | None = None
    azure_video_id: str | None = None
    indexing_status: str = "UNKNOWN"
    final_status: str = "REVIEW_REQUIRED"
    current_stage: str | None = None
    processing_complete: bool = False
    final_report: str | None = None
    policy_assessments: list[dict[str, Any]] = Field(default_factory=list)
    policy_coverage: dict[str, Any] = Field(default_factory=dict)
    requirement_assessments: list[dict[str, Any]] = Field(default_factory=list)
    audit_diagnostics: dict[str, Any] = Field(default_factory=dict)
    requirement_coverage: dict[str, Any] = Field(default_factory=dict)
    audit_decision_reasons: list[str] = Field(default_factory=list)
    compliance_results: list[dict[str, Any]] = Field(default_factory=list)
    citations: list[dict[str, Any]] = Field(default_factory=list)
    errors: list[dict[str, Any]] = Field(default_factory=list)
    extraction_status: dict[str, Any] = Field(default_factory=dict)
    video_metadata: dict[str, Any] = Field(default_factory=dict)


class AuditJobAccepted(BaseModel):
    job_id: str
    status: Literal["QUEUED"]
    status_url: str


class AuditJobStatus(BaseModel):
    job_id: str
    status: Literal["QUEUED", "RUNNING", "COMPLETED", "FAILED"]
    current_stage: str | None = None
    created_at: str | None = None
    updated_at: str | None = None
    result: dict[str, Any] | None = None
    error: dict[str, Any] | None = None


@asynccontextmanager
async def lifespan(_: FastAPI):
    logger.info("Brand Guardian API starting.")

    try:
        yield

    finally:
        logger.info("Brand Guardian API stopping.")
        global _job_queue
        if _job_queue is not None:
            try:
                _job_queue.close()
            except Exception:
                logger.exception("Could not close Redis queue client cleanly.")
            finally:
                _job_queue = None

        if langsmith_tracing_enabled:
            shutdown_langsmith_tracing()

        if telemetry_enabled:
            shutdown_telemetry()


# Create the FastAPI application before registering handlers or middleware.
app = FastAPI(
    title="Brand Guardian Compliance API",
    description=(
        "Video ingestion, transcript/OCR extraction, and "
        "evidence-grounded brand and regulatory compliance auditing."
    ),
    version="1.0.0",
    lifespan=lifespan,
)

register_exception_handlers(app)

# ------------------------------------------------------------
# CORS
# ------------------------------------------------------------

allowed_origins = [
    origin.strip()
    for origin in os.getenv(
        "CORS_ALLOWED_ORIGINS",
        "http://127.0.0.1:3000",
    ).split(",")
    if origin.strip()
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type", "Authorization", "X-API-Key"],
)


# ------------------------------------------------------------
# Health endpoints
# ------------------------------------------------------------

@app.get("/", tags=["Health"])
async def root() -> dict[str, str]:
    """Basic service information."""
    return {
        "service": "Brand Guardian Compliance API",
        "status": "running",
        "docs": "/docs",
    }


@app.get("/health", tags=["Health"])
async def health() -> dict[str, str]:
    """Liveness check. Does not verify Azure dependencies."""
    return {"status": "healthy"}


@app.get("/health/ready", tags=["Health"])
async def readiness() -> dict[str, Any]:
    """Configuration readiness check; does not make billable remote calls."""
    required = (
        "AZURE_STORAGE_CONNECTION_STRING",
        "AZURE_AI_FOUNDRY_ENDPOINT",
        "AZURE_AI_FOUNDRY_API_KEY",
        "GROK_DEPLOYMENT_NAME",
        "AZURE_OPENAI_EMBEDDING_ENDPOINT",
        "AZURE_OPENAI_EMBEDDING_API_KEY",
        "AZURE_OPENAI_EMBEDDING_DEPLOYMENT",
        "AZURE_SEARCH_ENDPOINT",
        "AZURE_SEARCH_API_KEY",
        "AZURE_SEARCH_INDEX_NAME",
        "AZURE_VI_ACCOUNT_ID",
        "AZURE_VI_LOCATION",
        "AZURE_SUBSCRIPTION_ID",
        "AZURE_RESOURCE_GROUP",
        "AZURE_VI_NAME",
        "REDIS_URL",
    )
    missing = [name for name in required if not os.getenv(name, "").strip()]
    auth_missing = len(API_KEY) < 32
    if auth_missing:
        missing.append("API_KEY")
    if not missing:
        try:
            if not get_audit_queue().ping():
                missing.append("REDIS_CONNECTION")
        except Exception:
            missing.append("REDIS_CONNECTION")
    if missing:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"status": "not_ready", "missing_configuration": missing},
        )
    return {"status": "ready", "configuration_present": True, "redis_connected": True}


@app.get("/health/config", tags=["Health"], dependencies=[Depends(require_api_key)])
async def health_config() -> dict[str, Any]:
    """Report non-secret configuration presence for operational checks."""
    return {
        "status": "configured",
        "azure_monitor_enabled": telemetry_enabled,
        "langsmith_tracing_enabled": langsmith_tracing_enabled,
        "langsmith_api_key_present": bool(
            os.getenv("LANGSMITH_API_KEY") or os.getenv("LANGCHAIN_API_KEY")
        ),
        "grok_endpoint_configured": bool(
            os.getenv("AZURE_AI_FOUNDRY_ENDPOINT")
        ),
        "grok_api_key_present": bool(os.getenv("AZURE_AI_FOUNDRY_API_KEY")),
        "embedding_endpoint_configured": bool(
            os.getenv("AZURE_OPENAI_EMBEDDING_ENDPOINT")
        ),
        "search_endpoint_configured": bool(os.getenv("AZURE_SEARCH_ENDPOINT")),
        "video_indexer_configured": all(
            os.getenv(key)
            for key in (
                "AZURE_VI_ACCOUNT_ID",
                "AZURE_VI_LOCATION",
                "AZURE_SUBSCRIPTION_ID",
                "AZURE_RESOURCE_GROUP",
                "AZURE_VI_NAME",
            )
        ),
    }


# ------------------------------------------------------------
# Durable queued audit endpoints
# ------------------------------------------------------------

@app.post(
    "/audit/jobs",
    response_model=AuditJobAccepted,
    status_code=status.HTTP_202_ACCEPTED,
    tags=["Compliance"],
    summary="Queue a YouTube video audit",
    dependencies=[Depends(require_api_key), Depends(enforce_audit_rate_limit)],
)
async def submit_audit_job(payload: AuditRequest) -> AuditJobAccepted:
    """Enqueue a durable audit job and return immediately."""
    try:
        queue = get_audit_queue()
        if not queue.ping():
            raise RuntimeError("Redis health check failed")
        job_id = queue.enqueue(payload.model_dump(mode="json"))
        return AuditJobAccepted(
            job_id=job_id,
            status="QUEUED",
            status_url=f"/audit/jobs/{job_id}",
        )
    except Exception as exc:
        logger.error("Unable to enqueue audit job. error_type=%s", type(exc).__name__)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Audit queue is unavailable. Try again later.",
        ) from None


@app.get(
    "/audit/jobs/{job_id}",
    response_model=AuditJobStatus,
    tags=["Compliance"],
    summary="Get audit job status and result",
    dependencies=[Depends(require_api_key)],
)
async def get_audit_job(job_id: str) -> AuditJobStatus:
    """Retrieve a queued audit status or completed result."""
    try:
        job = get_audit_queue().get_job(job_id)
    except Exception as exc:
        logger.error("Unable to retrieve audit job. error_type=%s", type(exc).__name__)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Audit queue is unavailable. Try again later.",
        ) from None
    if job is None:
        raise HTTPException(status_code=404, detail="Audit job was not found or has expired.")
    return AuditJobStatus(
        job_id=job_id,
        status=job.get("status", "FAILED"),
        current_stage=job.get("current_stage"),
        created_at=job.get("created_at"),
        updated_at=job.get("updated_at"),
        result=job.get("result"),
        error=job.get("error"),
    )


# ------------------------------------------------------------
# Synchronous compatibility endpoint
# ------------------------------------------------------------

@app.post(
    "/audit",
    response_model=AuditResponse,
    status_code=status.HTTP_200_OK,
    tags=["Compliance"],
    summary="Audit a YouTube video",
    dependencies=[
        Depends(require_api_key),
        Depends(enforce_audit_rate_limit),
        Depends(audit_capacity),
    ],
)
async def audit_video(payload: AuditRequest) -> AuditResponse:
    """Execute the compiled video compliance workflow."""
    video_url = str(payload.video_url)

    logger.info(
        "Video audit request accepted. commercial_relationship=%s "
        "youtube_placement=%s",
        payload.commercial_relationship,
        payload.youtube_placement,
    )

    initial_state: dict[str, Any] = {
        "video_url": video_url,
        "audit_context": {
            "commercial_relationship": payload.commercial_relationship,
            "youtube_placement": payload.youtube_placement,
            "ad_format": payload.ad_format,
            "jurisdiction": payload.jurisdiction,
        },
        "indexing_status": "PENDING",
        "final_status": "PENDING",
        "compliance_results": [],
        "errors": [],
        "citations": [],
        "transcript_segments": [],
        "ocr_segments": [],
        "raw_ocr_segments": [],
        "ocr_classifications": [],
        "processing_complete": False,
    }

    try:
        # ainvoke avoids directly blocking FastAPI's event loop.
        result = await compliance_graph.ainvoke(
            initial_state,
            config={
                "run_name": "brand-guardian-video-audit",
                "tags": ["brand-guardian", "video-compliance", "api"],
                "metadata": {
                    "video_platform": "youtube",
                    "commercial_relationship": payload.commercial_relationship,
                    "youtube_placement": payload.youtube_placement,
                },
            },
        )

        if not isinstance(result, dict):
            raise TypeError(
                "The compliance graph returned an unexpected result."
            )

        from backend.src.auditing.public_report import public_result
        return AuditResponse(**public_result(result, initial_state["audit_context"]))

    except Exception as exc:
        # The centralized handler logs the traceback and returns a safe message.
        raise PipelineExecutionError() from exc


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "backend.src.api.server:app",
        host=os.getenv("HOST", "127.0.0.1"),
        port=int(os.getenv("PORT", "8000")),
        reload=os.getenv("RELOAD", "false").lower() == "true",
    )
