"""Private LINE identity and explicitly configured HTTPS webhook lifecycle."""
import asyncio
import fcntl
import os
from pathlib import Path
import re
import stat
import time
from types import MethodType,SimpleNamespace

from .gateway import digest
from .gateway_line_ingress import snapshot,install,dispatch_stored,validate_binding

STATES=frozenset({'created','listening','listening-tls','disconnected','transport-unavailable','tls-refused','revoked','closed',
    'authentication-refused','identity-refused','rate-limited'})


def credentials(value,*,verify_tls=True):
    required={'channel_secret','channel_access_token','destination','port'}
    if not isinstance(value,dict) or set(value) not in (required,required|{'tls'}):
        raise ValueError('exact LINE channel credentials, bot destination and local port required')
    if (not isinstance(value['channel_secret'],str) or not re.fullmatch(r'[0-9a-f]{32}',value['channel_secret'])
            or not isinstance(value['channel_access_token'],str) or not 16<=len(value['channel_access_token'])<=8192
            or any(ord(c)<33 or ord(c)>126 for c in value['channel_access_token'])
            or not isinstance(value['destination'],str) or not re.fullmatch(r'U[0-9a-f]{32}',value['destination'])
            or type(value['port']) is not int or not 1024<=value['port']<=65535):
        raise ValueError('canonical private LINE identity and unprivileged loopback port required')
    result=dict(value)
    if 'tls' in result:
        from .gateway_line_tls import material
        result['tls']=material(result['tls'],verify=verify_tls)
    return result


def _directory(path):
    own=path.lstat()
    if path.resolve()!=path or not stat.S_ISDIR(own.st_mode) or own.st_uid!=os.geteuid() or own.st_mode&0o077:
        raise PermissionError('private canonical service-owned LINE directory required')


def build(value,parent,connector,policy,inbox):
    # Retained certificates can expire without taking other connectors down.
    # Actual activation validates system trust/time before any network access.
    value=credentials(value,verify_tls=False)
    def current():
        result=policy()
        authority=snapshot(result,connector,value['destination'])
        if not authority['bindings']:raise PermissionError('exact LINE owner grant required before profile use')
        for binding in result.bindings.values():
            if binding['connector']==connector:validate_binding(binding,require_epoch=True)
        if any(b['connector']==connector and b['scope']!=value['destination'] for b in result.bindings.values()):
            raise PermissionError('LINE profile cannot inherit grants for another bot identity')
        return result
    authority=snapshot(current(),connector,value['destination'])
    parent=Path(parent)
    if not parent.is_absolute():raise ValueError('absolute private LINE parent required')
    _directory(parent);profile=parent/digest([connector,value['destination']])
    try:profile.mkdir(mode=0o700)
    except FileExistsError:pass
    _directory(profile)
    fd=os.open(profile/'profile.lock',os.O_CREAT|os.O_RDWR|os.O_NOFOLLOW|os.O_NONBLOCK|os.O_CLOEXEC,0o600)
    try:
        own=os.fstat(fd)
        if not stat.S_ISREG(own.st_mode) or own.st_uid!=os.geteuid() or own.st_mode&0o077 or own.st_nlink!=1:
            raise PermissionError('private single-link LINE lease required')
        try:fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:raise PermissionError('LINE identity already active') from None
        home=profile/'home'
        try:home.mkdir(mode=0o700)
        except FileExistsError:pass
        _directory(home)
        from .gateway_matrix_profile import scope
        from .gateway_ingress import durable_adapter
        from .redaction import Redactor
        inbox.redactor=Redactor([*inbox.redactor.secrets,value['channel_secret'],value['channel_access_token'],
            *([value['tls']['private_key']] if 'tls' in value else [])])
        values={'LINE_CHANNEL_SECRET':value['channel_secret'],'LINE_CHANNEL_ACCESS_TOKEN':value['channel_access_token'],
            'LINE_ALLOW_ALL_USERS':'false','LINE_ALLOWED_USERS':'','LINE_ALLOWED_GROUPS':'','LINE_ALLOWED_ROOMS':''}
        os.environ['HERMES_SAFE_MODE']='1'
        with scope(home,values):
            from gateway.config import PlatformConfig
            from gateway.platform_registry import PlatformEntry
            from plugins.platforms.line import adapter as native
            class Context:
                def register_platform(self,**kwargs):self.entry=PlatformEntry(**kwargs)
            context=Context();native.register(context)
            if not context.entry.check_fn():raise RuntimeError('frozen LINE runtime requirements unavailable')
            adapter=install(durable_adapter(context.entry.adapter_factory(PlatformConfig(enabled=True,extra=value))))
            def pinned():
                result=current()
                if snapshot(result,connector,value['destination'])!=authority:
                    raise PermissionError('captured LINE profile grants changed')
                return result
            adapter._haos_native=SimpleNamespace(connector=connector,policy=pinned,inbox=inbox)
            publisher=None
            if any('read' in b['capabilities'] for b in current().bindings.values() if b['connector']==connector):
                from .gateway_line_delivery import Publisher
                publisher=Publisher(adapter)
        return _install(adapter,fd,profile,value,authority,publisher)
    except BaseException:os.close(fd);raise


