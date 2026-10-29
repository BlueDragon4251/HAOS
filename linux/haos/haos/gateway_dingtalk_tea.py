"""Closed private transport for the real generated DingTalk Robot SDK.

The actual Hermes helper, generated request, DingTalk SPI and response model
remain in use. Only an independently approved download-code lookup is admitted.
"""
from contextlib import contextmanager
from contextvars import ContextVar
import importlib
import json
import re
import threading
import time
from urllib.parse import unquote

from .gateway_dingtalk_http import Boundary as TokenBoundary, Failure
from .gateway_dingtalk_admission import finite
from .gateway_line_ingress import _object

_ACTIVE = ContextVar('haos_private_dingtalk_robot_lookup', default=None)
_LOCK = threading.RLock()
API = 'https://api.dingtalk.com'
PATH = '/v1.0/robot/messageFiles/download'


class Core:
    def __init__(self, original): self.original = original
    def __getattr__(self, name):
        if name in {'do_action', 'do_sse_action', 'async_do_sse_action'}:
            raise PermissionError('unreviewed private Robot SDK transport')
        return getattr(self.original, name)
    async def async_do_action(self, request, runtime):
        boundary = _ACTIVE.get()
        if not isinstance(boundary, Lookup):
            raise PermissionError('no independently approved private Robot lookup')
        return await boundary.request(request, runtime)


@contextmanager
def sdk_scope(boundary):
    if not isinstance(boundary, Lookup) or _ACTIVE.get() is not None:
        raise PermissionError('one closed private Robot lookup scope required')
    with _LOCK:
        module = importlib.import_module('alibabacloud_tea_openapi.client'); original = module.DaraCore
        if isinstance(original, Core):
            raise PermissionError('nested private Robot transport refused')
        module.DaraCore = Core(original); token = _ACTIVE.set(boundary)
        try:
            yield
        finally:
            _ACTIVE.reset(token); module.DaraCore = original


