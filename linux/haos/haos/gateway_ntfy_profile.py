"""Prepared isolated ntfy lifecycle; explicit factory, no public/plugin discovery."""
import asyncio
import fcntl
import os
from pathlib import Path
import stat
import time
from types import MethodType, SimpleNamespace

from .gateway import digest
from .gateway_ntfy import PreparedNtfyPolicy, _TOPIC, _EVENT, install
from .gateway_ntfy_transport import Subscription
from .gateway_ntfy_delivery import Publisher

STATES = frozenset({'created','connecting','ready','streaming','disconnected','authentication-denied',
    'source-unavailable','rate-limited','transport-unavailable','invalid-stream','revoked','closed'})


def credentials(value):
    from .gateway_mattermost import server_url
    if not isinstance(value, dict) or set(value) != {'token','server_url','topic'}:
        raise ValueError('ntfy requires a private token, exact HTTPS server and exact private topic')
    result = dict(value)
    try: result['server_url'] = server_url(value['server_url'])
    except ValueError: raise ValueError('provide an exact ntfy HTTPS server without embedded credentials') from None
    if (not isinstance(value['topic'],str) or not _TOPIC.fullmatch(value['topic'])
            or not isinstance(value['token'],str) or not 1 <= len(value['token']) <= 8192
            or any(ord(c)<33 or ord(c)>126 for c in value['token'])):
        raise ValueError('provide one bounded private ntfy credential and literal topic')
    return result


def _directory(path):
    info = path.lstat()
    if (path.resolve() != path or not stat.S_ISDIR(info.st_mode)
            or info.st_uid != os.geteuid() or info.st_mode & 0o077):
        raise PermissionError('ntfy profile directory must be canonical and private to this service')


def build(value, parent, connector, policy, inbox):
    value = credentials(value)
    def current():
        result = policy()
        if not isinstance(result, PreparedNtfyPolicy) or result.connectors.get(connector,{}).get('platform') != 'ntfy':
            raise PermissionError('ntfy profile requires exact independent prepared owner authority')
        return result
    current()
    parent = Path(parent)
    if not parent.is_absolute(): raise ValueError('absolute ntfy private profile parent required')
    _directory(parent)
    profile = parent/digest([value['server_url'],value['topic']])
    try: profile.mkdir(mode=0o700)
    except FileExistsError: pass
    _directory(profile)
    fd = os.open(profile/'profile.lock',os.O_CREAT|os.O_RDWR|os.O_NOFOLLOW|os.O_NONBLOCK|os.O_CLOEXEC,0o600)
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid() or info.st_mode&0o077 or info.st_nlink != 1:
            raise PermissionError('private single-link ntfy identity lease required')
        try: fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError: raise PermissionError('ntfy topic profile is already active') from None
        home = profile/'home'
        try: home.mkdir(mode=0o700)
        except FileExistsError: pass
        _directory(home)
        os.environ['HERMES_SAFE_MODE']='1'
        # Fixed reviewed bundle only. No plugin manager or root SDK setup path.
        from .gateway_matrix_profile import scope
        from .gateway_ingress import durable_adapter
        values={'NTFY_TOPIC':value['topic'],'NTFY_SERVER_URL':value['server_url'],'NTFY_TOKEN':value['token'],
            'NTFY_PUBLISH_TOPIC':value['topic'],'NTFY_ALLOWED_USERS':'','NTFY_ALLOW_ALL_USERS':'false'}
        class Context:
            def register_platform(self,**kwargs): self.entry=PlatformEntry(**kwargs)
        with scope(home,values):
            from gateway.config import PlatformConfig
            from gateway.platform_registry import PlatformEntry
            from plugins.platforms.ntfy import adapter as native
            context=Context(); native.register(context)
            if not context.entry.check_fn(): raise RuntimeError('frozen ntfy messaging dependencies unavailable')
            adapter=install(durable_adapter(context.entry.adapter_factory(PlatformConfig(enabled=True,extra={
                'server':value['server_url'],'topic':value['topic'],'publish_topic':value['topic'],
                'token':value['token'],'markdown':False}))))
        adapter._haos_native=SimpleNamespace(connector=connector,policy=current,inbox=inbox)
        return _install(adapter,fd,profile,values)
    except BaseException:
        os.close(fd); raise


