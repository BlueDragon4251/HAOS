#!/usr/bin/env python3
"""No-network logical fallback/normal target builder comparisons across the pinned catalogue."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import socket
import sys
from collections import Counter


def main():
    root = Path(sys.argv[1]).resolve(); sys.path.insert(0, str(root))
    from haos.provider_registry import http_providers, descriptor, default_mode, default_endpoint
    from haos.provider_profiles import register_profiles
    from haos.provider_policy import ProviderPolicy
    from haos.provider_messages import admit
    from haos.provider_fallback import extract, retarget
    from agent.transports import get_transport
    names = sorted(http_providers() | {'gemini', 'copilot', 'copilot-acp', 'bedrock', 'openai-codex', 'nous',
        'xai-oauth', 'qwen-oauth', 'minimax-oauth', 'azure-foundry', 'vertex', 'lmstudio', 'custom', 'local'})
    policies = {}
    for name in names:
        row = descriptor(name)
        model = next(iter(row['fallback_models']), 'fixture-model') if row else 'fixture-model'
        if name == 'copilot-acp': model = 'fixture-model'
        endpoint = {'local': 'http://127.0.0.1:11434/v1', 'custom': 'https://fixture.example.com/v1',
            'azure-foundry': 'https://fixture.services.ai.azure.com/openai/v1',
            'vertex': 'https://us-central1-aiplatform.googleapis.com/v1beta1/projects/fixture-project/locations/us-central1/endpoints/openapi'
            }.get(name, default_endpoint(name))
        policies[name] = ProviderPolicy({'version': 1, 'provider': name, 'endpoint': endpoint, 'models': [model],
            'default_model': model, 'api_mode': default_mode(name, model), 'requests_per_day': 200, 'requests_per_minute': 120})
    assert len(policies) == 53
    path_for = {'chat_completions': '/v1/chat/completions', 'codex_responses': '/v1/responses', 'anthropic_messages': '/v1/messages'}
    messages = [{'role': 'system', 'content': 'fixture-only system'}, {'role': 'assistant', 'content': 'prior fixture',
        'reasoning_details': [{'type': 'reasoning.encrypted', 'data': 'opaque fixture'}]}, {'role': 'user', 'content': 'continue fixture'}]
    tools = [{'type': 'function', 'function': {'name': 'fixture', 'parameters': {'type': 'object'}}}]
    def flatten(wire):
        output = deepcopy(wire); extra = output.pop('extra_body', None) or {}; output.update(extra)
        for key in ('extra_headers', 'extra_query', 'timeout'): output.pop(key, None)
        output['stream'] = True
        return output
    def canonical(value, provider):
        result = deepcopy(value)
        if provider == 'qwen-oauth' and isinstance(result.get('metadata'), dict):
            import uuid
            assert uuid.UUID(result['metadata']['promptId']).version == 4
            result['metadata']['promptId'] = '<fresh-prompt-id>'
        return result
    old_dns, old_connect = socket.getaddrinfo, socket.socket.connect
    def no_network(*args, **kwargs): raise AssertionError('wire builders cannot open a network connection')
    socket.getaddrinfo, socket.socket.connect = no_network, no_network
    checks = []
    try:
        for corpus in ('reasoning', 'native-features'):
            params = {'reasoning_config': {'enabled': True, 'effort': 'high'}, 'supports_reasoning': True,
                'max_tokens': 4096, 'temperature': 0.2, 'session_id': 'fixture-session', 'cache_scope_id': 'fixture-cache'}
            if corpus == 'native-features': params.update(fast_mode=True, context_length=1_000_000)
            source = {}; expected = {}; expected_features = {}
            for name, policy in policies.items():
                register_profiles({'version': 2, 'default': 'source', 'routes': {'source': policy.data, 'standby': policy.data},
                    'fallbacks': {'source': ['standby']}})
                base = 'http://127.0.0.1:9120/routes/source/v1'
                wire = get_transport(policy.api_mode).build_kwargs(policy.data['default_model'], deepcopy(messages), deepcopy(tools),
                    base_url=base, provider='custom', **params)
                payload, context = extract(flatten(wire), policy.api_mode)
                assert context is not None
                try:
                    admitted = admit(policy, path_for[policy.api_mode], payload)
                except (PermissionError, ValueError) as error:
                    raise AssertionError(name + ' source wire rejected; fields=' + ','.join(sorted(payload))) from error
                source[name] = (admitted, context)
                register_profiles(policy.data)
                wire = get_transport(policy.api_mode).build_kwargs(policy.data['default_model'], deepcopy(messages), deepcopy(tools),
                    base_url=policy.client_config()['model']['base_url'], provider='custom', **params)
                payload, _unused = extract(flatten(wire), policy.api_mode)
                expected[name] = canonical(admit(policy, path_for[policy.api_mode], payload), name)
                expected_features[name] = [item for key, value in (wire.get('extra_headers') or {}).items()
                    if key.lower() == 'anthropic-beta' for item in value.split(',')]
            for origin, policy in policies.items():
                payload, context = source[origin]
                for target, target_policy in policies.items():
                    if policy.api_mode != target_policy.api_mode: continue
                    request = {**payload, 'model': target_policy.data['default_model']}
                    features = {}
                    actual = retarget(target_policy, request, context, features)
                    if canonical(actual, target) != expected[target]:
                        changed = sorted(key for key in set(actual) | set(expected[target]) if canonical(actual, target).get(key) != expected[target].get(key))
                        raise AssertionError(corpus + ':' + origin + '->' + target + ' target fields differ: ' + ','.join(changed))
                    assert features.get('betas', []) == expected_features[target]
                    checks.append(corpus + ':' + origin + '->' + target)
    finally:
        socket.getaddrinfo, socket.socket.connect = old_dns, old_connect
    result = {'physical_profiles': len(policies), 'mode_counts': dict(Counter(p.api_mode for p in policies.values())),
        'compatible_native_builder_comparisons': len(checks), 'cases': checks, 'corpora': ['reasoning', 'native-features'],
        'network_and_live_inference_tested': False, 'actual_pinned_target_codecs': True,
        'source_sha256': {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in (Path(__file__),
            root / 'haos/provider_fallback.py', root / 'haos/provider_profiles.py', root / 'haos/provider_policy.py')}}
    Path(sys.argv[2]).write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps({k: v for k, v in result.items() if k not in {'cases', 'source_sha256'}}))


if __name__ == '__main__': main()
