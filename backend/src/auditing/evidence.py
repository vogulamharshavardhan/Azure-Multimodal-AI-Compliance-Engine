"""Bounded evidence selection; prioritize disclosure candidates before truncation."""
import json
import re

DISCLOSURE = re.compile(r'\b(?:sponsor(?:ed|ship|s)?|paid\s+(?:partnership|promotion|advertisement|for|by)|advertisement|affiliate|gifted|ad|partner(?:ship)?|provided\s+by)\b', re.I)


def all_records(state):
    records = {}
    for modality, key, fallback in [('TRANSCRIPT','transcript_segments','transcript'), ('OCR','ocr_segments','ocr_text')]:
        segments = state.get(key) or (state.get('raw_ocr_segments') if modality == 'OCR' else None) or []
        if not segments and state.get(fallback):
            segments = [{'text': str(state[fallback])}]
        for i, segment in enumerate(segments):
            if not isinstance(segment, dict) or not str(segment.get('text','')).strip():
                continue
            eid = f'{modality}_{i+1:04d}'
            records[eid] = {'evidence_id':eid,'modality':modality,'text':str(segment['text']), 'start':segment.get('start',segment.get('start_time')), 'end':segment.get('end',segment.get('end_time'))}
    # Preserve raw OCR candidates that cleaning may have removed. Keep separate IDs.
    existing = {(r['text'], str(r['start']), str(r['end'])) for r in records.values() if r['modality']=='OCR'}
    for i, segment in enumerate(state.get('raw_ocr_segments') or []):
        if not isinstance(segment, dict) or not DISCLOSURE.search(str(segment.get('text',''))):
            continue
        start, end = segment.get('start',segment.get('start_time')), segment.get('end',segment.get('end_time'))
        key = (str(segment['text']),str(start),str(end))
        if key not in existing:
            eid = f'OCR_RAW_{i+1:04d}'
            records[eid] = {'evidence_id':eid,'modality':'OCR','text':key[0],'start':start,'end':end}
            existing.add(key)
    return records


def candidates(records):
    return [k for k,v in records.items() if DISCLOSURE.search(v['text'])]


def build_catalog(state, budget=18000, domain='ADVERTISING_DISCLOSURES'):
    full = all_records(state)
    keys = list(full)
    priority = set(candidates(full)) if domain == 'ADVERTISING_DISCLOSURES' else set()
    # Include adjacent records in the same modality, e.g. sponsor name on next OCR line.
    nearby = {keys[j] for i,k in enumerate(keys) if k in priority for j in (i-1,i+1) if 0 <= j < len(keys) and keys[j].split('_')[0] == k.split('_')[0]}
    ordered = sorted(keys, key=lambda k: 0 if k in priority else 1 if k in nearby else 2)
    records = {}; used = 0
    for eid in ordered:
        record = full[eid]
        size = len(json.dumps(record, ensure_ascii=False, default=str)) + 10
        if used + size <= budget:
            records[eid] = record; used += size
    return records, len(full)-len(records)


def resolve_ids(ids, catalog):
    accepted, rejected = [], 0
    for eid in dict.fromkeys(ids):
        if eid in catalog:
            accepted.append({**catalog[eid], 'verified':True})
        else:
            rejected += 1
    return accepted, rejected


def absence_observation(state, omitted):
    extraction = state.get('extraction_status') or {}
    found = candidates(all_records(state))
    return {'status':'POTENTIAL_DISCLOSURE_DETECTED' if found else 'NOT_DETECTED_IN_EXTRACTED_EVIDENCE', 'candidate_count':len(found), 'transcription_status':extraction.get('transcription_status'), 'ocr_status':extraction.get('ocr_status'), 'omitted_segments':omitted, 'absence_verified':False, 'limitation':'OCR and transcript extraction cannot establish absence throughout the original audio/video; manual review required.'}
