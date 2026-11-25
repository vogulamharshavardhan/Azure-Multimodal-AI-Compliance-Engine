from backend.src.auditing.screening import enrich_report

def public_result(result: dict, context: dict | None = None) -> dict:
    """Map graph state to the API response contract without raw video evidence."""
    report = {
        "video_id": result.get("video_id"),
        "azure_video_id": result.get("azure_video_id"),
        "indexing_status": str(result.get("indexing_status", "UNKNOWN")),
        "final_status": str(result.get("final_status", "REVIEW_REQUIRED")),
        "current_stage": result.get("current_stage"),
        "processing_complete": bool(result.get("processing_complete", False)),
        "final_report": result.get("final_report"),
        "policy_assessments": result.get("policy_assessments") or [],
        "policy_coverage": result.get("policy_coverage") or {},
        "requirement_assessments": result.get("requirement_assessments") or [],
        "audit_diagnostics": result.get("audit_diagnostics") or {},
        "requirement_coverage": result.get("requirement_coverage") or {},
        "audit_decision_reasons": result.get("audit_decision_reasons") or [],
        "compliance_results": result.get("compliance_results") or [],
        "citations": result.get("citations") or result.get("regulatory_citations") or [],
        "errors": result.get("errors") or [],
        "extraction_status": result.get("extraction_status") or {},
        "video_metadata": result.get("metadata") or result.get("video_metadata") or {},
    }

    return enrich_report(report, context if context is not None else result.get("audit_context"))
