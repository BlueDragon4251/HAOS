#!/usr/bin/env python3
"""Actual pinned auxiliary call must not repeat an ambiguous broker dispatch."""
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
    from agent import auxiliary_client
    task = sys.argv[3] if len(sys.argv) == 4 else 'moa_reference'
    assert task in {'moa_reference', 'moa_aggregator'}
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
            'models': ['fixture-model'], 'default_model': 'fixture-model', 'api_mode': 'chat_completions',
            'requests_per_day': 200, 'requests_per_minute': 120})
        ledger = UsageLedger(Path(directory) / 'usage.db')
        server = Broker(('127.0.0.1', 0), policy, capability, Credentials(policy, {'api_key': None}), ledger)
        server.daemon_threads = False
        try:
            with serving(server) as broker:
                provider_policy.BASE = f'http://127.0.0.1:{broker}/v1'
                config = policy.client_config()
                Path(directory, 'config.yaml').write_text(json.dumps(config))
                register_profiles(policy.data)
                socket.getaddrinfo = only_loopback
                try:
                    auxiliary_client.call_llm(task=task, provider='custom:haos-model', model='fixture-model',
                        messages=[{'role': 'user', 'content': 'fixture-only ambiguous dispatch'}], max_tokens=64, timeout=3)
                except Exception:
                    pass
                else:
                    raise AssertionError('ambiguous provider disconnect returned success')
            assert len(calls) == 1, f'uncertain auxiliary request was dispatched {len(calls)} times'
            assert ledger.db.execute('SELECT status,input_tokens,output_tokens FROM requests').fetchall() == [(502, None, None)]
        finally:
            socket.getaddrinfo = original_dns
            provider_policy.BASE = old_base
            for key, value in (('HERMES_HOME', old_home), ('HAOS_MODEL_TOKEN', old_capability)):
                if value is None: os.environ.pop(key, None)
                else: os.environ[key] = value
            ledger.close()
    result = {'task': task, 'actual_pinned_auxiliary_calls': 1, 'ambiguous_upstream_dispatches': len(calls),
        'successful_receipt': False, 'non_loopback_connections_allowed': False, 'live_provider_tested': False,
        'source_sha256': {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in (Path(__file__),
            root/'haos/provider_moa_streams.py', root/'haos/provider_proxy.py', Path(auxiliary_client.__file__))}}
    Path(sys.argv[2]).write_text(json.dumps(result, indent=2) + '\n'); print(json.dumps(result))


if __name__ == '__main__': main()
