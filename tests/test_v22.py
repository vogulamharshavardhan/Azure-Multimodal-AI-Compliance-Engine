from backend.src.auditing.evidence import build_catalog, all_records, candidates, absence_observation, resolve_ids
from backend.src.auditing.passages import build_passages, resolve_passages, normalize_finding


def test_late_sponsor_candidate_survives_transcript_budget():
    state = {'transcript_segments':[{'text':'ordinary discussion '*20} for _ in range(200)], 'ocr_segments':[{'text':'SPONSORED BY','start':'0:04:58','end':'0:05:00'},{'text':'EA'}]}
    selected, omitted = build_catalog(state, budget=1000)
    assert omitted > 0 and 'OCR_0001' in selected and 'OCR_0002' in selected
    assert resolve_ids(['OCR_0001'],selected)[0][0]['start']=='0:04:58'
    assert candidates(all_records(state)) == ['OCR_0001']
    assert absence_observation(state, omitted)['status']=='POTENTIAL_DISCLOSURE_DETECTED'
    assert not absence_observation(state, omitted)['absence_verified']


def test_policy_id_provenance_and_domain_isolation():
    block='Source: ftc-guide.pdf\nPDF page: 2\nPolicy text:\nA disclosure must be clear.'
    catalog=build_passages({'ADVERTISING_DISCLOSURES':block})
    pid=next(iter(catalog))
    accepted, rejected=resolve_passages([pid,'FAKE'],catalog,'ADVERTISING_DISCLOSURES')
    assert rejected==1 and accepted[0]['page']==2 and accepted[0]['policy_text']=='A disclosure must be clear.'
    assert resolve_passages([pid],catalog,'YOUTUBE_AD_SPECIFICATIONS')==([],1)
    assert list(build_passages({'ADVERTISING_DISCLOSURES':block}))==[pid]
    assert not build_passages({'ADVERTISING_DISCLOSURES':block},budget=10)


def test_missing_citation_does_not_erase_applicable_scope():
    assert normalize_finding('APPLICABLE','NON_COMPLIANT',False,True,False,False)=='INSUFFICIENT_EVIDENCE'


def test_absence_never_conclusive():
    for status in ['COMPLIANT','NON_COMPLIANT']:
        assert normalize_finding('APPLICABLE',status,True,True,True,True)=='INSUFFICIENT_EVIDENCE'
    assert normalize_finding('UNCERTAIN','COMPLIANT',True,True,False,False)=='NOT_EVALUATED'


def test_cleaning_does_not_hide_raw_sponsor_candidate():
    state={'ocr_segments':[{'text':'EA'}], 'raw_ocr_segments':[{'text':'SPONSORED BY','start':1,'end':2}]}
    catalog,_=build_catalog(state)
    assert catalog['OCR_RAW_0001']['text']=='SPONSORED BY'
