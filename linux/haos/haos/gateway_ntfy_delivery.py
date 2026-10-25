"""Prepared native ntfy replies: exact topic, bounded chunks, no uncertain resend."""
from contextvars import ContextVar
from copy import deepcopy
import hashlib
import json
import math
from types import MethodType

from .gateway import digest
from .gateway_ntfy import _EVENT, _TOPIC

_APPROVED = ContextVar('haos_ntfy_publish', default=None)


class Publisher:
    def __init__(self, adapter):
        from .gateway_mattermost import server_url
        try:
            self.server = server_url(adapter._server)
        except ValueError:
            raise ValueError('ntfy publication requires an exact approved HTTPS server') from None
        if (not isinstance(adapter._topic, str) or not _TOPIC.fullmatch(adapter._topic)
                or not isinstance(adapter._token, str) or not 1 <= len(adapter._token) <= 8192
                or any(ord(c) < 33 or ord(c) > 126 for c in adapter._token)):
            raise ValueError('private ntfy topic and authentication required')
        existing = getattr(adapter, '_haos_ntfy_publisher', None)
        if existing is not None and not getattr(existing, 'closed', False):
            raise PermissionError('ntfy adapter already has a private publisher')
        self.adapter = adapter
        self.topic = adapter._topic
        self.credential_digest = hashlib.sha256(adapter._token.encode()).digest()
        self._target = self.server
        self.original = type(adapter).send
        self.client = None
        self.closed = False
        adapter._http_client = self
        adapter._haos_ntfy_publisher = self
        async def deny(_self, *_args, **_kwargs):
            raise PermissionError('ntfy publication requires an exact current retained owner route')
        adapter.send = MethodType(deny, adapter)

    def current(self, binding):
        if (self.closed or self.adapter._topic != self.topic or not isinstance(self.adapter._token, str)
                or hashlib.sha256(self.adapter._token.encode()).digest() != self.credential_digest):
            raise PermissionError('ntfy private publisher was closed or superseded')
        native = self.adapter._haos_native
        native.policy().current_binding({'binding_id': binding['id'], 'binding_digest': digest(binding)})
        if (binding['connector'] != native.connector or binding['sender'] != self.topic
                or binding['chat'] != self.topic or binding['scope'] or binding['thread']
                or binding.get('trust_topic_publishers') is not True):
            raise PermissionError('ntfy reply topic differs from the exact owner-approved route')

    async def post(self, url, *, content, headers, timeout):
        import httpx
        from plugins.platforms.ntfy.adapter import _publish_headers
        route = _APPROVED.get()
        if route is None or route['publisher'] is not self:
            raise PermissionError('no private ntfy publication capability')
        self.current(route['binding'])
        expected = _publish_headers(self.adapter._token, bool((self.adapter.config.extra or {}).get('markdown', False)))
        if (url != self.server+'/'+self.topic or content != route['body'] or headers != expected or timeout != 15.0):
            raise PermissionError('native ntfy publication changed approved endpoint or payload')
        if self.client is None:
            self.client = httpx.AsyncClient(trust_env=False, follow_redirects=False,
                transport=httpx.AsyncHTTPTransport(retries=0), timeout=httpx.Timeout(15))
        route['dispatched'] = True
        try:
            async with self.client.stream('POST', self._target+'/'+self.topic, content=content,
                    headers={**headers, 'Accept-Encoding': 'identity'}) as response:
                route['status'] = response.status_code
                try: delay = float(response.headers.get('Retry-After', '5'))
                except ValueError: delay = 5
                route['retry_after'] = min(86400, max(1, delay)) if math.isfinite(delay) else 5
                if 200 <= response.status_code < 300:
                    body = bytearray()
                    async for chunk in response.aiter_raw():
                        body.extend(chunk)
                        if len(body) > 65536: raise ValueError('bounded ntfy receipt exceeded')
                    from .gateway_ntfy_transport import _object
                    proof = json.loads(body.decode('utf-8'), object_pairs_hook=_object)
                    if (not isinstance(proof, dict) or proof.get('event') != 'message' or proof.get('topic') != self.topic
                            or not isinstance(proof.get('id'), str) or not _EVENT.fullmatch(proof['id'])
                            or type(proof.get('time')) is not int or proof['time'] <= 0):
                        raise ValueError('ntfy response has no exact native receipt')
                    from .redaction import Redactor
                    redactor = Redactor([self.adapter._token, expected['Authorization'].split(' ', 1)[-1]])
                    if redactor.text(proof['id']) != proof['id']:
                        raise ValueError('ntfy receipt is not safe for public status')
                    route['receipt'] = proof['id']
                    # The native codec sees the actual validated server ID only;
                    # its random fallback receipt is never used as delivery proof.
                    return httpx.Response(response.status_code, json={'id': proof['id']})
                return httpx.Response(response.status_code, json={'error': 'private ntfy request refused'})
        except Exception:
            # An attempted POST, even with no receipt, must never be replayed
            # automatically. Keep untrusted vendor bodies out of native logging.
            return httpx.Response(502, json={'error': 'private ntfy delivery outcome unknown'})

    async def send(self, binding, content):
        from gateway.platforms.base import SendResult
        binding = deepcopy(binding)
        self.current(binding)
        if not isinstance(content, str) or not content or len(content) > 65536 or len(content.encode()) > 65536:
            return SendResult(success=False, error_kind='too_long', raw_response={'haos_delivery': 'refused'})
        chunks = []
        current = ''
        size = 0
        for char in content:
            width = len(char.encode())
            if size + width > 4096:
                chunks.append(current); current = ''; size = 0
            current += char; size += width
        chunks.append(current)
        receipts = []
        for chunk in chunks:
            route = {'publisher': self, 'binding': binding, 'body': chunk.encode(), 'dispatched': False,
                     'status': None, 'receipt': None, 'retry_after': 5}
            token = _APPROVED.set(route)
            try:
                self.current(binding)
                result = await self.original(self.adapter, self.topic, chunk, metadata={'publish_topic': self.topic})
            except PermissionError:
                return SendResult(success=False, error_kind='forbidden', raw_response={
                    'partial_overflow': bool(receipts), 'haos_delivery': 'refused'})
            finally:
                _APPROVED.reset(token)
            if result.success is True and route['receipt'] and result.message_id == route['receipt']:
                receipts.append(route['receipt'])
                continue
            if receipts:
                return SendResult(success=False, raw_response={'partial_overflow': True, 'haos_chunk_receipts': receipts})
            code = route['status']
            if code in {400, 401, 403, 404, 413, 429}:
                kind = {400: 'bad_format', 401: 'forbidden', 403: 'forbidden', 404: 'not_found', 413: 'too_long', 429: 'rate_limited'}[code]
                return SendResult(success=False, error_kind=kind, retry_after=route['retry_after'], raw_response={'haos_delivery': 'refused'})
            return SendResult(success=False, raw_response={'haos_delivery': 'uncertain'})
        return SendResult(success=True, message_id=receipts[-1], raw_response={'haos_chunk_receipts': receipts})

    async def aclose(self):
        self.closed = True
        client, self.client = self.client, None
        if client is not None:
            await client.aclose()
