#!/usr/bin/env python3
"""Real SDK/tool-history codecs for Gemini signatures over approved Chat routes."""
import hashlib
import http.client
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import secrets
import socket
import sys
import tempfile
from probe_http_provider_matrix import serving, fixture_response


def main():
    root = Path(sys.argv[1]).resolve(); sys.path.insert(0, str(root))
    import httpx
    import openai
    from agent.transports import get_transport
    from agent.chat_completion_helpers import build_assistant_message
    from haos import provider_policy, provider_routes
    from haos.provider_routes import ProviderRoutes
    from haos.provider_profiles import register_profiles
    from haos.provider_proxy import Broker, Credentials, UsageLedger
    same_model = sys.argv[3].endswith('-same-model')
    requested = sys.argv[3].removesuffix('-same-model')
    native = requested.startswith('native-')
    option = requested.removeprefix('native-')
    assert option in {'sdk-json', 'moa-json', 'moa-stream'}
    mode = 'chat_completions'; models = {'primary': 'google/gemini-3-pro-preview', 'fallback': 'google/gemini-3-flash-preview'}
    endpoint = 'https://generativelanguage.googleapis.com/v1beta' if native else 'https://openrouter.ai/api/v1'
    if native: models = {key: value.removeprefix('google/') for key, value in models.items()}
    if same_model: models['fallback'] = models['primary']
    routes = ProviderRoutes({'version': 2, 'default': 'primary', 'routes': {
        name: {'version': 1, 'provider': 'gemini' if native else 'openrouter', 'endpoint': endpoint, 'models': [model],
            'default_model': model, 'api_mode': mode, 'requests_per_day': 200, 'requests_per_minute': 120}
        for name, model in models.items()}, 'fallbacks': {'primary': ['fallback']}})
    keys = {name: secrets.token_urlsafe(40) for name in models}
    opaque = 'gemini-thought-signature-fixture'; observed, failures = [], []; state = {'turn': 1}
    tools = [{'type': 'function', 'function': {'name': 'fixture', 'parameters': {'type': 'object'}}}]
    class Fixture(BaseHTTPRequestHandler):
        def log_message(self, *_): pass
        def do_POST(self):
            try:
                body = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                model = self.path.split('/models/', 1)[1].split(':', 1)[0] if native else body['model']
                name = next(name for name, value in keys.items() if (self.headers.get('x-goog-api-key') == value if native else self.headers.get('Authorization') == 'Bearer ' + value))
                assert model == models[name]
                if native:
                    assert self.path == '/v1beta/models/' + model + (':streamGenerateContent?alt=sse' if option.startswith('moa-') else ':generateContent')
                    assert self.headers['x-goog-api-key'] == keys[name]
                else:
                    assert self.path == '/api/v1/chat/completions'
                    assert self.headers['Authorization'] == 'Bearer ' + keys[name]
                    assert body.get('stream', False) == option.startswith('moa-')
                assert 'haos_replay_binding' not in json.dumps(body), 'local tool provenance reached vendor'
                observed.append((state['turn'], name, opaque in json.dumps(body)))
                if name == 'primary' and state['turn'] < 3:
                    self.send_response(503); self.send_header('Content-Length', '2'); self.end_headers(); self.wfile.write(b'{}'); return
                if native:
                    result = {'candidates': [{'content': {'parts': [{'text': 'native fixture'},
                        {'functionCall': {'name': 'fixture', 'args': {'x': 1}}, 'thoughtSignature': opaque}]}, 'finishReason': 'STOP'}],
                        'usageMetadata': {'promptTokenCount': 8, 'candidatesTokenCount': 5, 'totalTokenCount': 13}}
                    data = json.dumps(result).encode()
                    self.send_response(200); self.send_header('Content-Type', 'text/event-stream' if option.startswith('moa-') else 'application/json')
                    self.send_header('Connection', 'close'); self.end_headers()
                    self.wfile.write(b'data: ' + data + b'\n\n' if option.startswith('moa-') else data); self.wfile.flush()
                    self.close_connection = True; return
                result, early, terminal = fixture_response(mode, model, 'fixture', 'native fixture')
                extra = {'google': {'thought_signature': opaque}, 'haos_replay_binding': '0' * 64}
                result['choices'][0]['message']['tool_calls'][0]['extra_content'] = extra
                if not body.get('stream'):
                    data = json.dumps(result).encode()
                    self.send_response(200); self.send_header('Content-Type', 'application/json')
                    self.send_header('Content-Length', str(len(data))); self.end_headers(); self.wfile.write(data); return
                terminal[0]['choices'][0]['delta']['tool_calls'][0]['extra_content'] = extra
                self.send_response(200); self.send_header('Content-Type', 'text/event-stream'); self.send_header('Connection', 'close'); self.end_headers()
                for event in [*early, *terminal]:
                    self.wfile.write(('data: ' + (event if isinstance(event, str) else json.dumps(event)) + '\n\n').encode()); self.wfile.flush()
                self.close_connection = True
            except BaseException as error:
                failures.append(type(error).__name__); raise
    from haos import provider_native
    old_client = provider_native.create_client
    old_https, old_dns = http.client.HTTPSConnection, socket.getaddrinfo
    old_base, old_routes = provider_policy.BASE, provider_routes.BASE
    old_home, old_token = os.environ.get('HERMES_HOME'), os.environ.get('HAOS_MODEL_TOKEN')
    def only_loopback(host, *args, **kwargs):
        assert host == '127.0.0.1'
        return old_dns(host, *args, **kwargs)
    with tempfile.TemporaryDirectory() as directory, serving(ThreadingHTTPServer(('127.0.0.1', 0), Fixture)) as port:
        def local(host, port_number=443, **kwargs):
            assert host == 'openrouter.ai' and port_number == 443
            return http.client.HTTPConnection('127.0.0.1', port, timeout=kwargs.get('timeout', 10))
        http.client.HTTPSConnection = local
        if native:
            from agent.gemini_native_adapter import GeminiNativeClient
            provider_native.create_client = lambda policy, headers, credentials: GeminiNativeClient(
                api_key=headers['Authorization'].removeprefix('Bearer '), base_url=f'http://127.0.0.1:{port}/v1beta')
        ledger = UsageLedger(Path(directory) / 'usage.db'); capability = secrets.token_urlsafe(48)
        os.environ['HERMES_HOME'], os.environ['HAOS_MODEL_TOKEN'] = directory, capability
        try:
            server = Broker(('127.0.0.1', 0), routes, capability,
                {name: Credentials(policy, {'api_key': keys[name]}) for name, policy in routes.routes.items()}, ledger)
            server.daemon_threads = False
            with serving(server) as broker:
                provider_policy.BASE = provider_routes.BASE = f'http://127.0.0.1:{broker}/v1'
                config = routes.client_config(); Path(directory, 'config.yaml').write_text(json.dumps(config))
                register_profiles(routes.data); socket.getaddrinfo = only_loopback
                base = config['providers']['haos-primary']['base_url']
                from run_agent import AIAgent
                agent = AIAgent(api_key=capability, base_url=base, provider='custom', requested_provider='custom:haos-primary',
                    model=models['primary'], api_mode=mode, quiet_mode=True, skip_context_files=True,
                    skip_memory=True, skip_background_review=True, enabled_toolsets=[], cwd=directory)
                assert not agent.tools
                history = [{'role': 'user', 'content': 'native fixture'}]
                with openai.OpenAI(api_key=capability, base_url=base, max_retries=0, http_client=httpx.Client(trust_env=False)) as client:
                    for turn in (1, 2, 3):
                        state['turn'] = turn
                        if option == 'sdk-json':
                            transport = get_transport(mode)
                            wire = transport.build_kwargs(models['primary'], history, tools, base_url=base, provider='custom', max_tokens=4096)
                            response = client.chat.completions.create(**wire)
                            normalized = transport.normalize_response(response)
                        else:
                            from agent.auxiliary_client import call_llm, _aggregate_chat_stream
                            response = call_llm(task='moa_aggregator', provider='custom:haos-primary', model=models['primary'],
                                messages=history, tools=tools, max_tokens=4096, stream=option == 'moa-stream')
                            if option == 'moa-stream': response = _aggregate_chat_stream(response, model=models['primary'])
                            normalized = get_transport(mode).normalize_response(response)
                        assert normalized.tool_calls[0].name == 'fixture' and json.loads(normalized.tool_calls[0].arguments) == {'x': 1}
                        assistant = build_assistant_message(agent, normalized, normalized.finish_reason)
                        history.extend([assistant, {'role': 'tool', 'tool_call_id': assistant['tool_calls'][0]['id'], 'content': 'synthetic fixture result; no tool executed'},
                            {'role': 'user', 'content': 'continue fixture'}])
            assert not failures
            assert observed == [(1, 'primary', False), (1, 'fallback', False), (2, 'primary', False), (2, 'fallback', True), (3, 'primary', False)], observed
            assert ledger.db.execute('SELECT status,input_tokens,output_tokens FROM requests ORDER BY rowid').fetchall() == [
                (503, None, None), (200, 8, 5), (503, None, None), (200, 8, 5), (200, 8, 5)]
        finally:
            provider_native.create_client = old_client
            http.client.HTTPSConnection, socket.getaddrinfo = old_https, old_dns
            provider_policy.BASE, provider_routes.BASE = old_base, old_routes
            for key, value in (('HERMES_HOME', old_home), ('HAOS_MODEL_TOKEN', old_token)):
                if value is None: os.environ.pop(key, None)
                else: os.environ[key] = value
            ledger.close()
    result = {'case': option, 'native_gemini_codec': native, 'same_model_distinct_private_keys': same_model, 'sdk_completions': 3, 'actual_main_agent_storage_calls': 3,
        'actual_main_agent_conversation_turns': 0, 'actual_moa_auxiliary_calls': 0 if option == 'sdk-json' else 3,
        'http_dispatches': observed, 'host_tools_granted': False, 'tools_executed': False, 'live_provider_tested': False,
        'source_sha256': {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in (Path(__file__),
            root/'haos/provider_response_replay.py', root/'haos/provider_profiles.py', root/'haos/provider_moa_streams.py', root/'haos/provider_proxy.py', root/'haos/provider_native.py')}}
    Path(sys.argv[2]).write_text(json.dumps(result, indent=2) + '\n'); print(json.dumps(result))


if __name__ == '__main__': main()
