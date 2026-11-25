import json

import pytest

from backend.src.services.audit_job_queue import AuditJobQueue
from backend.src.worker import _public_result


class FakeRedis:
    def __init__(self):
        self.hashes = {}
        self.stream = []

    def eval(self, script, numkeys, stream, key, max_queue, job_id, payload, now, ttl):
        if len(self.stream) >= int(max_queue):
            return 0
        self.hashes[key] = {
            "job_id": job_id,
            "status": "QUEUED",
            "payload": payload,
            "created_at": now,
            "updated_at": now,
        }
        self.stream.append({"job_id": job_id})
        return 1

    def hgetall(self, key):
        return self.hashes.get(key, {})

    def close(self):
        pass


def test_enqueue_stores_job_payload_and_status(monkeypatch):
    fake = FakeRedis()
    monkeypatch.setenv("MAX_QUEUED_AUDITS", "10")
    monkeypatch.setattr("backend.src.services.audit_job_queue.Redis.from_url", lambda *a, **k: fake)
    queue = AuditJobQueue("redis://localhost:6379/0")

    job_id = queue.enqueue({"video_url": "https://youtu.be/example"})
    job = queue.get_job(job_id)

    assert job["status"] == "QUEUED"
    assert json.loads(job["payload"])["video_url"] == "https://youtu.be/example"


def test_enqueue_rejects_full_queue(monkeypatch):
    fake = FakeRedis()
    fake.stream = [{}]
    monkeypatch.setenv("MAX_QUEUED_AUDITS", "1")
    monkeypatch.setattr("backend.src.services.audit_job_queue.Redis.from_url", lambda *a, **k: fake)
    queue = AuditJobQueue("redis://localhost:6379/0")

    with pytest.raises(OverflowError):
        queue.enqueue({"video_url": "https://youtu.be/example"})


def test_worker_persists_only_public_result_fields():
    safe = _public_result({
        "video_id": "video-1",
        "final_status": "REVIEW_REQUIRED",
        "transcript": "private transcript",
        "raw_ocr_segments": [{"text": "private OCR"}],
        "metadata": {"duration": 10},
    })
    assert safe["video_id"] == "video-1"
    assert safe["final_status"] == "REVIEW_REQUIRED"
    assert safe["video_metadata"] == {"duration": 10}
    assert "transcript" not in safe
    assert "raw_ocr_segments" not in safe