def _install(adapter,fd,profile,values):
    from .gateway_matrix_profile import scope
    db=adapter._haos_native.inbox.db
    db.execute('''CREATE TABLE IF NOT EXISTS ntfy_profile_status (
        connector TEXT PRIMARY KEY, status TEXT NOT NULL, last_error TEXT NOT NULL,
        updated_at REAL NOT NULL, next_attempt REAL NOT NULL)''')
    adapter._haos_ntfy_profile=profile
    adapter._haos_ntfy_subscription=None
    adapter._haos_ntfy_worker=None
    adapter._haos_ntfy_profile_closed=False
    adapter._haos_ntfy_connect_task=None
    close_lock=asyncio.Lock()

    def status(kind):
        if kind not in STATES: raise ValueError('invalid safe ntfy status')
        sub=adapter._haos_ntfy_subscription
        deadline=sub.state()['next_attempt'] if sub is not None else 0
        error=kind if kind in {'authentication-denied','source-unavailable','rate-limited','transport-unavailable','invalid-stream','revoked'} else ''
        db.execute('INSERT INTO ntfy_profile_status VALUES(?,?,?,?,?) ON CONFLICT(connector) DO UPDATE SET '
            'status=excluded.status,updated_at=excluded.updated_at,next_attempt=excluded.next_attempt,'
            "last_error=CASE WHEN excluded.status='streaming' THEN '' WHEN excluded.last_error!='' THEN excluded.last_error ELSE ntfy_profile_status.last_error END",
            (adapter._haos_native.connector,kind,error,time.time(),deadline))

    def native_status(_self,_context,**_fields):
        # Native's global asynchronous status writer cannot retain private HOME.
        # Real status is persisted synchronously in this service-owned inbox.
        return None

    def transport_status(self,kind):
        status(kind)
        if kind=='streaming': self._mark_connected()
        else: self._mark_disconnected()

    def health(self):
        return dict(db.execute('SELECT * FROM ntfy_profile_status WHERE connector=?',
            (self._haos_native.connector,)).fetchone())

    async def send(self,chat,content,reply_to=None,metadata=None):
        if self._haos_ntfy_profile_closed or not self.is_connected:
            raise PermissionError('private ntfy profile is not connected')
        if (not isinstance(metadata,dict) or set(metadata)!={'haos_scope','thread_id','haos_binding'}
                or metadata['haos_scope'] or metadata['thread_id']
                or not isinstance(metadata['haos_binding'],dict) or set(metadata['haos_binding'])!={'binding_id','binding_digest'}
                or reply_to is not None and (not isinstance(reply_to,str) or not _EVENT.fullmatch(reply_to))):
            raise PermissionError('exact current ntfy owner delivery metadata required')
        binding=self._haos_native.policy().current_binding(metadata['haos_binding'])
        if chat!=binding['chat']: raise PermissionError('ntfy reply destination differs from retained route')
        with scope(profile/'home',values):
            return await self._haos_ntfy_publisher.send(binding,content)

    async def disconnect(self):
        sub=self._haos_ntfy_subscription
        try:
            if sub is not None: await sub.close()
            task=self._haos_ntfy_worker
            if task is not None:
                task.cancel(); await asyncio.gather(task,return_exceptions=True)
        finally:
            try:
                publisher=getattr(self,'_haos_ntfy_publisher',None)
                if publisher is not None: await publisher.aclose()
            finally:
                self._mark_disconnected()
                self._haos_ntfy_worker=None
                status('disconnected')

    async def connect(self,**_kwargs):
        if self._haos_ntfy_profile_closed or self._haos_ntfy_connect_task is not None:
            raise PermissionError('ntfy private profile is closed or already connecting')
        self._haos_ntfy_connect_task=asyncio.current_task()
        try:
            await disconnect(self)
            status('connecting')
            with scope(profile/'home',values):
                sub=self._haos_ntfy_subscription=Subscription(self)
                Publisher(self)
                self.send=MethodType(send,self)
                self._haos_ntfy_worker=asyncio.create_task(sub.run())
            async with asyncio.timeout(45):
                while not self.is_connected:
                    if self._haos_ntfy_worker.done():
                        await self._haos_ntfy_worker
                        await disconnect(self)
                        return False
                    await asyncio.sleep(.05)
            return True
        except asyncio.CancelledError:
            await disconnect(self); raise
        except PermissionError:
            status('revoked')
            await disconnect(self); return False
        except Exception:
            status('transport-unavailable')
            await disconnect(self); return False
        finally: self._haos_ntfy_connect_task=None

    async def close(self):
        async with close_lock:
            if self._haos_ntfy_profile_closed: return
            self._haos_ntfy_profile_closed=True
            task=self._haos_ntfy_connect_task
            if task is not None and task is not asyncio.current_task():
                task.cancel(); await asyncio.gather(task,return_exceptions=True)
            try: await disconnect(self)
            finally:
                try: status('closed')
                finally: os.close(fd)

    for name,method in {'connect':connect,'disconnect':disconnect,'send':send,'close_profile':close,
            '_write_runtime_status_safe':native_status,'_haos_ntfy_transport_status':transport_status,'ntfy_status':health}.items():
        setattr(adapter,name,MethodType(method,adapter))
    status('created')
    return adapter
