import base64
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread

import pytest
from haos.hermes_artifact import ArtifactRefused, endpoint, read


@pytest.mark.parametrize('url', ['ws://localhost/api/ws?token=x', 'wss://127.0.0.1/api/ws?token=x',
    'ws://127.0.0.1/api/ws?token=x&token=y', 'ws://127.0.0.1/api/ws?token=x&other=y',
    'ws://user@127.0.0.1/api/ws?token=x', 'ws://127.0.0.1/api/ws?token=x%0Ay'])
def test_origin_refused(url):
    with pytest.raises((ArtifactRefused, ValueError)):
        endpoint(url)


@pytest.mark.parametrize('mode', ['ok', 'redirect', 'bad-base64', 'revoked', 'empty', 'encoded', 'oversized', 'truncated'])
def test_bounded_authenticated_read(mode, monkeypatch):
    if mode == 'oversized':
        monkeypatch.setattr('haos.hermes_artifact.MAX_RESPONSE', 1024)
    requests = []
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            requests.append((self.path, self.headers.get('Authorization')))
            self.send_response(302 if mode == 'redirect' else 200)
            if mode == 'encoded':
                self.send_header('Content-Encoding', 'gzip')
            if mode == 'truncated':
                self.send_header('Content-Length', '50000')
            self.send_header('Location', 'http://example.invalid/private')
            self.end_headers()
            if mode == 'oversized':
                self.wfile.write(b' ' * 20000)
                return
            self.wfile.write(json.dumps({'dataUrl': 'data:image/png;base64,' +
                ('!!!!' if mode == 'bad-base64' else base64.b64encode(b'' if mode == 'empty' else b'fixture').decode())}).encode())
        def log_message(self, *_):
            pass
    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    thread = Thread(target=server.serve_forever, daemon=True); thread.start()
    calls = []
    def current():
        calls.append(True)
        if mode == 'revoked' and len(calls) > 1:
            raise PermissionError('withdrawn')
    try:
        args = (f'ws://127.0.0.1:{server.server_port}/api/ws?token=private',
                'durable-id', '/agent/result.png', current)
        if mode == 'ok':
            assert read(*args) == b'fixture'
        else:
            with pytest.raises((ArtifactRefused, PermissionError)):
                read(*args)
        assert len(requests) == 1
        assert requests[0][1] == 'Bearer private'
        assert 'session_id=durable-id' in requests[0][0]
        assert 'private' not in requests[0][0]
    finally:
        server.shutdown(); server.server_close(); thread.join()
