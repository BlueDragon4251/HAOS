#!/usr/bin/env python3
"""Actual pinned main-agent fallback history, using loopback provider fixtures only."""
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
    from haos import provider_policy, provider_routes
    from haos.provider_routes import ProviderRoutes
    from haos.provider_profiles import register_profiles
    from haos.provider_proxy import Broker, Credentials, UsageLedger
    aliases = sys.argv[3].endswith('-aliases')
    mode = {'responses': 'codex_responses', 'messages': 'anthropic_messages'}[sys.argv[3].removesuffix('-aliases')]
    provider = 'openai-api' if mode == 'codex_responses' else 'anthropic'
    endpoint = 'https://api.openai.com/v1' if provider == 'openai-api' else 'https://api.anthropic.com'
    models = {'primary': 'gpt-5.4', 'fallback': 'gpt-6-sol'} if provider == 'openai-api' else {
        'primary': 'claude-sonnet-4-6', 'fallback': 'claude-opus-4-6'}
    if aliases:
        models = {key: value + '-900k' for key, value in models.items()} if mode == 'codex_responses' else {
            'primary': 'anthropic/claude-sonnet-4.6', 'fallback': 'claude-opus-4.6'}
    keys = {name: secrets.token_urlsafe(40) for name in models}
    routes = ProviderRoutes({'version': 2, 'default': 'primary', 'routes': {
        name: {'version': 1, 'provider': provider, 'endpoint': endpoint, 'models': [model],
            'default_model': model, 'api_mode': mode, 'requests_per_day': 200, 'requests_per_minute': 120}
        for name, model in models.items()}, 'fallbacks': {'primary': ['fallback']}})
    from haos.provider_messages import native_model
    wire_models = {name: native_model(routes.routes[name], model) for name, model in models.items()}
    state = {'turn': 1}; observed, failures = [], []
    opaque = 'encrypted-fixture' if mode == 'codex_responses' else 'signed-fixture'
    class Fixture(BaseHTTPRequestHandler):
        def log_message(self, *_): pass
        def do_POST(self):
            try:
                body = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                name = next(key for key in models if wire_models[key] == body['model'])
                assert self.path == ('/v1/responses' if mode == 'codex_responses' else '/v1/messages')
                assert (self.headers['Authorization'] == 'Bearer ' + keys[name] if mode == 'codex_responses'
                    else self.headers['x-api-key'] == keys[name])
                present = opaque in json.dumps(body)
                observed.append((state['turn'], name, present))
                assert 'haos_replay_binding' not in json.dumps(body), 'local provenance reached vendor'
                if name == 'primary' and state['turn'] < 3:
                    self.send_response(503); self.send_header('Content-Length', '2'); self.end_headers(); self.wfile.write(b'{}'); return
                result, early, terminal = fixture_response(mode, body['model'], 'fixture', 'native fixture')
                if mode == 'codex_responses':
                    # A final text answer: no host or fixture tool execution.
                    result['output'] = [item for item in result['output'] if item['type'] != 'function_call']
                    terminal = [event for event in terminal if not event['type'].startswith('response.function_call')
                        and event.get('item', {}).get('type') != 'function_call']
                    native = {'id': 'rs_fixture', 'type': 'reasoning', 'summary': [], 'encrypted_content': opaque, 'haos_replay_binding': '0' * 64}
                    result['output'].insert(0, native)
                    for event in [*early, *terminal]:
                        if 'output_index' in event: event['output_index'] += 1
                    early.insert(1, {'type': 'response.output_item.added', 'output_index': 0, 'item': native})
                    terminal.insert(0, {'type': 'response.output_item.done', 'output_index': 0, 'item': native})
                else:
                    result['content'] = [item for item in result['content'] if item['type'] != 'tool_use']
                    result['stop_reason'] = 'end_turn'
                    terminal = [event for event in terminal if event.get('index') != 1]
                    terminal[-2]['delta']['stop_reason'] = 'end_turn'
                    native = {'type': 'thinking', 'thinking': 'native thought', 'signature': opaque}
                    result['content'].insert(0, native)
                    for event in [*early, *terminal]:
                        if 'index' in event: event['index'] += 1
                    early[1:1] = [{'type': 'content_block_start', 'index': 0, 'content_block': {'type': 'thinking', 'thinking': '', 'signature': '', 'haos_replay_binding': '0' * 64}},
                        {'type': 'content_block_delta', 'index': 0, 'delta': {'type': 'thinking_delta', 'thinking': 'native thought'}},
                        {'type': 'content_block_delta', 'index': 0, 'delta': {'type': 'signature_delta', 'signature': opaque}},
                        {'type': 'content_block_stop', 'index': 0}]
                self.send_response(200); self.send_header('Content-Type', 'text/event-stream')
                self.send_header('Connection', 'close'); self.end_headers()
                for index, event in enumerate([*early, *terminal]):
                    if mode == 'codex_responses': event['sequence_number'] = index
                    self.wfile.write(('event: ' + event['type'] + '\ndata: ' + json.dumps(event) + '\n\n').encode()); self.wfile.flush()
                self.close_connection = True
            except BaseException as error:
                failures.append(type(error).__name__); raise
    old_https, old_dns = http.client.HTTPSConnection, socket.getaddrinfo
    old_base, old_routes = provider_policy.BASE, provider_routes.BASE
    old_home, old_token = os.environ.get('HERMES_HOME'), os.environ.get('HAOS_MODEL_TOKEN')
    def only_loopback(host, *args, **kwargs):
        assert host == '127.0.0.1', 'fixture forbids non-loopback connections'
        return old_dns(host, *args, **kwargs)
    with tempfile.TemporaryDirectory() as directory, serving(ThreadingHTTPServer(('127.0.0.1', 0), Fixture)) as port:
        def local(host, port_number=443, **kwargs):
            assert host in {'api.openai.com', 'api.anthropic.com'} and port_number == 443
            return http.client.HTTPConnection('127.0.0.1', port, timeout=kwargs.get('timeout', 10))
        http.client.HTTPSConnection = local
        ledger = UsageLedger(Path(directory) / 'usage.db'); capability = secrets.token_urlsafe(48)
        os.environ['HERMES_HOME'], os.environ['HAOS_MODEL_TOKEN'] = directory, capability
        try:
            credentials = {name: Credentials(policy, {'api_key': keys[name]}) for name, policy in routes.routes.items()}
            server = Broker(('127.0.0.1', 0), routes, capability, credentials, ledger); server.daemon_threads = False
            with serving(server) as broker:
                provider_policy.BASE = provider_routes.BASE = f'http://127.0.0.1:{broker}/v1'
                config = routes.client_config(); Path(directory, 'config.yaml').write_text(json.dumps(config))
                register_profiles(routes.data); socket.getaddrinfo = only_loopback
                from run_agent import AIAgent
                agent = AIAgent(api_key=capability, base_url=config['providers']['haos-primary']['base_url'], provider='custom',
                    requested_provider='custom:haos-primary', model=models['primary'], api_mode=mode,
                    max_iterations=1, quiet_mode=True, skip_context_files=True, skip_memory=True,
                    skip_background_review=True, enabled_toolsets=[], cwd=directory, run_budget_seconds=30)
                assert not agent.tools
                history = None
                for turn in (1, 2, 3):
                    state['turn'] = turn
                    result = agent.run_conversation('native fixture' if turn == 1 else 'continue fixture', conversation_history=history)
                    history = result['messages']
                    assert 'native fixture' in json.dumps(history), 'actual main-agent answer missing'
            assert not failures
            assert observed == [(1, 'primary', False), (1, 'fallback', False), (2, 'primary', False), (2, 'fallback', True), (3, 'primary', False)], observed
            assert ledger.db.execute('SELECT status,input_tokens,output_tokens FROM requests ORDER BY rowid').fetchall() == [
                (503, None, None), (200, 8, 5), (503, None, None), (200, 8, 5), (200, 8, 5)]
        finally:
            http.client.HTTPSConnection, socket.getaddrinfo = old_https, old_dns
            provider_policy.BASE, provider_routes.BASE = old_base, old_routes
            for key, value in (('HERMES_HOME', old_home), ('HAOS_MODEL_TOKEN', old_token)):
                if value is None: os.environ.pop(key, None)
                else: os.environ[key] = value
            ledger.close()
    result = {'mode': mode, 'owner_aliases': aliases, 'actual_main_agent_turns': 3, 'http_dispatches': observed, 'host_tools_granted': False,
        'live_provider_tested': False, 'source_sha256': {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in (
            Path(__file__), root/'haos/provider_profiles.py', root/'haos/provider_proxy.py', root/'haos/provider_response_replay.py',
            root/'haos/provider_replay.py', root/'haos/provider_messages.py', root/'haos/provider_moa_streams.py')}}
    Path(sys.argv[2]).write_text(json.dumps(result, indent=2) + '\n'); print(json.dumps(result))


if __name__ == '__main__': main()
