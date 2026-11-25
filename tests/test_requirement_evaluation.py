from unittest.mock import MagicMock, patch
from dotenv import load_dotenv
load_dotenv()
from backend.src.graph.nodes import (
    RequirementEvaluationResponse, RequirementEvaluationOutput,
    RequirementReferenceOutput, _resolve_requirement_status,
    _policy_quote_is_grounded, audit_content_node,
)


def _coverage():
    return {
        "ADVERTISING_DISCLOSURES": "APPLICABLE",
        "YOUTUBE_AD_SPECIFICATIONS": "NOT_APPLICABLE",
    }


def _assessment(status="COMPLIANT", applicability="APPLICABLE"):
    return {
        "requirement_id": "AD-DISC-001",
        "requirement_name": "Disclose material connections",
        "applicability": applicability,
        "evaluation_status": status,
    }


def test_pass_requires_complete_domain_coverage_and_compliant_requirements():
    status, _ = _resolve_requirement_status(_coverage(), [_assessment()])
    assert status == "PASS"


def test_uncertain_policy_domain_blocks_pass():
    coverage = _coverage()
    coverage["YOUTUBE_AD_SPECIFICATIONS"] = "UNCERTAIN"
    status, _ = _resolve_requirement_status(coverage, [_assessment()])
    assert status == "REVIEW_REQUIRED"


def test_verified_non_compliance_in_applicable_requirement_fails():
    status, _ = _resolve_requirement_status(_coverage(), [_assessment("NON_COMPLIANT")])
    assert status == "FAIL"


def test_insufficient_evidence_requires_review():
    status, _ = _resolve_requirement_status(_coverage(), [_assessment("INSUFFICIENT_EVIDENCE")])
    assert status == "REVIEW_REQUIRED"


def test_no_applicable_domain_requires_review():
    coverage = {d: "NOT_APPLICABLE" for d in _coverage()}
    status, _ = _resolve_requirement_status(coverage, [])
    assert status == "REVIEW_REQUIRED"


def test_policy_quote_must_be_grounded_in_retrieved_passage():
    policy = "A clear and conspicuous disclosure must be made with the endorsement."
    assert _policy_quote_is_grounded("clear and conspicuous disclosure", policy)
    assert not _policy_quote_is_grounded("a fabricated policy requirement", policy)


def test_requirement_node_retrieves_only_applicable_domain_and_verifies_quotes():
    transcript = "I received this product for free and I am reviewing it."
    policy_text = (
        "Source: influencer-guide.pdf\nPDF page: 2\nPolicy text:\n"
        "A clear and conspicuous disclosure must be made with the endorsement."
    )
    response = RequirementEvaluationResponse(assessments=[
        RequirementEvaluationOutput(
            requirement_id="AD-DISC-001",
            domain="ADVERTISING_DISCLOSURES",
            requirement_name="Disclose a gifted product",
            applicability="APPLICABLE",
            evaluation_status="INSUFFICIENT_EVIDENCE",
            reasoning="The transcript establishes a material connection, but the supplied OCR does not establish whether a clear and conspicuous disclosure appeared with the endorsement.",
            evidence_ids=["TRANSCRIPT_0001"],
            regulatory_references=[RequirementReferenceOutput(
                source="influencer-guide.pdf", page=2,
                policy_quote="A clear and conspicuous disclosure must be made with the endorsement",
            )],
            confidence=0.9,
        )
    ])
    prompt = MagicMock()
    chain = MagicMock()
    prompt.__or__.return_value = chain
    chain.invoke.return_value = response
    grok = MagicMock()
    grok.with_structured_output.return_value = MagicMock()

    state = {
        "indexing_status": "COMPLETED",
        "audit_context": {"jurisdiction": "US"},
        "transcript": transcript,
        "ocr_text": "",
        "policy_coverage": _coverage(),
        "policy_assessments": [
            {"domain": "ADVERTISING_DISCLOSURES", "applicability": "APPLICABLE"},
            {"domain": "YOUTUBE_AD_SPECIFICATIONS", "applicability": "NOT_APPLICABLE"},
        ],
    }
    with (
        patch("backend.src.graph.nodes.get_grok_client", return_value=grok),
        patch("backend.src.graph.nodes.get_embedding_client", return_value=object()),
        patch("backend.src.graph.nodes.get_vector_store", return_value=object()),
        patch("backend.src.graph.nodes.retrieve_regulatory_evidence", return_value=(policy_text, [{"source": "influencer-guide.pdf", "page": 2}])) as retrieve,
        patch("backend.src.graph.nodes.ChatPromptTemplate.from_messages", return_value=prompt),
    ):
        result = audit_content_node(state)

    assert result["final_status"] == "REVIEW_REQUIRED"
    assert result["requirement_coverage"]["insufficient_evidence"] == 1
    assert result["requirement_assessments"][0]["regulatory_references"][0]["page"] == 2
    retrieve.assert_called_once()