class Lookup:
    def __init__(self, token_owner, token, code, current):
        if (not isinstance(token_owner, TokenBoundary) or not callable(current)
                or not isinstance(token, str) or token not in token_owner.tokens
                or not isinstance(code, str) or not 16 <= len(code) <= 8192 or '://' in code
                or any(not 33 <= ord(char) <= 126 for char in code)):
            raise PermissionError('one observed private token and approved native resource code required')
        self.owner = token_owner; self.token = token; self.code = code; self.current = current
        self.used = False; self.failure = None; self.retry_after=0; self.url = None; self.client = None
        token_owner.register(code); self.check()

    def check(self):
        self.current(); self.owner.current()
        if self.owner.tokens.get(self.token, {}).get('until', 0) <= time.monotonic():
            self.refuse('invalid-token')

    def refuse(self, kind, retry_after=0):
        self.failure = kind; self.retry_after=retry_after; raise Failure(kind,retry_after)

    async def request(self, request, runtime):
        self.check()
        if self.used or _ACTIVE.get() is not self:
            raise PermissionError('one current native resource lookup required')
        if (request.protocol != 'https' or request.method != 'POST' or request.pathname != PATH
                or request.query not in (None, {}) or request.port != 80):
            raise PermissionError('unreviewed native Robot SDK route')
        # Pinned DaraRequest retains its constructor's port=80 hint even for
        # HTTPS. It is not a destination: the actual private URL below is fixed
        # to https://api.dingtalk.com (443), independent of that SDK hint.
        permitted = {'key', 'cert', 'ca', 'readTimeout', 'connectTimeout', 'httpProxy', 'httpsProxy',
            'noProxy', 'socks5Proxy', 'socks5NetWork', 'maxIdleConns', 'retryOptions', 'ignoreSSL',
            'tlsMinVersion', 'disableHttp2'}
        if not isinstance(runtime, dict) or set(runtime) != permitted:
            raise PermissionError('closed native Robot SDK runtime options required')
        numeric = {'readTimeout', 'connectTimeout', 'maxIdleConns'}
        # Pinned DaraCore.to_number(None) is exactly integer zero. These SDK
        # default hints cannot remove the private transport's fixed deadlines.
        if (any(type(runtime[key]) is not int or runtime[key] != 0 for key in numeric)
                or any(value is not None for key, value in runtime.items() if key not in numeric | {'disableHttp2'})
                or runtime['disableHttp2'] is not False):
            raise PermissionError('native Robot runtime widened proxy, TLS, retry or client capabilities')
        headers = request.headers
        if (not isinstance(headers, dict) or set(headers) != {'host', 'user-agent', 'accept', 'content-type', 'x-acs-dingtalk-access-token'}
                or headers['host'] != 'api.dingtalk.com' or headers['accept'] != 'application/json'
                or headers['content-type'] != 'application/json; charset=utf-8'
                or headers['x-acs-dingtalk-access-token'] != self.token
                or not isinstance(headers['user-agent'], str) or not 1 <= len(headers['user-agent']) <= 512
                or not headers['user-agent'].startswith('AlibabaCloud (')
                or any(ord(char) < 32 or ord(char) == 127 for char in headers['user-agent'])):
            raise PermissionError('unreviewed native Robot SDK headers or identity')
        if not isinstance(request.body, str) or len(request.body.encode()) > 32768:
            raise PermissionError('bounded generated Robot lookup body required')
        try:
            body = json.loads(request.body, object_pairs_hook=_object, parse_constant=finite)
        except (ValueError, RecursionError):
            raise PermissionError('exact generated Robot lookup JSON required') from None
        if body != {'downloadCode': self.code, 'robotCode': self.owner.value['robot_code']}:
            raise PermissionError('Robot lookup changed approved resource or app identity')
        self.used = True
        import httpx
        self.client = httpx.AsyncClient(trust_env=False, follow_redirects=False,
            timeout=httpx.Timeout(connect=5, read=10, write=10, pool=5),
            limits=httpx.Limits(max_connections=1, max_keepalive_connections=0),
            headers={'Accept-Encoding': 'identity'})
        try:
            async with self.client.stream('POST', API + PATH, headers=headers, content=request.body.encode()) as response:
                self.check(); status = response.status_code
                if status in {401, 403}: self.refuse('authentication-refused')
                if status == 429:
                    from .gateway_retry import retry_after
                    self.refuse('rate-limited',retry_after(response.headers.get('Retry-After'),default=60,
                        private_values=self.owner.redactor.secrets))
                if 300 <= status < 400: self.refuse('redirect-refused')
                if status != 200: self.refuse('server-refused')
                if response.headers.get('Content-Encoding', 'identity').lower() not in {'', 'identity'}:
                    self.refuse('invalid-response')
                if response.headers.get('Content-Type', '').split(';', 1)[0].strip().lower() != 'application/json':
                    self.refuse('invalid-response')
                length = response.headers.get('Content-Length')
                if length is not None and (not length.isascii() or not length.isdecimal() or len(length) > 8 or int(length) > 65536):
                    self.refuse('response-too-large')
                raw = bytearray()
                async for chunk in response.aiter_bytes():
                    self.check(); raw.extend(chunk)
                    if len(raw) > 65536: self.refuse('response-too-large')
                if length is not None and len(raw) != int(length): self.refuse('truncated-response')
                try:
                    data = json.loads(bytes(raw).decode(), object_pairs_hook=_object, parse_constant=finite)
                except (ValueError, UnicodeError, RecursionError): self.refuse('invalid-response')
                if (not isinstance(data, dict) or not 1 <= len(data) <= 64 or not isinstance(data.get('downloadUrl'), str)
                        or not 1 <= len(data['downloadUrl']) <= 16384): self.refuse('invalid-response')
                from .gateway_dingtalk_download import validate_url
                self.url = validate_url(data['downloadUrl'])
                decoded = self.url
                for _ in range(2):
                    decoded = unquote(decoded)
                    if any(secret in decoded for secret in (self.token, self.owner.value['client_secret'])):
                        self.refuse('invalid-response')
                self.owner.register(self.url); self.check()
                from darabonba.response import DaraResponse
                result = DaraResponse(); result.status_code = 200; result.status_message = 'OK'
                result.headers = {'content-type': 'application/json', 'content-length': str(len(raw))}
                result.body = bytes(raw); return result
        except Failure as error:
            self.failure = error.kind; raise
        except httpx.ConnectError as error:
            import ssl
            pending = [error]; seen = set(); tls = False
            for _ in range(8):
                if not pending: break
                cause = pending.pop()
                if id(cause) in seen: continue
                seen.add(id(cause))
                if isinstance(cause, ssl.SSLError): tls = True; break
                pending.extend(part for part in [cause.__cause__, cause.__context__, *cause.args]
                               if isinstance(part, BaseException))
            self.refuse('tls-refused' if tls else 'transport-unavailable')
        except httpx.RemoteProtocolError: self.refuse('truncated-response')
        except Exception: self.refuse('transport-unavailable')
        finally:
            await self.close()

    async def close(self):
        if self.client is not None:
            self.client.cookies.clear(); await self.client.aclose(); self.client = None
