"""Private prepared DingTalk Stream profile; public delivery/media activation separate."""
import asyncio
import os
from pathlib import Path
import time
from types import MethodType, SimpleNamespace

from .gateway import GatewayPolicy, digest
from .gateway_dingtalk import credentials, scope as account_scope, authority
from .gateway_dingtalk_cache import RawEvents
from .gateway_dingtalk_ingress import install, capture, dispatch_stored

STATES = frozenset({'created', 'connecting', 'connected-ws', 'authentication-refused',
    'rate-limited', 'tls-refused', 'transport-unavailable', 'source-unavailable',
    'storage-unavailable', 'revoked', 'disconnected', 'closed'})
BLOCKS = frozenset({'authentication-refused', 'tls-refused'})


def build(value, *, parent, connector, policy, inbox):
    from .gateway_runtime import require_runtime_identity
    require_runtime_identity(); value = credentials(value)
    def snapshot(latest):
        if not isinstance(latest, GatewayPolicy) or latest.connectors.get(connector, {}).get('platform') != 'dingtalk':
            raise PermissionError('prepared independent DingTalk policy required')
        bindings = [row for row in latest.bindings.values() if row['connector'] == connector]
        if not bindings or any(row['scope'] != account_scope(value) or row['sender'] == value['robot_code'] for row in bindings):
            raise PermissionError('explicit timed DingTalk grants matching exact app identity required')
        return digest([latest.publication, connector, bindings, value])
    initial = snapshot(policy()); publication = authority(connector, value)
    def pinned():
        latest = policy()
        if snapshot(latest) != initial:
            raise PermissionError('DingTalk profile grant or credential identity changed')
        authority(connector, value, publication); return latest
    from .gateway_line_profile import _directory
    from .gateway_matrix_profile import acquire_lease, scope
    parent = Path(parent); _directory(parent); profile = parent / ('dingtalk-' + digest([connector, value]))
    try:
        profile.mkdir(mode=0o700)
    except FileExistsError:
        pass
    lease = acquire_lease(profile); originals = None
    try:
        home = profile / 'home'
        try:
            home.mkdir(mode=0o700)
        except FileExistsError:
            pass
        _directory(home)
        from .redaction import Redactor
        inbox.redactor = Redactor([*inbox.redactor.secrets, value['client_secret']])
        environment = {'HERMES_SAFE_MODE': '1', 'DINGTALK_CLIENT_ID': value['client_id'],
            'DINGTALK_CLIENT_SECRET': value['client_secret'], 'DINGTALK_REQUIRE_MENTION': 'true',
            'DINGTALK_ALLOWED_USERS': ','.join(sorted({row['sender'] for row in pinned().bindings.values() if row['connector'] == connector})),
            'GATEWAY_ALLOW_ALL_USERS': 'false'}
        with scope(home, environment):
            from gateway.config import PlatformConfig
            from plugins.platforms.dingtalk import adapter as native
            from .gateway_ingress import durable_adapter
            if not native.DINGTALK_STREAM_AVAILABLE or not native.HTTPX_AVAILABLE:
                raise RuntimeError('pinned DingTalk SDK unavailable; no automatic installation')
            adapter = install(durable_adapter(native.DingTalkAdapter(PlatformConfig(enabled=True, extra={
                'client_id': value['client_id'], 'client_secret': value['client_secret'],
                'robot_code': value['robot_code'], 'card_template_id': ''}))))
        adapter._haos_native = SimpleNamespace(connector=connector, policy=pinned, inbox=inbox)
        adapter._haos_dingtalk_value = value; adapter._haos_dingtalk_home = home
        adapter._haos_dingtalk_environment = environment; adapter._haos_dingtalk_closed = False
        def current():
            if adapter._haos_dingtalk_closed:
                raise PermissionError('private DingTalk profile closed')
            pinned()
            if (adapter._client_id != value['client_id'] or adapter._client_secret != value['client_secret']
                    or adapter._robot_code != value['robot_code'] or adapter._card_template_id):
                raise PermissionError('native DingTalk app identity changed')
        adapter._haos_dingtalk_check = current
        originals = RawEvents(profile / 'originals.db', inbox.redactor, current)
        adapter._haos_dingtalk_raw = originals
        return _lifecycle(adapter, lease, initial)
    except BaseException:
        if originals is not None:
            originals.close()
        os.close(lease); raise


