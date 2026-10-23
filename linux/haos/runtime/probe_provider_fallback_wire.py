#!/usr/bin/env python3
"""Actual pinned target codec parity on an approved HTTP fallback, not inference."""
import hashlib
import http.client
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import secrets
import sys
import tempfile
import threading
from urllib.parse import urlsplit
from probe_http_provider_matrix import serving


def main():
    root = Path(sys.argv[1]).resolve(); sys.path.insert(0, str(root))
    import httpx
    import openai
    from agent.transports import get_transport
    from haos.provider_profiles import register_profiles
    from haos.provider_routes import ProviderRoutes
    from haos.provider_proxy import Broker, Credentials, UsageLedger
    from haos.provider_registry import default_endpoint
    scenario = sys.argv[3] if len(sys.argv) == 4 else 'reasoning'
    assert scenario in {'reasoning', 'developer'}
    providers = ('openrouter', 'openai-api') if scenario == 'reasoning' else ('openai-api', 'deepseek')
    models = {'source': 'model-source', 'target': 'model-target'} if scenario == 'reasoning' else {'source': 'gpt-5', 'target': 'deepseek-chat'}
    routes = ProviderRoutes({'version': 2, 'default': 'source', 'routes': {
        key: {'version': 1, 'provider': provider, 'endpoint': default_endpoint(provider),
            'models': [models[key]], 'default_model': models[key], 'api_mode': 'chat_completions',
            'requests_per_day': 200, 'requests_per_minute': 120} for key, provider in zip(('source', 'target'), providers)},
        'fallbacks': {'source': ['target']}})
    register_profiles(routes.data)
    messages = [{'role': 'assistant', 'content': 'prior fixture', 'reasoning_details': [
        {'type': 'reasoning.encrypted', 'data': 'opaque source fixture'}]}, {'role': 'user', 'content': 'continue fixture'}]
    if scenario == 'developer':
        messages = [{'role': 'system', 'content': 'system fixture'}, {'role': 'user', 'content': 'continue fixture'}]
    tools = [{'type': 'function', 'function': {'name': 'fixture', 'parameters': {'type': 'object'}}}]
    config = routes.client_config()
    def wire(key):
        return get_transport('chat_completions').build_kwargs(models[key], messages, tools,
            base_url=config['providers']['haos-' + key]['base_url'], max_tokens=64)
    source_body, target_body = wire('source'), wire('target')
    if scenario == 'reasoning':
        assert 'reasoning_details' in source_body['messages'][0]
        assert 'reasoning_details' not in target_body['messages'][0]
    else:
        assert source_body['messages'][0]['role'] == 'developer' and target_body['messages'][0]['role'] == 'system'
    keys = {key: secrets.token_urlsafe(40) for key in routes.routes}
    calls, failures = [], []
    finished = threading.Event()
    class Ledger(UsageLedger):
        def finish(self, *args):
            super().finish(*args)
            if self.db.execute('SELECT COUNT(status) FROM requests').fetchone()[0] == 2:
                finished.set()
    class Fixture(BaseHTTPRequestHandler):
        def log_message(self, *_): pass
        def do_POST(self):
            try:
                data = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                key = next(key for key, model in models.items() if model == data['model']); calls.append(key)
                assert 'haos_fallback_context' not in json.dumps(data)
                assert self.headers['Authorization'] == 'Bearer ' + keys[key]
                if key == 'source':
                    assert data['messages'] == source_body['messages']
                    encoded = b'{}'; status = 503
                else:
                    expected = dict(target_body); expected.update(expected.pop('extra_body', {}) or {})
                    expected.update(store=False, stream=False)
                    assert data == expected, 'fallback did not use the pinned target request codec'
                    encoded = json.dumps({'id': 'fixture', 'object': 'chat.completion', 'created': 1, 'model': models['target'],
                        'choices': [{'index': 0, 'finish_reason': 'tool_calls', 'message': {'role': 'assistant', 'content': 'target fixture', 'tool_calls': [{'id': 'call-fixture', 'type': 'function',
                            'function': {'name': 'fixture', 'arguments': '{"x":1}'}}]}}],
                        'usage': {'prompt_tokens': 3, 'completion_tokens': 2}}).encode(); status = 200
                self.send_response(status); self.send_header('Content-Type', 'application/json')
                self.send_header('Content-Length', str(len(encoded))); self.end_headers(); self.wfile.write(encoded)
            except BaseException as error:
                failures.append(type(error).__name__)
                raise
    original = http.client.HTTPSConnection
    with serving(ThreadingHTTPServer(('127.0.0.1', 0), Fixture)) as port, tempfile.TemporaryDirectory() as directory:
        def local(host, port_number=443, **kwargs):
            assert port_number == 443 and host in {urlsplit(row.endpoint).hostname for row in routes.routes.values()}
            return http.client.HTTPConnection('127.0.0.1', port, timeout=kwargs.get('timeout', 5))
        http.client.HTTPSConnection = local
        ledger = Ledger(Path(directory) / 'usage.db'); capability = secrets.token_urlsafe(48)
        try:
            credentials = {key: Credentials(row, {'api_key': keys[key]}) for key, row in routes.routes.items()}
            with serving(Broker(('127.0.0.1', 0), routes, capability, credentials, ledger)) as broker:
                with openai.OpenAI(api_key=capability, base_url=f'http://127.0.0.1:{broker}/routes/source/v1',
                        max_retries=0, timeout=10, http_client=httpx.Client(trust_env=False)) as client:
                    response = client.chat.completions.create(**source_body)
                    assert response.choices[0].message.content == 'target fixture'
                    assert response.choices[0].message.tool_calls[0].function.name == 'fixture'
            assert finished.wait(5)
            assert ledger.db.execute('SELECT status FROM requests ORDER BY rowid').fetchall() == [(503,), (200,)]
            assert calls == ['source', 'target'] and not failures
        finally:
            http.client.HTTPSConnection = original
            ledger.close()
    result = {'scenario': scenario, 'actual_pinned_source_and_target_request_codecs': True, 'approved_broker_http_hops': calls,
        'target_uses_its_own_key_and_model': True, 'opaque_source_only_reasoning_not_forwarded': True,
        'live_provider_tested': False, 'source_sha256': {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in (
            Path(__file__), root / 'haos/provider_proxy.py', root / 'haos/provider_policy.py', root / 'haos/provider_fallback.py', root / 'haos/provider_profiles.py')}}
    Path(sys.argv[2]).write_text(json.dumps(result, indent=2) + '\n'); print(json.dumps(result))


if __name__ == '__main__': main()
