#!/usr/bin/env python3
"""Real scoped SDK/broker fallback streams and native replay; no live inference."""
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
    import anthropic
    import httpx
    import openai
    from agent.auxiliary_client import CodexAuxiliaryClient, AnthropicAuxiliaryClient
    from agent.reasoning_summaries import append_streamed_reasoning_detail
    from haos import provider_policy, provider_routes
    from haos.provider_routes import ProviderRoutes
    from haos.provider_profiles import register_profiles
    from haos.provider_proxy import Broker, Credentials, UsageLedger
    from haos.provider_moa_streams import create_stream, _binding
    from agent.transports import get_transport
    checks = []
    for mode in ('codex_responses', 'anthropic_messages'):
        provider = 'openai-api' if mode == 'codex_responses' else 'anthropic'
        endpoint = 'https://api.openai.com/v1' if provider == 'openai-api' else 'https://api.anthropic.com'
        models = {'primary': 'gpt-5.4', 'fallback': 'gpt-6-sol'} if provider == 'openai-api' else {
            'primary': 'claude-sonnet-4-6', 'fallback': 'claude-opus-4-6'}
        keys = {name: secrets.token_urlsafe(40) for name in models}
        routes = ProviderRoutes({'version': 2, 'default': 'primary', 'routes': {
            name: {'version': 1, 'provider': provider, 'endpoint': endpoint, 'models': [model],
                'default_model': model, 'api_mode': mode, 'requests_per_day': 200, 'requests_per_minute': 120}
            for name, model in models.items()}, 'fallbacks': {'primary': ['fallback']}})
        state = {'turn': 1}; observed, failures = [], []
        opaque = 'encrypted-fixture' if mode == 'codex_responses' else 'signed-fixture'
        class Fixture(BaseHTTPRequestHandler):
            def log_message(self, *_): pass
            def do_POST(self):
                try:
                    body = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                    name = next(key for key in models if models[key] == body['model'])
                    assert self.path == ('/v1/responses' if mode == 'codex_responses' else '/v1/messages')
                    assert (self.headers['Authorization'] == 'Bearer ' + keys[name] if mode == 'codex_responses'
                        else self.headers['x-api-key'] == keys[name])
                    present = opaque in json.dumps(body)
                    assert present == (state['turn'] == 2 and name == 'fallback'), f'native replay crossed issuer or disappeared: {mode}:{state["turn"]}:{name}:present={present}'
                    observed.append((state['turn'], name, present))
                    if name == 'primary' and state['turn'] < 3:
                        self.send_response(503); self.send_header('Content-Length', '2'); self.end_headers(); self.wfile.write(b'{}'); return
                    result, early, terminal = fixture_response(mode, body['model'], 'fixture', 'native fixture')
                    if mode == 'codex_responses':
                        native = {'id': 'rs_fixture', 'type': 'reasoning', 'summary': [], 'encrypted_content': opaque}
                        result['output'].insert(0, native)
                        for event in [*early, *terminal]:
                            if 'output_index' in event: event['output_index'] += 1
                        early.insert(1, {'type': 'response.output_item.added', 'output_index': 0, 'item': native})
                        terminal.insert(0, {'type': 'response.output_item.done', 'output_index': 0, 'item': native})
                    else:
                        native = {'type': 'thinking', 'thinking': 'native thought', 'signature': opaque}
                        result['content'].insert(0, native)
                        for event in [*early, *terminal]:
                            if 'index' in event: event['index'] += 1
                        early[1:1] = [{'type': 'content_block_start', 'index': 0, 'content_block': {'type': 'thinking', 'thinking': '', 'signature': ''}},
                            {'type': 'content_block_delta', 'index': 0, 'delta': {'type': 'thinking_delta', 'thinking': 'native thought'}},
                            {'type': 'content_block_delta', 'index': 0, 'delta': {'type': 'signature_delta', 'signature': opaque}},
                            {'type': 'content_block_stop', 'index': 0}]
                    self.send_response(200); self.send_header('Content-Type', 'text/event-stream')
                    self.send_header('Connection', 'close'); self.send_header('X-HAOS-Replay-Binding', '0' * 64); self.end_headers()
                    for index, event in enumerate([*early, *terminal]):
                        if mode == 'codex_responses': event['sequence_number'] = index
                        self.wfile.write(('event: ' + event['type'] + '\ndata: ' + json.dumps(event) + '\n\n').encode())
                        self.wfile.flush()
                    self.close_connection = True
                except BaseException as error:
                    failures.append(type(error).__name__); raise
        old_https = http.client.HTTPSConnection
        old_base, old_routes = provider_policy.BASE, provider_routes.BASE
        old_home, old_token = os.environ.get('HERMES_HOME'), os.environ.get('HAOS_MODEL_TOKEN')
        with tempfile.TemporaryDirectory() as directory, serving(ThreadingHTTPServer(('127.0.0.1', 0), Fixture)) as port:
            def local(host, port_number=443, **kwargs):
                assert host in {'api.openai.com', 'api.anthropic.com'} and port_number == 443
                return http.client.HTTPConnection('127.0.0.1', port, timeout=kwargs.get('timeout', 10))
            http.client.HTTPSConnection = local
            ledger = UsageLedger(Path(directory) / 'usage.db'); capability = secrets.token_urlsafe(48)
            os.environ['HERMES_HOME'], os.environ['HAOS_MODEL_TOKEN'] = directory, capability
            try:
                credentials = {name: Credentials(policy, {'api_key': keys[name]}) for name, policy in routes.routes.items()}
                server = Broker(('127.0.0.1', 0), routes, capability, credentials, ledger)
                # Join real request finalizers before closing their SQLite
                # connection, including on an assertion-failure teardown.
                server.daemon_threads = False
                with serving(server) as broker:
                    provider_policy.BASE = provider_routes.BASE = f'http://127.0.0.1:{broker}/v1'
                    config = routes.client_config(); Path(directory, 'config.yaml').write_text(json.dumps(config))
                    register_profiles(routes.data)
                    base = config['providers']['haos-primary']['base_url']
                    actual_base = base.removesuffix('/v1') if mode == 'anthropic_messages' else base
                    cls = openai.OpenAI if mode == 'codex_responses' else anthropic.Anthropic
                    wrapper = CodexAuxiliaryClient if mode == 'codex_responses' else AnthropicAuxiliaryClient
                    real = cls(api_key=capability, base_url=actual_base, max_retries=0, http_client=httpx.Client(trust_env=False))
                    client = (wrapper(real, models['primary']) if mode == 'codex_responses' else
                        wrapper(real, models['primary'], capability, base))
                    # The named custom wrapper exposes the approved /v1 route even
                    # though the native Anthropic SDK appends /v1/messages itself.
                    client.base_url = base
                    messages = [{'role': 'user', 'content': 'native fixture'}]
                    try:
                        for turn in (1, 2, 3):
                            state['turn'] = turn
                            chunks = list(create_stream(client, {'model': models['primary'], 'messages': messages,
                                'tools': [{'type': 'function', 'function': {'name': 'fixture', 'parameters': {'type': 'object'}}}], 'max_tokens': 4096}))
                            details = []
                            for chunk in chunks:
                                for item in getattr(chunk.choices[0].delta, 'reasoning_details', []) or []:
                                    append_streamed_reasoning_detail(details, item)
                            carrier = next(item for item in details if item['type'] == 'haos.moa.native_assistant')
                            expected = _binding(get_transport(mode), config['providers']['haos-' + ('fallback' if turn < 3 else 'primary')]['base_url'],
                                models['fallback' if turn < 3 else 'primary'])
                            assert carrier['binding'] == expected, 'fallback native replay was attributed to the primary issuer'
                            messages = [messages[0], {'role': 'assistant', 'content': 'native fixture', 'reasoning_details': details,
                                'tool_calls': [{'id': 'call_fixture', 'type': 'function', 'function': {'name': 'fixture', 'arguments': '{"x":1}'}}]},
                                {'role': 'tool', 'tool_call_id': 'call_fixture', 'content': 'local fixture result'}, {'role': 'user', 'content': 'continue fixture'}]
                    finally: client.close()
                assert observed == [(1, 'primary', False), (1, 'fallback', False), (2, 'primary', False), (2, 'fallback', True), (3, 'primary', False)]
                assert not failures
                assert ledger.db.execute('SELECT status,input_tokens,output_tokens FROM requests ORDER BY rowid').fetchall() == [
                    (503, None, None), (200, 8, 5), (503, None, None), (200, 8, 5), (200, 8, 5)]
                checks.append({'mode': mode, 'native_sdk_streams': 3, 'http_dispatches': observed})
            finally:
                http.client.HTTPSConnection = old_https
                provider_policy.BASE, provider_routes.BASE = old_base, old_routes
                for key, value in (('HERMES_HOME', old_home), ('HAOS_MODEL_TOKEN', old_token)):
                    if value is None: os.environ.pop(key, None)
                    else: os.environ[key] = value
                ledger.close()
    result = {'cases': checks, 'live_provider_tested': False, 'source_sha256': {
        p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in (Path(__file__), root/'haos/provider_moa_streams.py', root/'haos/provider_proxy.py', root/'haos/provider_fallback.py')}}
    Path(sys.argv[2]).write_text(json.dumps(result, indent=2) + '\n'); print(json.dumps({'protocols': len(checks), 'native_streams': 6, 'http_dispatches': 10}))


if __name__ == '__main__': main()
