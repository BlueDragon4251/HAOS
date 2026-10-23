"""Broker-owned provenance carried through public native SDK response codecs."""
from copy import deepcopy
import re

from .provider_replay import route_binding

FIELD = 'haos_replay_binding'


def clean(value):
    """An upstream server cannot supply local replay provenance."""
    if isinstance(value, dict):
        return {key: clean(item) for key, item in value.items() if key != FIELD}
    if isinstance(value, list):
        return [clean(item) for item in value]
    return value


def annotate(value, policy, model):
    result = clean(value)
    if policy.api_mode not in {'chat_completions', 'codex_responses', 'anthropic_messages'} or not isinstance(result, dict):
        return result
    binding = route_binding(policy, model)
    def blocks(container):
        if not isinstance(container, dict):
            return
        for key in ('output', 'content'):
            for block in container.get(key, []) if isinstance(container.get(key), list) else []:
                if isinstance(block, dict):
                    block[FIELD] = binding
    if policy.api_mode == 'chat_completions':
        for choice in result.get('choices', []):
            for key in ('message', 'delta'):
                message = choice.get(key)
                if not isinstance(message, dict):
                    continue
                for detail in message.get('reasoning_details') or []:
                    if isinstance(detail, dict) and not str(detail.get('type', '')).endswith('.native_assistant'):
                        detail[FIELD] = binding
    blocks(result)
    for key in ('response', 'message'):
        blocks(result.get(key))
    for key in ('item', 'content_block'):
        if isinstance(result.get(key), dict):
            result[key][FIELD] = binding
    return result


def bind_chat_details(details):
    """Also consume raw native stream details returned by the MoA facade."""
    from .provider_moa_streams import REPLAY_TYPE
    values = [item.get(FIELD) for item in details if isinstance(item, dict) and FIELD in item]
    if not values:
        return details
    if any(not isinstance(value, str) or not re.fullmatch('[a-f0-9]{64}', value) for value in values) or len(set(values)) != 1:
        raise PermissionError('invalid or mixed local chat replay provenance')
    native = [clean(item) for item in details
        if not isinstance(item, dict) or not str(item.get('type', '')).endswith('.native_assistant')]
    kept = [item for item in details if isinstance(item, dict) and str(item.get('type', '')).endswith('.native_assistant')]
    return kept + [{'type': REPLAY_TYPE, 'binding': values[0], 'data': {'chat_reasoning_details': native}}]


def normalize(response, normalized, mode):
    """Consume SDK-preserved block metadata before native state enters history."""
    from .provider_moa_streams import REPLAY_FIELDS, REPLAY_TYPE
    blocks = getattr(response, 'output' if mode == 'codex_responses' else 'content', None) or []
    if mode == 'chat_completions':
        data = deepcopy(normalized.provider_data or {})
        details = data.get('reasoning_details')
        if isinstance(details, list):
            data['reasoning_details'] = bind_chat_details(details)
            normalized.provider_data = data
        return normalized
    markers = []
    for block in blocks:
        value = block.get(FIELD) if isinstance(block, dict) else getattr(block, FIELD, None)
        if value is not None:
            if not isinstance(value, str) or not re.fullmatch('[a-f0-9]{64}', value):
                raise PermissionError('invalid local response replay provenance')
            markers.append(value)
    if not markers:
        return normalized
    if len(set(markers)) != 1:
        raise PermissionError('mixed local response replay provenance')
    data = clean(deepcopy(normalized.provider_data or {}))
    replay = {key: data.pop(key) for key in REPLAY_FIELDS if key in data}
    details = data.get('reasoning_details') or []
    signed = [item for item in details if isinstance(item, dict) and item.get('type') in {'thinking', 'redacted_thinking'}]
    if signed and 'anthropic_content_blocks' not in replay:
        from agent.anthropic_message_convert import _sanitize_replay_block, _to_plain_data
        replay['anthropic_content_blocks'] = [item for block in blocks
            if (item := _sanitize_replay_block(clean(_to_plain_data(block)))) is not None]
    if replay:
        data['reasoning_details'] = [item for item in details if item not in signed] + [{
            'type': REPLAY_TYPE, 'binding': markers[0], 'data': replay}]
    normalized.provider_data = data or None
    return normalized
