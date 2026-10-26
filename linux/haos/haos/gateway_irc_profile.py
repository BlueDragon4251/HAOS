"""Prepared private IRC identity, persistent recovery and bounded reconnect."""
import asyncio
import fcntl
import os
from pathlib import Path
import stat
import time
from types import MethodType,SimpleNamespace

from .gateway import digest
from .gateway_irc_ingress import PreparedIRCPolicy,install as install_ingress,snapshot,dispatch_stored
from .gateway_irc_transport import credentials,install as install_transport,AuthenticationRejected,RateLimited

STATES=frozenset({'created','connecting','streaming','disconnected','authentication-refused',
    'transport-unavailable','rate-limited','revoked','closed'})


def _directory(path):
    own=path.lstat()
    if (path.resolve()!=path or not stat.S_ISDIR(own.st_mode) or own.st_uid!=os.geteuid() or own.st_mode&0o077):
        raise PermissionError('canonical private service-owned IRC directory required')


def build(value,parent,connector,policy,inbox):
    value=credentials(value);server=f"{value['server']}:{value['port']}"
    def current():
        result=policy()
        if not isinstance(result,PreparedIRCPolicy) or not snapshot(result,connector,server)['bindings']:
            raise PermissionError('prepared exact IRC account grants required')
        return result
    authority=snapshot(current(),connector,server)
    parent=Path(parent)
    if not parent.is_absolute():raise ValueError('absolute private IRC parent required')
    _directory(parent)
    profile=parent/digest([server,connector,value['nickname']])
    try:profile.mkdir(mode=0o700)
    except FileExistsError:pass
    _directory(profile)
    fd=os.open(profile/'profile.lock',os.O_CREAT|os.O_RDWR|os.O_NOFOLLOW|os.O_NONBLOCK|os.O_CLOEXEC,0o600)
    try:
        own=os.fstat(fd)
        if not stat.S_ISREG(own.st_mode) or own.st_uid!=os.geteuid() or own.st_mode&0o077 or own.st_nlink!=1:
            raise PermissionError('private single-link IRC kernel lease required')
        try:fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:raise PermissionError('IRC identity profile already active') from None
        home=profile/'home'
        try:home.mkdir(mode=0o700)
        except FileExistsError:pass
        _directory(home)
        os.environ['HERMES_SAFE_MODE']='1'
        from .gateway_matrix_profile import scope
        from .gateway_ingress import durable_adapter
        values={'IRC_SERVER':value['server'],'IRC_PORT':str(value['port']),'IRC_NICKNAME':value['nickname'],
            'IRC_CHANNEL':value['channel'],'IRC_USE_TLS':'true','IRC_SERVER_PASSWORD':value.get('server_password',''),
            'IRC_NICKSERV_PASSWORD':''}
        with scope(home,values):
            from gateway.config import PlatformConfig
            from gateway.platform_registry import PlatformEntry
            from plugins.platforms.irc import adapter as native
            class Context:
                def register_platform(self,**kwargs):self.entry=PlatformEntry(**kwargs)
            context=Context();native.register(context)
            if not context.entry.check_fn():raise RuntimeError('frozen IRC adapter requirements unavailable')
            adapter=install_ingress(durable_adapter(context.entry.adapter_factory(PlatformConfig(enabled=True,extra=value))))
            adapter._haos_native=SimpleNamespace(connector=connector,policy=current,inbox=inbox)
            boundary=install_transport(adapter,value)
        # Nick/channel/owner epochs are not new server accounts.
        credential_scope=digest([connector,server,value.get('server_password',''),
            value.get('sasl_username',''),value.get('sasl_password','')])
        identity=digest([credential_scope,authority])
        return _install(adapter,boundary,fd,profile,values,identity,credential_scope)
    except BaseException:os.close(fd);raise


