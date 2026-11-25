
from unittest.mock import MagicMock, patch
from dotenv import load_dotenv
load_dotenv()
from backend.src.graph.nodes import (
    OCRClassificationBatch,
    OCRSegmentClassification,
    classify_ocr_node,
)


def test_classification_skipped_when_indexing_fails():
    result = classify_ocr_node({
        "indexing_status": "FAILED",
        "ocr_segments": [],
    })

    assert result["ocr_classifications"] == []
    assert result["current_stage"] == "OCR_CLASSIFICATION_SKIPPED"


def test_classification_skipped_when_no_ocr_exists():
    result = classify_ocr_node({
        "indexing_status": "COMPLETED",
        "ocr_segments": [],
        "raw_ocr_segments": [],
        "ocr_text": "",
    })

    assert result["ocr_classifications"] == []
    assert result["current_stage"] == "OCR_CLASSIFICATION_SKIPPED"


def test_valid_ocr_segments_are_classified():
    segments = [
        {
            "text": "Guaranteed 100 percent improvement",
            "start": 1.5,
            "end": 3.0,
        },
        {
            "text": "Terms and conditions apply",
            "start": 4.0,
            "end": 5.0,
        },
    ]

    mock_response = OCRClassificationBatch(
        classifications=[
            OCRSegmentClassification(
                segment_index=0,
                category="CLAIM",
                relevance_score=0.98,
                reasoning="This is a product performance claim.",
            ),
            OCRSegmentClassification(
                segment_index=1,
                category="DISCLAIMER",
                relevance_score=0.95,
                reasoning="This communicates a qualification.",
            ),
        ]
    )

    mock_grok = MagicMock()

    mock_structured = MagicMock()
    mock_grok.with_structured_output.return_value = mock_structured

    mock_chain = MagicMock()
    mock_chain.invoke.return_value = mock_response

    mock_prompt = MagicMock()
    mock_prompt.__or__.return_value = mock_chain

    with (
        patch(
            "backend.src.graph.nodes.get_grok_client",
            return_value=mock_grok,
        ),
        patch(
            "backend.src.graph.nodes.ChatPromptTemplate.from_messages",
            return_value=mock_prompt,
        ),
    ):
        result = classify_ocr_node({
            "indexing_status": "COMPLETED",
            "ocr_segments": segments,
            "raw_ocr_segments": segments,
        })

    assert len(result["ocr_classifications"]) == 2

    assert result["ocr_classifications"][0]["category"] == "CLAIM"

    assert (
        result["ocr_classifications"][1]["category"]
        == "DISCLAIMER"
    )

    assert result["ocr_classifications"][0]["start"] == 1.5

    assert result["ocr_classifications"][1]["end"] == 5.0

    assert (
        result["current_stage"]
        == "OCR_CLASSIFICATION_COMPLETED"
    )

    mock_chain.invoke.assert_called_once()


def test_missing_model_classification_becomes_uncertain():
    segments = [
        {
            "text": "Special offer available",
            "start": 2.0,
            "end": 3.0,
        }
    ]

    mock_response = OCRClassificationBatch(
        classifications=[]
    )

    mock_grok = MagicMock()

    mock_structured = MagicMock()
    mock_grok.with_structured_output.return_value = mock_structured

    mock_chain = MagicMock()
    mock_chain.invoke.return_value = mock_response

    mock_prompt = MagicMock()
    mock_prompt.__or__.return_value = mock_chain

    with (
        patch(
            "backend.src.graph.nodes.get_grok_client",
            return_value=mock_grok,
        ),
        patch(
            "backend.src.graph.nodes.ChatPromptTemplate.from_messages",
            return_value=mock_prompt,
        ),
    ):
        result = classify_ocr_node({
            "indexing_status": "COMPLETED",
            "ocr_segments": segments,
        })

    classification = result["ocr_classifications"][0]

    assert classification["category"] == "UNCERTAIN"
    assert classification["relevance_score"] == 0.0
    assert classification["start"] == 2.0


def test_classification_failure_preserves_ocr_evidence():
    segments = [
        {
            "text": "Limited period offer",
            "start": 10.0,
            "end": 12.0,
        }
    ]

    with patch(
        "backend.src.graph.nodes.get_grok_client",
        side_effect=RuntimeError("Mock API failure"),
    ):
        result = classify_ocr_node({
            "indexing_status": "COMPLETED",
            "ocr_segments": segments,
        })

    assert len(result["ocr_classifications"]) == 1

    classification = result["ocr_classifications"][0]

    assert classification["text"] == "Limited period offer"
    assert classification["category"] == "UNCERTAIN"
    assert classification["start"] == 10.0

    assert result["current_stage"] == "OCR_CLASSIFICATION_FAILED"
    assert len(result["errors"]) == 1


def test_raw_ocr_is_used_when_cleaned_ocr_is_unavailable():
    raw_segments = [
        {
            "text": "18+ Terms and conditions apply",
            "start": 5.0,
            "end": 7.0,
        }
    ]

    mock_response = OCRClassificationBatch(
        classifications=[
            OCRSegmentClassification(
                segment_index=0,
                category="DISCLAIMER",
                relevance_score=0.92,
                reasoning="This contains a qualification.",
            )
        ]
    )

    mock_grok = MagicMock()

    mock_structured = MagicMock()
    mock_grok.with_structured_output.return_value = mock_structured

    mock_chain = MagicMock()
    mock_chain.invoke.return_value = mock_response

    mock_prompt = MagicMock()
    mock_prompt.__or__.return_value = mock_chain

    with (
        patch(
            "backend.src.graph.nodes.get_grok_client",
            return_value=mock_grok,
        ),
        patch(
            "backend.src.graph.nodes.ChatPromptTemplate.from_messages",
            return_value=mock_prompt,
        ),
    ):
        result = classify_ocr_node({
            "indexing_status": "COMPLETED",
            "ocr_segments": [],
            "raw_ocr_segments": raw_segments,
        })

    assert len(result["ocr_classifications"]) == 1

    assert (
        result["ocr_classifications"][0]["category"]
        == "DISCLAIMER"
    )
