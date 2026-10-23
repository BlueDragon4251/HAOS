"""Account-scoped Router reasoning metadata stays in the private broker."""
from copy import deepcopy
import hashlib
import json
import sys
import time
from urllib.parse import urlsplit


def safe_items(items, approved, allowed_levels):
    if not isinstance(items, list) or len(items) > 4096:
        raise ValueError('invalid private Router catalogue')
    result = []
    for item in items:
        if not isinstance(item, dict) or not isinstance(item.get('id'), str) or item['id'] not in approved:
            continue
        router = item.get('router')
        capabilities = router.get('capabilities') if isinstance(router, dict) else None
        reasoning = capabilities.get('reasoning') if isinstance(capabilities, dict) else None
        if not isinstance(reasoning, dict) or ('supported' in reasoning and type(reasoning['supported']) is not bool):
            continue
        if reasoning.get('supported') is False:
            safe = {'supported': False}
        else:
            values = reasoning.get('efforts') or []
            if not isinstance(values, list) or len(values) > 32:
                continue
            safe = {'efforts': [{'value': entry['value']} for entry in values
                if isinstance(entry, dict) and entry.get('value') in allowed_levels]}
            if 'supported' in reasoning: safe['supported'] = reasoning['supported']
        result.append({'id': item['id'], 'router': {'capabilities': {'reasoning': safe}}})
    return result


def _catalogue(policy, credentials, headers):
    from .provider_discovery import get_json
    from .provider_messages import native_model
    from providers import get_provider_profile
    from agent.reasoning_effort import EFFORT_LADDER
    approved = {native_model(policy, model) for model in policy.models}
    endpoint = credentials.effective_endpoint
    identity = hashlib.sha256(json.dumps([endpoint, headers.get('Authorization'), sorted(approved)], separators=(',', ':')).encode()).hexdigest()
    with credentials.lock:
        cache = credentials.router_cache
        now = time.monotonic()
        if cache.get('identity') == identity and now < cache.get('retry_at', 0):
            return cache.get('efforts', {})
        previous = cache.get('efforts', {}) if cache.get('identity') == identity else {}
        try:
            data = get_json(policy, endpoint, urlsplit(endpoint).path.rstrip('/') + '/models', headers)
            items = data if isinstance(data, list) else data.get('data') if isinstance(data, dict) else None
            # The pinned parser logs unknown levels. Only reviewed public
            # IDs/levels may reach it; reflected credential strings cannot.
            safe = safe_items(items, approved, EFFORT_LADDER)
            module = sys.modules[type(get_provider_profile('router')).__module__]
            efforts = module._parse_efforts(safe) or {}
        except Exception:
            # Match the native cache's stale/unknown behaviour without
            # borrowing another route's identity or retrying model dispatch.
            credentials.router_cache = {'identity': identity, 'retry_at': now + 30, 'efforts': previous}
            return previous
        credentials.router_cache = {'identity': identity, 'retry_at': now + 300, 'efforts': efforts}
        return efforts


def adapt(policy, payload, context, credentials, headers):
    if policy.provider != 'router' or policy.api_mode != 'codex_responses':
        return payload
    levels = _catalogue(policy, credentials, headers).get(payload['model'])
    if levels is None:
        return payload
    from agent.reasoning_effort import clamp_effort
    from agent.transports.codex import _reasoning_fields
    original = payload.get('reasoning') or {}
    config = context['params'].get('reasoning_config') if context is not None else None
    if isinstance(config, dict):
        enabled, requested = config.get('enabled') is not False, config.get('effort') or 'medium'
    elif context is not None:
        enabled, requested = True, 'medium'
    else:
        enabled, requested = bool(original) and original.get('effort') != 'none', original.get('effort')
    effort = (clamp_effort(requested, levels) if enabled else 'none' if 'none' in levels else None) if levels else None
    fields = _reasoning_fields(payload['model'], {}, effort=effort, enabled=enabled and bool(levels),
        replay_encrypted_reasoning=True, is_xai_responses=False, is_github_responses=False)
    if context is None and enabled and 'summary' in original and 'reasoning' in fields:
        fields['reasoning']['summary'] = original['summary']
    output = deepcopy(payload)
    output.pop('reasoning', None)
    extra_include = [value for value in output.get('include', []) if value != 'reasoning.encrypted_content']
    fields['include'] = extra_include + fields.get('include', [])
    output.update(fields)
    return output
