"""Prepared isolated HA lifecycle. No public setup or history authority implied."""
import asyncio
import fcntl
import hashlib
import os
from pathlib import Path
import stat
import time
from types import MethodType, SimpleNamespace

from .gateway import digest
from .gateway_homeassistant_ingress import PreparedHomeAssistantPolicy, install, dispatch_stored, snapshot
from .gateway_homeassistant_transport import install as install_transport
from .gateway_homeassistant_delivery import Publisher

PROFILE_STATES=frozenset({'created','connecting','streaming','disconnected','authentication-refused',
    'transport-unavailable','rate-limited','revoked','closed'})


def credentials(value):
    from .gateway_mattermost import server_url
    if not isinstance(value,dict) or set(value)!={'server_url','token'}:
        raise ValueError('exact private HTTPS Home Assistant URL and token required')
    token=value['token']
    if not isinstance(token,str) or not 1<=len(token)<=8192 or any(ord(c)<33 or ord(c)>126 for c in token):
        raise ValueError('bounded private Home Assistant bearer token required')
    return {'server_url':server_url(value['server_url']),'token':token}


def _directory(path):
    info=path.lstat()
    if (path.resolve()!=path or not stat.S_ISDIR(info.st_mode)
            or info.st_uid!=os.geteuid() or info.st_mode&0o077):
        raise PermissionError('canonical private service-owned Home Assistant directory required')


def build(value,parent,connector,policy,inbox):
    value=credentials(value)
    def current():
        result=policy()
        if not isinstance(result,PreparedHomeAssistantPolicy):
            raise PermissionError('prepared independent Home Assistant authority required')
        if not snapshot(result,connector)['bindings']:
            raise PermissionError('exact user/entity owner grant required before profile creation')
        return result
    authority=snapshot(current(),connector)
    parent=Path(parent)
    if not parent.is_absolute():raise ValueError('absolute private Home Assistant parent required')
    _directory(parent)
    profile=parent/digest([value['server_url'],connector])
    try:profile.mkdir(mode=0o700)
    except FileExistsError:pass
    _directory(profile)
    fd=os.open(profile/'profile.lock',os.O_CREAT|os.O_RDWR|os.O_NOFOLLOW|os.O_NONBLOCK|os.O_CLOEXEC,0o600)
    try:
        info=os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_uid!=os.geteuid() or info.st_mode&0o077 or info.st_nlink!=1:
            raise PermissionError('private single-link Home Assistant lease required')
        try:fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:raise PermissionError('Home Assistant profile already active') from None
        home=profile/'home'
        try:home.mkdir(mode=0o700)
        except FileExistsError:pass
        _directory(home)
        os.environ['HERMES_SAFE_MODE']='1'
        from .gateway_matrix_profile import scope
        from .gateway_ingress import durable_adapter
        values={'HASS_URL':value['server_url'],'HASS_TOKEN':value['token']}
        with scope(home,values):
            from gateway.config import PlatformConfig
            from gateway.platform_registry import PlatformEntry
            from plugins.platforms.homeassistant import adapter as native
            class Context:
                def register_platform(self,**kwargs):self.entry=PlatformEntry(**kwargs)
            context=Context();native.register(context)
            if not context.entry.check_fn():raise RuntimeError('frozen Home Assistant messaging dependencies unavailable')
            entities=sorted({b['chat'] for b in current().bindings.values() if b['connector']==connector})
            adapter=install(durable_adapter(context.entry.adapter_factory(PlatformConfig(enabled=True,token=value['token'],
                extra={'url':value['server_url'],'watch_entities':entities,'watch_all':False,'cooldown_seconds':0}))))
            adapter._haos_native=SimpleNamespace(connector=connector,policy=current,inbox=inbox)
            install_transport(adapter)
        identity=digest([value['server_url'],connector,authority,hashlib.sha256(value['token'].encode()).hexdigest()])
        return _install(adapter,fd,profile,values,identity)
    except BaseException:os.close(fd);raise


