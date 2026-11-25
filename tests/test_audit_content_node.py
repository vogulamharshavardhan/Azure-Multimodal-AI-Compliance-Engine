from unittest.mock import MagicMock, patch

from backend.src.graph import nodes
from dotenv import load_dotenv
load_dotenv()

def _domain_assessments():
    return [
        {"domain": "ADVERTISING_DISCLOSURES", "applicability": "APPLICABLE"},
        {"domain": "YOUTUBE_AD_SPECIFICATIONS", "applicability": "NOT_APPLICABLE"},
    ]


def _policy_coverage():
    return {
        "ADVERTISING_DISCLOSURES": "APPLICABLE",
        "YOUTUBE_AD_SPECIFICATIONS": "NOT_APPLICABLE",
    }


def _response(evaluation_status="NON_COMPLIANT", quote="paid partnership"):
    reference = nodes.RequirementReferenceOutput(
        source="influencer-guide.pdf",
        page=2,
        policy_quote="A clear and conspicuous disclosure must be made with the endorsement.",
    )
    assessment = nodes.RequirementEvaluationOutput(
        requirement_id="AD-DISC-001",
        domain="ADVERTISING_DISCLOSURES",
        requirement_name="Disclose material connections",
        applicability="APPLICABLE",
        evaluation_status=evaluation_status,
        reasoning="The supplied video evidence was evaluated against the retrieved policy passage.",
        evidence_ids=["TRANSCRIPT_0001" if quote == "paid partnership" else "INVENTED_ID"],
        regulatory_references=[reference],
        confidence=0.95,
        severity="HIGH",
        recommendation="Add a clear disclosure with the endorsement.",
    )
    return nodes.RequirementEvaluationResponse(assessments=[assessment])


def _run_audit(response, transcript="This video includes a paid partnership with a brand."):
    prompt = MagicMock()
    chain = MagicMock()
    prompt.__or__.return_value = chain
    chain.invoke.return_value = response
    grok = MagicMock()
    grok.with_structured_output.return_value = MagicMock()
    policy_text = (
        "Source: influencer-guide.pdf\nPDF page: 2\nPolicy text:\n"
        "A clear and conspicuous disclosure must be made with the endorsement."
    )
    state = {
        "indexing_status": "COMPLETED",
        "audit_context": {"jurisdiction": "US"},
        "transcript": transcript,
        "ocr_text": "",
        "metadata": {},
        "transcript_segments": [],
        "ocr_segments": [],
        "policy_coverage": _policy_coverage(),
        "policy_assessments": _domain_assessments(),
    }
    with (
        patch.object(nodes, "get_grok_client", return_value=grok),
        patch.object(nodes, "get_embedding_client", return_value=object()),
        patch.object(nodes, "get_vector_store", return_value=object()),
        patch.object(
            nodes,
            "retrieve_regulatory_evidence",
            return_value=(policy_text, [{"source": "influencer-guide.pdf", "page": 2}]),
        ),
        patch.object(nodes.ChatPromptTemplate, "from_messages", return_value=prompt),
    ):
        return nodes.audit_content_node(state)


def test_audit_skipped_when_indexing_fails():
    result = nodes.audit_content_node({"indexing_status": "FAILED"})
    assert result["final_status"] == "REVIEW_REQUIRED"
    assert result["current_stage"] == "AUDIT_SKIPPED"


def test_audit_skipped_when_no_evidence_exists():
    result = nodes.audit_content_node({
        "indexing_status": "COMPLETED",
        "audit_context": {"jurisdiction": "US"}, "transcript": "", "ocr_text": "",
    })
    assert result["final_status"] == "REVIEW_REQUIRED"
    assert result["requirement_assessments"] == []


def test_valid_transcript_evidence_is_accepted():
    assert nodes._evidence_is_grounded("paid partnership", "This is a paid partnership.", "")


def test_valid_ocr_evidence_is_accepted():
    assert nodes._evidence_is_grounded("#ad sponsored", "", "#Ad Sponsored")


def test_fabricated_evidence_is_rejected():
    assert not nodes._evidence_is_grounded("guaranteed 100 percent improvement", "ordinary product review", "")


def test_short_evidence_is_rejected():
    assert not nodes._evidence_is_grounded("ad", "This is an ad", "")


def test_evidence_matching_is_case_insensitive():
    assert nodes._evidence_is_grounded("PAID PARTNERSHIP", "This is a paid partnership.", "")


def test_verified_requirement_violation_returns_fail():
    result = _run_audit(_response("NON_COMPLIANT"))
    assert result["final_status"] == "FAIL"
    assert len(result["compliance_results"]) == 1
    assert result["requirement_coverage"]["non_compliant"] == 1


def test_compliant_requirement_returns_pass_when_scope_complete():
    result = _run_audit(_response("COMPLIANT"))
    assert result["final_status"] == "PASS"
    assert result["compliance_results"] == []


def test_fabricated_video_quote_is_excluded_and_requires_review():
    result = _run_audit(_response("NON_COMPLIANT", "invented sponsorship disclosure quote"))
    assert result["final_status"] == "REVIEW_REQUIRED"
    assert result["compliance_results"] == []
    assert "rejected" in result["final_report"].lower()


