"""Evidence validation and deterministic compliance decision rules."""
from __future__ import annotations

import logging
import re
from typing import Any
from dotenv import load_dotenv
load_dotenv()
from backend.src.graph.states import POLICY_DOMAINS

logger = logging.getLogger(__name__)

def _resolve_audit_status(
    model_status: str,
    verified_issue_count: int,
    rejected_evidence_count: int,
    policy_coverage: dict[str, str] | None,
) -> str:
    """Backward-compatible deterministic resolver for legacy callers/tests.

    The Phase 1.3 auditor uses requirement-level decisions below. This helper
    remains available for existing integrations that still submit a model
    status and domain coverage summary.
    """
    status = model_status if model_status in {"PASS", "FAIL", "REVIEW"} else "REVIEW"
    logger.debug(
        "Resolving audit status. model_status=%s verified_issues=%d rejected_evidence=%d",
        status,
        verified_issue_count,
        rejected_evidence_count,
    )
    coverage = policy_coverage or {}
    complete = all(
        coverage.get(domain) in {"APPLICABLE", "NOT_APPLICABLE"}
        for domain in POLICY_DOMAINS
    )
    has_applicable = any(
        coverage.get(domain) == "APPLICABLE" for domain in POLICY_DOMAINS
    )
    if rejected_evidence_count > 0 or not complete or not has_applicable:
        return "REVIEW"
    if status == "FAIL" and verified_issue_count <= 0:
        return "REVIEW"
    if status == "PASS" and verified_issue_count > 0:
        return "REVIEW"
    return status


def _evidence_is_grounded(
    evidence: str,
    transcript: str,
    ocr_text: str,
    metadata_text: str = "",
) -> bool:
    """
    Require evidence quotes to occur in extracted source text.

    Matching ignores case and repeated whitespace.
    """

    quote = re.sub(
        r"\s+",
        " ",
        evidence,
    ).strip().casefold()

    if len(quote) < 8:
        return False

    sources = [
        transcript,
        ocr_text,
        metadata_text,
    ]

    for source in sources:

        normalized = re.sub(
            r"\s+",
            " ",
            source,
        ).strip().casefold()

        if quote in normalized:
            return True

    return False


def _normalize_for_match(value: str) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip().casefold()


def _policy_quote_is_grounded(quote: str, retrieved_policy: str) -> bool:
    normalized = _normalize_for_match(quote)
    return len(normalized) >= 12 and normalized in _normalize_for_match(retrieved_policy)


def _resolve_requirement_status(
    policy_coverage: dict[str, str],
    assessments: list[dict[str, Any]],
) -> tuple[str, list[str]]:
    """Resolve the final result from verified requirement-level evidence only."""
    reasons: list[str] = []
    if not policy_coverage or any(
        policy_coverage.get(domain) not in {"APPLICABLE", "NOT_APPLICABLE"}
        for domain in POLICY_DOMAINS
    ):
        return "REVIEW_REQUIRED", ["Policy applicability coverage is incomplete or uncertain."]

    applicable_domains = {
        domain for domain, status in policy_coverage.items()
        if status == "APPLICABLE"
    }
    if not applicable_domains:
        logger.info("Audit decision requires review because no policy domain is applicable.")
        return "REVIEW_REQUIRED", ["Neither supported policy domain was established as applicable; human confirmation is required."]

    applicable_assessments = [
        item for item in assessments
        if item.get("applicability") == "APPLICABLE"
    ]
    if not applicable_assessments:
        return "REVIEW_REQUIRED", ["No applicable policy requirements were successfully evaluated."]

    if any(item.get("evaluation_status") == "NON_COMPLIANT" for item in applicable_assessments):
        logger.info("Audit decision: FAIL. A verified non-compliant requirement exists.")
        return "FAIL", ["At least one applicable requirement has a verified non-compliant finding."]

    incomplete = [
        item for item in applicable_assessments
        if item.get("evaluation_status") != "COMPLIANT"
    ]
    if incomplete:
        reasons.append("One or more applicable requirements have insufficient evidence or were not evaluated.")
        return "REVIEW_REQUIRED", reasons

    if any(item.get("applicability") == "UNCERTAIN" for item in assessments):
        return "REVIEW_REQUIRED", ["At least one requirement has uncertain applicability."]

    logger.info("Audit decision: PASS. All applicable evaluated requirements are compliant.")
    return "PASS", ["All retrieved applicable requirements were evaluated as compliant against the supplied video evidence."]

