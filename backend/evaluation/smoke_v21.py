"""Synthetic public-decision regression cases, NOT an AI accuracy benchmark."""
import json
from pathlib import Path
from backend.src.auditing.screening import enrich_report

CASES = [
    ('screening-pass-blocked', 'PASS', 'REVIEW_REQUIRED'),
    ('known-screening-failure', 'FAIL', 'FAIL'),
    ('unresolved-evidence', 'REVIEW_REQUIRED', 'REVIEW_REQUIRED'),
    ('outside-supported-scope', 'NOT_APPLICABLE', 'NOT_APPLICABLE'),
]

def main():
    rows = []
    for case, raw, expected in CASES:
        actual = enrich_report({'final_status':raw}, {})['final_status']
        rows.append({'case_id':case,'notes':'Synthetic decision guard only; no video or LLM evaluation.', 'expected':{'decision':expected}, 'predicted':{'decision':actual}})
    path = Path('backend/evaluation/synthetic_guard_cases.jsonl')
    path.write_text(''.join(json.dumps(row)+'\n' for row in rows), encoding='utf-8')
    print(f'{sum(r["expected"] == r["predicted"] for r in rows)}/{len(rows)} synthetic decision guard cases passed')

if __name__ == '__main__':
    main()
