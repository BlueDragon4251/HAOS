"""Prepared private Photon profile; public registration waits for owner/output paths."""
import asyncio
import base64
import json
import os
from pathlib import Path
import secrets
import tempfile
import time
from types import MethodType, SimpleNamespace

from .gateway import Conflict, digest
from .gateway_photon import credentials, scope, checked_policy
from .gateway_photon_custody import Originals
from .gateway_photon_cursor import Cursor
from .gateway_photon_health import Ledger, TERMINAL
from .gateway_photon_control import PolicyServer
from .gateway_photon_process import Child, PROGRAMS


def build(value, *, parent, connector, policy, inbox):
    from .gateway_runtime import require_runtime_identity
    from .gateway_line_profile import _directory
    from .gateway_matrix_profile import acquire_lease, scope as native_scope
    from .redaction import Redactor
    require_runtime_identity(); value = credentials(value)
    def snapshot():
        selected = checked_policy(policy())
        if selected.connectors.get(connector, {}).get('platform') != 'photon':
            raise PermissionError('independent prepared Photon connector required')
        rows = [row for row in selected.bindings.values() if row['connector'] == connector]
        if not rows or any(row['scope'] != scope(value) or row['sender'] == value['phone'] for row in rows):
            raise PermissionError('exact independent Photon project, phone, sender/chat/thread grants required')
        return selected, digest([selected.publication, connector, sorted(rows, key=lambda row: row['id']), value])
    initial, identity = snapshot()
    def authority():
        selected, current = snapshot()
        if current != identity: raise PermissionError('Photon owner publication, account or grants changed')
        return selected
    parent = Path(parent); _directory(parent)
    profile = parent / ('photon-' + digest([value['project_id'], value['phone']]))
    try: profile.mkdir(mode=0o700)
    except FileExistsError: pass
    _directory(profile); lease = acquire_lease(profile); originals = None
    try:
        home = profile / 'home'
        try: home.mkdir(mode=0o700)
        except FileExistsError: pass
        _directory(home)
        basic = base64.b64encode((value['project_id'] + ':' + value['project_secret']).encode()).decode()
        inbox.redactor.secrets = Redactor([*inbox.redactor.secrets, value['project_secret'], basic, 'Basic ' + basic]).secrets
        environment = {'HERMES_SAFE_MODE': '1', 'PHOTON_PROJECT_ID': value['project_id'], 'PHOTON_PROJECT_SECRET': value['project_secret'],
            'PHOTON_NODE_BIN': str(PROGRAMS['node']), 'PHOTON_SIDECAR_AUTOSTART': 'false', 'PHOTON_MARKDOWN': 'false',
            'PHOTON_REQUIRE_MENTION': 'false', 'PHOTON_REACTIONS': 'false', 'PHOTON_ALLOW_ALL_USERS': 'false',
            'GATEWAY_ALLOW_ALL_USERS': 'false', 'PHOTON_ALLOWED_USERS': ','.join(sorted({row['sender'] for row in initial.bindings.values() if row['connector'] == connector}))}
        with native_scope(home, environment):
            from gateway.config import PlatformConfig
            from plugins.platforms.photon.adapter import PhotonAdapter
            from .gateway_ingress import durable_adapter
            adapter = durable_adapter(PhotonAdapter(PlatformConfig(enabled=True, extra={'require_mention': False})))
        adapter._haos_native = SimpleNamespace(connector=connector, policy=authority, inbox=inbox)
        adapter._haos_photon_value = value; adapter._haos_photon_closed = False; adapter._haos_photon_stopping = False
        def check():
            if adapter._haos_photon_closed or adapter._haos_photon_stopping: raise PermissionError('private Photon profile stopped')
            selected = authority()
            if (adapter._project_id != value['project_id'] or adapter._project_secret != value['project_secret']
                    or adapter.require_mention is not False or adapter._autostart_sidecar is not False):
                raise PermissionError('native Photon identity or guarded transport changed')
            return selected
        adapter._haos_photon_check = check
        originals = Originals(profile / 'originals.db', inbox.redactor, check); adapter._haos_photon_originals = originals
        adapter._haos_photon_cursor = Cursor(originals, value, authority)
        adapter._haos_photon_health = Ledger(inbox, connector, value, identity, authority)
        from .gateway_photon_codec import install
        install(adapter)
        return lifecycle(adapter, lease, home)
    except BaseException:
        if originals is not None: originals.close()
        os.close(lease); raise