def test_missing_policy_assessment_blocks_audit_model_call():
    with patch.object(nodes, "get_grok_client") as grok:
        result = nodes.audit_content_node({
            "indexing_status": "COMPLETED",
        "audit_context": {"jurisdiction": "US"},
            "transcript": "A video transcript is available for review.",
            "policy_coverage": _policy_coverage(),
            "policy_assessments": [],
        })
    grok.assert_not_called()
    assert result["final_status"] == "REVIEW_REQUIRED"


def test_missing_policy_reference_cannot_produce_fail():
    response = _response("NON_COMPLIANT")
    response.assessments[0].regulatory_references = []
    result = _run_audit(response)
    assert result["final_status"] == "REVIEW_REQUIRED"
    assert result["compliance_results"] == []

def test_both_policy_domains_not_applicable_returns_not_applicable():
    state = {
        "indexing_status": "COMPLETED",
        "audit_context": {"jurisdiction": "US"},
        "transcript": "Ordinary cricket match highlights.",
        "ocr_text": "",
        "metadata": {},
        "policy_assessments": [
            {
                "domain": "ADVERTISING_DISCLOSURES",
                "applicability": "NOT_APPLICABLE",
                "confidence": 1.0,
                "missing_information": [],
            },
            {
                "domain": "YOUTUBE_AD_SPECIFICATIONS",
                "applicability": "NOT_APPLICABLE",
                "confidence": 1.0,
                "missing_information": [],
            },
        ],
        "policy_coverage": {
            "ADVERTISING_DISCLOSURES": "NOT_APPLICABLE",
            "YOUTUBE_AD_SPECIFICATIONS": "NOT_APPLICABLE",
        },
    }

    with patch.object(nodes, "get_grok_client") as grok:
        result = nodes.audit_content_node(state)

    grok.assert_not_called()
    assert result["final_status"] == "NOT_APPLICABLE"
    assert result["current_stage"] == "AUDIT_NOT_APPLICABLE"
    assert result["processing_complete"] is True
    assert result["requirement_assessments"] == []
    assert result["compliance_results"] == []
    assert result["requirement_coverage"]["total_identified"] == 0


def test_uncertain_domain_with_no_applicable_domains_requires_review():
    state = {
        "indexing_status": "COMPLETED",
        "audit_context": {"jurisdiction": "US"},
        "transcript": "Ordinary video content.",
        "ocr_text": "",
        "metadata": {},
        "policy_assessments": [
            {
                "domain": "ADVERTISING_DISCLOSURES",
                "applicability": "NOT_APPLICABLE",
                "confidence": 1.0,
            },
            {
                "domain": "YOUTUBE_AD_SPECIFICATIONS",
                "applicability": "UNCERTAIN",
                "confidence": 0.5,
            },
        ],
        "policy_coverage": {
            "ADVERTISING_DISCLOSURES": "NOT_APPLICABLE",
            "YOUTUBE_AD_SPECIFICATIONS": "UNCERTAIN",
        },
    }

    with patch.object(nodes, "get_grok_client") as grok:
        result = nodes.audit_content_node(state)

    grok.assert_not_called()
    assert result["final_status"] == "REVIEW_REQUIRED"
    assert result["current_stage"] == "AUDIT_REVIEW_REQUIRED"
    assert result["processing_complete"] is True


def test_applicable_domain_with_other_domain_not_applicable_runs_audit():
    result = _run_audit(_response("COMPLIANT"))

    assert result["final_status"] == "PASS"
    assert result["requirement_coverage"]["applicable"] == 1
    assert result["requirement_coverage"]["compliant"] == 1
    assert result["compliance_results"] == []


def test_uncertain_domain_reason_does_not_claim_requirements_were_evaluated():
    response = _response("NOT_EVALUATED")
    response.assessments[0].applicability = "UNCERTAIN"
    prompt = MagicMock()
    chain = MagicMock()
    prompt.__or__.return_value = chain
    chain.invoke.return_value = response
    grok = MagicMock()
    grok.with_structured_output.return_value = MagicMock()
    policy_text = (
        "Source: influencer-guide.pdf\nPDF page: 2\nPolicy text:\n"
        "A clear and conspicuous disclosure must be made with the endorsement."
    )
    state = {
        "indexing_status": "COMPLETED",
        "audit_context": {"jurisdiction": "US"},
        "transcript": "This video includes a paid partnership with a brand.",
        "ocr_text": "",
        "metadata": {},
        "transcript_segments": [],
        "ocr_segments": [],
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
        patch.object(nodes, "get_grok_client", return_value=grok),
        patch.object(nodes, "get_embedding_client", return_value=object()),
        patch.object(nodes, "get_vector_store", return_value=object()),
        patch.object(
            nodes, "retrieve_regulatory_evidence",
            return_value=(policy_text, [{"source": "influencer-guide.pdf", "page": 2}]),
        ),
        patch.object(nodes.ChatPromptTemplate, "from_messages", return_value=prompt),
    ):
        result = nodes.audit_content_node(state)

    assert result["final_status"] == "REVIEW_REQUIRED"
    assert result["requirement_coverage"]["uncertain"] == 1
    assert result["requirement_coverage"]["not_evaluated"] == 1
    assert any(
        "YOUTUBE_AD_SPECIFICATIONS" in reason
        for reason in result["audit_decision_reasons"]
    )
    assert all(
        "Requirements in other confirmed applicable domains were still evaluated" not in reason
        for reason in result["audit_decision_reasons"]
    )