def _install(adapter,boundary,fd,profile,values,identity,credential_scope):
    from .gateway_matrix_profile import scope
    db=adapter._haos_native.inbox.db
    connector=adapter._haos_native.connector
    db.execute('''CREATE TABLE IF NOT EXISTS irc_profile_status (
        identity TEXT PRIMARY KEY, connector TEXT NOT NULL, status TEXT NOT NULL,
        updated_at REAL NOT NULL, next_attempt REAL NOT NULL, gap_since REAL NOT NULL,
        credential_scope TEXT NOT NULL)''')
    prior=db.execute('SELECT status,next_attempt,gap_since FROM irc_profile_status WHERE connector=? AND credential_scope=?',
        (connector,credential_scope)).fetchall()
    blocked=any(row['status']=='authentication-refused' for row in prior)
    deadline=max([row['next_attempt'] for row in prior]+[0])
    gap=min([row['gap_since'] for row in prior if row['gap_since']>0]+
        [min(b['since'] for b in adapter._haos_native.policy().bindings.values() if b['connector']==connector)/1000])
    db.execute('INSERT OR IGNORE INTO irc_profile_status VALUES(?,?,?,?,?,?,?)',
        (identity,connector,'authentication-refused' if blocked else 'created',time.time(),deadline,gap,credential_scope))
    db.execute('UPDATE irc_profile_status SET status=CASE WHEN ? THEN ? ELSE status END,'
        'next_attempt=MAX(next_attempt,?),gap_since=CASE WHEN gap_since=0 THEN ? ELSE MIN(gap_since,?) END WHERE identity=?',
        (blocked,'authentication-refused',deadline,gap,gap,identity))
    adapter._haos_irc_profile=profile
    adapter._haos_irc_worker=None;adapter._haos_irc_replay=None
    adapter._haos_irc_closed=False;adapter._haos_irc_connect_task=None
    adapter._haos_irc_retry_steps=(5,10,30,60)
    close_lock=asyncio.Lock()

    def health(self):
        return dict(db.execute('SELECT connector,status,updated_at,next_attempt,gap_since FROM irc_profile_status WHERE identity=?',
            (identity,)).fetchone())

    def status(kind,delay=0):
        if kind not in STATES:raise ValueError('invalid safe IRC profile status')
        db.execute('UPDATE irc_profile_status SET status=?,updated_at=?,next_attempt=? WHERE identity=?',
            (kind,time.time(),time.time()+delay if delay else 0,identity))

    async def replay():
        try:
            while True:
                boundary.current()
                key=adapter._haos_native.inbox.due(connector)
                if key is not None:
                    try:await dispatch_stored(adapter,key)
                    except PermissionError:boundary.current()
                    except Exception:pass  # The journal retains bounded retry and expiry.
                await asyncio.sleep(.2)
        except PermissionError:pass

    async def run():
        failures=0
        try:
            while True:
                boundary.current();row=health(adapter)
                if row['status']=='authentication-refused':return
                if row['next_attempt']>time.time():await asyncio.sleep(row['next_attempt']-time.time())
                boundary.current();status('connecting')
                try:
                    with scope(profile/'home',values):
                        await boundary.connect();status('streaming');failures=0
                        await boundary.receive()
                except AuthenticationRejected:status('authentication-refused');return
                except RateLimited as error:status('rate-limited',error.retry_after);continue
                except PermissionError:raise
                except Exception:pass
                finally:await boundary.disconnect()
                delay=adapter._haos_irc_retry_steps[min(failures,len(adapter._haos_irc_retry_steps)-1)]
                failures+=1;status('transport-unavailable',delay)
        except PermissionError:status('revoked')
        finally:adapter._mark_disconnected();await boundary.disconnect()

    async def disconnect(self):
        self._mark_disconnected()
        tasks=[task for task in (self._haos_irc_worker,self._haos_irc_replay) if task is not None]
        for task in tasks:task.cancel()
        await asyncio.gather(*tasks,return_exceptions=True)
        self._haos_irc_worker=None;self._haos_irc_replay=None
        await boundary.disconnect()
        row=health(self)
        if row['status'] not in {'authentication-refused','revoked','closed'}:
            status('disconnected',max(0,row['next_attempt']-time.time()))

    async def connect(self,**_kwargs):
        if self._haos_irc_closed or self._haos_irc_connect_task is not None:
            raise PermissionError('IRC profile closed or already connecting')
        self._haos_irc_connect_task=asyncio.current_task()
        try:
            await disconnect(self);boundary.current()
            if health(self)['status'] in {'authentication-refused','revoked'}:return False
            with scope(profile/'home',values):
                self._haos_irc_worker=asyncio.create_task(run())
                self._haos_irc_replay=asyncio.create_task(replay())
            async with asyncio.timeout(45):
                while not self.is_connected:
                    if self._haos_irc_worker.done():
                        await self._haos_irc_worker;await disconnect(self);return False
                    await asyncio.sleep(.05)
            return True
        except asyncio.CancelledError:await disconnect(self);raise
        except Exception:await disconnect(self);return False
        finally:self._haos_irc_connect_task=None

    async def close(self):
        async with close_lock:
            if self._haos_irc_closed:return
            self._haos_irc_closed=True
            task=self._haos_irc_connect_task
            if task is not None and task is not asyncio.current_task():
                task.cancel();await asyncio.gather(task,return_exceptions=True)
            try:await disconnect(self)
            finally:
                boundary.closed=True
                try:
                    row=health(self)
                    if row['status'] not in {'authentication-refused','revoked'}:
                        status('closed',max(0,row['next_attempt']-time.time()))
                finally:os.close(fd)

    def no_global_status(self,*_args,**_kwargs):return None
    for name,method in {'connect':connect,'disconnect':disconnect,'close_profile':close,'irc_status':health,
            '_write_runtime_status_safe':no_global_status}.items():setattr(adapter,name,MethodType(method,adapter))
    return adapter