def lifecycle(adapter, lease, home):
    from plugins.platforms.photon.adapter import PhotonAdapter
    from .gateway_photon_ingress import on_line, recover
    native = adapter._haos_native; value = adapter._haos_photon_value
    check = adapter._haos_photon_check; health = adapter._haos_photon_health; cursor = adapter._haos_photon_cursor
    serial = asyncio.Lock(); stopping = asyncio.Lock(); tasks = {}; resource = {'child': None, 'server': None, 'directory': None}
    async def stop(*, immediate=False):
        async with stopping:
            adapter._inbound_running = False
            current = asyncio.current_task(); pending = [task for task in tasks.values() if task is not current]
            for task in pending: task.cancel()
            if pending: await asyncio.gather(*pending, return_exceptions=True)
            tasks.clear()
            child = resource['child']; server = resource['server']
            if child is not None: await child.stop(immediate=immediate)
            if server is not None: await server.close()
            if adapter._http_client is not None:
                await adapter._http_client.aclose(); adapter._http_client = None
            directory = resource['directory']
            if directory is not None:
                try: directory.rmdir()  # Preserve any unrecognized recovery entry.
                except OSError: pass
            resource.update(child=None, server=None, directory=None)
            adapter._mark_disconnected()

    async def local_call(self, path, body):
        check()
        if path != '/healthz' or body != {} or self._http_client is None:
            raise PermissionError('native Photon write requires a dedicated one-shot output capability')
        from .gateway_dingtalk_admission import parse
        async with self._http_client.stream('POST', 'http://photon.invalid/healthz', json={}, headers=self._sidecar_headers(), timeout=3) as response:
            if response.status_code != 200: raise ConnectionError('private Photon control unavailable')
            content = bytearray()
            async for chunk in response.aiter_bytes():
                if len(content) + len(chunk) > 8192: raise Conflict('private Photon health response exceeds limit')
                content.extend(chunk)
        check(); return parse(bytes(content))

    async def monitor():
        next_health = 0
        while True:
            try: check()
            except PermissionError:
                health.update('revoked'); adapter._haos_photon_stopping = True; await stop(immediate=True); return
            if cursor.status()['state'] == 'cursor-refused':
                health.update('cursor-refused'); await stop(immediate=True); return
            if health.recorded()['status'] in TERMINAL or not health.permitted():
                await stop(immediate=True); return
            child = resource['child']
            if child is None or child.pid is None:
                health.update('transport-unavailable', 2); await stop(immediate=True); return
            if time.monotonic() >= next_health:
                try:
                    observed = await adapter._sidecar_call('/healthz', {})
                    stream = observed.get('stream')
                    if not isinstance(stream, dict) or stream.get('ok') is False: raise ConnectionError('native Photon stream degraded')
                except asyncio.CancelledError: raise
                except Exception:
                    health.update('transport-unavailable', 2); await stop(immediate=True); return
                next_health = time.monotonic() + 3
            await asyncio.sleep(.1)

    async def replay():
        while True:
            check()
            try: await recover(adapter)
            except asyncio.CancelledError: raise
            except PermissionError:
                check(); health.update('source-unavailable')
            except (Conflict, OSError, ValueError):
                check(); health.update('source-unavailable')
            await asyncio.sleep(.5)

    async def connect(self):
        async with serial:
            if self._haos_photon_closed: raise PermissionError('Photon profile closed')
            if tasks: return self.is_connected
            if not health.permitted() or cursor.status()['state'] == 'cursor-refused': return False
            self._haos_photon_stopping = False; check(); health.update('connecting')
            try:
                directory = Path(tempfile.mkdtemp(prefix='hp-', dir='/tmp')); resource['directory'] = directory
                token = secrets.token_hex(32); self._sidecar_token = token
                child = Child(value, home, directory / 'policy.sock', directory / 'control.sock', token, check); resource['child'] = child
                server = PolicyServer(directory / 'policy.sock', token, child_pid=lambda: child.pid, connector=native.connector,
                    value=value, policy=native.policy, originals=self._haos_photon_originals, current=check, cursor=cursor, health=health)
                resource['server'] = server
                await server.start(); await child.start(); check()
                import httpx
                self._http_client = httpx.AsyncClient(transport=httpx.AsyncHTTPTransport(uds=str(directory / 'control.sock')),
                    trust_env=False, follow_redirects=False, timeout=5)
                self._inbound_running = True; health.update('local-ready'); self._mark_connected()
                tasks.update(receive=asyncio.create_task(PhotonAdapter._inbound_loop(self)),
                    monitor=asyncio.create_task(monitor()), replay=asyncio.create_task(replay()))
                return True
            except asyncio.CancelledError: await stop(immediate=True); raise
            except Exception:
                await stop(immediate=True)
                try: check(); health.update('transport-unavailable', 2)
                except PermissionError: health.update('revoked')
                return False

    async def disconnect(self):
        self._haos_photon_stopping = True
        async with serial:
            await stop()
            try: health.update('disconnected')
            except PermissionError: health.update('revoked')

    async def close(self):
        async with serial:
            if self._haos_photon_closed: return
            self._haos_photon_stopping = True; await stop(immediate=True)
            try: health.update('closed')
            except PermissionError: health.update('revoked')
            self._haos_photon_closed = True; self._haos_photon_originals.close(); os.close(lease)

    async def inbound(self, line): return await on_line(self, line)
    async def no_output(self, *args, **kwargs):
        raise PermissionError('Photon output requires the guarded native publisher; public activation is not enabled')
    for name, method in [('connect', connect), ('disconnect', disconnect), ('close', close), ('_on_inbound_line', inbound),
            ('_sidecar_call', local_call), ('send', no_output)]: setattr(adapter, name, MethodType(method, adapter))
    adapter._sidecar_url = lambda path: 'http://photon.invalid' + path
    return adapter
