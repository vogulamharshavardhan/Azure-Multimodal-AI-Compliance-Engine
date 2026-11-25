"""Deterministic checks for original assets using reviewer-approved numeric rules.

Not called by the YouTube pipeline: the downloaded/transcoded rendition is not
proof of original campaign asset specifications. No policy thresholds are assumed.
"""
import math

METRICS = {'duration_seconds', 'width', 'height', 'size_bytes'}

def evaluate_numeric_rule(rule, metadata, *, original_asset_verified=False):
    """Evaluate a separately approved rule or return an explicit unknown result."""
    result = {'requirement_id': rule.get('id'), 'evaluation_status': 'NOT_EVALUATED'}
    if rule.get('approval_status') != 'APPROVED' or not rule.get('source') or not rule.get('version'):
        return {**result, 'reason': 'A versioned, approved policy rule is required.'}
    if not original_asset_verified:
        return {**result, 'evaluation_status': 'INSUFFICIENT_EVIDENCE', 'reason': 'Original asset provenance is not verified.'}
    metric = rule.get('metric')
    value, limit = metadata.get(metric), rule.get('limit')
    valid = lambda x: type(x) in (int, float) and math.isfinite(x) and x >= 0
    if metric not in METRICS or not valid(limit) or rule.get('operator') not in ('<=', '>=', '=='):
        return {**result, 'reason': 'Unsupported or invalid rule.'}
    if not valid(value):
        return {**result, 'evaluation_status': 'INSUFFICIENT_EVIDENCE', 'reason': 'Required measurement is unavailable.'}
    passed = {'<=': value <= limit, '>=': value >= limit, '==': value == limit}[rule['operator']]
    return {**result, 'evaluation_status': 'COMPLIANT' if passed else 'NON_COMPLIANT',
            'metric': metric, 'observed': value, 'limit': limit, 'operator': rule['operator'],
            'source': rule['source'], 'version': rule['version']}
