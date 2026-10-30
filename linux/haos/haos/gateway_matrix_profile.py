"""Private Matrix profile lifecycle for the owner-approved native service."""
import asyncio
from contextlib import contextmanager
import fcntl
import math
import os
from pathlib import Path
import stat
import time
from types import MethodType,SimpleNamespace

from .gateway import GatewayPolicy,digest
from .gateway_matrix import private_store,protect_crypto
from .gateway_matrix_http import homeserver_url
from .gateway_matrix_policy import opaque,snapshot
from .gateway_matrix_sync import SyncJournal,DeferredDispatch,receive_sync,dispatch_page

PROFILE_STATES=frozenset({'created','connecting','connected','decode-pending','rate-limited','authentication-refused',
    'identity-refused','transport-unavailable','policy-unavailable','disconnected','closed'})


def credentials(value):
    required={'token','homeserver','user_id','device_id'}
    if not isinstance(value,dict) or not required<=set(value)<=required|{'recovery_key'}:
        raise ValueError('explicit Matrix token, HTTPS homeserver, user and stable device required')
    result=dict(value);result['homeserver']=homeserver_url(value['homeserver'])
    if (not isinstance(value['token'],str) or not 1<=len(value['token'])<=8192
            or any(ord(c)<33 or ord(c)>126 for c in value['token'])
            or not opaque(value['user_id'],'@') or ':' not in value['user_id']
            or not opaque(value['device_id']) or value['device_id']=='*'):
        raise ValueError('bounded private Matrix token and exact user/device identity required')
    if 'recovery_key' in value and (not isinstance(value['recovery_key'],str) or not 1<=len(value['recovery_key'])<=4096):
        raise ValueError('bounded explicit Matrix recovery material required')
    return result


@contextmanager
def scope(home,values):
    from hermes_constants import set_hermes_home_override,reset_hermes_home_override
    from .gateway_slack import secret_scope
    token=set_hermes_home_override(home)
    try:
        with secret_scope(values,str(home)):yield
    finally:reset_hermes_home_override(token)


def acquire_lease(profile):
    """One actual kernel lock per private device profile, without SDK imports."""
    profile=Path(profile);own=profile.lstat()
    if not stat.S_ISDIR(own.st_mode) or own.st_uid!=os.geteuid() or own.st_mode&0o077:
        raise PermissionError('Matrix profile lease requires its private identity directory')
    fd=os.open(profile/'profile.lock',os.O_RDWR|os.O_CREAT|os.O_NOFOLLOW|os.O_NONBLOCK|os.O_CLOEXEC,0o600)
    try:
        own=os.fstat(fd)
        if not stat.S_ISREG(own.st_mode) or own.st_uid!=os.geteuid() or own.st_mode&0o077 or own.st_nlink!=1:
            raise PermissionError('Matrix profile lock must be private regular and single-link')
        try:fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:raise PermissionError('Matrix identity profile is already in use') from None
        return fd
    except BaseException:os.close(fd);raise


def build(value,parent,connector,policy,inbox):
    value=credentials(value)
    def current():
        try:result=policy()
        except Exception:raise PermissionError('Matrix independent owner policy is unavailable') from None
        if (not isinstance(result,GatewayPolicy) or connector not in result.connectors
                or result.connectors[connector]['platform']!='matrix'):
            raise PermissionError('prepared Matrix connector has no independent owner policy')
        return result
    current()
    parent=Path(parent)
    if not parent.is_absolute() or parent.resolve()!=parent:
        raise ValueError('canonical private Matrix profile parent required')
    identity=digest([value['homeserver'],value['user_id'],value['device_id']])
    profile=private_store(parent/identity);home=private_store(profile/'home')
    fd=acquire_lease(profile)
    try:
        journal=SyncJournal(profile/'sync.db',identity)
        try:
            os.environ['HERMES_SAFE_MODE']='1'
            values={'MATRIX_ACCESS_TOKEN':value['token'],'MATRIX_PASSWORD':'','MATRIX_RECOVERY_KEY':'',
                'MATRIX_RECOVERY_KEY_OUTPUT_FILE':'','MATRIX_PROXY':''}
            with scope(home,values):
                from gateway.config import PlatformConfig
                from plugins.platforms.matrix.adapter import MatrixAdapter
                from .gateway_ingress import durable_adapter
                adapter=durable_adapter(MatrixAdapter(PlatformConfig(enabled=True,token=value['token'],extra={
                    'homeserver':value['homeserver'],'user_id':value['user_id'],'device_id':value['device_id'],
                    'e2ee_mode':'required','auto_thread':False,'reactions':False,'process_notices':False})))
            adapter._proxy_url=None
            adapter._haos_native=SimpleNamespace(connector=connector,policy=current,inbox=inbox)
            protect_crypto(adapter,profile/'crypto',recovery_key=value.get('recovery_key'))
            return _install(adapter,journal,fd,home,values)
        except BaseException:journal.close();raise
    except BaseException:os.close(fd);raise


