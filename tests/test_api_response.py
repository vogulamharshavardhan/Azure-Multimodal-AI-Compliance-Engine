
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from backend.src.api import server


def test_api_preserves_not_applicable_audit_result():
    graph_result = {
        "video_id": "video-test-001",
        "azure_video_id": "azure-test-001",
        "indexing_status": "COMPLETED",
        "final_status": "NOT_APPLICABLE",
        "current_stage": "AUDIT_NOT_APPLICABLE",
        "processing_complete": True,
        "final_report": (
            "Both supported policy domains were assessed "
            "as not applicable."
        ),
        "policy_assessments": [
            {
                "domain": "ADVERTISING_DISCLOSURES",
                "applicability": "NOT_APPLICABLE",
            },
            {
                "domain": "YOUTUBE_AD_SPECIFICATIONS",
                "applicability": "NOT_APPLICABLE",
            },
        ],
        "policy_coverage": {
            "ADVERTISING_DISCLOSURES": "NOT_APPLICABLE",
            "YOUTUBE_AD_SPECIFICATIONS": "NOT_APPLICABLE",
        },
        "requirement_assessments": [],
        "requirement_coverage": {
            "total_identified": 0,
            "applicable": 0,
            "not_applicable": 0,
            "uncertain": 0,
            "compliant": 0,
            "non_compliant": 0,
            "insufficient_evidence": 0,
            "not_evaluated": 0,
        },
        "audit_decision_reasons": [
            "Both supported policy domains are not applicable."
        ],
        "compliance_results": [],
        "citations": [],
        "errors": [],
        "extraction_status": {
            "download_status": "SUCCESS",
        },
        "metadata": {},
    }

    with patch.object(
        server.compliance_graph,
        "ainvoke",
        new_callable=AsyncMock,
        return_value=graph_result,
    ):
        with TestClient(server.app) as client:
            response = client.post(
                "/audit",
                json={
                    "video_url": "https://www.youtube.com/watch?v=test123",
                    "commercial_relationship": "NONE",
                    "youtube_placement": "ORGANIC_UPLOAD",
                },
                headers={"X-API-Key": "test-only-secret-key-with-at-least-32-characters"},
            )

    assert response.status_code == 200

    data = response.json()

    assert data["final_status"] == "NOT_APPLICABLE"
    assert data["current_stage"] == "AUDIT_NOT_APPLICABLE"
    assert data["processing_complete"] is True
    assert data["indexing_status"] == "COMPLETED"
    assert data["requirement_assessments"] == []
    assert data["compliance_results"] == []
    assert data["errors"] == []
    assert len(data["policy_assessments"]) == 2


def test_api_key_is_required_outside_test_environment(monkeypatch):
    from fastapi import HTTPException
    import pytest

    monkeypatch.setattr(server, "APP_ENV", "production")
    monkeypatch.setattr(server, "API_KEY", "test-secret-key-with-at-least-32-characters")

    with pytest.raises(HTTPException) as missing:
        server.require_api_key(None)
    assert missing.value.status_code == 401

    with pytest.raises(HTTPException) as invalid:
        server.require_api_key("wrong-secret")
    assert invalid.value.status_code == 401

    assert server.require_api_key("test-secret-key-with-at-least-32-characters") is None


def test_api_fails_closed_when_api_key_is_not_configured(monkeypatch):
    from fastapi import HTTPException
    import pytest

    monkeypatch.setattr(server, "APP_ENV", "production")
    monkeypatch.setattr(server, "API_KEY", "")

    with pytest.raises(HTTPException) as error:
        server.require_api_key("any-value")
    assert error.value.status_code == 503


def test_api_queues_audit_and_returns_job_status(monkeypatch):
    class FakeQueue:
        def __init__(self):
            self.job = {
                "status": "QUEUED",
                "created_at": "2026-11-23T00:00:00+00:00",
                "updated_at": "2026-11-23T00:00:00+00:00",
                "result": None,
                "error": None,
            }

        def ping(self):
            return True

        def enqueue(self, payload):
            assert payload["youtube_placement"] == "ORGANIC_UPLOAD"
            return "job-test-001"

        def get_job(self, job_id):
            assert job_id == "job-test-001"
            return self.job

    fake_queue = FakeQueue()
    monkeypatch.setattr(server, "get_audit_queue", lambda: fake_queue)

    with TestClient(server.app) as client:
        submitted = client.post(
            "/audit/jobs",
            json={
                "video_url": "https://www.youtube.com/watch?v=test123",
                "commercial_relationship": "NONE",
                "youtube_placement": "ORGANIC_UPLOAD",
            },
            headers={"X-API-Key": "test-only-secret-key-with-at-least-32-characters"},
        )
        assert submitted.status_code == 202
        assert submitted.json()["job_id"] == "job-test-001"
        assert submitted.json()["status"] == "QUEUED"

        status_response = client.get(
            "/audit/jobs/job-test-001",
            headers={"X-API-Key": "test-only-secret-key-with-at-least-32-characters"},
        )
        assert status_response.status_code == 200
        assert status_response.json()["status"] == "QUEUED"
