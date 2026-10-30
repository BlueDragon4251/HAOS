"""Bounded session artifact reads inside the agent namespace, never host paths.

This primitive confers no gateway permission. Callers must independently check
mission/output provenance and owner grants before, during and after the read.
"""
import base64
import binascii
import http.client
import json
import time
from urllib.parse import parse_qs, urlencode, urlsplit

MAX_BYTES = 8 * 1024 * 1024
MAX_RESPONSE = 4 * ((MAX_BYTES + 2) // 3) + 4096


class ArtifactRefused(RuntimeError):
    pass


def endpoint(websocket_url):
    u = urlsplit(websocket_url)
    query = parse_qs(u.query, strict_parsing=True, keep_blank_values=True)
    if (u.scheme != 'ws' or u.hostname not in {'127.0.0.1', '::1'}
            or u.username or u.password or u.fragment or u.path != '/api/ws'
            or set(query) != {'token'} or len(query['token']) != 1
            or not 1 <= len(query['token'][0]) <= 1024
            or any(not 33 <= ord(c) <= 126 for c in query['token'][0])):
        raise ArtifactRefused('authenticated literal loopback Hermes endpoint required')
    return u.hostname, u.port or 80, query['token'][0]


def read(websocket_url, session_id, path, current):
    """Read only an explicitly selected durable-session artifact; no retries."""
    host, port, token = endpoint(websocket_url)
    if (not isinstance(session_id, str) or not 1 <= len(session_id) <= 256
            or not session_id.strip() or not isinstance(path, str)
            or not 1 <= len(path) <= 4096 or any(ord(c) < 32 for c in path)
            or not callable(current)):
        raise ArtifactRefused('bounded session artifact reference required')
    current()
    deadline = time.monotonic() + 30
    connection = http.client.HTTPConnection(host, port, timeout=5)
    try:
        # http.client has no proxy, redirect, cookie or automatic retry support.
        connection.request('GET', '/api/fs/read-data-url?' + urlencode(
            {'session_id': session_id, 'path': path}),
            headers={'Authorization': 'Bearer ' + token, 'Accept-Encoding': 'identity'})
        response = connection.getresponse()
        if response.status != 200 or response.getheader('Content-Encoding', 'identity') != 'identity':
            raise ArtifactRefused('agent artifact unavailable: status ' + str(response.status))
        lengths = response.headers.get_all('Content-Length', [])
        if len(lengths) > 1 or (lengths and (not lengths[0].isdigit()
                or int(lengths[0]) > MAX_RESPONSE)):
            raise ArtifactRefused('invalid agent artifact transport length')
        expected = int(lengths[0]) if lengths else None
        raw = bytearray()
        while True:
            current()
            if time.monotonic() >= deadline:
                raise ArtifactRefused('agent artifact read deadline exceeded')
            chunk = response.read1(min(48 * 1024, MAX_RESPONSE + 1 - len(raw)))
            if not chunk:
                break
            raw.extend(chunk)
            if len(raw) > MAX_RESPONSE:
                raise ArtifactRefused('agent artifact exceeds transport bound')
        if expected is not None and len(raw) != expected:
            raise ArtifactRefused('incomplete agent artifact receipt')
        value = json.loads(raw)
        if not isinstance(value, dict) or set(value) != {'dataUrl'} or not isinstance(value['dataUrl'], str):
            raise ArtifactRefused('invalid agent artifact receipt')
        header, separator, encoded = value['dataUrl'].partition(',')
        if (not separator or not header.startswith('data:') or not header.endswith(';base64')
                or len(header) > 256):
            raise ArtifactRefused('invalid agent artifact encoding')
        data = base64.b64decode(encoded, validate=True)
        if not 1 <= len(data) <= MAX_BYTES or base64.b64encode(data).decode('ascii') != encoded:
            raise ArtifactRefused('invalid agent artifact size or encoding')
        current()
        return data
    except (OSError, http.client.HTTPException, ValueError, binascii.Error):
        # Do not reflect paths, authentication headers, URLs or server bodies.
        raise ArtifactRefused('agent artifact read failed') from None
    finally:
        connection.close()
