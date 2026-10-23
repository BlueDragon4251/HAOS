"""Local logical request context for rebuilding an explicitly approved fallback."""
from copy import deepcopy
import json
import re
import uuid

FIELD = 'haos_fallback_context'
PARAMS = frozenset({'max_tokens', 'max_completion_tokens', 'temperature', 'top_p', 'stop', 'seed',
    'frequency_penalty', 'presence_penalty', 'logprobs', 'top_logprobs', 'reasoning_config',
    'response_format', 'tool_choice', 'parallel_tool_calls', 'verbosity', 'service_tier', 'fast_mode',
    'drop_context_1m_beta', 'context_length', 'session_id', 'cache_scope_id', 'prompt_cache_key', 'supports_reasoning',
    'provider_preferences', 'openrouter_min_coding_score', 'qwen_session_metadata', 'ollama_num_ctx'})


def capture(mode, model, messages, tools, params):
    values = {key: value for key, value in params.items() if key in PARAMS}
    # JSON data only: no profile, credential, client, callback or process object.
    return json.loads(json.dumps({'version': 1, 'mode': mode, 'model': model, 'messages': messages,
        'tools': tools, 'params': values}, ensure_ascii=False, allow_nan=False))


def attach(wire, context):
    if context is None:
        return wire
    output = dict(wire)
    output['extra_body'] = {**(wire.get('extra_body') or {}), FIELD: context}
    return output


def extract(payload, mode):
    if not isinstance(payload, dict):
        raise ValueError('model request must be an object')
    output = dict(payload)
    context = output.pop(FIELD, None)
    if context is None:
        return output, None
    if (not isinstance(context, dict) or set(context) != {'version', 'mode', 'model', 'messages', 'tools', 'params'}
            or type(context['version']) is not int or context['version'] != 1 or context['mode'] != mode
            or not isinstance(context['model'], str) or not isinstance(context['messages'], list)
            or not all(isinstance(item, dict) for item in context['messages'])
            or not (context['tools'] is None or isinstance(context['tools'], list) and len(context['tools']) <= 256
                and all(isinstance(item, dict) and item.get('type') == 'function'
                    and isinstance(item.get('function'), dict)
                    and isinstance(item['function'].get('name'), str)
                    and isinstance(item['function'].get('parameters', {}), dict) for item in context['tools']))
            or not isinstance(context['params'], dict) or set(context['params']) - PARAMS):
        raise PermissionError('invalid local fallback context')
    return output, context


def _names(mode, tools):
    return [(tool.get('function', {}) if mode == 'chat_completions' else tool).get('name') for tool in tools or []]


