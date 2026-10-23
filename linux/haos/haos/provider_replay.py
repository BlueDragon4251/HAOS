"""Keep private native replay on its approved model/endpoint at broker admission."""
from copy import deepcopy
import hashlib
import json

from .provider_bedrock_replay import TYPE


def messages_for_route(policy, payload):
    if policy.api_mode != 'chat_completions' or not isinstance(payload.get('messages'), list):
        return payload
    result = dict(payload)
    result['messages'] = deepcopy(payload['messages'])
    binding = hashlib.sha256(policy.endpoint.encode()).hexdigest()
    for message in result['messages']:
        if not isinstance(message, dict):
            continue
        # Only the broker's bound carrier can restore these after admission.
        for field in ('bedrock_content_blocks', 'codex_reasoning_items', 'codex_message_items', 'anthropic_content_blocks'):
            message.pop(field, None)
        details = message.get('reasoning_details')
        if not isinstance(details, list):
            continue
        def allowed(item):
            if not isinstance(item, dict) or not isinstance(item.get('type'), str) or not item['type'].endswith('.native_assistant'):
                return True
            return (policy.provider == 'bedrock' and item['type'] == TYPE
                and item.get('model') == payload['model'] and item.get('endpoint_sha256') == binding
                and isinstance(item.get('blocks'), list))
        kept = [item for item in details if allowed(item)]
        if kept:
            message['reasoning_details'] = kept
        else:
            message.pop('reasoning_details', None)
    return result


def issuer_binding(context, model):
    if isinstance(context, (list, tuple)) and len(context) >= 3:
        from types import SimpleNamespace
        from .provider_messages import native_model
        model = native_model(SimpleNamespace(provider=context[0], api_mode=context[1], endpoint=context[2]), model)
    return hashlib.sha256(json.dumps([context, model], separators=(",", ":")).encode()).hexdigest()


def route_binding(policy, model, scope=None):
    provider = "openai-api" if policy.provider == "openai" else policy.provider
    return issuer_binding([provider, policy.api_mode, policy.endpoint, *(scope or [])], model)


def capability_generation(token):
    """Public one-way scope of the existing limited local capability."""
    return hashlib.sha256(token.encode()).hexdigest()