def _install(adapter,journal,fd,home,values):
    from .gateway_matrix_ingress import install,attach_client,dispatch_stored
    from .gateway_matrix_delivery import install as delivery
    from .gateway_matrix_history import install_reads,recover_one
    from .gateway_matrix_recipients import RecipientGuard
    install(adapter)
    native_connect=adapter.connect;native_disconnect=adapter.disconnect
    protected_auth=adapter._connect_authenticate
    adapter._haos_profile_closed=False;adapter._haos_profile_closing=False
    adapter._haos_connect_task=None;adapter._haos_recovery_task=None
    close_lock=asyncio.Lock()
    adapter._haos_matrix_journal=journal;adapter._haos_profile_home=home
    journal.db.execute('''CREATE TABLE IF NOT EXISTS matrix_profile_status(
        scope TEXT PRIMARY KEY,status TEXT NOT NULL,updated_at REAL NOT NULL,next_sync REAL NOT NULL DEFAULT 0)''')
    journal.db.execute('''CREATE TABLE IF NOT EXISTS matrix_native_status(
        scope TEXT PRIMARY KEY,state TEXT NOT NULL,updated_at REAL NOT NULL)''')
    columns={row['name'] for row in journal.db.execute('PRAGMA table_info(matrix_profile_status)')}
    for name,declaration in [('last_error',"TEXT NOT NULL DEFAULT ''"),('error_at','REAL NOT NULL DEFAULT 0')]:
        if name not in columns:journal.db.execute('ALTER TABLE matrix_profile_status ADD COLUMN '+name+' '+declaration)
    kinds=PROFILE_STATES
    adapter._haos_native.inbox.db.execute('''CREATE TABLE IF NOT EXISTS matrix_transport(
        connector TEXT PRIMARY KEY,status TEXT NOT NULL,last_error TEXT NOT NULL,updated_at REAL NOT NULL,
        next_sync REAL NOT NULL,pending_pages INTEGER NOT NULL)''')
    transport_columns={row['name'] for row in adapter._haos_native.inbox.db.execute('PRAGMA table_info(matrix_transport)')}
    for name,declaration in [('history_gaps','INTEGER NOT NULL DEFAULT 0'),('history_error',"TEXT NOT NULL DEFAULT ''")]:
        if name not in transport_columns:adapter._haos_native.inbox.db.execute('ALTER TABLE matrix_transport ADD COLUMN '+name+' '+declaration)
    def status(kind,next_sync=0):
        if kind not in kinds:raise ValueError('safe Matrix profile status required')
        now=time.time();error=kind if kind in kinds-{'created','connecting','connected','decode-pending','disconnected','closed'} else ''
        journal.db.execute('INSERT INTO matrix_profile_status(scope,status,updated_at,next_sync,last_error,error_at) VALUES(?,?,?,?,?,?) '
            "ON CONFLICT(scope) DO UPDATE SET status=excluded.status,updated_at=excluded.updated_at,next_sync=excluded.next_sync,"
            "last_error=CASE WHEN excluded.status='connected' THEN '' WHEN excluded.last_error!='' THEN excluded.last_error ELSE matrix_profile_status.last_error END,"
            "error_at=CASE WHEN excluded.status='connected' THEN 0 WHEN excluded.last_error!='' THEN excluded.error_at ELSE matrix_profile_status.error_at END",
            (journal.scope,kind,now,next_sync,error,now if error else 0))
        last=journal.db.execute('SELECT last_error FROM matrix_profile_status WHERE scope=?',(journal.scope,)).fetchone()[0]
        pending=journal.db.execute("SELECT COUNT(*) FROM matrix_sync_pages WHERE scope=? AND state='pending'",(journal.scope,)).fetchone()[0]
        gaps=journal.db.execute("SELECT COUNT(*) FROM matrix_sync_gaps g LEFT JOIN matrix_history_progress p ON p.gap_id=g.id WHERE g.scope=? AND (p.gap_id IS NULL OR p.state='pending')",(journal.scope,)).fetchone()[0]
        history=journal.db.execute("SELECT last_error FROM matrix_history_progress WHERE state='pending' AND last_error!='' ORDER BY updated_at DESC LIMIT 1").fetchone()
        adapter._haos_native.inbox.db.execute('INSERT INTO matrix_transport(connector,status,last_error,updated_at,next_sync,pending_pages,history_gaps,history_error) VALUES(?,?,?,?,?,?,?,?) '
            'ON CONFLICT(connector) DO UPDATE SET status=excluded.status,last_error=excluded.last_error,updated_at=excluded.updated_at,'
            'next_sync=excluded.next_sync,pending_pages=excluded.pending_pages,history_gaps=excluded.history_gaps,history_error=excluded.history_error',
            (adapter._haos_native.connector,kind,last,now,next_sync,pending,gaps,history['last_error'] if history else ''))
    def health(self):
        row=journal.db.execute('SELECT status,updated_at,next_sync,last_error,error_at FROM matrix_profile_status WHERE scope=?',(journal.scope,)).fetchone()
        native=journal.db.execute('SELECT state FROM matrix_native_status WHERE scope=?',(journal.scope,)).fetchone()
        return {**dict(row),'pending_pages':journal.db.execute(
            "SELECT COUNT(*) FROM matrix_sync_pages WHERE scope=? AND state='pending'",(journal.scope,)).fetchone()[0],
            'pending_raw_inputs':self._haos_native.inbox.db.execute(
                "SELECT COUNT(*) FROM native_inbox WHERE connector=? AND state IN ('pending','processing')",(self._haos_native.connector,)).fetchone()[0],
            'native_state':native['state'] if native else 'created'}
    def native_status(self,context,**_fields):
        # The pinned SDK status publisher uses a process-global background
        # writer, which cannot retain this task's private home context. Route
        # its real state transitions to this profile's owned SQLite instead.
        state=context if context in {'connected','disconnected','fatal','connected_degraded'} else 'unavailable'
        try:
            journal.db.execute('INSERT INTO matrix_native_status(scope,state,updated_at) VALUES(?,?,?) '
                'ON CONFLICT(scope) DO UPDATE SET state=excluded.state,updated_at=excluded.updated_at',
                (journal.scope,state,time.time()))
        except Exception:
            import logging
            logging.warning('Matrix private native status persistence unavailable')
    async def no_action(self,*_args,**_kwargs):return None
    async def auth(self,client,api):
        self._haos_stopping=False
        self._haos_matrix_phase='authentication'
        result=await protected_auth(client,api)
        if result:self._haos_matrix_phase='identity'
        return result
    async def initial(self,client):
        boundary=self._haos_matrix_http
        attach_client(self,client);delivery(self,boundary)
        self._haos_profile_send=self.send;self.send=MethodType(send,self)
        RecipientGuard(self,client,boundary);install_reads(self,boundary)
        try:await receive_sync(self,client,journal,snapshot(self._haos_native.policy(),self._haos_native.connector),initial=True)
        except DeferredDispatch:status('decode-pending')
        self._haos_matrix_phase='sync'
        self._haos_recovery_task=asyncio.create_task(recover(self,client))
    async def recover(self,client):
        try:
            while not self._closing:
                self._haos_native.policy()
                key=journal.due()
                if key is not None:
                    try:await dispatch_page(self,client,journal,key)
                    except DeferredDispatch:pass
                key=self._haos_native.inbox.due(self._haos_native.connector)
                if key is not None:
                    try:await dispatch_stored(self,self._haos_native_dispatch,key)
                    except (ConnectionError,ValueError):pass
                try:await recover_one(self,client,journal)
                except DeferredDispatch:pass
                await asyncio.sleep(0.2)
        except asyncio.CancelledError:raise
        except PermissionError:
            try:status('policy-unavailable')
            finally:self._mark_disconnected()
        except Exception:
            try:status('transport-unavailable')
            finally:self._mark_disconnected()
    async def sync(self):
        from mautrix.errors import MatrixRequestError
        client=self._client
        try:
            while not self._closing:
                self._haos_native.policy()
                row=journal.db.execute('SELECT next_sync FROM matrix_profile_status WHERE scope=?',(journal.scope,)).fetchone()
                if row['next_sync']>time.time():
                    await asyncio.sleep(min(1,row['next_sync']-time.time()));continue
                try:
                    await receive_sync(self,client,journal,snapshot(self._haos_native.policy(),self._haos_native.connector),timeout_ms=30000)
                    status('connected')
                except DeferredDispatch:status('decode-pending')
                except MatrixRequestError as error:
                    if error.http_status in {401,403}:
                        status('authentication-refused')
                        self._set_fatal_error('matrix_auth','Matrix account refused; correct private owner credentials',retryable=False)
                        return
                    delay=getattr(error,'retry_after',5)
                    if type(delay) not in {int,float} or not math.isfinite(delay):delay=5
                    status('rate-limited' if error.http_status==429 else 'transport-unavailable',time.time()+min(86400,max(1,delay)))
                await asyncio.sleep(0.05)
        except asyncio.CancelledError:raise
        except PermissionError:
            try:status('policy-unavailable')
            finally:self._mark_disconnected()
        except Exception:
            try:status('transport-unavailable')
            finally:self._mark_disconnected()
    async def disconnect(self):
        if self._haos_profile_closed:return
        self._haos_stopping=True
        self._haos_matrix_http.revoke()
        task=self._haos_recovery_task;self._haos_recovery_task=None
        if task is not None:
            task.cancel();await asyncio.gather(task,return_exceptions=True)
        with scope(home,values):
            try:await native_disconnect()
            finally:
                self._crypto_db=None;self._mark_disconnected()
        old=self.matrix_status()
        if old['status'] not in {'authentication-refused','identity-refused','policy-unavailable','rate-limited'}:
            status('disconnected',old['next_sync'])
    async def connect_once(self,**kwargs):
        if self._haos_profile_closed:raise PermissionError('Matrix private profile is closed')
        if self.has_fatal_error and not self._fatal_error_retryable:return False
        self._haos_native.policy();self._haos_stopping=False;self._closing=False
        previous=self.matrix_status()['next_sync']
        if previous>time.time():return False
        status('connecting',previous)
        try:
            with scope(home,values):
                result=await native_connect(**kwargs)
            if result:
                if self.matrix_status()['status']!='decode-pending':status('connected',previous)
                return True
            code=self._haos_matrix_http.last_status
            if code==429:status('rate-limited',time.time()+self._haos_matrix_http.last_retry_after)
            else:status('authentication-refused' if code in {401,403} else 'identity-refused' if code==200 else 'transport-unavailable')
        except asyncio.CancelledError:
            await disconnect(self);raise
        except Exception:
            code=self._haos_matrix_http.last_status
            status('authentication-refused' if code in {401,403} else 'rate-limited' if code==429 else 'transport-unavailable',
                time.time()+self._haos_matrix_http.last_retry_after if code==429 else 0)
        if self.matrix_status()['status']=='authentication-refused':
            with scope(home,values):
                self._set_fatal_error('matrix_auth','Matrix account refused; correct private owner credentials',retryable=False)
        await disconnect(self);return False
    async def connect(self,**kwargs):
        if self._haos_profile_closed or self._haos_profile_closing:
            raise PermissionError('Matrix private profile is closed')
        if self._haos_connect_task is not None:raise PermissionError('Matrix private profile is already connecting')
        self._haos_connect_task=asyncio.current_task()
        try:return await connect_once(self,**kwargs)
        finally:self._haos_connect_task=None
    async def send(self,*args,**kwargs):
        # Delivery is installed after actual crypto setup. Before connect there
        # is no send authority, including through native plaintext fallback.
        if self._haos_profile_closed or self._haos_profile_closing or not self.is_connected:
            raise PermissionError('Matrix private profile is not connected')
        with scope(home,values):return await self._haos_profile_send(*args,**kwargs)
    async def close(self):
        async with close_lock:
            if self._haos_profile_closed:return
            self._haos_profile_closing=True
            task=self._haos_connect_task
            if task is not None and task is not asyncio.current_task():
                task.cancel();await asyncio.gather(task,return_exceptions=True)
            try:await disconnect(self)
            finally:
                try:status('closed',self.matrix_status()['next_sync'])
                finally:
                    try:journal.close()
                    finally:os.close(fd);self._haos_profile_closed=True
    for name,method in {'_connect_authenticate':auth,'_connect_initial_sync':initial,'_sync_loop':sync,
            '_refresh_dm_cache':no_action,'_on_invite':no_action,'_on_reaction':no_action,
            '_write_runtime_status_safe':native_status,'connect':connect,'disconnect':disconnect,
            'close_profile':close,'matrix_status':health,'send':send}.items():
        setattr(adapter,name,MethodType(method,adapter))
    old=journal.db.execute('SELECT next_sync FROM matrix_profile_status WHERE scope=?',(journal.scope,)).fetchone()
    status('created',old['next_sync'] if old else 0)
    return adapter
