"""Shared actual account → broker → pinned SDK model fixture, never live inference."""
import http.client
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import secrets
import tempfile
import threading
from urllib.parse import urlsplit

from probe_http_provider_matrix import serving, fixture_response, sdk_stream


def exercise(policy, credentials, key, sdk_http_client):
    import anthropic
    import httpx
    import openai
    from agent.transports import get_transport
    from haos.provider_profiles import register_profiles
    from haos.provider_proxy import Broker, UsageLedger
    register_profiles(policy.data)
    mode, endpoint = policy.api_mode, policy.endpoint
    transport = get_transport(mode)
    body = transport.build_kwargs(policy.data['default_model'], [{'role': 'user', 'content': 'account fixture'}],
        [{'type': 'function', 'function': {'name': 'fixture', 'parameters': {'type': 'object'}}}],
        base_url=policy.client_config()['model']['base_url'], max_tokens=64)
    release, finished = threading.Event(), threading.Event()
    calls, failures, checks, state = [], [], [], {}
    class Ledger(UsageLedger):
        def finish(self, *args):
            super().finish(*args)
            finished.set()
    class Fixture(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass
        def do_POST(self):
            try:
                data = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                path = urlsplit(endpoint).path.rstrip('/')
                if mode == 'anthropic_messages' and not path.endswith('/v1'):
                    path += '/v1'
                path += {'anthropic_messages': '/messages', 'codex_responses': '/responses',
                    'chat_completions': '/chat/completions'}[mode]
                assert self.path == path and data['model'] == body['model']
                assert self.headers['Authorization'] == 'Bearer ' + key
                assert state['capability'] not in ' '.join(self.headers.values())
                calls.append(state['case'])
                case = state['case']
                if case in {'401', '429'}:
                    encoded = json.dumps({'error': {'message': key, 'type': 'fixture'}}).encode()
                    self.send_response(int(case)); self.send_header('Content-Type', 'application/json')
                    self.send_header('Content-Length', str(len(encoded))); self.end_headers(); self.wfile.write(encoded)
                    return
                result, early, terminal = fixture_response(mode, data['model'], 'fixture', 'early account fixture ' + key)
                if case == 'json':
                    encoded = json.dumps(result).encode()
                    self.send_response(200); self.send_header('Content-Type', 'application/json')
                    self.send_header('Content-Length', str(len(encoded))); self.end_headers(); self.wfile.write(encoded)
                    return
                self.send_response(200); self.send_header('Content-Type', 'text/event-stream')
                self.send_header('Connection', 'close'); self.end_headers()
                def send(value):
                    prefix = 'event: ' + value['type'] + '\n' if mode == 'anthropic_messages' else ''
                    encoded = value if isinstance(value, str) else json.dumps(value)
                    self.wfile.write((prefix + 'data: ' + encoded + '\n\n').encode()); self.wfile.flush()
                for value in early:
                    send(value)
                assert release.wait(5), 'account model stream buffered before terminal'
                if case == 'stream':
                    for value in terminal:
                        send(value)
                self.close_connection = True
            except BaseException as exc:
                failures.append(type(exc).__name__)
                raise
    cases = ("stream", "abort", "401", "429") if policy.provider == "openai-codex" else ("json", "stream", "abort", "401", "429")
    original = http.client.HTTPSConnection
    with serving(ThreadingHTTPServer(('127.0.0.1', 0), Fixture)) as port:
        def local(host, port_number=443, **kwargs):
            assert host == urlsplit(endpoint).hostname and port_number == 443
            return http.client.HTTPConnection('127.0.0.1', port, timeout=kwargs.get('timeout', 5))
        http.client.HTTPSConnection = local
        try:
            for case in cases:
                release.clear(); finished.clear()
                capability = secrets.token_urlsafe(48)
                state.update(case=case, capability=capability)
                with tempfile.TemporaryDirectory() as tmp:
                    ledger = Ledger(Path(tmp) / 'usage.db')
                    with serving(Broker(('127.0.0.1', 0), policy, capability, credentials, ledger)) as broker:
                        cls = anthropic.Anthropic if mode == 'anthropic_messages' else openai.OpenAI
                        base = f'http://127.0.0.1:{broker}' + ('' if mode == 'anthropic_messages' else '/v1')
                        with cls(api_key=capability, base_url=base, max_retries=0, timeout=10,
                                http_client=sdk_http_client(trust_env=False, transport=httpx.HTTPTransport(trust_env=False))) as client:
                            call = client.messages.create if mode == 'anthropic_messages' else (
                                client.responses.create if mode == 'codex_responses' else client.chat.completions.create)
                            if case in {'401', '429'}:
                                try:
                                    call(**body, **({"stream": True} if policy.provider == "openai-codex" else {}))
                                except (anthropic.APIStatusError, openai.APIStatusError) as exc:
                                    assert exc.status_code == int(case) and key not in str(exc) and capability not in str(exc)
                                else:
                                    raise AssertionError('account error accepted')
                            elif case == 'json':
                                result = call(**body)
                                normalized = transport.normalize_response(result)
                                assert normalized.tool_calls[0].name == 'fixture'
                                assert json.loads(normalized.tool_calls[0].arguments) == {'x': 1}
                                assert key not in result.model_dump_json() and capability not in result.model_dump_json()
                            else:
                                first, interrupted, values = False, False, []
                                try:
                                    with sdk_stream(client, mode, call, body, accumulate=case == 'stream') as stream:
                                        for value in stream:
                                            encoded = value.model_dump_json(); values.append(value)
                                            assert key not in encoded and capability not in encoded
                                            if not first and 'early account fixture ' in encoded:
                                                assert not release.is_set(); first = True; release.set()
                                        if case == 'stream' and mode in {'anthropic_messages', 'codex_responses'}:
                                            result = stream.get_final_message() if mode == 'anthropic_messages' else stream.get_final_response()
                                            normalized = transport.normalize_response(result)
                                            assert normalized.tool_calls[0].name == 'fixture'
                                            assert json.loads(normalized.tool_calls[0].arguments) == {'x': 1}
                                except httpx.RemoteProtocolError:
                                    interrupted = True
                                assert first and interrupted == (case == 'abort')
                                if case == 'stream':
                                    assert any('call_fixture' in value.model_dump_json() for value in values)
                    assert finished.wait(5)
                    expected = (502, None, None) if case == 'abort' else ((int(case), None, None) if case in {'401', '429'} else (200, 8, 5))
                    assert ledger.db.execute('SELECT status,input_tokens,output_tokens FROM requests').fetchall() == [expected]
                    ledger.close()
                checks.append(case)
        finally:
            release.set()
            http.client.HTTPSConnection = original
    assert not failures and calls == checks == list(cases)
    return checks