def test_missing_policy_applicability_prevents_llm_evaluation():
    result = audit_content_node({
        "indexing_status": "COMPLETED",
        "audit_context": {"jurisdiction": "US"},
        "transcript": "A video transcript is present.",
        "policy_coverage": {},
        "policy_assessments": [],
    })
    assert result["final_status"] == "REVIEW_REQUIRED"
    assert result["requirement_assessments"] == []


def test_uncertain_domain_does_not_block_evaluation_of_confirmed_applicable_domain():
    transcript = "I received this product for free and I am reviewing it."
    policy_text = (
        "Source: influencer-guide.pdf\nPDF page: 2\nPolicy text:\n"
        "A clear and conspicuous disclosure must be made with the endorsement."
    )
    response = RequirementEvaluationResponse(assessments=[
        RequirementEvaluationOutput(
            requirement_id="AD-DISC-001",
            domain="ADVERTISING_DISCLOSURES",
            requirement_name="Disclose a gifted product",
            applicability="APPLICABLE",
            evaluation_status="INSUFFICIENT_EVIDENCE",
            reasoning="The transcript establishes a material connection, but disclosure placement cannot be verified.",
            evidence_ids=["TRANSCRIPT_0001"],
            regulatory_references=[RequirementReferenceOutput(
                source="influencer-guide.pdf", page=2,
                policy_quote="A clear and conspicuous disclosure must be made with the endorsement",
            )],
            confidence=0.9,
        )
    ])
    prompt = MagicMock()
    chain = MagicMock()
    prompt.__or__.return_value = chain
    chain.invoke.return_value = response
    grok = MagicMock()
    grok.with_structured_output.return_value = MagicMock()
    state = {
        "indexing_status": "COMPLETED",
        "audit_context": {"jurisdiction": "US"},
        "transcript": transcript,
        "ocr_text": "",
        "policy_coverage": {
            "ADVERTISING_DISCLOSURES": "APPLICABLE",
            "YOUTUBE_AD_SPECIFICATIONS": "UNCERTAIN",
        },
        "policy_assessments": [
            {"domain": "ADVERTISING_DISCLOSURES", "applicability": "APPLICABLE"},
            {"domain": "YOUTUBE_AD_SPECIFICATIONS", "applicability": "UNCERTAIN"},
        ],
    }
    with (
        patch("backend.src.graph.nodes.get_grok_client", return_value=grok),
        patch("backend.src.graph.nodes.get_embedding_client", return_value=object()),
        patch("backend.src.graph.nodes.get_vector_store", return_value=object()),
        patch("backend.src.graph.nodes.retrieve_regulatory_evidence", return_value=(policy_text, [{"source": "influencer-guide.pdf", "page": 2}])) as retrieve,
        patch("backend.src.graph.nodes.ChatPromptTemplate.from_messages", return_value=prompt),
    ):
        result = audit_content_node(state)
    assert result["final_status"] == "REVIEW_REQUIRED"
    assert result["requirement_coverage"]["total_identified"] == 1
    assert result["requirement_assessments"][0]["requirement_id"] == "AD-DISC-001"
    assert any("Overall PASS is blocked" in reason for reason in result["audit_decision_reasons"])
    retrieve.assert_called_once()
