from backend.src.auditing.screening import enrich_report, corpus_fingerprint
from backend.src.auditing.policy_scope import citation_matches_block, source_matches_domain
from backend.src.auditing.public_report import public_result


def test_unknown_context_is_actionable():
    result = enrich_report({'final_status':'REVIEW_REQUIRED','policy_coverage':{
        'ADVERTISING_DISCLOSURES':'UNCERTAIN','YOUTUBE_AD_SPECIFICATIONS':'UNCERTAIN'}}, {})
    assert result['required_user_inputs'] == ['commercial_relationship','youtube_placement']
    assert result['review_required']
    assert result['requirement_evaluation_status'] == 'NOT_EVALUATED'


def test_screening_pass_is_not_regulatory_clearance():
    result = enrich_report({'final_status':'PASS','final_report':'Final decision: PASS'}, {})
    assert result['screening_status'] == 'PASS'
    assert result['final_status'] == 'REVIEW_REQUIRED'
    assert 'Final decision: PASS' not in result['final_report']
    assert not result['policy_coverage_verified']


def test_fail_and_out_of_scope_preserved():
    for status in ['FAIL','NOT_APPLICABLE']:
        assert enrich_report({'final_status':status}, {})['final_status'] == status


def test_page_less_markdown_citation():
    packet = 'Source: ftc-guide.md\nPDF page: Not applicable\nPolicy text:\nDisclose material connections clearly.'
    assert citation_matches_block('ftc-guide.md', None, 'Disclose material connections', packet)
    assert not citation_matches_block('ftc-guide.md', 1, 'Disclose material connections', packet)


def test_cross_block_citation_rejected():
    packet = 'Source: a.pdf\nPDF page: 1\nPolicy text:\nFirst source only.\n\n---\n\nSource: b.pdf\nPDF page: 2\nPolicy text:\nDisclose material connections clearly.'
    assert not citation_matches_block('a.pdf', 1, 'Disclose material connections', packet)
    assert not citation_matches_block('a.pdf', 2, 'Disclose material connections', packet)
    assert citation_matches_block('b.pdf', 2, 'Disclose material connections', packet)


def test_source_domain_filter():
    assert source_matches_domain('ftc-endorsement-guides-faq.md','ADVERTISING_DISCLOSURES')
    assert not source_matches_domain('google-ads-youtube-video-specs.md','ADVERTISING_DISCLOSURES')
    assert not source_matches_domain('unverified.md','YOUTUBE_AD_SPECIFICATIONS')


def test_public_report_omits_raw_transcript():
    result = public_result({'transcript':'private','final_status':'FAIL'}, {'ad_format':'BUMPER'})
    assert 'transcript' not in result
    assert result['audit_context']['ad_format'] == 'BUMPER'
    assert len(corpus_fingerprint()) == 64


def test_paid_ad_requires_format():
    result = enrich_report({'final_status':'REVIEW_REQUIRED'}, {'youtube_placement':'PAID_AD'})
    assert 'ad_format' in result['required_user_inputs']


def test_deterministic_rule_requires_approval_and_original_asset():
    from backend.src.auditing.technical_checks import evaluate_numeric_rule
    # Synthetic limit for unit testing, not a real Google Ads specification.
    rule = {'id':'TEST-1','metric':'duration_seconds','operator':'<=','limit':10,
            'approval_status':'APPROVED','source':'synthetic test','version':'test'}
    assert evaluate_numeric_rule(rule, {'duration_seconds':12})['evaluation_status'] == 'INSUFFICIENT_EVIDENCE'
    assert evaluate_numeric_rule(rule, {'duration_seconds':12}, original_asset_verified=True)['evaluation_status'] == 'NON_COMPLIANT'
    assert evaluate_numeric_rule(rule, {'duration_seconds':10}, original_asset_verified=True)['evaluation_status'] == 'COMPLIANT'
    assert evaluate_numeric_rule({**rule,'approval_status':'DRAFT'}, {}, original_asset_verified=True)['evaluation_status'] == 'NOT_EVALUATED'