def _install(adapter,fd,profile,value,authority,publisher):
    from .gateway_line_identity import Identity
    db=adapter._haos_native.inbox.db;connector=adapter._haos_native.connector
    credential_scope=digest([connector,value['channel_secret'],value['channel_access_token'],value['destination']])
    identity=digest([credential_scope,authority])
    db.execute('''CREATE TABLE IF NOT EXISTS line_profile_status(
        identity TEXT PRIMARY KEY,connector TEXT NOT NULL,credential_scope TEXT NOT NULL,status TEXT NOT NULL,
        updated_at REAL NOT NULL,next_attempt REAL NOT NULL)''')
    prior=db.execute('SELECT status,next_attempt FROM line_profile_status WHERE connector=? AND credential_scope=?',
        (connector,credential_scope)).fetchall()
    blocked=next((r['status'] for r in prior if r['status'] in {'authentication-refused','identity-refused'}),None)
    deadline=max([r['next_attempt'] for r in prior]+[0])
    db.execute('INSERT OR IGNORE INTO line_profile_status VALUES(?,?,?,?,?,?)',
        (identity,connector,credential_scope,blocked or 'created',time.time(),deadline))
    db.execute('UPDATE line_profile_status SET next_attempt=MAX(next_attempt,?),status=CASE WHEN ? THEN ? ELSE status END WHERE identity=?',
        (deadline,blocked is not None,blocked or 'created',identity))
    adapter._haos_line_profile=profile;adapter._haos_line_publisher=publisher
    adapter._haos_line_verified_destination=None
    adapter._haos_line_runner=None;adapter._haos_line_replay=None;adapter._haos_line_closed=False
    adapter._haos_line_identity=Identity(value['channel_access_token'],value['destination'])
    lifecycle=asyncio.Lock()
    def status(state,delay=0):db.execute('UPDATE line_profile_status SET status=?,updated_at=?,next_attempt=? WHERE identity=?',
        (state,time.time(),time.time()+delay if delay else 0,identity))
    def health(self):return dict(db.execute('SELECT connector,status,updated_at,next_attempt FROM line_profile_status WHERE identity=?',(identity,)).fetchone())
    def check():
        current=snapshot(adapter._haos_native.policy(),connector,value['destination'])
        if current!=authority:raise PermissionError('LINE owner publication changed')
        if (adapter.channel_secret!=value['channel_secret'] or adapter.channel_access_token!=value['channel_access_token']):
            raise PermissionError('LINE profile credentials changed')
    async def stop():
        task=adapter._haos_line_replay;adapter._haos_line_replay=None
        if task is not None and task is not asyncio.current_task():task.cancel();await asyncio.gather(task,return_exceptions=True)
        runner=adapter._haos_line_runner;adapter._haos_line_runner=None
        if runner is not None:await runner.cleanup()
        adapter._haos_line_verified_destination=None
        adapter._mark_disconnected()
    async def replay():
        try:
            while True:
                check();key=adapter._haos_native.inbox.due(connector)
                if key is not None:
                    try:
                        if publisher is None:await dispatch_stored(adapter,key)
                        else:
                            async with publisher.lock:check();await dispatch_stored(adapter,key)
                    except PermissionError:check()
                    except Exception:pass  # Persistent retry/expiry belong to NativeInbox.
                await asyncio.sleep(.2)
        except PermissionError:
            status('revoked')
            # Shut down incoming network without cancelling the worker itself.
            runner=adapter._haos_line_runner;adapter._haos_line_runner=None
            if runner is not None:await runner.cleanup()
            adapter._haos_line_verified_destination=None
            adapter._mark_disconnected()
    async def connect(self,**_kwargs):
        from aiohttp import web
        from .gateway_line_listener import application
        async with lifecycle:
            if self._haos_line_closed:raise PermissionError('LINE profile closed')
            await stop();check()
            health_row=health(self)
            if health_row['status'] in {'authentication-refused','identity-refused'} or health_row['next_attempt']>time.time():return False
            tls=None;host='127.0.0.1'
            if 'tls' in value:
                try:
                    from .gateway_line_tls import context
                    tls=context(value['tls'],profile);host=value['tls']['bind_host']
                except Exception:
                    status('tls-refused');return False
            verified,delay=await self._haos_line_identity.verify();check()
            if verified!='verified':status(verified,delay);return False
            runner=web.AppRunner(application(self,value['destination']),access_log=None,shutdown_timeout=5)
            self._haos_line_runner=runner
            try:
                await runner.setup()
                site=web.TCPSite(runner,host,value['port'],ssl_context=tls);await site.start();check()
                self._haos_line_verified_destination=value['destination'];self._mark_connected();status('listening-tls' if tls else 'listening')
                self._haos_line_replay=asyncio.create_task(replay());return True
            except asyncio.CancelledError:await stop();raise
            except PermissionError:await stop();status('revoked');raise
            except Exception:await stop();status('transport-unavailable');return False
    async def disconnect(self):
        async with lifecycle:
            await stop()
            if health(self)['status'] not in {'revoked','closed','authentication-refused','identity-refused','rate-limited','tls-refused'}:status('disconnected')
    async def send(self,chat_id,content,reply_to=None,metadata=None):
        from .gateway_delivery_authority import current_delivery
        if publisher is None:raise PermissionError('LINE creation-only profile has no outbound authority')
        current_delivery(self,'line',chat_id,metadata)()
        binding=self._haos_native.policy().current_binding(metadata['haos_binding'])
        return await publisher.send(binding,metadata.get('haos_delivery_id'),metadata.get('haos_delivery_attempt'),content)
    async def close(self):
        async with lifecycle:
            if self._haos_line_closed:return
            self._haos_line_closed=True;await stop()
            if publisher is not None:await publisher.close()
            await self._haos_line_identity.close()
            os.close(fd)
            if health(self)['status'] not in {'authentication-refused','identity-refused','rate-limited','tls-refused'}:status('closed')
    adapter.connect=MethodType(connect,adapter);adapter.disconnect=MethodType(disconnect,adapter)
    adapter.close_profile=MethodType(close,adapter);adapter.native_health=MethodType(health,adapter)
    adapter.send=MethodType(send,adapter)
    return adapter
