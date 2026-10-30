#!/usr/bin/env python3
"""Actual Google authorized-user refresh followed by private Model Garden HTTP."""
import hashlib
import http.client
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import secrets
import socket
import sys
from urllib.parse import parse_qs, urlsplit
from probe_http_provider_matrix import serving


def main():
    root = Path(sys.argv[1]).resolve(); sys.path.insert(0, str(root))
    import google.auth
    from haos.provider_discovery import discover
    from haos.provider_policy import ProviderPolicy
    token = secrets.token_urlsafe(40)
    data = {'type': 'authorized_user', 'client_id': secrets.token_urlsafe(20),
        'client_secret': secrets.token_urlsafe(40), 'refresh_token': secrets.token_urlsafe(40)}
    state, observed, token_calls, failures, checks = {}, [], [], [], []
    cases = ('pages', 'selected-publisher', 'empty', '401', '429', 'redirect', 'short-body', 'invalid-json',
        'wrong-shape', 'repeated-cursor', 'page-limit', 'overlong-cursor', 'wrong-cursor-type', 'oversized', 'token-denied')
    class Fixture(BaseHTTPRequestHandler):
        def log_message(self, *_): pass
        def reply(self, status, value, *, short=False, invalid=False):
            body = b'invalid fixture JSON' if invalid else json.dumps(value).encode()
            self.send_response(status); self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(body) + (16 if short else 0)))
            self.send_header('Connection', 'close')
            if state['case'] == 'redirect': self.send_header('Location', 'https://foreign.invalid/steal')
            self.end_headers(); self.wfile.write(body); self.close_connection = True
        def do_POST(self):
            try:
                assert self.path == '/google-token'
                form = parse_qs(self.rfile.read(int(self.headers['Content-Length'])).decode())
                for key in ('client_id', 'client_secret', 'refresh_token'): assert form[key] == [data[key]]
                assert form['grant_type'] == ['refresh_token']
                token_calls.append(state['case'])
                self.reply(400 if state['case'] == 'token-denied' else 200,
                    {'error': 'invalid_grant'} if state['case'] == 'token-denied' else {'access_token': token, 'token_type': 'Bearer', 'expires_in': 3600})
            except BaseException as error:
                failures.append(type(error).__name__); raise
        def do_GET(self):
            try:
                parsed = urlsplit(self.path); query = parse_qs(parsed.query)
                assert parsed.path == '/v1beta1/publishers/' + state['publisher'] + '/models'
                assert query['view'] == ['PUBLISHER_MODEL_VIEW_BASIC'] and query['pageSize'] == ['1000']
                assert self.headers['Authorization'] == 'Bearer ' + token
                assert not self.headers.get('x-api-key') and not self.headers.get('Cookie')
                observed.append((state['case'], query.get('pageToken'))); state['page'] += 1
                name = 'publishers/' + state['publisher'] + '/models/'
                value = {'publisherModels': [{'name': name + state['model']}, {'name': name + state['model']},
                    {'name': 'publishers/foreign/models/not-selected'}, {'name': name + token}, {'name': name + '../unsafe'}]}
                case = state['case']
                if case == 'pages':
                    if state['page'] == 1: value['nextPageToken'] = 'page/2'
                    else:
                        assert query['pageToken'] == ['page/2']
                        value = {'publisherModels': [{'name': name + 'gemini-next-fixture'}]}
                if case == 'empty': value = {'publisherModels': []}
                if case == 'wrong-shape': value = {'publisherModels': 'not-a-list'}
                if case in {'repeated-cursor', 'page-limit'}: value['nextPageToken'] = 'repeated' if case == 'repeated-cursor' else str(state['page'])
                if case == 'overlong-cursor': value['nextPageToken'] = 'x' * 1025
                if case == 'wrong-cursor-type': value['nextPageToken'] = False
                if case == 'oversized': value = {'publisherModels': [{'name': name + str(number)} for number in range(4097)]}
                self.reply(int(case) if case in {'401', '429'} else 302 if case == 'redirect' else 200, value, short=case == 'short-body', invalid=case == 'invalid-json')
            except BaseException as error:
                failures.append(type(error).__name__); raise
    original_google, original_https, original_dns = google.auth.load_credentials_from_dict, http.client.HTTPSConnection, socket.getaddrinfo
    def only_loopback(host, *args, **kwargs):
        assert host == '127.0.0.1', 'catalogue fixture forbids non-loopback connections'
        return original_dns(host, *args, **kwargs)
    with serving(ThreadingHTTPServer(('127.0.0.1', 0), Fixture)) as port:
        def load(value, **kwargs):
            credential, project = original_google(value, **kwargs)
            credential._token_uri = f'http://127.0.0.1:{port}/google-token'
            return credential, project
        def local(host, port_number=443, **kwargs):
            assert host == 'us-central1-aiplatform.googleapis.com' and port_number == 443
            return http.client.HTTPConnection('127.0.0.1', port, timeout=kwargs.get('timeout', 10))
        google.auth.load_credentials_from_dict, http.client.HTTPSConnection, socket.getaddrinfo = load, local, only_loopback
        try:
            for case in cases:
                state.update(case=case, publisher='meta' if case == 'selected-publisher' else 'google', model='llama-fixture' if case == 'selected-publisher' else 'gemini-fixture', page=0)
                policy = ProviderPolicy({'version': 1, 'provider': 'vertex',
                    'endpoint': 'https://us-central1-aiplatform.googleapis.com/v1beta1/projects/fixture-project/locations/us-central1/endpoints/openapi',
                    'models': [state['publisher'] + '/' + state['model']], 'default_model': state['publisher'] + '/' + state['model'],
                    'api_mode': 'chat_completions', 'requests_per_day': 200, 'requests_per_minute': 120})
                result = discover(policy, json.dumps(data))
                if case in {'pages', 'selected-publisher', 'empty'}:
                    assert result['source'] == 'provider-api' and result['diagnostic'] == 'publisher-catalog'
                    expected = [] if case == 'empty' else [state['publisher'] + '/' + state['model']]
                    if case == 'pages': expected.append('google/gemini-next-fixture')
                    assert [row['id'] for row in result['models']] == expected
                else:
                    assert result['source'] != 'provider-api'
                    assert result['diagnostic'] == ('account-required' if case == '401' else 'catalog-unavailable')
                assert not result['inference_tested'] and all(secret not in json.dumps(result) for secret in (token, data['client_secret'], data['refresh_token']))
                assert token_calls.count(case) == 1
                assert state['page'] == (2 if case in {'pages', 'repeated-cursor'} else 5 if case == 'page-limit' else 0 if case == 'token-denied' else 1), (case, state['page'])
                checks.append({'case': case, 'catalogue_http_calls': state['page'], 'actual_google_token_refreshes': 1, 'source': result['source'], 'diagnostic': result['diagnostic']})
        finally:
            google.auth.load_credentials_from_dict, http.client.HTTPSConnection, socket.getaddrinfo = original_google, original_https, original_dns
    assert not failures
    result = {'cases': checks, 'live_account_tested': False, 'model_inference_tested': False,
        'api_contract': 'Google published v1beta1 ModelGardenService.ListPublisherModels',
        'source_sha256': {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in (Path(__file__), root/'haos/provider_discovery.py', root/'haos/provider_cloud.py', root/'haos/initial_setup_gui.py')}}
    Path(sys.argv[2]).write_text(json.dumps(result, indent=2) + '\n'); print(json.dumps({'cases': len(checks)}))


if __name__ == '__main__': main()
