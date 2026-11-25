from unittest.mock import patch

from backend.src.graph.workflow import create_graph
from dotenv import load_dotenv
load_dotenv()

def test_successful_workflow_executes_nodes_in_order():
    execution_order = []

    with (
        patch("backend.src.graph.workflow.index_video_node") as mock_indexer,
        patch("backend.src.graph.workflow.classify_ocr_node") as mock_classifier,
        patch("backend.src.graph.workflow.policy_applicability_node") as mock_applicability,
        patch("backend.src.graph.workflow.audit_content_node") as mock_auditor,
    ):
        mock_indexer.side_effect = lambda _state: (
            execution_order.append("indexer")
            or {
                "indexing_status": "COMPLETED",
                "transcript": "Test transcript",
                "ocr_segments": [{"text": "Test disclosure"}],
                "ocr_classifications": [],
                "compliance_results": [],
                "errors": [],
            }
        )
        mock_classifier.side_effect = lambda _state: (
            execution_order.append("ocr_classifier")
            or {"ocr_classifications": []}
        )
        mock_applicability.side_effect = lambda _state: (
            execution_order.append("policy_applicability")
            or {
                "policy_assessments": [],
                "policy_coverage": {
                    "ADVERTISING_DISCLOSURES": "APPLICABLE",
                    "YOUTUBE_AD_SPECIFICATIONS": "NOT_APPLICABLE",
                },
            }
        )
        mock_auditor.side_effect = lambda _state: (
            execution_order.append("auditor")
            or {
                "final_status": "PASS",
                "final_report": "No violations detected.",
                "compliance_results": [],
            }
        )

        result = create_graph().invoke({
            "video_url": "https://example.com/video",
            "compliance_results": [],
            "errors": [],
        })

    assert execution_order == [
        "indexer",
        "ocr_classifier",
        "policy_applicability",
        "auditor",
    ]
    mock_indexer.assert_called_once()
    mock_classifier.assert_called_once()
    mock_applicability.assert_called_once()
    mock_auditor.assert_called_once()
    assert result["indexing_status"] == "COMPLETED"
    assert result["final_status"] == "PASS"


def test_indexing_failure_skips_all_downstream_nodes():
    with (
        patch("backend.src.graph.workflow.index_video_node") as mock_indexer,
        patch("backend.src.graph.workflow.classify_ocr_node") as mock_classifier,
        patch("backend.src.graph.workflow.policy_applicability_node") as mock_applicability,
        patch("backend.src.graph.workflow.audit_content_node") as mock_auditor,
    ):
        mock_indexer.return_value = {
            "indexing_status": "FAILED",
            "errors": [{
                "node": "index_video_node",
                "message": "Video download failed",
                "recoverable": False,
            }],
        }

        result = create_graph().invoke({
            "video_url": "https://example.com/video",
            "compliance_results": [],
            "errors": [],
        })

    mock_indexer.assert_called_once()
    mock_classifier.assert_not_called()
    mock_applicability.assert_not_called()
    mock_auditor.assert_not_called()
    assert result["indexing_status"] == "FAILED"
    assert len(result["errors"]) == 1


def test_classifier_fallback_still_runs_applicability_and_auditor():
    with (
        patch("backend.src.graph.workflow.index_video_node") as mock_indexer,
        patch("backend.src.graph.workflow.classify_ocr_node") as mock_classifier,
        patch("backend.src.graph.workflow.policy_applicability_node") as mock_applicability,
        patch("backend.src.graph.workflow.audit_content_node") as mock_auditor,
    ):
        mock_indexer.return_value = {
            "indexing_status": "COMPLETED",
            "ocr_segments": [{"text": "Sample claim"}],
            "ocr_classifications": [],
            "compliance_results": [],
            "errors": [],
        }
        mock_classifier.return_value = {
            "ocr_classifications": [{
                "text": "Sample claim",
                "category": "UNCERTAIN",
                "relevance_score": 0.0,
                "reasoning": "Classification unavailable",
            }],
            "errors": [{
                "node": "classify_ocr_node",
                "message": "Classification service unavailable",
                "recoverable": True,
            }],
        }
        mock_applicability.return_value = {
            "policy_assessments": [],
            "policy_coverage": {
                "ADVERTISING_DISCLOSURES": "UNCERTAIN",
                "YOUTUBE_AD_SPECIFICATIONS": "UNCERTAIN",
            },
        }
        mock_auditor.return_value = {
            "final_status": "REVIEW_REQUIRED",
            "final_report": "Manual review required.",
            "compliance_results": [],
        }

        result = create_graph().invoke({
            "video_url": "https://example.com/video",
            "compliance_results": [],
            "errors": [],
        })

    mock_indexer.assert_called_once()
    mock_classifier.assert_called_once()
    mock_applicability.assert_called_once()
    mock_auditor.assert_called_once()
    assert result["final_status"] == "REVIEW_REQUIRED"
    assert result["ocr_classifications"][0]["category"] == "UNCERTAIN"
    assert len(result["errors"]) == 1
