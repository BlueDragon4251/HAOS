"""One independently approved native session reply, strict TLS and vendor ACK.

The webhook has no remote message ID. A local acceptance proof must never be
presented as a remote ID or evidence that the recipient read the message.
"""
from copy import deepcopy
import hashlib
import json
import re
import time

from .gateway import digest
from .gateway_dingtalk_admission import session_webhook, finite
from .gateway_line_ingress import _object
from .redaction import Redactor

MAX_REPLY = 65536


class Refused(PermissionError):
    def __init__(self):
        super().__init__('private native DingTalk reply transport refused')


class Boundary:
    def __init__(self, target, expires_at, current, redactor):
        if (not isinstance(target, dict) or set(target) != {'url', 'payload', 'intent_sha256'}
                or not isinstance(target['intent_sha256'], str)
                or not re.fullmatch('[0-9a-f]{64}', target['intent_sha256'])
                or type(expires_at) is not int or not callable(current) or not isinstance(redactor, Redactor)):
            raise PermissionError('one exact independently approved private DingTalk reply required')
        url, token = session_webhook(target['url'])
        payload = target['payload']
        if (not isinstance(payload, dict) or set(payload) != {'msgtype', 'markdown'}
                or payload['msgtype'] != 'markdown' or not isinstance(payload['markdown'], dict)
                or set(payload['markdown']) != {'title', 'text'} or payload['markdown']['title'] != 'Hermes'
                or not isinstance(payload['markdown']['text'], str)
                or not 1 <= len(payload['markdown']['text'].encode()) <= 128000):
            raise PermissionError('one exact native DingTalk markdown payload required')
        self.target = deepcopy(target); self.expires_at = expires_at; self.current = current
        self.redactor = redactor; self.client = None; self.used = False; self.write_started = False
        self.state = 'not-dispatched'; self.error = ''; self.acceptance_id = None
        self.retry_after = 0
        self.redactor.secrets = sorted(set([*redactor.secrets, url, token]), key=len, reverse=True)
        if redactor.clean(payload) != payload:
            raise PermissionError('DingTalk credential reflection refused')
        current()

    def reject(self, error, retry_after=0):
        self.state = 'rejected'; self.error = error; self.retry_after = retry_after
        raise Refused()

    async def post(self, url, **options):
        self.current()
        if (self.used or set(options) != {'json', 'timeout'} or options['json'] != self.target['payload']
                or type(options['timeout']) not in {int, float} or options['timeout'] != 15.0
                or url != self.target['url']):
            raise Refused()
        self.used = True
        if self.expires_at <= time.time() * 1000:
            self.reject('expired-session')
        import httpx
        self.client = httpx.AsyncClient(trust_env=False, follow_redirects=False,
            timeout=httpx.Timeout(connect=5, read=10, write=10, pool=5),
            limits=httpx.Limits(max_connections=1, max_keepalive_connections=0),
            headers={'Accept': 'application/json', 'Accept-Encoding': 'identity'})
        self.current(); self.write_started = True; self.state = 'uncertain'
        try:
            async with self.client.stream('POST', url, json=self.target['payload']) as response:
                self.current(); status = response.status_code
                if status in {401, 403}:
                    self.reject('authentication-refused')
                if status == 429:
                    retry = response.headers.get('Retry-After', '')
                    wait = int(retry) if retry.isascii() and retry.isdecimal() and 1 <= len(retry) <= 5 and 1 <= int(retry) <= 86400 else 60
                    self.reject('rate-limited', wait)
                # A redirect, server failure or malformed response after writing
                # is not proof of non-delivery and cannot trigger an automatic send.
                if status != 200 or response.headers.get('Content-Encoding', 'identity').lower() not in {'', 'identity'}:
                    raise Refused()
                if response.headers.get('Content-Type', '').split(';', 1)[0].strip().lower() != 'application/json':
                    raise Refused()
                length = response.headers.get('Content-Length')
                if length is not None and (not length.isascii() or not length.isdecimal() or len(length) > 8 or int(length) > MAX_REPLY):
                    raise Refused()
                data = bytearray()
                async for chunk in response.aiter_bytes():
                    self.current(); data.extend(chunk)
                    if len(data) > MAX_REPLY:
                        raise Refused()
                if length is not None and len(data) != int(length):
                    raise Refused()
                try:
                    body = json.loads(bytes(data).decode('utf-8'), object_pairs_hook=_object, parse_constant=finite)
                except (ValueError, UnicodeError, RecursionError):
                    raise Refused() from None
                if (not isinstance(body, dict) or not {'errcode', 'errmsg'} <= set(body) or len(body) > 64
                        or type(body['errcode']) is not int or body['errcode'] < 0
                        or not isinstance(body['errmsg'], str) or len(body['errmsg']) > 4096):
                    raise Refused()
                if body['errcode'] != 0:
                    self.reject('native-refused')
                self.current()
                self.acceptance_id = 'haos-dingtalk-' + digest([self.target['intent_sha256'],
                    self.target['url'], self.target['payload'], hashlib.sha256(bytes(data)).hexdigest()])
                self.state = 'confirmed'
                # The actual native sender still evaluates its real httpx
                # response. Only the closed vendor-ACK witness proves acceptance.
                return httpx.Response(200, content=bytes(data), headers={'Content-Type': 'application/json'},
                                      request=httpx.Request('POST', url))
        except Refused:
            raise
        except Exception:
            raise Refused() from None
        finally:
            self.client.cookies.clear(); await self.client.aclose(); self.client = None

    async def close(self):
        if self.client is not None:
            self.client.cookies.clear(); await self.client.aclose(); self.client = None
