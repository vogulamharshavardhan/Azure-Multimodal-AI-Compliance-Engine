"""Azure Monitor OpenTelemetry configuration."""

import logging
import os
from threading import Lock

from dotenv import load_dotenv
from azure.monitor.opentelemetry import configure_azure_monitor

load_dotenv()

logger = logging.getLogger("brand-guardian.telemetry")

_telemetry_initialized = False
_telemetry_shutdown = False
_telemetry_lock = Lock()


def setup_telemetry() -> bool:
    """Initialize Azure Monitor once.

    Returns True when telemetry is initialized, otherwise False.
    """
    global _telemetry_initialized

    with _telemetry_lock:
        if _telemetry_initialized:
            return True
        if _telemetry_shutdown:
            logger.warning("Azure Monitor cannot be reinitialized after shutdown.")
            return False

        connection_string = os.getenv("APPLICATIONINSIGHTS_CONNECTION_STRING")
        if not connection_string:
            logger.warning(
                "Application Insights connection string is missing. "
                "Azure Monitor telemetry is disabled."
            )
            return False

        try:
            # Exclude signed YouTube media URLs from HTTP dependency telemetry.
            youtube_pattern = r".*(?:manifest.*)?googlevideo\.com/.*"
            for variable in (
                "OTEL_PYTHON_EXCLUDED_URLS",
                "OTEL_PYTHON_REQUESTS_EXCLUDED_URLS",
                "OTEL_PYTHON_URLLIB3_EXCLUDED_URLS",
                "OTEL_PYTHON_HTTPX_EXCLUDED_URLS",
            ):
                existing = [
                    item.strip()
                    for item in os.getenv(variable, "").split(",")
                    if item.strip()
                ]
                if youtube_pattern not in existing:
                    existing.append(youtube_pattern)
                os.environ[variable] = ",".join(existing)

            configure_azure_monitor(
                connection_string=connection_string,
                logger_name="brand-guardian-tracer",
            )
            _telemetry_initialized = True
            logger.info("Azure Monitor OpenTelemetry initialized.")
            return True
        except Exception:
            logger.exception(
                "Azure Monitor initialization failed. "
                "The API will continue without Azure Monitor."
            )
            return False


def shutdown_telemetry() -> None:
    """Flush and stop Azure Monitor providers once, after LangSmith is drained."""
    global _telemetry_shutdown

    with _telemetry_lock:
        if not _telemetry_initialized or _telemetry_shutdown:
            return
        _telemetry_shutdown = True

    # Resolve providers only after LangSmith tracing has been drained.
    from opentelemetry import metrics, trace
    from opentelemetry._logs import get_logger_provider

    providers = [
        ("traces", trace.get_tracer_provider()),
        ("metrics", metrics.get_meter_provider()),
        ("logs", get_logger_provider()),
    ]

    # Flush every provider before shutting any provider down.
    for name, provider in providers:
        try:
            force_flush = getattr(provider, "force_flush", None)
            if callable(force_flush):
                result = force_flush(timeout_millis=5000)
                logger.info("OpenTelemetry %s flush completed: %s", name, result)
        except Exception:
            logger.exception("Failed to flush OpenTelemetry %s provider.", name)

    for name, provider in providers:
        try:
            shutdown = getattr(provider, "shutdown", None)
            if callable(shutdown):
                shutdown()
                logger.info("OpenTelemetry %s provider shut down.", name)
        except Exception:
            logger.exception("Failed to shut down OpenTelemetry %s provider.", name)
