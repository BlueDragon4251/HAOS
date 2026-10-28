"""Prepared private email receiver and supervised durable SMTP reply lifecycle."""
import asyncio
import base64
import os
import sqlite3
from pathlib import Path
import time
from types import MethodType,SimpleNamespace

from .gateway import digest,Conflict
from .gateway_email import credentials,scope as mailbox_scope
from .gateway_email_admission import approve,Refused
from .gateway_email_cache import RawCache
from .gateway_email_ingress import install,capture,dispatch_stored
from .gateway_email_journal import Journal
from . import gateway_email_process as process

STATES=frozenset({'created','connecting','receiving','source-unavailable','storage-unavailable','tls-refused',
    'smtp-authentication-refused','rate-limited','imap-unavailable','uid-state-changed','revoked','disconnected','closed'})


class Deferred(Exception):
    def __init__(self,code):super().__init__('private email source deferred');self.code=code


def checked(result):
    if 'error' in result:raise Deferred(result['error'])
    return result


def build(value,*,parent,connector,policy,inbox):
    value=credentials(value);initial=policy()
    def snapshot(latest):
        if latest.connectors.get(connector,{}).get('platform')!='email':raise PermissionError('configured email connector required')
        bindings=[row for row in latest.bindings.values() if row['connector']==connector]
        if not bindings or any(row['scope']!=mailbox_scope(value) or row['sender']==value['address'] for row in bindings):
            raise PermissionError('explicit timed email sender grants matching the receiving mailbox required')
        return digest([latest.publication,connector,bindings,value])
    authority=snapshot(initial)
    def pinned():
        latest=policy()
        if snapshot(latest)!=authority:raise PermissionError('email owner publication changed')
        return latest
    from .gateway_line_profile import _directory
    from .gateway_matrix_profile import acquire_lease,scope
    parent=Path(parent);_directory(parent);profile=parent/('email-'+digest([connector,value]))
    try:profile.mkdir(mode=0o700)
    except FileExistsError:pass
    fd=acquire_lease(profile)
    try:
        home=profile/'home'
        try:home.mkdir(mode=0o700)
        except FileExistsError:pass
        _directory(home)
        from .redaction import Redactor
        password=value['password'];plain=base64.b64encode(('\0'+value['address']+'\0'+password).encode()).decode()
        inbox.redactor=Redactor([*inbox.redactor.secrets,password,base64.b64encode(password.encode()).decode(),plain])
        env={'EMAIL_'+key.upper():str(item) for key,item in value.items() if key!='authserv_id'}
        env.update(EMAIL_AUTHSERV_ID=value['authserv_id'],EMAIL_IMAP_TLS_VERIFY='true',EMAIL_SMTP_TLS_VERIFY='true',
            EMAIL_TRUST_FROM_HEADER='false',EMAIL_ALLOW_ALL_USERS='false',GATEWAY_ALLOW_ALL_USERS='false',
            EMAIL_ALLOWED_USERS='',GATEWAY_ALLOWED_USERS='')
        with scope(home,env):
            from gateway.config import PlatformConfig
            from gateway.platform_registry import PlatformEntry
            from plugins.platforms.email import adapter as native
            from .gateway_ingress import durable_adapter
            class Context:
                def register_platform(self,**kwargs):self.entry=PlatformEntry(**kwargs)
            context=Context();native.register(context)
            if not context.entry.check_fn():raise RuntimeError('pinned email runtime unavailable')
            adapter=install(durable_adapter(context.entry.adapter_factory(PlatformConfig(enabled=True,extra={
                'skip_attachments':True,'require_authenticated_sender':True,'authserv_id':value['authserv_id']}))))
        adapter._haos_native=SimpleNamespace(connector=connector,policy=pinned,inbox=inbox)
        adapter._haos_email_value=value;adapter._haos_email_environment=env;adapter._haos_email_home=home
        adapter._haos_email_raw=RawCache(profile/'raw.db',inbox.redactor)
        return _install(adapter,fd,profile,authority)
    except BaseException:os.close(fd);raise


