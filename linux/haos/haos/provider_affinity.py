"""Reviewed conversation affinity, never arbitrary caller-selected headers."""
from urllib.parse import urlsplit

KEY = 'session_affinity_key'


def is_opencode(policy):
    return policy.provider in {'opencode-go', 'opencode-zen'} or urlsplit(policy.endpoint).hostname == 'opencode.ai'


def validate_key(value):
    if not isinstance(value, str) or not 1 <= len(value) <= 512 or any(ord(char) < 33 or ord(char) > 126 for char in value):
        raise PermissionError('invalid local conversation affinity')
    return value


def capture(policy, params):
    from agent.opencode_affinity import resolve_affinity_key, opencode_session_headers
    value = resolve_affinity_key(params.get('session_id'))
    if not value and is_opencode(policy):
        value = opencode_session_headers(policy.provider, policy.endpoint).get('x-opencode-session')
    return validate_key(value) if value else None


def headers(policy, context):
    if not is_opencode(policy):
        return {}
    from agent.opencode_affinity import opencode_session_headers
    value = context['params'].get(KEY) if context is not None else None
    if value is not None: value = validate_key(value)
    result = opencode_session_headers(policy.provider, policy.endpoint, value)
    if set(result) != {'x-opencode-session'}:
        raise PermissionError('unexpected native conversation header')
    validate_key(result['x-opencode-session'])
    return result
