"""Resolve policy IDs only within the retrieved, supplied domain packet."""
import hashlib
import json


def build_passages(packets, budget=50000):
    result = {}; used = 0
    for domain, packet in packets.items():
        for block in packet.split('\n\n---\n\n'):
            header, sep, content = block.partition('Policy text:')
            fields = dict(line.split(': ',1) for line in header.splitlines() if ': ' in line)
            if not sep or not fields.get('Source') or not content.strip():
                continue
            raw_page = fields.get('PDF page','Not applicable')
            if raw_page != 'Not applicable' and not raw_page.isdigit():
                continue
            record = {'domain':domain,'source':fields['Source'],'page':int(raw_page) if raw_page.isdigit() else None,'policy_text':content.strip()}
            if fields.get('Source URL') not in (None,'Not recorded'):
                record['source_url'] = fields['Source URL']
            pid = 'POL_' + hashlib.sha256(json.dumps(record,sort_keys=True).encode()).hexdigest()[:24]
            record['policy_passage_id'] = pid
            size = len(json.dumps(record,ensure_ascii=False)) + 10
            if pid not in result and used+size <= budget:
                result[pid] = record; used += size
    return result


def resolve_passages(ids, catalog, domain):
    accepted = []; rejected = 0
    for pid in dict.fromkeys(ids):
        row = catalog.get(pid)
        if row and row['domain'] == domain:
            accepted.append({k:v for k,v in row.items() if k != 'domain'})
        else:
            rejected += 1
    return accepted,rejected


def normalize_finding(applicability, evaluation, has_policy, has_video, absence_claim, has_candidates):
    # Missing citations block conclusions but do not erase the model's scope assertion.
    if applicability != 'APPLICABLE':
        return 'NOT_EVALUATED'
    if not has_policy or not has_video or absence_claim:
        return 'INSUFFICIENT_EVIDENCE'
    return evaluation
