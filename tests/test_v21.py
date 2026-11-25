import json
from backend.src.auditing.evidence import build_catalog, resolve_ids, absence_observation
from backend.src.auditing.policy_scope import jurisdiction_supported
from backend.src.auditing.screening import enrich_report
from backend.src.auditing import extraction_cache, progress


def test_ids_resolve_original_text_and_timestamps():
    catalog, omitted = build_catalog({'ocr_segments':[{'text':'FLAT 70%', 'start':1,'end':2}]})
    found, rejected = resolve_ids(['OCR_0001','FAKE','OCR_0001'], catalog)
    assert omitted == 0 and rejected == 1 and len(found) == 1
    assert found[0]['text'] == 'FLAT 70%' and found[0]['start'] == 1


def test_omitted_record_cannot_be_cited():
    catalog, omitted = build_catalog({'transcript':'long text'*100}, budget=10)
    assert omitted == 1 and resolve_ids(['TRANSCRIPT_0001'],catalog) == ([],1)


def test_absence_is_not_verified_even_with_successful_extraction():
    assert not absence_observation({'extraction_status':{'ocr_status':'SUCCESS','transcription_status':'SUCCESS'}},0)['absence_verified']


def test_jurisdiction_scope():
    for country in ['UNKNOWN','India','IN']:
        assert not jurisdiction_supported('ADVERTISING_DISCLOSURES',country)
    assert jurisdiction_supported('ADVERTISING_DISCLOSURES','United States')
    assert jurisdiction_supported('YOUTUBE_AD_SPECIFICATIONS','UNKNOWN')


def test_partial_evaluation():
    report = enrich_report({'requirement_assessments':[{'evaluation_status':'INSUFFICIENT_EVIDENCE'},{'evaluation_status':'NOT_EVALUATED'}]}, {})
    assert report['requirement_evaluation_status'] == 'PARTIALLY_EVALUATED'
    assert report['requirements_attempted'] == 1 and report['requirements_conclusively_evaluated'] == 0


def test_cache_only_extraction(monkeypatch):
    class Client:
        data = {}
        def set(self,key,value,ex): self.data[key] = value; assert ex == 60
        def get(self,key): return self.data.get(key)
    client = Client()
    monkeypatch.setenv('EXTRACTION_CACHE_TTL_SECONDS','60')
    extraction_cache.write(client,'url',{'indexing_status':'COMPLETED','transcript':'example','final_status':'PASS','audit_context':{'jurisdiction':'US'}})
    assert extraction_cache.read(client,'url') == {'indexing_status':'COMPLETED','transcript':'example'}
    assert extraction_cache.read(client,'other') is None


def test_progress_scoped():
    stages=[]
    token=progress.callback.set(stages.append)
    try: progress.emit('AZURE_INDEXING')
    finally: progress.callback.reset(token)
    progress.emit('AFTER')
    assert stages == ['AZURE_INDEXING']
