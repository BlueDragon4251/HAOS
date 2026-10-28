"""Prepared private Twilio identity, HTTPS receiver, replay and lifecycle."""
import asyncio
import fcntl
import os
from pathlib import Path
import re
import stat
import time
from types import MethodType,SimpleNamespace

from .gateway import digest,Conflict
from .gateway_sms import credentials,scope,snapshot,validate_binding
from .gateway_sms_ingress import install,capture,dispatch_stored
from .gateway_sms_rest import Rest,Refused


def build(value,*,parent,connector,policy,inbox):
    value=credentials(value);current=policy();authority=snapshot(current,connector,value)
    bindings=[b for b in current.bindings.values() if b['connector']==connector]
    if not bindings:raise PermissionError('explicit SMS sender grant required')
    for binding in bindings:
        validate_binding(binding,require_epoch=True)
        if binding['scope']!=scope(value):raise PermissionError('SMS binding differs from configured receiving account/number')
    from .gateway_line_profile import _directory
    parent=Path(parent);_directory(parent)
    profile=parent/('sms-'+digest([connector,value]))
    try:profile.mkdir(mode=0o700)
    except FileExistsError:pass
    _directory(profile)
    fd=os.open(profile/'lease',os.O_RDWR|os.O_CREAT|os.O_NOFOLLOW|os.O_NONBLOCK,0o600)
    try:
        own=os.fstat(fd)
        if not stat.S_ISREG(own.st_mode) or own.st_uid!=os.geteuid() or own.st_mode&0o077 or own.st_nlink!=1:
            raise PermissionError('private SMS lease required')
        try:fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:raise PermissionError('SMS identity already active') from None
        home=profile/'home'
        try:home.mkdir(mode=0o700)
        except FileExistsError:pass
        _directory(home)
        from .gateway_matrix_profile import scope as secret_scope
        from .gateway_ingress import durable_adapter
        from .redaction import Redactor
        inbox.redactor=Redactor([*inbox.redactor.secrets,value['auth_token'],value['tls']['private_key']])
        values={'TWILIO_ACCOUNT_SID':value['account_sid'],'TWILIO_AUTH_TOKEN':value['auth_token'],
            'TWILIO_PHONE_NUMBER':value['from_number'],'SMS_WEBHOOK_PORT':str(value['port']),
            'SMS_WEBHOOK_HOST':'127.0.0.1','SMS_WEBHOOK_URL':value['tls']['public_url'],
            'SMS_INSECURE_NO_SIGNATURE':'false','SMS_ALLOW_ALL_USERS':'false','SMS_ALLOWED_USERS':'','SMS_HOME_CHANNEL':''}
        with secret_scope(home,values):
            from gateway.config import PlatformConfig
            from gateway.platform_registry import PlatformEntry
            from plugins.platforms.sms import adapter as native
            class Context:
                def register_platform(self,**kwargs):self.entry=PlatformEntry(**kwargs)
            context=Context();native.register(context)
            if not context.entry.check_fn():raise RuntimeError('frozen SMS runtime unavailable')
            adapter=install(durable_adapter(context.entry.adapter_factory(PlatformConfig(enabled=True))))
        def pinned():
            result=policy()
            if snapshot(result,connector,value)!=authority:raise PermissionError('SMS owner publication changed')
            return result
        adapter._haos_native=SimpleNamespace(connector=connector,policy=pinned,inbox=inbox)
        adapter._haos_sms_value=value
        return _install(adapter,fd,profile,value,authority)
    except BaseException:os.close(fd);raise


def application(adapter):
    from aiohttp import web
    async def receive(request):
        if request.content_type!='application/x-www-form-urlencoded':return web.Response(status=415)
        signatures=request.headers.getall('X-Twilio-Signature',[])
        if len(signatures)!=1:return web.Response(status=403)
        try:
            raw=await asyncio.wait_for(request.read(),5)
            await capture(adapter,raw,signatures[0])
        except web.HTTPRequestEntityTooLarge:return web.Response(status=413)
        except Refused as exc:
            if exc.status in {401,403,429}:
                adapter._haos_sms_pause('rate-limited' if exc.status==429 else 'authentication-refused',exc.delay)
            return web.Response(status=503)
        except PermissionError:return web.Response(status=403)
        except Conflict:return web.Response(status=503)
        except (ValueError,UnicodeError):return web.Response(status=400)
        except (ConnectionError,OSError,TimeoutError):return web.Response(status=503)
        except Exception:return web.Response(status=503)
        from plugins.platforms.sms.adapter import _twiml_response
        return _twiml_response()
    app=web.Application(client_max_size=65536);app.router.add_post('/webhooks/twilio',receive)
    return app


