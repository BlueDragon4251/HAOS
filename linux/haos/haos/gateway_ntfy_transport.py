"""Prepared bounded ntfy subscription with durable cursor; no public activation."""
import asyncio
import hashlib
import json
import math
import time

from .gateway import digest
from .gateway_ntfy import _EVENT, _TOPIC, capture, dispatch_stored, snapshot


def _object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('duplicate ntfy JSON field')
        result[key] = value
    return result


class Subscription:
    def __init__(self, adapter):
        from .gateway_mattermost import server_url
        self.adapter = adapter
        try:
            self.server = server_url(adapter._server)
        except ValueError:
            raise ValueError('ntfy requires an exact HTTPS server without credentials or ambiguous paths') from None
        if (not isinstance(adapter._topic, str) or not _TOPIC.fullmatch(adapter._topic)
                or not isinstance(adapter._token, str) or not 1 <= len(adapter._token) <= 8192
                or any(ord(c) < 33 or ord(c) > 126 for c in adapter._token)):
            raise ValueError('ntfy requires one exact private topic and a private authentication credential')
        self._target = self.server
        self.topic = adapter._topic
        self.credential_digest = hashlib.sha256(adapter._token.encode()).digest()
        self.native = adapter._haos_native
        self.authority = snapshot(self.native.policy(), self.native.connector)
        if not any(b['connector'] == self.native.connector and b['chat'] == adapter._topic
                   for b in self.native.policy().bindings.values()):
            raise PermissionError('ntfy subscription requires an exact current topic grant')
        self.identity = digest({'authority': self.authority, 'server': self.server, 'topic': adapter._topic,
                                'token_sha256': hashlib.sha256(adapter._token.encode()).hexdigest()})
        self.db = self.native.inbox.db
        self.db.execute('''CREATE TABLE IF NOT EXISTS ntfy_subscription (
            identity TEXT PRIMARY KEY, connector TEXT NOT NULL, cursor TEXT NOT NULL DEFAULT '',
            status TEXT NOT NULL DEFAULT 'ready', next_attempt REAL NOT NULL DEFAULT 0)''')
        self.db.execute('INSERT OR IGNORE INTO ntfy_subscription(identity,connector) VALUES(?,?)',
                        (self.identity, self.native.connector))
        self.client = None
        self.stopping = False
        self.lock = asyncio.Lock()
        self.workers = set()

    def state(self):
        value = dict(self.db.execute('SELECT cursor,status,next_attempt FROM ntfy_subscription WHERE identity=?',
                                     (self.identity,)).fetchone())
        if (not isinstance(value['cursor'], str) or value['cursor'] and not _EVENT.fullmatch(value['cursor'])
                or value['status'] not in {'ready','streaming','disconnected','authentication-denied',
                    'source-unavailable','rate-limited','transport-unavailable','invalid-stream','revoked'}
                or type(value['next_attempt']) not in {int,float} or not math.isfinite(value['next_attempt'])
                or value['next_attempt'] < 0):
            raise ValueError('invalid private ntfy cursor metadata')
        return value

    def status(self, value, delay=0):
        self.db.execute('UPDATE ntfy_subscription SET status=?,next_attempt=? WHERE identity=?',
                        (value, time.time()+delay if delay else 0, self.identity))
        callback = getattr(self.adapter, '_haos_ntfy_transport_status', None)
        if callback is not None:
            callback(value)

    def current(self):
        if (self.stopping or self.adapter._topic != self.topic
                or not isinstance(self.adapter._token, str)
                or hashlib.sha256(self.adapter._token.encode()).digest() != self.credential_digest
                or snapshot(self.native.policy(), self.native.connector) != self.authority):
            raise PermissionError('ntfy subscription grant changed or was revoked')

    async def recover(self):
        self.current()
        key = self.native.inbox.due(self.native.connector)
        if key is not None:
            return await dispatch_stored(self.adapter, key)
        return False

    async def receive_once(self):
        import httpx
        async with self.lock:
            self.current()
            state = self.state()
            if state['status'] in {'authentication-denied', 'source-unavailable'} or state['next_attempt'] > time.time():
                return False
            if self.client is None:
                self.client = httpx.AsyncClient(trust_env=False, follow_redirects=False,
                    transport=httpx.AsyncHTTPTransport(retries=0),
                    timeout=httpx.Timeout(connect=15, read=90, write=15, pool=15))
            params = {'poll': 'false'}
            if state['cursor']:
                params['since'] = state['cursor']
            else:
                # Request server cache after the earliest exact current grant;
                # capture independently enforces each original grant boundary.
                bindings = self.native.policy().bindings.values()
                params['since'] = str(min(b['since'] for b in bindings if b['connector'] == self.native.connector and b['chat'] == self.adapter._topic)//1000)
            try:
                async with self.client.stream('GET', self._target+'/'+self.adapter._topic+'/json',
                        headers={**self.adapter._auth_headers(), 'Accept-Encoding': 'identity', 'Accept': 'application/x-ndjson'}, params=params) as response:
                    self.current()
                    if response.status_code in {401, 403}:
                        self.status('authentication-denied'); return False
                    if response.status_code == 404:
                        self.status('source-unavailable'); return False
                    if response.status_code == 429:
                        try: delay = float(response.headers.get('Retry-After', '5'))
                        except ValueError: delay = 5
                        if not math.isfinite(delay): delay = 5
                        self.status('rate-limited', min(86400, max(1, delay))); return False
                    if response.status_code != 200:
                        self.status('transport-unavailable', 2); return False
                    if response.headers.get('Content-Type', '').split(';')[0].strip() != 'application/x-ndjson':
                        self.status('invalid-stream', 2); return False
                    if response.headers.get('Content-Encoding', 'identity') != 'identity':
                        self.status('invalid-stream', 2); return False
                    self.status('streaming')
                    buffer = bytearray()
                    async for chunk in response.aiter_raw():
                        self.current()
                        buffer.extend(chunk)
                        while b'\n' in buffer:
                            line, _, rest = buffer.partition(b'\n'); buffer = bytearray(rest)
                            if len(line) > 16384:
                                raise ValueError('bounded ntfy line exceeded')
                            if not line.strip(): continue
                            event = json.loads(line.decode('utf-8'), object_pairs_hook=_object)
                            if not isinstance(event, dict): raise ValueError('invalid ntfy event')
                            if event.get('event') in {'open', 'keepalive'}: continue
                            if (event.get('event') != 'message' or event.get('topic') != self.adapter._topic
                                    or not isinstance(event.get('id'), str) or not _EVENT.fullmatch(event['id'])):
                                raise ValueError('invalid ntfy original identity')
                            # Raw obligation commits first. A crash before the
                            # separate cursor write only causes idempotent replay.
                            try:
                                key = capture(self.adapter, event, self.authority)
                            except PermissionError:
                                self.current()
                                key = None
                            self.current()
                            self.db.execute('UPDATE ntfy_subscription SET cursor=? WHERE identity=?', (event['id'], self.identity))
                            if key is not None:
                                await dispatch_stored(self.adapter, key)
                        if len(buffer) > 16384:
                            raise ValueError('bounded ntfy line exceeded')
                    if buffer.strip(): raise ValueError('incomplete ntfy stream line')
                self.status('disconnected', 2)
            except asyncio.CancelledError:
                self.status('disconnected', 2)
                raise
            except PermissionError:
                self.status('revoked')
                raise
            except Exception:
                # No vendor bodies, credentials or exception text in metadata.
                self.status('transport-unavailable', 2)
            return False

    async def run(self):
        """Maintain streaming and retained replay independently until close/revocation."""
        self.current()
        if self.workers:
            raise RuntimeError('ntfy subscription already running')

        async def incoming():
            while not self.stopping:
                self.current()
                if self.state()['status'] in {'authentication-denied', 'source-unavailable'}:
                    return
                await self.receive_once()
                delay = max(.1, min(1, self.state()['next_attempt']-time.time()))
                await asyncio.sleep(delay)

        async def recovery():
            while not self.stopping:
                self.current()
                try:
                    await self.recover()
                except asyncio.CancelledError:
                    raise
                except Exception:
                    self.current()
                    # The inbox has already retained a bounded retry obligation.
                    # Recovery must not block later native stream/key events.
                await asyncio.sleep(.25)

        self.workers = {asyncio.create_task(incoming()), asyncio.create_task(recovery())}
        try:
            done, _pending = await asyncio.wait(self.workers, return_when=asyncio.FIRST_COMPLETED)
            for task in done:
                if task.cancelled() and self.stopping:
                    continue
                task.result()
        except PermissionError:
            self.status('revoked')
            raise
        finally:
            await self.close()

    async def close(self):
        self.stopping = True
        workers = [task for task in self.workers if task is not asyncio.current_task()]
        for task in workers:
            task.cancel()
        if workers:
            await asyncio.gather(*workers, return_exceptions=True)
        self.workers.clear()
        client, self.client = self.client, None
        if client is not None:
            await client.aclose()
