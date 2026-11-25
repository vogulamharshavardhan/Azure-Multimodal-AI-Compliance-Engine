"""LangSmith tracing configuration and graceful shutdown."""

import logging
import os
from threading import Lock

from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger("brand-guardian.tracing")
_tracing_shutdown = False
_tracing_shutdown_lock = Lock()


def setup_langsmith_tracing() -> bool:
    """Enable LangChain/LangGraph tracing when explicitly configured.

    Supports current LANGSMITH_* names and legacy LANGCHAIN_* names.
    This function never logs or returns API keys.
    """
    tracing_value = os.getenv("LANGSMITH_TRACING")
    if tracing_value is None:
        tracing_value = os.getenv("LANGCHAIN_TRACING_V2", "false")
    enabled = tracing_value.strip().lower() in {"1", "true", "yes", "on"}

    api_key = (
        os.getenv("LANGSMITH_API_KEY")
        or os.getenv("LANGCHAIN_API_KEY")
        or ""
    ).strip()

    if not enabled:
        logger.warning("LangSmith tracing is disabled by configuration.")
        return False
    if not api_key:
        logger.error("LangSmith tracing was requested but no API key is configured.")
        return False

    os.environ["LANGSMITH_TRACING"] = "true"
    os.environ["LANGCHAIN_TRACING_V2"] = "true"
    if not os.getenv("LANGSMITH_API_KEY"):
        os.environ["LANGSMITH_API_KEY"] = api_key
    if not os.getenv("LANGSMITH_ENDPOINT"):
        os.environ["LANGSMITH_ENDPOINT"] = os.getenv(
            "LANGCHAIN_ENDPOINT", "https://api.smith.langchain.com"
        )

    project = (
        os.getenv("LANGSMITH_PROJECT")
        or os.getenv("LANGCHAIN_PROJECT")
        or "brand-guardian"
    )
    os.environ["LANGSMITH_PROJECT"] = project
    os.environ["LANGCHAIN_PROJECT"] = project

    logger.info("LangSmith tracing enabled. project=%s", project)
    return True


def shutdown_langsmith_tracing(timeout: float = 10.0) -> None:
    """Drain LangChain/LangSmith tracing and stop its background workers.

    Call this before shutting down Azure Monitor's OpenTelemetry providers.
    """
    global _tracing_shutdown

    with _tracing_shutdown_lock:
        if _tracing_shutdown:
            return
        _tracing_shutdown = True

    try:
        # Wait for LangChain callback executors and the cached LangSmith client.
        from langchain_core.tracers.langchain import wait_for_all_tracers

        wait_for_all_tracers()
    except Exception:
        logger.exception("Failed while waiting for LangChain tracers.")

    try:
        # cleanup() flushes pending runs and stops the LangSmith background
        # tracing threads. The fallback supports older LangSmith SDK versions.
        from langchain_core.tracers.langchain import get_client

        client = get_client()
        cleanup = getattr(client, "cleanup", None)
        if callable(cleanup):
            cleanup(timeout=timeout)
        else:
            flush = getattr(client, "flush", None)
            if callable(flush):
                flush(timeout=timeout)
        logger.info("LangSmith tracing shutdown completed.")
    except Exception:
        logger.exception("Failed to shut down LangSmith tracing cleanly.")
