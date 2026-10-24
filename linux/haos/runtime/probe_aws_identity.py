#!/usr/bin/env python3
"""Actual private AWS profile/STS refresh, cache and concurrent request snapshots."""
from datetime import datetime, timedelta, timezone
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import secrets
import sys
import tempfile
import threading
from urllib.parse import parse_qs
from xml.sax.saxutils import escape

from probe_http_provider_matrix import serving


def main():
    root = Path(sys.argv[1]).resolve(); sys.path.insert(0, str(root))
    from haos.provider_policy import ProviderPolicy
    from haos.provider_proxy import Credentials
    from haos.provider_cloud import mantle_headers
    from haos.redaction import REDACTED
    from botocore.auth import SigV4Auth
    from botocore.awsrequest import AWSRequest
    from botocore.credentials import Credentials as SDKCredentials
    source_key, source_secret = 'fixture-source-access', secrets.token_urlsafe(40)
    identities = [{'access_key_id': 'fixture-role-access-' + str(i),
        'secret_access_key': secrets.token_urlsafe(40), 'session_token': secrets.token_urlsafe(40)} for i in range(2)]
    calls, failures, snapshots = [], [], []
    class STS(BaseHTTPRequestHandler):
        def log_message(self, *_): pass
        def do_POST(self):
            try:
                raw = self.rfile.read(int(self.headers['Content-Length']))
                values = parse_qs(raw.decode())
                assert values['Action'] == ['AssumeRole'] and values['Version'] == ['2011-06-15']
                assert values['RoleArn'] == ['arn:aws:iam::123456789012:role/fixture']
                signed = self.headers['Authorization'].split('SignedHeaders=', 1)[1].split(',', 1)[0].split(';')
                request = AWSRequest(method='POST', url=f'http://127.0.0.1:{self.server.server_port}/', data=raw,
                    headers={key: self.headers[key] for key in signed})
                request.context['timestamp'] = self.headers['X-Amz-Date']
                signer = SigV4Auth(SDKCredentials(source_key, source_secret), 'sts', 'us-east-1')
                expected = signer.signature(signer.string_to_sign(request, signer.canonical_request(request)), request)
                assert self.headers['Authorization'].endswith('Signature=' + expected)
                index = len(calls); assert index < 2
                calls.append(index); identity = identities[index]
                expiration = (datetime.now(timezone.utc) + timedelta(hours=1)).strftime('%Y-%m-%dT%H:%M:%SZ')
                body = ('<AssumeRoleResponse xmlns="https://sts.amazonaws.com/doc/2011-06-15/">'
                    '<AssumeRoleResult><Credentials>'
                    '<AccessKeyId>' + escape(identity['access_key_id']) + '</AccessKeyId>'
                    '<SecretAccessKey>' + escape(identity['secret_access_key']) + '</SecretAccessKey>'
                    '<SessionToken>' + escape(identity['session_token']) + '</SessionToken>'
                    '<Expiration>' + expiration + '</Expiration></Credentials>'
                    '<AssumedRoleUser><AssumedRoleId>fixture:session</AssumedRoleId>'
                    '<Arn>arn:aws:sts::123456789012:assumed-role/fixture/session</Arn></AssumedRoleUser>'
                    '</AssumeRoleResult><ResponseMetadata><RequestId>fixture</RequestId>'
                    '</ResponseMetadata></AssumeRoleResponse>').encode()
                self.send_response(200); self.send_header('Content-Type', 'text/xml')
                self.send_header('Content-Length', str(len(body))); self.end_headers(); self.wfile.write(body)
            except BaseException as error:
                failures.append(type(error).__name__); raise
    with tempfile.TemporaryDirectory() as directory, serving(ThreadingHTTPServer(('127.0.0.1', 0), STS)) as port:
        config = Path(directory)/'config'; credentials_file = Path(directory)/'credentials'
        config.write_text('[profile role]\nrole_arn=arn:aws:iam::123456789012:role/fixture\nsource_profile=source\nregion=us-east-1\n')
        credentials_file.write_text(f'[source]\naws_access_key_id={source_key}\naws_secret_access_key={source_secret}\n')
        config.chmod(0o600); credentials_file.chmod(0o600)
        overrides = {'AWS_CONFIG_FILE': str(config), 'AWS_SHARED_CREDENTIALS_FILE': str(credentials_file),
            'AWS_ENDPOINT_URL_STS': f'http://127.0.0.1:{port}', 'AWS_EC2_METADATA_DISABLED': 'true', 'AWS_DEFAULT_REGION': 'us-east-1'}
        keys = {*overrides, 'AWS_ACCESS_KEY_ID', 'AWS_SECRET_ACCESS_KEY', 'AWS_SESSION_TOKEN', 'AWS_PROFILE', 'AWS_DEFAULT_PROFILE'}
        previous = {key: os.environ.get(key) for key in keys}
        policy = ProviderPolicy({'version': 1, 'provider': 'bedrock', 'endpoint': 'https://bedrock-runtime.us-east-1.amazonaws.com',
            'models': ['openai.gpt-5.5'], 'default_model': 'openai.gpt-5.5', 'api_mode': 'codex_responses',
            'requests_per_day': 200, 'requests_per_minute': 30})
        ready, release = threading.Event(), threading.Event()
        try:
            for key in keys: os.environ.pop(key, None)
            os.environ.update(overrides)
            private = Credentials(policy, {'api_key': json.dumps({'profile': 'role'})})
            def first_request():
                try:
                    _, redactor = private.headers(); frozen = dict(private.cloud_data)
                    assert frozen == identities[0]
                    ready.set(); assert release.wait(10)
                    assert private.cloud_data == frozen, 'concurrent SDK refresh replaced an in-flight signer identity'
                    signed = mantle_headers(policy, private.cloud_data, b'{}', {})
                    assert frozen['access_key_id'] in signed['Authorization']
                    assert signed['X-Amz-Security-Token'] == frozen['session_token']
                    assert all(redactor.text(value) == REDACTED for value in frozen.values())
                    snapshots.append('first-request-retained')
                except BaseException as error:
                    failures.append(type(error).__name__); ready.set()
            thread = threading.Thread(target=first_request); thread.start()
            try:
                assert ready.wait(10) and not failures
                _, cached_redactor = private.headers()
                assert private.cloud_data == identities[0] and calls == [0], 'native role session was not cached'
                assert cached_redactor.text(identities[0]['session_token']) == REDACTED
                # Expire only the fixture's actual SDK credential clock; the next
                # native get_frozen_credentials must perform a second STS call.
                sdk_credentials = private.cloud_cache['aws_session'].get_credentials()
                expired = datetime.now(timezone.utc) - timedelta(seconds=1)
                sdk_credentials._expiry_time = expired
                # The native AssumeRole fetcher has a second response cache.
                # Expire its timestamp too, keeping the real fetch/parser intact.
                fetcher = sdk_credentials._refresh_using.__self__
                for entry in fetcher._cache.values():
                    entry['Credentials']['Expiration'] = expired.strftime('%Y-%m-%dT%H:%M:%SZ')
                _, refreshed_redactor = private.headers()
                assert private.cloud_data == identities[1] and calls == [0, 1]
                assert all(refreshed_redactor.text(value) == REDACTED for value in identities[1].values())
            finally:
                release.set(); thread.join(10)
            assert not thread.is_alive() and not failures and snapshots == ['first-request-retained']
        finally:
            for key, value in previous.items():
                if value is None: os.environ.pop(key, None)
                else: os.environ[key] = value
    receipt = {'actual_native_sts_assume_role_http_calls': len(calls), 'source_sigv4_verified_cryptographically': True,
        'native_session_cache_and_expired_role_refresh': True, 'concurrent_request_keeps_its_frozen_signer_and_redactor': True,
        'private_credential_files_only_in_fixture': True, 'live_account_tested': False,
        'source_sha256': {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in
            (Path(__file__), root/'haos/provider_cloud.py', root/'haos/provider_proxy.py')}}
    Path(sys.argv[2]).write_text(json.dumps(receipt, indent=2) + '\n'); print(json.dumps(receipt))


if __name__ == '__main__': main()