def _install(adapter,fd,profile,identity):
    native=adapter._haos_native;db=native.inbox.db;value=adapter._haos_email_value;connector=native.connector
    adapter._haos_email_closed=False;adapter._haos_email_tasks=[];lifecycle=asyncio.Lock()
    db.execute('''CREATE TABLE IF NOT EXISTS email_profile_status(identity TEXT PRIMARY KEY,connector TEXT NOT NULL,
        credential_scope TEXT NOT NULL,status TEXT NOT NULL,updated_at REAL NOT NULL,next_attempt REAL NOT NULL)''')
    credential_scope=digest([connector,value])
    prior=db.execute('SELECT status,next_attempt FROM email_profile_status WHERE connector=? AND credential_scope=?',(connector,credential_scope)).fetchall()
    blocked=next((row['status'] for row in prior if row['status']=='smtp-authentication-refused'),None)
    deadline=max([row['next_attempt'] for row in prior]+[0])
    db.execute('INSERT OR IGNORE INTO email_profile_status VALUES(?,?,?,?,?,?)',(identity,connector,credential_scope,blocked or 'created',time.time(),deadline))
    db.execute('UPDATE email_profile_status SET next_attempt=MAX(next_attempt,?),status=CASE WHEN ? THEN ? ELSE status END WHERE identity=?',
        (deadline,blocked is not None,blocked or 'created',identity))
    def current():
        if adapter._haos_email_closed:raise PermissionError('email profile closed')
        native.policy()
        for key in ('address','password','imap_host','imap_port','imap_security','smtp_host','smtp_port','smtp_security'):
            if getattr(adapter,'_'+key)!=value[key]:raise PermissionError('native email identity changed')
        if adapter._imap_tls_verify is not True or adapter._smtp_tls_verify is not True:raise PermissionError('verified email TLS required')
    adapter._haos_email_check=current
    from .gateway_email_delivery import Publisher
    publisher=Publisher(adapter) if any(row['connector']==connector and 'read' in row['capabilities'] for row in native.policy().bindings.values()) else None
    adapter._haos_email_publisher=publisher
    journal=Journal(native.inbox,connector,mailbox_scope(value),current);adapter._haos_email_journal=journal
    def status(state,delay=0):
        if state not in STATES:raise ValueError('finite private email profile status required')
        db.execute('UPDATE email_profile_status SET status=?,updated_at=?,next_attempt=? WHERE identity=?',
            (state,time.time(),time.time()+delay if delay else 0,identity))
    def health(self):return dict(db.execute('SELECT connector,status,updated_at,next_attempt FROM email_profile_status WHERE identity=?',(identity,)).fetchone())
    async def stop():
        adapter._mark_disconnected();tasks=adapter._haos_email_tasks;adapter._haos_email_tasks=[]
        others=[task for task in tasks if task is not asyncio.current_task()]
        for task in others:task.cancel()
        if others:await asyncio.gather(*others,return_exceptions=True)
    async def collect_once():
        current();metadata=checked(await process.mailbox(value,connector,current))
        if journal.observe(metadata['uid_validity'],metadata['uid_next'])['status']!='ready':raise Deferred('uid-state-changed')
        page=journal.page()
        if page is None:return False
        found=checked(await process.search(value,connector,current,page));current()
        if journal.observe(found['uid_validity'],found['uid_next'])['status']!='ready':raise Deferred('uid-state-changed')
        outcomes=[]
        for uid in found['uids']:
            current();header=checked(await process.headers(value,connector,current,uid,page['uid_validity']))
            if journal.observe(header['uid_validity'],header['uid_next'])['status']!='ready':raise Deferred('uid-state-changed')
            row={'uid':uid,'header_sha256':__import__('hashlib').sha256(header['content']).hexdigest(),
                'internal_at':header['internal_at'],'status':'ignored','reason':'unapproved-sender','native_id':None}
            try:
                approval=approve(native.policy(),connector,value,header)
                key=native.inbox.key(connector,approval['envelope'])
                prior=db.execute('SELECT binding_digest FROM native_inbox WHERE id=?',(key,)).fetchone()
                if prior is not None:
                    if prior['binding_digest']!=approval['binding_digest']:raise Refused('pre-grant')
                    journal.remember_capture(key)
                else:
                    resource=await process.message(value,connector,current,uid,page['uid_validity'],approval['header_sha256'],
                        {'binding_id':approval['binding_id'],'binding_digest':approval['binding_digest']})
                    if 'error' in resource:
                        if resource['error'] in {'unapproved-sender','unapproved-thread','pre-grant','self-or-automated','unsupported-content','authentication-refused'}:
                            raise Refused(resource['error'])
                        raise Deferred(resource['error'])
                    key=capture(adapter,resource)
                row.update(status='captured',reason='',native_id=key)
            except Refused as error:row.update(status='refused',reason=error.reason)
            outcomes.append(row)
        current();journal.commit(page,outcomes,uids=found['uids']);return True
    adapter._haos_email_collect_once=collect_once
    async def receive_loop():
        try:
            while True:
                try:
                    more=await collect_once();status('receiving')
                    if not more:await asyncio.sleep(15)
                except Deferred as error:
                    state=error.code if error.code in STATES else 'source-unavailable';status(state,30)
                    if state in {'smtp-authentication-refused','tls-refused','uid-state-changed'}:
                        async with lifecycle:await stop()
                        return
                    await asyncio.sleep(30)
                except (Conflict,sqlite3.Error):status('storage-unavailable',30);await asyncio.sleep(30)
                except PermissionError:current();status('source-unavailable',30);await asyncio.sleep(30)
                except (ConnectionError,OSError,ValueError,TimeoutError):status('source-unavailable',30);await asyncio.sleep(30)
        except PermissionError:
            status('revoked')
            async with lifecycle:await stop()
    async def replay_loop():
        try:
            while True:
                current();key=native.inbox.due(connector)
                if key is not None:
                    try:await dispatch_stored(adapter,key)
                    except asyncio.CancelledError:raise
                    except PermissionError:current()
                    except Exception:pass  # Retained native backoff; no raw exceptions.
                await asyncio.sleep(.1)
        except PermissionError:
            status('revoked')
            async with lifecycle:await stop()
    async def connect(self,**_kwargs):
        async with lifecycle:
            current()
            if self.is_connected:return True
            state=health(self)
            if state['status']=='smtp-authentication-refused' or state['next_attempt']>time.time():return False
            status('connecting')
            try:
                found=checked(await process.probe(value,connector,current));current()
                if journal.observe(found['uid_validity'],found['uid_next'])['status']!='ready':status('uid-state-changed');return False
            except Deferred as error:status(error.code if error.code in STATES else 'source-unavailable',30);return False
            except PermissionError:status('revoked');raise
            except Exception:status('source-unavailable',30);return False
            self._mark_connected();status('receiving')
            self._haos_email_tasks=[asyncio.create_task(receive_loop()),asyncio.create_task(replay_loop())];return True
    async def disconnect(self):
        async with lifecycle:
            await stop()
            if health(self)['status'] not in {'revoked','smtp-authentication-refused','tls-refused','uid-state-changed','source-unavailable','storage-unavailable','imap-unavailable','rate-limited'}:status('disconnected')
    async def send(self,chat_id,content,reply_to=None,metadata=None):
        from .gateway_delivery_authority import current_delivery
        if publisher is None:raise PermissionError('creation-only email profile has no reply authority')
        async with lifecycle:
            authority=current_delivery(self,'email',chat_id,metadata)
            binding=native.policy().current_binding(metadata['haos_binding'])
            result=await publisher.send(binding,metadata.get('haos_delivery_id'),metadata.get('haos_delivery_attempt'),content,reply_to,authority)
            if result.error_kind=='forbidden':
                status('tls-refused' if result.raw_response.get('email_error')=='tls-refused' else 'smtp-authentication-refused');await stop()
            elif result.error_kind=='rate_limited':status('rate-limited',result.retry_after);await stop()
            return result
    async def close(self):
        async with lifecycle:
            if self._haos_email_closed:return
            self._haos_email_closed=True
            try:
                await stop()
                if publisher is not None:await publisher.close()
                self._haos_email_raw.close()
                if health(self)['status'] not in {'revoked','smtp-authentication-refused','tls-refused','uid-state-changed','source-unavailable','storage-unavailable','imap-unavailable','rate-limited'}:status('closed')
            finally:os.close(fd)
    adapter.connect=MethodType(connect,adapter);adapter.disconnect=MethodType(disconnect,adapter);adapter.send=MethodType(send,adapter)
    adapter.close_profile=MethodType(close,adapter);adapter.native_health=MethodType(health,adapter)
    return adapter
