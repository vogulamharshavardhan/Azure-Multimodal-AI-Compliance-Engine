"""Durable Redis Streams queue for long-running video audit jobs."""
from __future__ import annotations

import json
import os
import uuid
from datetime import datetime, timezone
from typing import Any

from redis import Redis
from redis.exceptions import ResponseError


class AuditJobQueue:
    STREAM = "brand_guardian:audit_jobs"
    GROUP = "brand_guardian:audit_workers"
    JOB_PREFIX = "brand_guardian:job:"
    JOB_TTL_SECONDS = 7 * 24 * 60 * 60

    def __init__(self, redis_url: str | None = None) -> None:
        url = (redis_url or os.getenv("REDIS_URL", "")).strip()
        if not url:
            raise RuntimeError("REDIS_URL is required for queued audits.")
        self.client = Redis.from_url(
            url,
            decode_responses=True,
            socket_connect_timeout=5,
            socket_timeout=10,
            health_check_interval=30,
        )

    @classmethod
    def _job_key(cls, job_id: str) -> str:
        return f"{cls.JOB_PREFIX}{job_id}"

    def ping(self) -> bool:
        return bool(self.client.ping())

    def ensure_group(self) -> None:
        try:
            self.client.xgroup_create(self.STREAM, self.GROUP, id="0", mkstream=True)
        except ResponseError as exc:
            if "BUSYGROUP" not in str(exc):
                raise

    def enqueue(self, payload: dict[str, Any]) -> str:
        """Atomically enqueue a job, enforcing a hard queue-depth limit."""
        job_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc).isoformat()
        key = self._job_key(job_id)
        max_queue = int(os.getenv("MAX_QUEUED_AUDITS", "100"))
        if max_queue < 1:
            raise RuntimeError("MAX_QUEUED_AUDITS must be a positive integer.")
        script = """
        local queued = redis.call('XLEN', KEYS[1])
        if queued >= tonumber(ARGV[1]) then return 0 end
        redis.call('HSET', KEYS[2],
            'job_id', ARGV[2],
            'status', 'QUEUED',
            'payload', ARGV[3],
            'created_at', ARGV[4],
            'updated_at', ARGV[4])
        redis.call('EXPIRE', KEYS[2], tonumber(ARGV[5]))
        redis.call('XADD', KEYS[1], '*', 'job_id', ARGV[2])
        return 1
        """
        accepted = self.client.eval(
            script,
            2,
            self.STREAM,
            key,
            max_queue,
            job_id,
            json.dumps(payload, separators=(",", ":")),
            now,
            self.JOB_TTL_SECONDS,
        )
        if not accepted:
            raise OverflowError("Audit queue is at capacity.")
        return job_id

    def get_job(self, job_id: str) -> dict[str, Any] | None:
        data = self.client.hgetall(self._job_key(job_id))
        if not data:
            return None
        result: dict[str, Any] = dict(data)
        for field in ("result", "error"):
            if result.get(field):
                try:
                    result[field] = json.loads(result[field])
                except json.JSONDecodeError:
                    result[field] = None
        return result

    def read_new(self, consumer: str, block_ms: int = 5000):
        self.ensure_group()
        messages = self.client.xreadgroup(
            self.GROUP,
            consumer,
            {self.STREAM: ">"},
            count=1,
            block=block_ms,
        )
        if not messages:
            return None
        _, entries = messages[0]
        return entries[0] if entries else None

    def claim_stale(self, consumer: str, min_idle_ms: int = 60_000):
        self.ensure_group()
        response = self.client.xautoclaim(
            self.STREAM,
            self.GROUP,
            consumer,
            min_idle_time=min_idle_ms,
            start_id="0-0",
            count=1,
        )
        entries = response[1] if response and len(response) > 1 else []
        return entries[0] if entries else None

    def mark_running(self, job_id: str, stream_id: str) -> None:
        now = datetime.now(timezone.utc).isoformat()
        self.client.hset(self._job_key(job_id), mapping={
            "status": "RUNNING",
            "current_stage": "INITIALIZING",
            "stream_id": stream_id,
            "updated_at": now,
        })

    def mark_progress(self, job_id: str, stage: str) -> None:
        self.client.hset(self._job_key(job_id), mapping={
            "current_stage": stage,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        })

    def mark_completed(self, job_id: str, result: dict[str, Any]) -> None:
        now = datetime.now(timezone.utc).isoformat()
        self.client.hset(self._job_key(job_id), mapping={
            "status": "COMPLETED",
            "current_stage": result.get("current_stage") or "COMPLETED",
            "result": json.dumps(result, default=str, separators=(",", ":")),
            "updated_at": now,
        })

    def mark_failed(self, job_id: str, error_type: str) -> None:
        now = datetime.now(timezone.utc).isoformat()
        self.client.hset(self._job_key(job_id), mapping={
            "status": "FAILED",
            "current_stage": "FAILED",
            "error": json.dumps({"error_type": error_type, "message": "Audit processing failed. Check server logs."}),
            "updated_at": now,
        })

    def touch_pending(self, consumer: str, stream_id: str) -> None:
        """Reset the pending-message idle timer while a worker is active."""
        self.client.xclaim(
            self.STREAM,
            self.GROUP,
            consumer,
            min_idle_time=0,
            message_ids=[stream_id],
            justid=True,
        )

    def acknowledge(self, stream_id: str) -> None:
        pipe = self.client.pipeline(transaction=True)
        pipe.xack(self.STREAM, self.GROUP, stream_id)
        pipe.xdel(self.STREAM, stream_id)
        pipe.execute()

    def close(self) -> None:
        self.client.close()