def _install(adapter,fd,profile,value,authority):
    db=adapter._haos_native.inbox.db;connector=adapter._haos_native.connector
    credential_scope=digest([connector,value['account_sid'],value['auth_token'],value['from_number']])
    identity=digest([credential_scope,authority]);lifecycle=asyncio.Lock();workers=set()
    db.execute('''CREATE TABLE IF NOT EXISTS sms_profile_status(identity TEXT PRIMARY KEY,connector TEXT NOT NULL,
        credential_scope TEXT NOT NULL,status TEXT NOT NULL,updated_at REAL NOT NULL,next_attempt REAL NOT NULL)''')
    prior=db.execute('SELECT status,next_attempt FROM sms_profile_status WHERE connector=? AND credential_scope=?',(connector,credential_scope)).fetchall()
    blocked=next((r['status'] for r in prior if r['status'] in {'authentication-refused','identity-refused'}),None)
    deadline=max([r['next_attempt'] for r in prior]+[0])
    db.execute('INSERT OR IGNORE INTO sms_profile_status VALUES(?,?,?,?,?,?)',(identity,connector,credential_scope,blocked or 'created',time.time(),deadline))
    db.execute('UPDATE sms_profile_status SET next_attempt=MAX(next_attempt,?),status=CASE WHEN ? THEN ? ELSE status END WHERE identity=?',
        (deadline,blocked is not None,blocked or 'created',identity))
    adapter._haos_sms_rest=Rest(value,adapter._haos_native.inbox.redactor)
    adapter._haos_sms_closed=False;adapter._haos_sms_runner=None;adapter._haos_sms_replay=None
    def status(state,delay=0):db.execute('UPDATE sms_profile_status SET status=?,updated_at=?,next_attempt=? WHERE identity=?',
        (state,time.time(),time.time()+delay if delay else 0,identity))
    def health(self):return dict(db.execute('SELECT connector,status,updated_at,next_attempt FROM sms_profile_status WHERE identity=?',(identity,)).fetchone())
    def check():
        if (adapter._haos_sms_closed or snapshot(adapter._haos_native.policy(),connector,value)!=authority
                or adapter._account_sid!=value['account_sid'] or adapter._auth_token!=value['auth_token']
                or adapter._from_number!=value['from_number'] or adapter._webhook_url!=value['tls']['public_url']):
            raise PermissionError('SMS profile closed or owner identity changed')
    adapter._haos_sms_check=check
    from .gateway_sms_delivery import Publisher
    publisher=Publisher(adapter) if any('read' in b['capabilities'] for b in adapter._haos_native.policy().bindings.values() if b['connector']==connector) else None
    adapter._haos_sms_publisher=publisher
    async def stop():
        adapter._mark_disconnected()
        task=adapter._haos_sms_replay;adapter._haos_sms_replay=None
        if task is not None and task is not asyncio.current_task():task.cancel();await asyncio.gather(task,return_exceptions=True)
        runner=adapter._haos_sms_runner;adapter._haos_sms_runner=None
        if runner is not None:await runner.cleanup()
    async def pause_work(state,delay):
        async with lifecycle:status(state,delay);await stop()
    def pause(state,delay):
        adapter._mark_disconnected();task=asyncio.create_task(pause_work(state,delay));workers.add(task);task.add_done_callback(workers.discard)
    adapter._haos_sms_pause=pause
    async def replay():
        try:
            while True:
                check();key=adapter._haos_native.inbox.due(connector)
                if key is not None:
                    try:
                        if publisher is None:await dispatch_stored(adapter,key)
                        else:
                            async with publisher.lock:check();await dispatch_stored(adapter,key)
                    except asyncio.CancelledError:raise
                    except PermissionError:raise
                    except Exception:pass  # Retained retry/backoff, never raw errors or text.
                await asyncio.sleep(.1)
        except PermissionError:
            status('revoked')
            async with lifecycle:await stop()
    async def connect(self,**_kwargs):
        async with lifecycle:
            check()
            if self.is_connected:return True
            row=health(self)
            if row['status'] in {'authentication-refused','identity-refused'} or row['next_attempt']>time.time():return False
            from .gateway_line_tls import context
            try:tls=context(value['tls'],profile,webhook_path='/webhooks/twilio')
            except Exception:status('tls-refused');return False
            try:capabilities=await self._haos_sms_rest.verify(check);check()
            except Refused as exc:
                status('authentication-refused' if exc.status in {401,403} else 'rate-limited' if exc.status==429 else 'transport-unavailable',exc.delay);return False
            except PermissionError:
                try:check()
                except PermissionError:status('revoked');raise
                status('identity-refused');return False
            except Exception:status('transport-unavailable');return False
            try:
                from .gateway_https import start
                self._haos_sms_runner=await start('sms',value,application(self),tls);check()
                self._mark_connected();status('listening-tls');self._haos_sms_replay=asyncio.create_task(replay());return True
            except asyncio.CancelledError:await stop();raise
            except PermissionError:await stop();status('revoked');raise
            except Exception:await stop();status('transport-unavailable');return False
    async def disconnect(self):
        async with lifecycle:
            await stop()
            if health(self)['status'] not in {'revoked','closed','authentication-refused','identity-refused','rate-limited','tls-refused'}:status('disconnected')
    async def send(self,chat_id,content,reply_to=None,metadata=None):
        from .gateway_delivery_authority import current_delivery
        if publisher is None:raise PermissionError('creation-only SMS profile has no reply authority')
        async with lifecycle:
            current_delivery(self,'sms',chat_id,metadata)()
            binding=self._haos_native.policy().current_binding(metadata['haos_binding'])
            result=await publisher.send(binding,metadata.get('haos_delivery_id'),metadata.get('haos_delivery_attempt'),content)
            if result.error_kind=='forbidden':status('authentication-refused');await stop()
            elif result.error_kind=='rate_limited':status('rate-limited',result.retry_after);await stop()
            return result
    async def close(self):
        async with lifecycle:
            if self._haos_sms_closed:return
            self._haos_sms_closed=True
            try:
                await stop()
                if publisher is not None:await publisher.close()
                await self._haos_sms_rest.close()
                if health(self)['status'] not in {'authentication-refused','identity-refused','rate-limited','tls-refused','revoked'}:status('closed')
            finally:os.close(fd)
        for task in tuple(workers):
            if not task.done():task.cancel()
        if workers:await asyncio.gather(*workers,return_exceptions=True)
    adapter.connect=MethodType(connect,adapter);adapter.disconnect=MethodType(disconnect,adapter)
    adapter.send=MethodType(send,adapter);adapter.close_profile=MethodType(close,adapter);adapter.native_health=MethodType(health,adapter)
    return adapter
