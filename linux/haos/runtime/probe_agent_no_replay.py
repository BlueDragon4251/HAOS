#!/usr/bin/env python3
"""Actual pinned main-agent turn must not repeat an ambiguous broker dispatch."""
import hashlib
import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import secrets
import socket
import sys
import tempfile
from probe_http_provider_matrix import serving


def main():
    root = Path(sys.argv[1]).resolve(); sys.path.insert(0, str(root))
    from haos import provider_policy
    from haos.provider_policy import ProviderPolicy
    from haos.provider_profiles import register_profiles
    from haos.provider_proxy import Broker, Credentials, UsageLedger
    option = sys.argv[3] if len(sys.argv) == 4 else 'chat'
    legacy = option.endswith('-legacy')
    option = option.removesuffix('-legacy')
    mode = {'chat': 'chat_completions', 'responses': 'codex_responses', 'messages': 'anthropic_messages'}[option]
    calls = []
    class Fixture(BaseHTTPRequestHandler):
        def log_message(self, *_): pass
        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
            assert body['model'] == 'fixture-model'
            assert not self.headers.get('Authorization') and not self.headers.get('x-api-key')
            calls.append(True)
            self.close_connection = True
            self.connection.shutdown(socket.SHUT_RDWR)
    old_base = provider_policy.BASE
    old_home, old_capability = os.environ.get('HERMES_HOME'), os.environ.get('HAOS_MODEL_TOKEN')
    original_dns = socket.getaddrinfo
    def only_loopback(host, *args, **kwargs):
        assert host == '127.0.0.1', 'fixture forbids any non-loopback destination'
        return original_dns(host, *args, **kwargs)
    with tempfile.TemporaryDirectory() as directory, serving(ThreadingHTTPServer(('127.0.0.1', 0), Fixture)) as port:
        capability = secrets.token_urlsafe(48)
        os.environ['HERMES_HOME'], os.environ['HAOS_MODEL_TOKEN'] = directory, capability
        policy = ProviderPolicy({'version': 1, 'provider': 'local', 'endpoint': f'http://127.0.0.1:{port}/v1',
            'models': ['fixture-model'], 'default_model': 'fixture-model', 'api_mode': mode,
            'requests_per_day': 200, 'requests_per_minute': 120})
        ledger = UsageLedger(Path(directory) / 'usage.db')
        server = Broker(('127.0.0.1', 0), policy, capability, Credentials(policy, {'api_key': None}), ledger)
        server.daemon_threads = False
        try:
            with serving(server) as broker:
                provider_policy.BASE = f'http://127.0.0.1:{broker}/v1'
                config = policy.client_config()
                owner_client = {key: value for key, value in config.items() if key != 'agent'} if legacy else config
                owner_path = Path(directory, 'owner-client.json')
                owner_path.write_text(json.dumps(owner_client))
                original_owner_bytes = owner_path.read_bytes()
                if legacy:
                    from haos.sandbox import runtime_provider_config
                    descriptor = runtime_provider_config(policy, owner_client)
                    try: runtime_config = json.loads(os.read(descriptor, 65536))
                    finally: os.close(descriptor)
                else: runtime_config = config
                Path(directory, 'config.yaml').write_text(json.dumps(runtime_config))
                register_profiles(policy.data)
                socket.getaddrinfo = only_loopback
                from run_agent import AIAgent
                agent = AIAgent(api_key=capability, base_url=provider_policy.BASE, provider='custom',
                    requested_provider='custom:haos-model', model='fixture-model', api_mode=mode,
                    max_iterations=1, quiet_mode=True, skip_context_files=True, skip_memory=True,
                    skip_background_review=True, enabled_toolsets=[], cwd=directory, run_budget_seconds=30)
                assert not agent.tools, 'fixture must not grant any host tools'
                initial_api_attempts = agent._api_max_retries
                initial_auto_recovery = agent._auto_recovery_cycles
                # Bound the before-fix regression: exposing the normal retry
                # loop is sufficient; do not wait through five recovery cycles.
                agent._auto_recovery_cycles = 0
                agent.run_conversation('fixture-only ambiguous dispatch')
                assert initial_api_attempts == 1 and initial_auto_recovery == 0
                assert owner_path.read_bytes() == original_owner_bytes
            assert len(calls) == 1, f'uncertain main-agent request was dispatched {len(calls)} times'
            assert ledger.db.execute('SELECT status,input_tokens,output_tokens FROM requests').fetchall() == [(502, None, None)]
        finally:
            socket.getaddrinfo = original_dns
            provider_policy.BASE = old_base
            for key, value in (('HERMES_HOME', old_home), ('HAOS_MODEL_TOKEN', old_capability)):
                if value is None: os.environ.pop(key, None)
                else: os.environ[key] = value
            ledger.close()
    result = {'native_api_mode': mode, 'legacy_runtime_derivation': legacy, 'owner_config_preserved': True,
        'actual_pinned_main_agent_turns': 1, 'configured_api_attempts': initial_api_attempts,
        'configured_auto_recovery_cycles': initial_auto_recovery, 'host_tools_granted': False, 'ambiguous_upstream_dispatches': len(calls),
        'successful_receipt': False, 'non_loopback_connections_allowed': False, 'live_provider_tested': False,
        'source_sha256': {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in (Path(__file__),
            root/'haos/provider_policy.py', root/'haos/provider_proxy.py', root/'haos/sandbox.py')}}
    Path(sys.argv[2]).write_text(json.dumps(result, indent=2) + '\n'); print(json.dumps(result))


if __name__ == '__main__': main()