def retarget(policy, payload, context, features=None, *, model=None):
    """Run pinned target wire builders without changing global transports or auth."""
    if context is None and (policy.api_mode != 'chat_completions' or policy.provider in {'local', 'lmstudio', 'custom'}):
        return payload
    from providers import get_provider_profile
    from agent.transports.chat_completions import ChatCompletionsTransport
    from agent.transports.codex import ResponsesApiTransport
    from agent.transports.anthropic import AnthropicTransport
    source = 'openai-api' if policy.provider == 'openai' else policy.provider
    profile = get_provider_profile(source) or get_provider_profile('custom')
    endpoint = policy.endpoint
    if source == 'bedrock':
        if policy.api_mode == 'codex_responses':
            from .provider_cloud import mantle_endpoint
            endpoint = mantle_endpoint(endpoint)
        elif policy.api_mode == 'anthropic_messages':
            endpoint = None
        else:
            from copy import copy
            from .provider_bedrock_replay import TYPE
            profile = copy(profile)
            object.__setattr__(profile, 'native_reasoning_details_type', TYPE)
    classes = {'chat_completions': ChatCompletionsTransport, 'codex_responses': ResponsesApiTransport,
        'anthropic_messages': AnthropicTransport}
    transport = classes[policy.api_mode]()
    if context is None:
        # Legacy direct HTTP callers have no logical envelope. Still apply the
        # real target message sanitizer instead of forwarding foreign sidecars.
        output = dict(payload)
        output['messages'] = transport.convert_messages(deepcopy(payload.get('messages', [])),
            model=payload['model'], base_url=endpoint, provider_profile=profile)
        return output
    model = model or policy.data['default_model']
    params = deepcopy(context['params'])
    params.update(provider=source, provider_profile=profile, base_url=endpoint, is_oauth=False)
    if source == 'qwen-oauth' and not params.get('qwen_session_metadata'):
        params['qwen_session_metadata'] = {'sessionId': params.get('session_id') or 'hermes', 'promptId': str(uuid.uuid4())}
    from .provider_moa_streams import _restore
    from .provider_replay import route_binding
    messages = _restore(context['messages'], route_binding(policy, model))
    wire = transport.build_kwargs(model, messages, deepcopy(context['tools']), **params)
    extra = wire.pop('extra_body', None)
    if extra:
        if not isinstance(extra, dict):
            raise ValueError('target builder returned invalid wire extras')
        wire.update(extra)
    wire.pop(FIELD, None)
    _transport_features(wire, context, features)
    wire['model'] = model
    wire['stream'] = payload.get('stream', False)
    # Preserve the caller's native tool identity for its response normalizer.
    # A future codec changing it must supply a reviewed reversible mapping.
    target_names = _names(policy.api_mode, wire.get('tools'))
    source_names = _names(policy.api_mode, payload.get('tools'))
    if target_names != source_names:
        # Responses backends reserve different local-function names. Preserve
        # the source SDK's request-local identity when returning target results.
        if (policy.api_mode != 'codex_responses' or features is None
                or len(target_names) != len(source_names)
                or not all(isinstance(name, str) and name for name in [*target_names, *source_names])
                or len(set(target_names)) != len(target_names) or len(set(source_names)) != len(source_names)):
            raise PermissionError('fallback changed local function wire identities')
        native_aliases = getattr(transport, '_last_wire_aliases', None) or {}
        logical_names = [tool['function']['name'] for tool in context['tools'] or []]
        if [native_aliases.get(name, name) for name in target_names] != logical_names:
            raise PermissionError('target codec changed logical local function identities')
        features['tool_names'] = {target: source for target, source in zip(target_names, source_names) if target != source}
    from .provider_messages import admit
    path = {'chat_completions': '/v1/chat/completions', 'codex_responses': '/v1/responses',
        'anthropic_messages': '/v1/messages'}[policy.api_mode]
    return admit(policy, path, wire)


def _transport_features(wire, context, features):
    generated = wire.pop('extra_headers', None) or {}
    if not isinstance(generated, dict) or any(key.lower() != 'anthropic-beta' for key in generated):
        raise PermissionError('target codec returned an unreviewed transport header')
    betas = []
    for value in generated.values():
        if not isinstance(value, str) or not re.fullmatch(r'[a-z0-9][a-z0-9,-]{0,2047}', value):
            raise PermissionError('invalid native feature header')
        betas.extend(value.split(','))
    if wire.get('extra_query'):
        raise PermissionError('target codec cannot override the approved SDK query')
    wire.pop('extra_query', None)
    wire.pop('timeout', None)
    if features is not None:
        features.update(betas=betas, drop_context_1m_beta=bool(context['params'].get('drop_context_1m_beta')))


def source_features(policy, context, features):
    if context is None or policy.api_mode != 'anthropic_messages':
        return
    # Reuse the immutable native builder solely for its feature headers. The
    # primary body remains the independently admitted SDK request.
    retarget(policy, {'model': context['model'], 'stream': False}, {**context, 'tools': None}, features, model=context['model'])


def merge_features(headers, features):
    if not features:
        return headers
    output = dict(headers)
    key = next((key for key in output if key.lower() == 'anthropic-beta'), 'anthropic-beta')
    betas = [value for value in output.get(key, '').split(',') if value]
    if features.get('drop_context_1m_beta'):
        from agent.anthropic_adapter import _CONTEXT_1M_BETA
        betas = [value for value in betas if value != _CONTEXT_1M_BETA]
    betas.extend(features.get('betas', []))
    if betas:
        output[key] = ','.join(dict.fromkeys(betas))
    else:
        output.pop(key, None)
    return output
