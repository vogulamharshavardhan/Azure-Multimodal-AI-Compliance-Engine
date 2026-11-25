from unittest.mock import patch

from backend.src.graph import nodes

from dotenv import load_dotenv
load_dotenv()
class FakeChain:
    def __init__(self, response):
        self.response = response

    def invoke(self, _payload):
        if isinstance(self.response, Exception):
            raise self.response
        return self.response


class FakePrompt:
    def __or__(self, _structured):
        return FakeChain(_FAKE_RESPONSE[0])


_FAKE_RESPONSE = [None]


class FakeGrok:
    def with_structured_output(self, *_args, **_kwargs):
        return object()


def _assessment(domain, applicability, quote=None, confidence=0.95):
    return nodes.PolicyDomainAssessment(
        domain=domain,
        applicability=applicability,
        confidence=confidence,
        rationale="Classification based on supplied video evidence.",
        supporting_evidence=[quote] if quote else [],
        missing_information=[],
    )


def _run_with_response(response, state=None):
    _FAKE_RESPONSE[0] = response
    base_state = {
        "indexing_status": "COMPLETED",
        "transcript": (
            "This is an independent editorial review with no paid partnership."
        ),
        "ocr_text": "",
        "transcript_segments": [],
        "ocr_segments": [],
        "ocr_classifications": [],
    }
    if state:
        base_state.update(state)

    with (
        patch.object(nodes, "get_grok_client", return_value=FakeGrok()),
        patch.object(nodes.ChatPromptTemplate, "from_messages", return_value=FakePrompt()),
    ):
        return nodes.policy_applicability_node(base_state)


def test_indexing_failure_skips_applicability():
    result = nodes.policy_applicability_node({"indexing_status": "FAILED"})

    assert result["policy_assessments"] == []
    assert result["policy_coverage"] == {}
    assert result["current_stage"] == "POLICY_APPLICABILITY_SKIPPED"


def test_missing_transcript_and_ocr_returns_uncertain_without_calling_grok():
    with patch.object(nodes, "get_grok_client") as grok:
        result = nodes.policy_applicability_node({
            "indexing_status": "COMPLETED",
            "transcript": "",
            "ocr_text": "",
            "ocr_segments": [],
        })

    grok.assert_not_called()
    assert result["policy_coverage"] == {
        "ADVERTISING_DISCLOSURES": "UNCERTAIN",
        "YOUTUBE_AD_SPECIFICATIONS": "UNCERTAIN",
    }
    assert result["current_stage"] == "POLICY_APPLICABILITY_REVIEW_REQUIRED"


def test_grounded_applicable_assessment_is_preserved():
    response = nodes.PolicyApplicabilityResponse(assessments=[
        _assessment(
            "ADVERTISING_DISCLOSURES",
            "APPLICABLE",
            "paid partnership",
        ),
        _assessment(
            "YOUTUBE_AD_SPECIFICATIONS",
            "UNCERTAIN",
            None,
        ),
    ])

    result = _run_with_response(response, {
        "transcript": "This video includes a paid partnership with a brand."
    })

    assert result["policy_coverage"]["ADVERTISING_DISCLOSURES"] == "APPLICABLE"
    assert result["policy_coverage"]["YOUTUBE_AD_SPECIFICATIONS"] == "UNCERTAIN"
    assert result["policy_assessments"][0]["supporting_evidence"] == ["paid partnership"]


def test_applicable_without_grounded_quote_becomes_uncertain():
    response = nodes.PolicyApplicabilityResponse(assessments=[
        _assessment("ADVERTISING_DISCLOSURES", "APPLICABLE", "invented sponsorship quote"),
        _assessment("YOUTUBE_AD_SPECIFICATIONS", "UNCERTAIN"),
    ])

    result = _run_with_response(response)

    assert result["policy_coverage"]["ADVERTISING_DISCLOSURES"] == "UNCERTAIN"
    assert result["policy_assessments"][0]["supporting_evidence"] == []


def test_not_applicable_requires_grounded_quote_and_high_confidence():
    response = nodes.PolicyApplicabilityResponse(assessments=[
        _assessment(
            "ADVERTISING_DISCLOSURES",
            "NOT_APPLICABLE",
            "independent editorial review",
            confidence=0.95,
        ),
        _assessment(
            "YOUTUBE_AD_SPECIFICATIONS",
            "NOT_APPLICABLE",
            "independent editorial review",
            confidence=0.95,
        ),
    ])

    result = _run_with_response(response)

    assert result["policy_coverage"] == {
        "ADVERTISING_DISCLOSURES": "NOT_APPLICABLE",
        "YOUTUBE_AD_SPECIFICATIONS": "NOT_APPLICABLE",
    }


def test_not_applicable_without_quote_becomes_uncertain():
    response = nodes.PolicyApplicabilityResponse(assessments=[
        _assessment("ADVERTISING_DISCLOSURES", "NOT_APPLICABLE", None, confidence=0.99),
        _assessment("YOUTUBE_AD_SPECIFICATIONS", "UNCERTAIN"),
    ])

    result = _run_with_response(response)

    assert result["policy_coverage"]["ADVERTISING_DISCLOSURES"] == "UNCERTAIN"


def test_missing_domain_assessment_becomes_uncertain():
    response = nodes.PolicyApplicabilityResponse(assessments=[
        _assessment(
            "ADVERTISING_DISCLOSURES",
            "APPLICABLE",
            "independent editorial review",
        )
    ])

    result = _run_with_response(response)

    assert result["policy_coverage"]["YOUTUBE_AD_SPECIFICATIONS"] == "UNCERTAIN"


