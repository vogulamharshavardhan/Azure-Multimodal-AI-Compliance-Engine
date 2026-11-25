"""FastAPI exception-handler registration and safe error responses."""
from __future__ import annotations

import logging

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from backend.src.core.exceptions import CompliancePipelineError

logger = logging.getLogger("brand-guardian.exceptions")


def register_exception_handlers(app: FastAPI) -> None:
    """Register handlers for known pipeline errors and unexpected failures."""

    @app.exception_handler(CompliancePipelineError)
    async def handle_pipeline_error(
        request: Request, exc: CompliancePipelineError
    ) -> JSONResponse:
        logger.exception(
            "Pipeline error. method=%s path=%s error_type=%s",
            request.method, request.url.path, type(exc).__name__,
        )
        return JSONResponse(
            status_code=exc.status_code,
            content={"detail": exc.public_message},
        )

    @app.exception_handler(Exception)
    async def handle_unexpected_error(
        request: Request, exc: Exception
    ) -> JSONResponse:
        logger.exception(
            "Unhandled application error. method=%s path=%s error_type=%s",
            request.method, request.url.path, type(exc).__name__,
        )
        return JSONResponse(
            status_code=500,
            content={"detail": "An unexpected server error occurred. Check server logs."},
        )
