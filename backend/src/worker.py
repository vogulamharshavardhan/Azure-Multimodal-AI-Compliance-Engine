"""Redis Streams worker for durable Brand Guardian audits.

Run: uv run python -m backend.src.worker
"""
from __future__ import annotations

import json
import logging
import os
import socket
import time
from threading import Event, Thread

from dotenv import load_dotenv

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
load_dotenv(os.path.join(PROJECT_ROOT, ".env"), override=False)

from backend.src.core.logging_config import setup_logging
from backend.src.api.telemetry import setup_telemetry, shutdown_telemetry
from backend.src.api.tracing import setup_langsmith_tracing, shutdown_langsmith_tracing
from backend.src.services.audit_job_queue import AuditJobQueue

setup_logging()
logger = logging.getLogger("brand-guardian.worker")
telemetry_enabled = setup_telemetry()
tracing_enabled = setup_langsmith_tracing()

from backend.src.graph.workflow import app as compliance_graph


def _initial_state(payload: dict) -> dict:
    return {
        "video_url": payload["video_url"],
        "audit_context": {
            "commercial_relationship": payload.get("commercial_relationship", "UNKNOWN"),
            "youtube_placement": payload.get("youtube_placement", "UNKNOWN"),
            "ad_format": payload.get("ad_format", "UNKNOWN"),
            "jurisdiction": payload.get("jurisdiction", "UNKNOWN"),
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


from backend.src.auditing.public_report import public_result as _public_result


def _heartbeat(queue: AuditJobQueue, consumer: str, stream_id: str, stop: Event) -> None:
    """Keep a long-running job owned by this worker; stale jobs can be reclaimed after a crash."""
    while not stop.wait(20):
        try:
            queue.touch_pending(consumer, stream_id)
        except Exception:
            logger.exception("Could not renew audit-job ownership. stream_id=%s", stream_id)


def run() -> None:
    queue: AuditJobQueue | None = None
    consumer = f"{socket.gethostname()}-{os.getpid()}"
    try:
        queue = AuditJobQueue()
        queue.ensure_group()
        logger.info("Audit worker started. consumer=%s", consumer)
        while True:
            message = queue.claim_stale(consumer)
            if message is None:
                message = queue.read_new(consumer)
            if message is None:
                continue

            stream_id, fields = message
            job_id = fields.get("job_id")
            if not job_id:
                queue.acknowledge(stream_id)
                continue

            job = queue.get_job(job_id)
            if not job or job.get("status") in {"COMPLETED", "FAILED"}:
                queue.acknowledge(stream_id)
                continue

            queue.mark_running(job_id, stream_id)
            heartbeat_stop = Event()
            heartbeat = Thread(
                target=_heartbeat,
                args=(queue, consumer, stream_id, heartbeat_stop),
                name=f"audit-heartbeat-{job_id[:8]}",
                daemon=True,
            )
            heartbeat.start()
            try:
                payload = json.loads(job["payload"])
                initial = _initial_state(payload)
                started = time.monotonic()
                from backend.src.auditing.progress import callback
                from backend.src.auditing import extraction_cache
                stage_events = []
                def record_stage(stage):
                    stage_events.append({"stage": stage, "elapsed_seconds": round(time.monotonic() - started, 3)})
                    queue.mark_progress(job_id, stage)
                progress_token = callback.set(record_stage)
                result = initial.copy()
                for update in compliance_graph.stream(
                    initial,
                    stream_mode="values",
                    config={
                        "run_name": "brand-guardian-video-audit",
                        "tags": ["brand-guardian", "video-compliance", "redis-worker"],
                        "metadata": {
                            "commercial_relationship": payload.get("commercial_relationship", "UNKNOWN"),
                            "youtube_placement": payload.get("youtube_placement", "UNKNOWN"),
                        },
                    },
                ):
                    result = update
                    record_stage(result.get("current_stage") or "PROCESSING")
                public = _public_result(result, initial["audit_context"])
                public["elapsed_seconds"] = round(time.monotonic() - started, 3)
                public["stage_events"] = stage_events
                public["extraction_cache_status"] = next((e["stage"].removeprefix("EXTRACTION_CACHE_") for e in stage_events if e["stage"].startswith("EXTRACTION_CACHE_")), "UNKNOWN")
                queue.mark_completed(job_id, public)
                logger.info("Audit elapsed seconds=%.3f", time.monotonic() - started)
                logger.info("Audit job completed. job_id=%s status=%s", job_id, result.get("final_status"))
            except Exception as exc:
                logger.exception("Audit job failed. job_id=%s error_type=%s", job_id, type(exc).__name__)
                queue.mark_failed(job_id, type(exc).__name__)
            finally:
                if "progress_token" in locals():
                    callback.reset(progress_token)
                    del progress_token
                heartbeat_stop.set()
                heartbeat.join(timeout=3)
            # Do not acknowledge if persisting the terminal state raised.
            queue.acknowledge(stream_id)
    except KeyboardInterrupt:
        logger.info("Audit worker stopping.")
    except Exception:
        logger.exception("Audit worker stopped unexpectedly.")
        raise
    finally:
        if queue is not None:
            try:
                queue.close()
            except Exception:
                logger.exception("Could not close Redis queue client cleanly.")
        if tracing_enabled:
            shutdown_langsmith_tracing()
        if telemetry_enabled:
            shutdown_telemetry()


if __name__ == "__main__":
    run()
