
"""
Brand Guardian - Compliance QA Pipeline
Application entry point.

Usage:
    uv run python main.py --video-url "https://www.youtube.com/watch?v=VIDEO_ID"

Or configure VIDEO_URL in .env:
    uv run python main.py
"""

from __future__ import annotations
from dotenv import load_dotenv
load_dotenv()
import argparse
import json
import logging
import os
import time
import uuid
from typing import Any
from urllib.parse import parse_qs, urlparse

from dotenv import load_dotenv

# ---------------------------------------------------------------------
# 1. Environment configuration
# ---------------------------------------------------------------------

load_dotenv(override=False)

# ---------------------------------------------------------------------
# 2. Centralized logging configuration
# ---------------------------------------------------------------------

from backend.src.core.logging_config import setup_logging
from backend.src.core.exceptions import CompliancePipelineError

setup_logging()
logger = logging.getLogger("brand_guardian")

# Configure tracing before importing LangGraph/LangChain clients.
from backend.src.api.tracing import setup_langsmith_tracing

setup_langsmith_tracing()

# Import the graph after environment and logging configuration.
from backend.src.graph.workflow import app as compliance_graph

# ---------------------------------------------------------------------
# 3. Input validation
# ---------------------------------------------------------------------

def is_valid_youtube_url(url: str) -> bool:
    """Validate supported YouTube URL formats."""

    try:
        parsed = urlparse(url.strip())
        hostname = (parsed.hostname or "").lower()

        if hostname in {"youtu.be", "www.youtu.be"}:
            return bool(parsed.path.strip("/"))

        if hostname in {
            "youtube.com",
            "www.youtube.com",
            "m.youtube.com",
        }:
            if parsed.path == "/watch":
                return bool(parse_qs(parsed.query).get("v"))

            if parsed.path.startswith(("/shorts/", "/embed/")):
                return bool(parsed.path.split("/")[2:])

        return False

    except (ValueError, AttributeError):
        return False

# ---------------------------------------------------------------------
# 4. Initial graph state
# ---------------------------------------------------------------------

def build_initial_state(video_url: str) -> dict[str, Any]:
    """
    Build the initial LangGraph state.

    List fields are initialized because the graph state uses
    operator.add reducers for compliance_results and errors.
    """

    return {
        "video_url": video_url,
        "video_id": str(uuid.uuid4()),
        "local_file_path": None,
        "azure_video_id": None,

        "video_metadata": {},

        "transcript": None,
        "transcript_segments": [],

        "ocr_text": [],
        "ocr_segments": [],

        "extraction_status": {
            "download_status": "PENDING",
            "transcription_status": "PENDING",
            "ocr_status": "PENDING",
        },

        "indexing_status": "PENDING",
        "compliance_results": [],
        "errors": [],
        "regulatory_citations": [],

        "final_status": "PENDING",
        "final_report": "",

        "current_stage": "INITIALIZED",
        "processing_complete": False,
    }

# ---------------------------------------------------------------------
# 5. Reporting
# ---------------------------------------------------------------------

def print_audit_report(result: dict[str, Any], elapsed_time: float) -> None:
    """Print the final audit summary."""

    indexing_status = result.get("indexing_status", "UNKNOWN")
    final_status = result.get("final_status", "UNKNOWN")

    compliance_results = result.get("compliance_results", [])
    errors = result.get("errors", [])
    citations = result.get("regulatory_citations", [])

    print("\n" + "=" * 72)
    print("              BRAND GUARDIAN - COMPLIANCE AUDIT")
    print("=" * 72)

    print(f"Video ID          : {result.get('video_id', 'N/A')}")
    print(f"Azure Video ID    : {result.get('azure_video_id', 'N/A')}")
    print(f"Indexing Status   : {indexing_status}")
    print(f"Compliance Status : {final_status}")
    print(f"Processing Time   : {elapsed_time:.2f} seconds")

    print("\n" + "-" * 72)
    print("COMPLIANCE FINDINGS")
    print("-" * 72)

    if compliance_results:
        for index, issue in enumerate(compliance_results, start=1):
            print(f"\nFinding {index}")
            print(f"  Category      : {issue.get('category', 'N/A')}")
            print(f"  Severity      : {issue.get('severity', 'N/A')}")
            print(f"  Description   : {issue.get('description', 'N/A')}")
            print(f"  Timestamp     : {issue.get('timestamp', 'N/A')}")
            print(f"  Confidence    : {issue.get('confidence', 'N/A')}")
            print(f"  Detected By   : {issue.get('detected_by', 'N/A')}")
            print(f"  Evidence      : {issue.get('evidence', [])}")
            print(f"  Recommendation: {issue.get('recommendation', 'N/A')}")
    else:
        print("No compliance findings were returned.")

    print("\n" + "-" * 72)
    print("REGULATORY CITATIONS")
    print("-" * 72)

    if citations:
        for citation in citations:
            print(
                f"- Source: {citation.get('source', 'N/A')} | "
                f"Page: {citation.get('page', 'N/A')}"
            )
    else:
        print("No regulatory citations available.")

    print("\n" + "-" * 72)
    print("PROCESSING ERRORS")
    print("-" * 72)

    if errors:
        for error in errors:
            print(
                f"- Node: {error.get('node', 'N/A')} | "
                f"Type: {error.get('error_type', 'N/A')} | "
                f"Message: {error.get('message', 'N/A')} | "
                f"Recoverable: {error.get('recoverable', 'N/A')}"
            )
    else:
        print("No processing errors.")

    print("\n" + "=" * 72)

    if indexing_status != "COMPLETED":
        print("RESULT: Video indexing did not complete.")
    elif final_status == "PASS":
        print("RESULT: Content passed the compliance audit.")
    elif final_status == "FAIL":
        print("RESULT: Compliance violations detected.")
    elif final_status in {"REVIEW", "REVIEW_REQUIRED"}:
        print("RESULT: Manual compliance review required.")
    elif final_status == "NOT_APPLICABLE":
        print("RESULT: No supported policy domain was applicable. This is not a compliance pass.")
    else:
        print(f"RESULT: Audit finished with status {final_status}.")

    print("=" * 72 + "\n")

