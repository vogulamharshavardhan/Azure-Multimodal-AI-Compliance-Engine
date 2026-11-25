"""Centralized timestamp-based logging configuration for Brand Guardian."""

from __future__ import annotations

import logging
import os
from datetime import datetime
from pathlib import Path

_CONFIGURED = False
LOG_FILE_PATH: Path | None = None


def setup_logging() -> Path:
    """Configure console and per-run file logging once per process.

    Environment variables:
        LOG_LEVEL: DEBUG, INFO, WARNING, ERROR, or CRITICAL (default: INFO)
        LOG_DIR: Log directory, relative to the repository root by default

    A new timestamped file is created for each process initialization.
    """
    global _CONFIGURED, LOG_FILE_PATH

    project_root = Path(__file__).resolve().parents[3]
    configured_log_dir = Path(os.getenv("LOG_DIR", "logs"))
    log_dir = (
        configured_log_dir
        if configured_log_dir.is_absolute()
        else project_root / configured_log_dir
    )
    log_dir.mkdir(parents=True, exist_ok=True)

    if _CONFIGURED and LOG_FILE_PATH is not None:
        return LOG_FILE_PATH

    timestamp = datetime.now().strftime("%m_%d_%Y_%H_%M_%S")
    log_path = log_dir / f"{timestamp}.log"

    # Avoid collisions if two processes start within the same second.
    suffix = 1
    while log_path.exists():
        log_path = log_dir / f"{timestamp}_{suffix}.log"
        suffix += 1

    level_name = os.getenv("LOG_LEVEL", "INFO").upper()
    level = getattr(logging, level_name, logging.INFO)
    formatter = logging.Formatter(
        "[ %(asctime)s ] %(lineno)d %(name)s - %(levelname)s - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    root_logger = logging.getLogger()
    root_logger.setLevel(level)

    file_handler = logging.FileHandler(
        filename=log_path,
        mode="a",
        encoding="utf-8",
    )
    file_handler.setLevel(level)
    file_handler.setFormatter(formatter)
    file_handler._brand_guardian_handler = True  # type: ignore[attr-defined]
    root_logger.addHandler(file_handler)

    # Add our console handler only if one is not already configured.
    has_console_handler = any(
        isinstance(handler, logging.StreamHandler)
        and not isinstance(handler, logging.FileHandler)
        for handler in root_logger.handlers
    )
    if not has_console_handler:
        console_handler = logging.StreamHandler()
        console_handler.setLevel(level)
        console_handler.setFormatter(formatter)
        console_handler._brand_guardian_handler = True  # type: ignore[attr-defined]
        root_logger.addHandler(console_handler)

    # Keep noisy SDK transport logs at WARNING while preserving application logs.
    for logger_name in (
        "azure.core.pipeline.policies.http_logging_policy",
        "urllib3.connectionpool",
        "httpx",
        "httpcore",
    ):
        logging.getLogger(logger_name).setLevel(logging.WARNING)

    LOG_FILE_PATH = log_path
    _CONFIGURED = True

    logging.getLogger("brand_guardian.logging").info(
        "Logging initialized. Log file: %s", log_path
    )
    return log_path
