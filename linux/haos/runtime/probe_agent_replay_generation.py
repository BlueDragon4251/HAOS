#!/usr/bin/env python3
"""Fresh real broker/agent instances must not reuse a revoked capability's replay."""
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
    from haos import provider_policy
    from haos.provider_policy import ProviderPolicy
    from haos.provider_profiles import register_profiles
    from haos.provider_proxy import Broker, Credentials, UsageLedger
    policy = ProviderPolicy({'version': 1, 'provider': 'openai-api', 'endpoint': 'https://api.openai.com/v1',
        'models': ['gpt-5.4'], 'default_model': 'gpt-5.4', 'api_mode': 'codex_responses',
        'requests_per_day': 200, 'requests_per_minute': 120})
    first_capability, first_key = secrets.token_urlsafe(48), secrets.token_urlsafe(40)
    capabilities = [first_capability, first_capability, secrets.token_urlsafe(48)]
    keys = [first_key, first_key, secrets.token_urlsafe(40)]
    opaque = 'generation-bound-encrypted-fixture'; state = {'phase': 0}; calls, failures = [], []
    class Fixture(BaseHTTPRequestHandler):
        def log_message(self, *_): pass
        def do_POST(self):
            try:
                body = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                assert self.path == '/v1/responses' and body['model'] == 'gpt-5.4'
                assert self.headers['Authorization'] == 'Bearer ' + keys[state['phase']]
                present = opaque in json.dumps(body); calls.append(present)
                result, early, terminal = fixture_response('codex_responses', 'gpt-5.4', 'fixture', 'native fixture')
                result['output'] = [item for item in result['output'] if item['type'] != 'function_call']
                terminal = [event for event in terminal if not event['type'].startswith('response.function_call')
                    and event.get('item', {}).get('type') != 'function_call']
                native = {'id': 'rs_fixture', 'type': 'reasoning', 'summary': [], 'encrypted_content': opaque}
                result['output'].insert(0, native)
                for event in [*early, *terminal]:
                    if 'output_index' in event: event['output_index'] += 1
                early.insert(1, {'type': 'response.output_item.added', 'output_index': 0, 'item': native})
                terminal.insert(0, {'type': 'response.output_item.done', 'output_index': 0, 'item': native})
                self.send_response(200); self.send_header('Content-Type', 'text/event-stream'); self.send_header('Connection', 'close'); self.end_headers()
                for index, event in enumerate([*early, *terminal]):
                    event['sequence_number'] = index
                    self.wfile.write(('event: ' + event['type'] + '\ndata: ' + json.dumps(event) + '\n\n').encode()); self.wfile.flush()
                self.close_connection = True
            except BaseException as error:
                failures.append(type(error).__name__); raise
    old_https, old_base = http.client.HTTPSConnection, provider_policy.BASE
    old_home, old_token = os.environ.get('HERMES_HOME'), os.environ.get('HAOS_MODEL_TOKEN')
    with tempfile.TemporaryDirectory() as directory, serving(ThreadingHTTPServer(('127.0.0.1', 0), Fixture)) as port:
        def local(host, port_number=443, **kwargs):
            assert host == 'api.openai.com' and port_number == 443
            return http.client.HTTPConnection('127.0.0.1', port, timeout=kwargs.get('timeout', 10))
        http.client.HTTPSConnection = local
        os.environ['HERMES_HOME'] = directory
        ledger = UsageLedger(Path(directory)/'usage.db'); history = None
        try:
            for phase in (0, 1, 2):
                state['phase'] = phase; os.environ['HAOS_MODEL_TOKEN'] = capabilities[phase]
                server = Broker(('127.0.0.1', 0), policy, capabilities[phase], Credentials(policy, {'api_key': keys[phase]}), ledger)
                server.daemon_threads = False
                with serving(server) as broker:
                    provider_policy.BASE = f'http://127.0.0.1:{broker}/v1'
                    Path(directory, 'config.yaml').write_text(json.dumps(policy.client_config())); register_profiles(policy.data)
                    from run_agent import AIAgent
                    agent = AIAgent(api_key=capabilities[phase], base_url=provider_policy.BASE, provider='custom',
                        requested_provider='custom:haos-model', model='gpt-5.4', api_mode='codex_responses', max_iterations=1,
                        quiet_mode=True, skip_context_files=True, skip_memory=True, skip_background_review=True,
                        enabled_toolsets=[], cwd=directory, run_budget_seconds=30)
                    assert not agent.tools
                    result = agent.run_conversation('native fixture' if phase == 0 else 'continue fixture', conversation_history=history)
                    history = result['messages']
                    assert any(message.get('role') == 'assistant' and message.get('content') == 'native fixture' for message in history)
                    assert opaque in json.dumps(history), 'fixture must actually persist native replay before testing rotation'
            assert not failures and calls == [False, True, False], 'old native replay survived local capability rotation'
            assert ledger.db.execute('SELECT status,input_tokens,output_tokens FROM requests ORDER BY rowid').fetchall() == [(200, 8, 5)] * 3
        finally:
            http.client.HTTPSConnection, provider_policy.BASE = old_https, old_base
            for key, value in (('HERMES_HOME', old_home), ('HAOS_MODEL_TOKEN', old_token)):
                if value is None: os.environ.pop(key, None)
                else: os.environ[key] = value
            ledger.close()
    result = {'fresh_broker_and_main_agent_pairs': 3, 'unchanged_capability_restart_preserves_replay': True, 'same_route_model_endpoint': True,
        'native_replay_on_wire': calls, 'revoked_generation_replay_forwarded': False, 'limited_capability_and_private_key_changed': True,
        'host_tools_granted': False, 'live_account_tested': False, 'source_sha256': {
            p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in (Path(__file__), root/'haos/provider_replay.py',
                root/'haos/provider_moa_streams.py', root/'haos/provider_profiles.py', root/'haos/provider_proxy.py')}}
    Path(sys.argv[2]).write_text(json.dumps(result, indent=2) + '\n'); print(json.dumps(result))


if __name__ == '__main__': main()
