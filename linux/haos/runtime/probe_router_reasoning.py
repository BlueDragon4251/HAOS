#!/usr/bin/env python3
"""Actual Router SDK requests and account-specific native reasoning catalogues."""
import hashlib
import http.client
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import secrets
import sys
import tempfile
import threading
from probe_http_provider_matrix import serving, fixture_response, sdk_stream


def main():
    root = Path(sys.argv[1]).resolve(); sys.path.insert(0, str(root))
    import httpx
    import openai
    from providers import get_provider_profile
    from agent.transports import get_transport
    from agent.transports.codex import _reasoning_fields
    from agent.reasoning_effort import clamp_effort
    from haos import provider_policy, provider_routes
    from haos.provider_profiles import register_profiles
    from haos.provider_routes import ProviderRoutes
    from haos.provider_proxy import Broker, Credentials, UsageLedger
    models = ['gpt-5.4']; endpoint = 'https://api.router.com/v1'
    routes = ProviderRoutes({'version': 2, 'default': 'alpha', 'routes': {
        key: {'version': 1, 'provider': 'router', 'endpoint': endpoint, 'models': models,
            'default_model': models[0], 'api_mode': 'codex_responses', 'requests_per_day': 200, 'requests_per_minute': 120}
        for key in ('alpha', 'beta')}, 'fallbacks': {}})
    catalogues = {'alpha': {'data': [{'id': models[0], 'router': {'capabilities': {'reasoning': {'supported': False}}}}]},
        'beta': {'data': [{'id': models[0], 'router': {'capabilities': {'reasoning': {'supported': True, 'efforts': [{'value': 'low'}]}}}}]}}
    native_module = sys.modules[type(get_provider_profile('router')).__module__]
    expected = {}
    for key, data in catalogues.items():
        levels = native_module._parse_efforts(data['data'])[models[0]]
        expected[key] = _reasoning_fields(models[0], {}, effort=clamp_effort('high', levels) if levels else None,
            enabled=bool(levels), replay_encrypted_reasoning=True, is_xai_responses=False, is_github_responses=False)
    keys = {key: secrets.token_urlsafe(40) for key in catalogues}
    requests, catalogue_calls, failures = [], [], []; release = threading.Event()
    class Fixture(BaseHTTPRequestHandler):
        def log_message(self, *_): pass
        def identity(self):
            assert self.headers['User-Agent'].startswith('Hermes-Agent/')
            return next(key for key, value in keys.items() if self.headers['Authorization'] == 'Bearer ' + value)
        def do_GET(self):
            try:
                key = self.identity(); assert self.path == '/v1/models'; catalogue_calls.append(key)
                data = json.dumps(catalogues[key]).encode()
                self.send_response(200); self.send_header('Content-Type', 'application/json')
                self.send_header('Content-Length', str(len(data))); self.end_headers(); self.wfile.write(data)
            except BaseException as error:
                failures.append(type(error).__name__); raise
        def do_POST(self):
            try:
                key = self.identity(); assert self.path == '/v1/responses'
                body = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                assert 'haos_fallback_context' not in body and body['model'] == models[0]
                actual = {name: body[name] for name in ('reasoning', 'include') if name in body}
                requests.append({'route': key, 'stream': body.get('stream', False), 'fields': actual})
                assert actual == expected[key], (key, actual, expected[key])
                result, early, terminal = fixture_response('codex_responses', models[0], 'fixture', 'native fixture')
                if not body.get('stream'):
                    data = json.dumps(result).encode()
                    self.send_response(200); self.send_header('Content-Type', 'application/json')
                    self.send_header('Content-Length', str(len(data))); self.end_headers(); self.wfile.write(data); return
                self.send_response(200); self.send_header('Content-Type', 'text/event-stream'); self.send_header('Connection', 'close'); self.end_headers()
                for index, event in enumerate([*early, *terminal]):
                    if index == len(early): assert release.wait(5), 'Router SDK buffered early text until terminal'
                    self.wfile.write(('event: ' + event['type'] + '\ndata: ' + json.dumps(event) + '\n\n').encode()); self.wfile.flush()
                self.close_connection = True
            except BaseException as error:
                failures.append(type(error).__name__); raise
    old_https = http.client.HTTPSConnection
    old_base, old_routes = provider_policy.BASE, provider_routes.BASE
    old_home, old_token = os.environ.get('HERMES_HOME'), os.environ.get('HAOS_MODEL_TOKEN')
    with tempfile.TemporaryDirectory() as directory, serving(ThreadingHTTPServer(('127.0.0.1', 0), Fixture)) as port:
        def local(host, port_number=443, **kwargs):
            assert host == 'api.router.com' and port_number == 443
            return http.client.HTTPConnection('127.0.0.1', port, timeout=kwargs.get('timeout', 10))
        http.client.HTTPSConnection = local
        capability = secrets.token_urlsafe(48); ledger = UsageLedger(Path(directory)/'usage.db')
        os.environ['HERMES_HOME'], os.environ['HAOS_MODEL_TOKEN'] = directory, capability
        try:
            credentials = {key: Credentials(policy, {'api_key': keys[key]}) for key, policy in routes.routes.items()}
            server = Broker(('127.0.0.1', 0), routes, capability, credentials, ledger); server.daemon_threads = False
            with serving(server) as broker:
                provider_policy.BASE = provider_routes.BASE = f'http://127.0.0.1:{broker}/v1'
                config = routes.client_config(); Path(directory, 'config.yaml').write_text(json.dumps(config)); register_profiles(routes.data)
                for streaming in (False, True):
                    for key in ('alpha', 'beta', 'alpha'):
                        release.clear(); transport = get_transport('codex_responses')
                        base = config['providers']['haos-' + key]['base_url']
                        body = transport.build_kwargs(models[0], [{'role': 'user', 'content': 'native fixture'}],
                            [{'type': 'function', 'function': {'name': 'fixture', 'parameters': {'type': 'object'}}}],
                            base_url=base, provider='custom', reasoning_config={'enabled': True, 'effort': 'high'})
                        with openai.OpenAI(api_key=capability, base_url=base, max_retries=0, http_client=httpx.Client(trust_env=False)) as client:
                            if streaming:
                                with sdk_stream(client, 'codex_responses', client.responses.create, body, accumulate=True) as stream:
                                    early_seen = False
                                    for event in stream:
                                        if event.type == 'response.output_text.delta':
                                            assert not release.is_set(); early_seen = True; release.set()
                                    assert early_seen
                                    result = stream.get_final_response()
                            else: result = client.responses.create(**body)
                            normalized = transport.normalize_response(result)
                            assert normalized.content == 'native fixture' and normalized.tool_calls[0].name == 'fixture'
                            assert json.loads(normalized.tool_calls[0].arguments) == {'x': 1}
                # A changed private key invalidates this route's old caps,
                # even when provider, endpoint and model are identical.
                keys['alpha'] = secrets.token_urlsafe(40)
                credentials['alpha'].credentials['api_key'] = keys['alpha']
                catalogues['alpha'] = {'data': [{'id': models[0], 'router': {'capabilities': {'reasoning': {
                    'supported': True, 'efforts': [{'value': 'medium'}]}}}}]}
                levels = native_module._parse_efforts(catalogues['alpha']['data'])[models[0]]
                expected['alpha'] = _reasoning_fields(models[0], {}, effort=clamp_effort('high', levels),
                    enabled=True, replay_encrypted_reasoning=True, is_xai_responses=False, is_github_responses=False)
                transport = get_transport('codex_responses')
                base = config['providers']['haos-alpha']['base_url']
                body = transport.build_kwargs(models[0], [{'role': 'user', 'content': 'native fixture'}],
                    [{'type': 'function', 'function': {'name': 'fixture', 'parameters': {'type': 'object'}}}],
                    base_url=base, provider='custom', reasoning_config={'enabled': True, 'effort': 'high'})
                with openai.OpenAI(api_key=capability, base_url=base, max_retries=0, http_client=httpx.Client(trust_env=False)) as client:
                    result = client.responses.create(**body)
                    assert transport.normalize_response(result).content == 'native fixture'
            assert not failures and catalogue_calls == ['alpha', 'beta', 'alpha']
            assert ledger.db.execute('SELECT status,input_tokens,output_tokens FROM requests ORDER BY rowid').fetchall() == [(200, 8, 5)] * 7
        finally:
            http.client.HTTPSConnection = old_https
            provider_policy.BASE, provider_routes.BASE = old_base, old_routes
            for key, value in (('HERMES_HOME', old_home), ('HAOS_MODEL_TOKEN', old_token)):
                if value is None: os.environ.pop(key, None)
                else: os.environ[key] = value
            ledger.close()
    result = {'actual_router_sdk_cases': requests, 'catalogue_fetches': catalogue_calls,
        'native_parser_and_reasoning_math_compared': True, 'same_model_different_accounts_do_not_borrow_caps': True,
        'private_key_rotation_invalidates_caps': True, 'live_account_tested': False, 'source_sha256': {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in (
            Path(__file__), root/'haos/provider_proxy.py', root/'haos/provider_profiles.py', root/'haos/provider_router.py')}}
    Path(sys.argv[2]).write_text(json.dumps(result, indent=2) + '\n'); print(json.dumps({'cases': len(requests)}))


if __name__ == '__main__': main()
