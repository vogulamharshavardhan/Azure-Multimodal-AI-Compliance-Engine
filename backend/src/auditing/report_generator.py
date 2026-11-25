"""Pure formatting for requirement-level compliance reports."""
from __future__ import annotations

import logging
from typing import Any
from dotenv import load_dotenv
load_dotenv()
logger = logging.getLogger(__name__)


def generate_compliance_report(
    final_status: str,
    requirement_coverage: dict[str, int],
    assessments: list[dict[str, Any]],
    decision_reasons: list[str],
    citations: list[dict[str, Any]],
    rejected_policy_refs: int = 0,
    rejected_video_quotes: int = 0,
) -> str:
    """Format a deterministic report from verified audit results."""
    logger.debug(
        "Generating compliance report. status=%s assessments=%d citations=%d",
        final_status,
        len(assessments),
        len(citations),
    )

    lines = [
        f"Final decision: {final_status}",
        f"Requirements identified: {requirement_coverage.get('total_identified', 0)}",
        (
            f"Applicable: {requirement_coverage.get('applicable', 0)} | "
            f"Not applicable: {requirement_coverage.get('not_applicable', 0)} | "
            f"Uncertain: {requirement_coverage.get('uncertain', 0)} | "
            f"Compliant: {requirement_coverage.get('compliant', 0)} | "
            f"Non-compliant: {requirement_coverage.get('non_compliant', 0)} | "
            f"Insufficient evidence: {requirement_coverage.get('insufficient_evidence', 0)} | "
            f"Not evaluated: {requirement_coverage.get('not_evaluated', 0)}"
        ),
        "",
        "Requirement assessments:",
    ]

    for item in assessments:
        lines.append(
            f"- {item['requirement_id']} ({item['domain']}): "
            f"{item['requirement_name']} | "
            f"{item['applicability']} / {item['evaluation_status']} | "
            f"{item['reasoning']}"
        )

    lines.extend(["", "Decision reasons:"])
    lines.extend(f"- {reason}" for reason in decision_reasons)
    lines.extend(["", "Retrieved regulatory references:"])
    for citation in citations:
        location = (
            f"page {citation['page']}"
            if citation.get("page") is not None
            else f"chunk {citation['chunk_id']}"
            if citation.get("chunk_id")
            else "section/chunk location not available"
        )
        authority = citation.get("source_authority")
        url = citation.get("source_url")
        line = f"- {citation['source']} ({location})"
        if authority:
            line += f" | authority: {authority}"
        if url:
            line += f" | source: {url}"
        lines.append(line)

    if rejected_policy_refs or rejected_video_quotes:
        lines.append(
            "Rejected ungrounded material: "
            f"{rejected_policy_refs} policy reference(s), "
            f"{rejected_video_quotes} video quote(s)."
        )

    return "\n".join(lines)
