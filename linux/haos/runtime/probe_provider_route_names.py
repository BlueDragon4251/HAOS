#!/usr/bin/env python3
"""Actual Hermes resolver/SDK default and named-route aliases, including legacy data."""
import hashlib
import http.client
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import secrets
import sys
import tempfile
from probe_http_provider_matrix import serving, fixture_response


def main():
    root = Path(sys.argv[1]).resolve(); sys.path.insert(0, str(root))
    import httpx
    import openai
    from haos import provider_policy, provider_routes
    from haos.provider_routes import ProviderRoutes
    from haos.provider_profiles import register_profiles
    from haos.provider_proxy import Broker, Credentials, UsageLedger
    from hermes_cli.runtime_provider import resolve_runtime_provider
    from agent.transports import get_transport
    models = {'alpha': 'gpt-5.4', 'model': 'gpt-6-sol'}
    routes = ProviderRoutes({'version': 2, 'default': 'alpha', 'routes': {key: {
        'version': 1, 'provider': 'openai-api', 'endpoint': 'https://api.openai.com/v1', 'models': [model],
        'default_model': model, 'api_mode': 'codex_responses', 'requests_per_day': 200, 'requests_per_minute': 120}
        for key, model in models.items()}, 'fallbacks': {}})
    keys = {key: secrets.token_urlsafe(40) for key in models}; calls, failures = [], []
    class Fixture(BaseHTTPRequestHandler):
        def log_message(self, *_): pass
        def do_POST(self):
            try:
                body = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                name = next(key for key, model in models.items() if model == body['model'])
                assert self.headers['Authorization'] == 'Bearer ' + keys[name] and self.path == '/v1/responses'
                calls.append(name)
                result, _, _ = fixture_response('codex_responses', body['model'], 'fixture', 'native fixture')
                data = json.dumps(result).encode(); self.send_response(200)
                self.send_header('Content-Type', 'application/json'); self.send_header('Content-Length', str(len(data)))
                self.end_headers(); self.wfile.write(data)
            except BaseException as error:
                failures.append(type(error).__name__); raise
    old_https, old_base, old_routes = http.client.HTTPSConnection, provider_policy.BASE, provider_routes.BASE
    old_home, old_token = os.environ.get('HERMES_HOME'), os.environ.get('HAOS_MODEL_TOKEN')
    with tempfile.TemporaryDirectory() as directory, serving(ThreadingHTTPServer(('127.0.0.1', 0), Fixture)) as port:
        def local(host, port_number=443, **kwargs):
            assert host == 'api.openai.com' and port_number == 443
            return http.client.HTTPConnection('127.0.0.1', port, timeout=kwargs.get('timeout', 10))
        http.client.HTTPSConnection = local
        capability = secrets.token_urlsafe(48); os.environ['HERMES_HOME'], os.environ['HAOS_MODEL_TOKEN'] = directory, capability
        ledger = UsageLedger(Path(directory)/'usage.db')
        server = Broker(('127.0.0.1', 0), routes, capability, {key: Credentials(policy, {'api_key': keys[key]}) for key, policy in routes.routes.items()}, ledger)
        server.daemon_threads = False
        try:
            with serving(server) as broker:
                provider_policy.BASE = provider_routes.BASE = f'http://127.0.0.1:{broker}/v1'
                config = routes.client_config(); Path(directory, 'config.yaml').write_text(json.dumps(config)); register_profiles(routes.data)
                for requested, key in [('custom:haos-model', 'alpha'), ('custom:haos--model', 'model')]:
                    runtime = resolve_runtime_provider(requested=requested, target_model=models[key])
                    expected = provider_policy.BASE if key == 'alpha' else f'http://127.0.0.1:{broker}/routes/model/v1'
                    assert runtime['base_url'].rstrip('/') == expected, 'named model route shadowed owner default alias'
                    assert runtime['api_key'] == capability and runtime['api_mode'] == 'codex_responses'
                    transport = get_transport('codex_responses')
                    body = transport.build_kwargs(models[key], [{'role': 'user', 'content': 'native fixture'}],
                        [{'type': 'function', 'function': {'name': 'fixture', 'parameters': {'type': 'object'}}}], base_url=runtime['base_url'], provider='custom')
                    with openai.OpenAI(api_key=runtime['api_key'], base_url=runtime['base_url'], max_retries=0, http_client=httpx.Client(trust_env=False)) as client:
                        response = client.responses.create(**body)
                        normalized = transport.normalize_response(response)
                        assert normalized.content == 'native fixture' and normalized.tool_calls[0].name == 'fixture'
            assert not failures and calls == ['alpha', 'model']
            assert ledger.db.execute('SELECT status FROM requests ORDER BY rowid').fetchall() == [(200,), (200,)]
        finally:
            http.client.HTTPSConnection, provider_policy.BASE, provider_routes.BASE = old_https, old_base, old_routes
            for key, value in (('HERMES_HOME', old_home), ('HAOS_MODEL_TOKEN', old_token)):
                if value is None: os.environ.pop(key, None)
                else: os.environ[key] = value
            ledger.close()
    result = {'actual_pinned_runtime_resolutions': 2, 'actual_sdk_http_dispatches': calls,
        'owner_default_alias_preserved': True, 'named_model_route_distinct': True, 'live_provider_tested': False,
        'source_sha256': {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in (Path(__file__), root/'haos/provider_routes.py', root/'haos/provider_profiles.py')}}
    Path(sys.argv[2]).write_text(json.dumps(result, indent=2) + '\n'); print(json.dumps(result))


if __name__ == '__main__': main()