def test_grok_failure_returns_uncertain_for_both_domains():
    _FAKE_RESPONSE[0] = RuntimeError("simulated Grok outage")
    with (
        patch.object(nodes, "get_grok_client", return_value=FakeGrok()),
        patch.object(nodes.ChatPromptTemplate, "from_messages", return_value=FakePrompt()),
    ):
        result = nodes.policy_applicability_node({
            "indexing_status": "COMPLETED",
            "transcript": "A sufficiently long transcript for classification.",
            "ocr_text": "",
        })

    assert result["policy_coverage"] == {
        "ADVERTISING_DISCLOSURES": "UNCERTAIN",
        "YOUTUBE_AD_SPECIFICATIONS": "UNCERTAIN",
    }
    assert result["current_stage"] == "POLICY_APPLICABILITY_FAILED"
    assert result["errors"][0]["node"] == "policy_applicability_node"



def test_final_status_requires_complete_applicability_coverage():
    assert nodes._resolve_audit_status(
        "PASS", 0, 0, {}
    ) == "REVIEW"

    assert nodes._resolve_audit_status(
        "PASS",
        0,
        0,
        {"ADVERTISING_DISCLOSURES": "APPLICABLE"},
    ) == "REVIEW"


def test_uncertain_domain_blocks_pass():
    assert nodes._resolve_audit_status(
        "PASS",
        0,
        0,
        {
            "ADVERTISING_DISCLOSURES": "APPLICABLE",
            "YOUTUBE_AD_SPECIFICATIONS": "UNCERTAIN",
        },
    ) == "REVIEW"


def test_complete_coverage_allows_pass():
    assert nodes._resolve_audit_status(
        "PASS",
        0,
        0,
        {
            "ADVERTISING_DISCLOSURES": "APPLICABLE",
            "YOUTUBE_AD_SPECIFICATIONS": "NOT_APPLICABLE",
        },
    ) == "PASS"


def test_verified_issue_allows_fail_when_scope_is_complete():
    assert nodes._resolve_audit_status(
        "FAIL",
        1,
        0,
        {
            "ADVERTISING_DISCLOSURES": "APPLICABLE",
            "YOUTUBE_AD_SPECIFICATIONS": "NOT_APPLICABLE",
        },
    ) == "FAIL"


def test_fail_without_verified_issue_becomes_review():
    assert nodes._resolve_audit_status(
        "FAIL",
        0,
        0,
        {
            "ADVERTISING_DISCLOSURES": "APPLICABLE",
            "YOUTUBE_AD_SPECIFICATIONS": "NOT_APPLICABLE",
        },
    ) == "REVIEW"


def test_rejected_evidence_blocks_pass_and_fail():
    coverage = {
        "ADVERTISING_DISCLOSURES": "APPLICABLE",
        "YOUTUBE_AD_SPECIFICATIONS": "NOT_APPLICABLE",
    }
    assert nodes._resolve_audit_status("PASS", 0, 1, coverage) == "REVIEW"
    assert nodes._resolve_audit_status("FAIL", 1, 1, coverage) == "REVIEW"


def test_all_domains_not_applicable_requires_review():
    assert nodes._resolve_audit_status(
        "PASS",
        0,
        0,
        {
            "ADVERTISING_DISCLOSURES": "NOT_APPLICABLE",
            "YOUTUBE_AD_SPECIFICATIONS": "NOT_APPLICABLE",
        },
    ) == "REVIEW"


def test_explicit_requester_context_resolves_organic_noncommercial_video():
    response = nodes.PolicyApplicabilityResponse(assessments=[
        _assessment("ADVERTISING_DISCLOSURES", "UNCERTAIN"),
        _assessment("YOUTUBE_AD_SPECIFICATIONS", "UNCERTAIN"),
    ])
    result = _run_with_response(response, {
        "audit_context": {
            "commercial_relationship": "NONE",
            "youtube_placement": "ORGANIC_UPLOAD",
        }
    })
    assert result["policy_coverage"] == {
        "ADVERTISING_DISCLOSURES": "NOT_APPLICABLE",
        "YOUTUBE_AD_SPECIFICATIONS": "NOT_APPLICABLE",
    }
    assert result["policy_assessments"][0]["context_basis"]
    assert result["policy_assessments"][1]["context_basis"]


def test_explicit_sponsorship_context_resolves_disclosure_scope():
    response = nodes.PolicyApplicabilityResponse(assessments=[
        _assessment("ADVERTISING_DISCLOSURES", "UNCERTAIN"),
        _assessment("YOUTUBE_AD_SPECIFICATIONS", "UNCERTAIN"),
    ])
    result = _run_with_response(response, {
        "audit_context": {
            "commercial_relationship": "PAID_SPONSORSHIP",
            "youtube_placement": "ORGANIC_UPLOAD",
        }
    })
    assert result["policy_coverage"]["ADVERTISING_DISCLOSURES"] == "APPLICABLE"
    assert result["policy_coverage"]["YOUTUBE_AD_SPECIFICATIONS"] == "NOT_APPLICABLE"


def test_conflicting_user_context_and_video_assessment_remains_uncertain():
    response = nodes.PolicyApplicabilityResponse(assessments=[
        _assessment("ADVERTISING_DISCLOSURES", "APPLICABLE", "paid partnership"),
        _assessment("YOUTUBE_AD_SPECIFICATIONS", "UNCERTAIN"),
    ])
    result = _run_with_response(response, {
        "transcript": "This video includes a paid partnership with a brand.",
        "audit_context": {
            "commercial_relationship": "NONE",
            "youtube_placement": "ORGANIC_UPLOAD",
        },
    })
    assert result["policy_coverage"]["ADVERTISING_DISCLOSURES"] == "UNCERTAIN"
    assert "conflicts" in result["policy_assessments"][0]["rationale"]