# ---------------------------------------------------------------------
# 6. CLI arguments
# ---------------------------------------------------------------------

def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Brand Guardian video compliance auditing pipeline."
    )

    parser.add_argument(
        "--video-url",
        type=str,
        default=os.getenv("VIDEO_URL"),
        help="YouTube video URL. Can also be set through VIDEO_URL in .env.",
    )

    parser.add_argument(
        "--thread-id",
        type=str,
        default=None,
        help="Optional LangGraph thread identifier.",
    )

    return parser.parse_args()

# ---------------------------------------------------------------------
# 7. Pipeline execution
# ---------------------------------------------------------------------

def run_pipeline(video_url: str, thread_id: str | None = None) -> int:
    """Execute the LangGraph compliance workflow."""

    if not is_valid_youtube_url(video_url):
        logger.error("Invalid or unsupported YouTube URL.")
        return 2

    initial_state = build_initial_state(video_url)

    run_id = thread_id or str(uuid.uuid4())

    graph_config = {
        "configurable": {
            "thread_id": run_id,
        }
    }

    logger.info("Starting Brand Guardian compliance pipeline.")
    logger.info("Run ID: %s", run_id)

    start_time = time.perf_counter()

    try:
        result = compliance_graph.invoke(
            initial_state,
            config=graph_config,
        )

        elapsed_time = time.perf_counter() - start_time

        from backend.src.auditing.screening import enrich_report
        result = enrich_report(result, initial_state.get("audit_context"))
        print_audit_report(result, elapsed_time)

        if result.get("indexing_status") != "COMPLETED":
            logger.error("Video indexing failed.")
            return 1

        if result.get("final_status") in {
            "REVIEW",
            "REVIEW_REQUIRED",
            "FAIL",
        }:
            logger.warning(
                "Audit completed with status: %s",
                result.get("final_status"),
            )
            return 1

        if result.get("final_status") == "PASS":
            logger.info("Compliance audit passed successfully.")
            return 0

        if result.get("final_status") == "NOT_APPLICABLE":
            logger.info("Audit completed: no supported policy domain was applicable.")
            return 0

        logger.warning(
            "Pipeline returned an unexpected compliance status: %s",
            result.get("final_status"),
        )
        return 1

    except KeyboardInterrupt:
        logger.warning("Pipeline execution interrupted by user.")
        return 130

    except CompliancePipelineError as exc:
        logger.exception(
            "Known compliance pipeline failure. error_type=%s",
            type(exc).__name__,
        )
        return 1

    except Exception as exc:
        logger.exception(
            "Pipeline execution failed. Error type: %s",
            type(exc).__name__,
        )
        return 1

# ---------------------------------------------------------------------
# 8. Application entry point
# ---------------------------------------------------------------------

def main() -> int:
    args = parse_arguments()

    if not args.video_url:
        logger.error(
            "No video URL supplied. Use --video-url or configure VIDEO_URL in .env."
        )
        return 2

    return run_pipeline(
        video_url=args.video_url,
        thread_id=args.thread_id,
    )

if __name__ == "__main__":
    raise SystemExit(main())