def _install(adapter,fd,profile,values,identity):
    from .gateway_matrix_profile import scope
    boundary=adapter._haos_ha_transport
    db=adapter._haos_native.inbox.db
    db.execute('''CREATE TABLE IF NOT EXISTS homeassistant_profile_status (
        identity TEXT PRIMARY KEY, connector TEXT NOT NULL, status TEXT NOT NULL,
        updated_at REAL NOT NULL, next_attempt REAL NOT NULL, gap_since REAL NOT NULL)''')
    existed=db.execute('SELECT 1 FROM homeassistant_profile_status WHERE identity=?',(identity,)).fetchone()
    db.execute('INSERT OR IGNORE INTO homeassistant_profile_status VALUES(?,?,?,?,?,?)',
        (identity,adapter._haos_native.connector,'created',time.time(),0,
         min(b['since'] for b in adapter._haos_native.policy().bindings.values()
             if b['connector']==adapter._haos_native.connector)/1000))
    if existed:
        db.execute('UPDATE homeassistant_profile_status SET gap_since=CASE WHEN gap_since=0 THEN ? ELSE gap_since END WHERE identity=?',
            (time.time(),identity))
    adapter._haos_ha_profile=profile
    adapter._haos_ha_worker=None;adapter._haos_ha_replay=None;adapter._haos_ha_publisher=None
    adapter._haos_ha_closed=False;adapter._haos_ha_connect_task=None
    adapter._haos_ha_retry_steps=(5,10,30,60)
    close_lock=asyncio.Lock()

    def native_status(_self,*_args,**_kwargs):
        # Native global/asynchronous status cannot carry this private identity.
        # The service-owned inbox below is the sole profile status authority.
        return None

    def status(kind,delay=0,gap=False):
        if kind not in PROFILE_STATES:raise ValueError('invalid safe Home Assistant profile status')
        db.execute('UPDATE homeassistant_profile_status SET status=?,updated_at=?,next_attempt=?, '
            'gap_since=CASE WHEN ? AND gap_since=0 THEN ? ELSE gap_since END WHERE identity=?',
            (kind,time.time(),time.time()+delay if delay else 0,gap,time.time(),identity))

    def health(self):
        return dict(db.execute('SELECT connector,status,updated_at,next_attempt,gap_since FROM homeassistant_profile_status WHERE identity=?',
            (identity,)).fetchone())

    async def recover():
        try:
            while True:
                boundary.current()
                key=adapter._haos_native.inbox.due(adapter._haos_native.connector)
                if key is not None:
                    try:await dispatch_stored(adapter,key)
                    except PermissionError:boundary.current()
                    except Exception:pass  # Journal retains its bounded retry deadline.
                await asyncio.sleep(.2)
        except PermissionError:
            status('revoked',gap=True)
            worker=adapter._haos_ha_worker
            if worker is not None:worker.cancel()

    async def run():
        failures=0
        try:
            while True:
                boundary.current()
                row=health(adapter)
                if row['status']=='authentication-refused':return
                if row['next_attempt']>time.time():await asyncio.sleep(row['next_attempt']-time.time())
                boundary.current();status('connecting')
                if await adapter._ws_connect():
                    adapter._mark_connected();status('streaming');failures=0
                    try:await adapter._read_events()
                    except PermissionError:boundary.current()
                    except Exception:pass
                    finally:adapter._mark_disconnected();await adapter._cleanup_ws()
                    status('disconnected',gap=True)
                else:
                    adapter._mark_disconnected()
                    if boundary.status=='authentication-refused':status('authentication-refused',gap=True);return
                    if boundary.status=='rate-limited':
                        status('rate-limited',boundary.retry_after,gap=True);continue
                delay=adapter._haos_ha_retry_steps[min(failures,len(adapter._haos_ha_retry_steps)-1)]
                failures+=1;status('transport-unavailable',delay,gap=True)
        except PermissionError:status('revoked',gap=True)
        finally:adapter._mark_disconnected();await adapter._cleanup_ws()

    async def send(self,chat,content,reply_to=None,metadata=None):
        if self._haos_ha_closed or not self.is_connected:raise PermissionError('Home Assistant profile not connected')
        boundary.require_ready()
        if (not isinstance(metadata,dict) or not {'haos_scope','haos_binding','haos_delivery_id'}<=set(metadata)
                or set(metadata)-{'haos_scope','haos_binding','haos_delivery_id','thread_id','notify'}
                or metadata['haos_scope'] or metadata.get('thread_id','') or metadata.get('notify',True) is not True
                or not isinstance(metadata['haos_binding'],dict)
                or set(metadata['haos_binding'])!={'binding_id','binding_digest'}
                or reply_to is not None and (not isinstance(reply_to,str) or len(reply_to)!=64
                    or any(c not in '0123456789abcdef' for c in reply_to))):
            raise PermissionError('exact Home Assistant outbox capability required')
        binding=self._haos_native.policy().current_binding(metadata['haos_binding'])
        if chat!=binding['chat']:raise PermissionError('Home Assistant notification route changed')
        with scope(profile/'home',values):
            return await self._haos_ha_publisher.send(binding,metadata['haos_delivery_id'],content)

    async def disconnect(self):
        self._mark_disconnected()
        tasks=[task for task in [self._haos_ha_worker,self._haos_ha_replay] if task is not None]
        for task in tasks:task.cancel()
        if tasks:await asyncio.gather(*tasks,return_exceptions=True)
        self._haos_ha_worker=None;self._haos_ha_replay=None
        try:await self._cleanup_ws()
        finally:
            publisher=self._haos_ha_publisher;self._haos_ha_publisher=None
            if publisher is not None:await publisher.close()
        row=health(self)
        if row['status'] not in {'authentication-refused','revoked','closed'}:
            status('disconnected',max(0,row['next_attempt']-time.time()),gap=True)

    async def connect(self,**_kwargs):
        if self._haos_ha_closed or self._haos_ha_connect_task is not None:
            raise PermissionError('Home Assistant profile closed or already connecting')
        self._haos_ha_connect_task=asyncio.current_task()
        try:
            await disconnect(self)
            boundary.current()
            if health(self)['status'] in {'authentication-refused','revoked'}:return False
            with scope(profile/'home',values):
                self._haos_ha_publisher=Publisher(self)
                self.send=MethodType(send,self)
                self._haos_ha_worker=asyncio.create_task(run())
                self._haos_ha_replay=asyncio.create_task(recover())
            async with asyncio.timeout(45):
                while not self.is_connected:
                    if self._haos_ha_worker.done():
                        await self._haos_ha_worker;await disconnect(self);return False
                    await asyncio.sleep(.05)
            return True
        except asyncio.CancelledError:await disconnect(self);raise
        except Exception:
            await disconnect(self);return False
        finally:self._haos_ha_connect_task=None

    async def close(self):
        async with close_lock:
            if self._haos_ha_closed:return
            self._haos_ha_closed=True
            task=self._haos_ha_connect_task
            if task is not None and task is not asyncio.current_task():
                task.cancel();await asyncio.gather(task,return_exceptions=True)
            try:await disconnect(self)
            finally:
                try:await boundary.close()
                finally:
                    try:
                        row=health(self)
                        if row['status'] not in {'authentication-refused','revoked'}:
                            status('closed',max(0,row['next_attempt']-time.time()),gap=True)
                    finally:os.close(fd)

    for name,method in {'connect':connect,'disconnect':disconnect,'close_profile':close,'send':send,'homeassistant_status':health,
            '_write_runtime_status_safe':native_status}.items():
        setattr(adapter,name,MethodType(method,adapter))
    return adapter
