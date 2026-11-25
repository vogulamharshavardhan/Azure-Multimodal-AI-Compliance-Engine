"""Opt-in Redis extraction cache. Explicit short TTL; never caches decisions/context."""
import hashlib
import json
import os
import logging

FIELDS = ('indexing_status','azure_video_id','transcript','transcript_segments','ocr_text','raw_ocr_segments','ocr_segments','metadata','extraction_status')

def key_for(url):
    return 'bg:extraction:v1:' + hashlib.sha256(json.dumps([url, os.getenv('MAX_VIDEO_DIMENSION','1920'), os.getenv('MAX_VIDEO_DURATION_SECONDS','1200'), os.getenv('MAX_VIDEO_SIZE_MB','250')]).encode()).hexdigest()

def read(client, url):
    try:
        raw = client.get(key_for(url))
        data = json.loads(raw) if raw else None
        if isinstance(data, dict) and data.get('indexing_status') == 'COMPLETED':
            return {k:data[k] for k in FIELDS if k in data}
    except Exception:
        logging.getLogger(__name__).warning('Extraction cache read failed')
    return None

def write(client, url, result):
    if result.get('indexing_status') != 'COMPLETED':
        return
    try:
        ttl = min(86400, max(0, int(os.getenv('EXTRACTION_CACHE_TTL_SECONDS','0'))))
        if ttl:
            client.set(key_for(url), json.dumps({k:result[k] for k in FIELDS if k in result}, default=str), ex=ttl)
    except Exception:
        logging.getLogger(__name__).warning('Extraction cache write failed')
