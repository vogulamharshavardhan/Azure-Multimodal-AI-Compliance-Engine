"""Conservative public report enrichment. No external services required."""
import hashlib
import json
from pathlib import Path

DATA = Path(__file__).resolve().parents[2] / 'data'

def corpus_fingerprint():
    digest = hashlib.sha256()
    for path in sorted(DATA.glob('*')):
        if path.is_file():
            digest.update(path.name.encode())
            digest.update(path.read_bytes())
    return digest.hexdigest()

def enrich_report(report, context):
    report = dict(report)
    context = dict(context or {})
    coverage = report.get('policy_coverage') or {}
    required = []
    if coverage.get('ADVERTISING_DISCLOSURES') == 'UNCERTAIN' and context.get('commercial_relationship', 'UNKNOWN') == 'UNKNOWN':
        required.append('commercial_relationship')
    if coverage.get('YOUTUBE_AD_SPECIFICATIONS') == 'UNCERTAIN' and context.get('youtube_placement', 'UNKNOWN') == 'UNKNOWN':
        required.append('youtube_placement')
    if context.get('youtube_placement') == 'PAID_AD' and context.get('ad_format', 'UNKNOWN') == 'UNKNOWN':
        required.append('ad_format')
    if coverage.get('ADVERTISING_DISCLOSURES') == 'APPLICABLE' and context.get('jurisdiction', 'UNKNOWN') == 'UNKNOWN':
        required.append('jurisdiction')
    original = report.get('final_status', 'REVIEW_REQUIRED')
    reasons = list(report.get('audit_decision_reasons') or [])
    # The supplied corpus is a retrieval aid, not an independently approved exhaustive registry.
    # A screening PASS must never be represented as a complete regulatory clearance.
    if original == 'PASS':
        report['final_status'] = 'REVIEW_REQUIRED'
        report['current_stage'] = 'AUDIT_REVIEW_REQUIRED'
        reasons.append('Retrieved requirements passed screening, but exhaustive policy coverage has not been independently approved.')
        report['final_report'] = 'Human review required: retrieved requirements passed screening; complete policy coverage is not established.\n\n' + (report.get('final_report') or '').replace('Final decision: PASS', 'Retrieved-requirement screening: PASS')
    assessments = report.get("requirement_assessments") or []
    conclusive = sum(a.get("evaluation_status") in {"COMPLIANT", "NON_COMPLIANT"} for a in assessments)
    attempted = sum(a.get("evaluation_status") != "NOT_EVALUATED" for a in assessments)
    resolved = sum(a.get("evaluation_status") in {"COMPLIANT", "NON_COMPLIANT"} or a.get("applicability") == "NOT_APPLICABLE" for a in assessments)
    registry = json.loads((DATA.parent / "policies" / "registry.draft.json").read_text(encoding="utf-8"))
    report["policy_registry"] = {"version": registry["version"], "approval_status": registry["approval_status"], "candidate_requirement_ids": [r["id"] for r in registry["requirements"] if coverage.get(r["domain"]) == "APPLICABLE"]}
    report.update(requirements_attempted=attempted, requirements_conclusively_evaluated=conclusive)
    report.update(audit_context=context, screening_status=original,
                  policy_corpus_sha256=corpus_fingerprint(), policy_coverage_verified=False,
                  required_user_inputs=required, audit_decision_reasons=reasons,
                  review_required=report.get('final_status') == 'REVIEW_REQUIRED',
                  requirement_evaluation_status=('NOT_EVALUATED' if not attempted else 'EVALUATED' if resolved == len(assessments) else 'PARTIALLY_EVALUATED'))
    return report