def _lifecycle(adapter, lease, identity):
    native = adapter._haos_native; db = native.inbox.db; value = adapter._haos_dingtalk_value
    current = adapter._haos_dingtalk_check; lifecycle = asyncio.Lock()
    adapter._haos_dingtalk_socket = None; adapter._haos_dingtalk_task = None
    adapter._haos_dingtalk_live = False
    from .gateway_dingtalk_delivery import Publisher
    from .gateway_dingtalk_send import MAX_TEXT
    adapter.MAX_MESSAGE_LENGTH = MAX_TEXT
    adapter._haos_dingtalk_publisher = Publisher(adapter) if any(
        row['connector'] == native.connector and 'read' in row['capabilities']
        for row in native.policy().bindings.values()) else None
    credential_scope = digest([native.connector, value])
    db.execute('''CREATE TABLE IF NOT EXISTS dingtalk_profile_status(
        identity TEXT PRIMARY KEY, connector TEXT NOT NULL, credential_scope TEXT NOT NULL,
        status TEXT NOT NULL, updated_at REAL NOT NULL, next_attempt REAL NOT NULL)''')
    prior = db.execute('SELECT status,next_attempt FROM dingtalk_profile_status WHERE connector=? AND credential_scope=?',
                       (native.connector, credential_scope)).fetchall()
    blocked = next((row['status'] for row in prior if row['status'] in BLOCKS), None)
    deadline = max([row['next_attempt'] for row in prior] + [0])
    db.execute('INSERT OR IGNORE INTO dingtalk_profile_status VALUES(?,?,?,?,?,?)',
               (identity, native.connector, credential_scope, blocked or 'created', time.time(), deadline))
    db.execute('UPDATE dingtalk_profile_status SET next_attempt=MAX(next_attempt,?),status=CASE WHEN ? THEN ? ELSE status END WHERE identity=?',
               (deadline, blocked is not None, blocked or 'created', identity))
    def status(state, delay=0):
        if state not in STATES:
            raise ValueError('finite private DingTalk status required')
        db.execute('UPDATE dingtalk_profile_status SET status=?,updated_at=?,next_attempt=? WHERE identity=?',
                   (state, time.time(), time.time() + delay if delay else 0, identity))
    def health(self):
        return dict(db.execute('SELECT connector,status,updated_at,next_attempt FROM dingtalk_profile_status WHERE identity=?',
                               (identity,)).fetchone())
    def failure(kind, delay=2):
        state = kind if kind in STATES else 'transport-unavailable'
        status(state, 60 if state == 'rate-limited' else 0 if state in BLOCKS else delay)
    async def stop():
        adapter._haos_dingtalk_live = False
        task = adapter._haos_dingtalk_task; adapter._haos_dingtalk_task = None
        if task is not None and task is not asyncio.current_task():
            task.cancel(); await asyncio.gather(task, return_exceptions=True)
        socket = adapter._haos_dingtalk_socket; adapter._haos_dingtalk_socket = None
        if socket is not None:
            await socket.close()
        adapter._mark_disconnected()
    async def open_socket():
        from .gateway_dingtalk_ws_process import Session
        adapter._haos_dingtalk_socket = Session(value, native.connector, current, lambda raw: capture(adapter, raw))
        await adapter._haos_dingtalk_socket.start(); current()
        adapter._mark_connected(); adapter._haos_dingtalk_live = True; status('connected-ws')
    async def replay():
        backoff = 2
        try:
            while True:
                current(); socket = adapter._haos_dingtalk_socket
                if socket is not None and not socket.active:
                    kind = socket.failure; adapter._haos_dingtalk_socket = None; await socket.close()
                    adapter._mark_disconnected(); failure(kind, backoff); backoff = min(60, backoff * 2)
                row = health(adapter)
                if adapter._haos_dingtalk_socket is None and row['status'] not in BLOCKS and row['next_attempt'] <= time.time():
                    try:
                        await open_socket()
                    except asyncio.CancelledError:
                        raise
                    except PermissionError:
                        raise
                    except Exception:
                        socket = adapter._haos_dingtalk_socket; adapter._haos_dingtalk_socket = None
                        kind = socket.failure if socket is not None else None
                        if socket is not None:
                            await socket.close()
                        failure(kind, backoff); backoff = min(60, backoff * 2)
                try:
                    key = native.inbox.due(native.connector)
                    if key is not None:
                        await dispatch_stored(adapter, key)
                except PermissionError:
                    current()
                    if adapter._haos_dingtalk_socket is not None and adapter._haos_dingtalk_socket.active:
                        status('source-unavailable')
                except Exception:
                    current()
                    if adapter._haos_dingtalk_socket is not None and adapter._haos_dingtalk_socket.active:
                        status('storage-unavailable')
                await asyncio.sleep(.2)
        except PermissionError:
            status('revoked')
            async with lifecycle:
                await stop()
    async def connect(self, **_kwargs):
        async with lifecycle:
            if self._haos_dingtalk_closed:
                raise PermissionError('private DingTalk profile closed')
            await stop(); current()
            if not callable(getattr(self, '_haos_ingress', None)):
                raise PermissionError('private durable DingTalk handler required before connection')
            row = health(self)
            if row['status'] in BLOCKS or row['next_attempt'] > time.time():
                return False
            status('connecting')
            try:
                await open_socket()
                self._haos_dingtalk_task = asyncio.create_task(replay()); return True
            except asyncio.CancelledError:
                await stop(); raise
            except PermissionError:
                await stop(); status('revoked'); raise
            except Exception:
                socket = self._haos_dingtalk_socket; kind = socket.failure if socket is not None else None
                await stop(); failure(kind); return False
    async def disconnect(self):
        async with lifecycle:
            await stop()
            row = health(self)
            if row['status'] not in BLOCKS | {'revoked', 'rate-limited', 'closed'} and row['next_attempt'] <= time.time():
                status('disconnected')
    async def close(self):
        async with lifecycle:
            if self._haos_dingtalk_closed:
                return
            self._haos_dingtalk_closed = True; await stop()
            if self._haos_dingtalk_publisher is not None:
                await self._haos_dingtalk_publisher.close()
            self._haos_dingtalk_raw.close(); os.close(lease)
            row = health(self)
            if row['status'] not in BLOCKS | {'rate-limited'} and row['next_attempt'] <= time.time():
                status('closed')
    async def send(self, chat_id, content, reply_to=None, metadata=None):
        from .gateway_delivery_authority import current_delivery
        if self._haos_dingtalk_publisher is None:
            raise PermissionError('creation-only DingTalk profile has no reply authority')
        async with lifecycle:
            current = current_delivery(self, 'dingtalk', chat_id, metadata)
            binding = native.policy().current_binding(metadata['haos_binding'])
            prepared = metadata.get('haos_output')
            if prepared is not None:
                if (not isinstance(prepared, dict) or set(prepared) != {'items', 'text'}
                        or prepared['items'] != [] or not isinstance(prepared['text'], str)):
                    raise PermissionError('DingTalk outbound media has no connected private capability')
                content = prepared['text']
            return await self._haos_dingtalk_publisher.send(binding, metadata.get('haos_delivery_id'),
                metadata.get('haos_delivery_attempt'), content, reply_to, current)
    adapter.connect = MethodType(connect, adapter); adapter.disconnect = MethodType(disconnect, adapter)
    adapter.close_profile = MethodType(close, adapter); adapter.native_health = MethodType(health, adapter)
    adapter.send = MethodType(send, adapter)
    return adapter
