"""Demonstrate public report behavior with synthetic data, without cloud calls."""
import json
from backend.src.auditing.public_report import public_result

if __name__ == '__main__':
    cases = [
        ('Unknown scope', 'REVIEW_REQUIRED', {'ADVERTISING_DISCLOSURES':'UNCERTAIN','YOUTUBE_AD_SPECIFICATIONS':'UNCERTAIN'}),
        ('Retrieved rules pass', 'PASS', {'ADVERTISING_DISCLOSURES':'APPLICABLE','YOUTUBE_AD_SPECIFICATIONS':'NOT_APPLICABLE'}),
        ('Verified finding (simulated)', 'FAIL', {'ADVERTISING_DISCLOSURES':'APPLICABLE','YOUTUBE_AD_SPECIFICATIONS':'NOT_APPLICABLE'}),
        ('Out of supported scope', 'NOT_APPLICABLE', {'ADVERTISING_DISCLOSURES':'NOT_APPLICABLE','YOUTUBE_AD_SPECIFICATIONS':'NOT_APPLICABLE'}),
    ]
    for name, status, coverage in cases:
        result = public_result({'final_status':status,'policy_coverage':coverage,'processing_complete':True,'indexing_status':'COMPLETED'})
        print(json.dumps({'synthetic_case':name,'screening_status':result['screening_status'],
                          'final_status':result['final_status'],'required_user_inputs':result['required_user_inputs']}))
