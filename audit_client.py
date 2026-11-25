"""Shared client for the CLI and local dashboard."""
import json
import os
from urllib.request import Request, urlopen
from urllib.parse import quote
from urllib.error import HTTPError

RELATIONSHIPS = ('UNKNOWN','NONE','PAID_SPONSORSHIP','GIFTED','AFFILIATE','OTHER_MATERIAL_CONNECTION')
PLACEMENTS = ('UNKNOWN','ORGANIC_UPLOAD','PAID_AD')
FORMATS = ('UNKNOWN','SKIPPABLE_IN_STREAM','NON_SKIPPABLE_IN_STREAM','BUMPER','IN_FEED','SHORTS','MASTHEAD')

def request_json(path, payload=None, *, api_key=None):
    key = api_key or os.getenv('API_KEY')
    if not key:
        raise RuntimeError('Configure API_KEY in .env')
    url = os.getenv('AUDIT_API_URL', 'http://127.0.0.1:8000').rstrip('/') + path
    request = Request(url, data=json.dumps(payload).encode() if payload is not None else None,
                      headers={'X-API-Key': key, 'Content-Type': 'application/json'},
                      method='POST' if payload is not None else 'GET')
    try:
        with urlopen(request, timeout=30) as response:
            return json.load(response)
    except HTTPError as exc:
        raise RuntimeError(f'API returned HTTP {exc.code}') from exc

def get_job(job_id, **kwargs):
    return request_json('/audit/jobs/' + quote(job_id, safe=''), **kwargs)
