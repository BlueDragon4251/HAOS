"""Private prepared native Feishu HTTPS and supervised WS profile with durable replay and revocation.

Public registry and media activation remain separate.
"""
import asyncio
import os
from pathlib import Path
import time
from types import MethodType,SimpleNamespace

from .gateway import digest
from .gateway_feishu import credentials,scope as account_scope,PreparedFeishuPolicy,authority
from .gateway_feishu_admission import Refused
from .gateway_feishu_cache import RawEvents
from .gateway_feishu_ingress import install,dispatch_stored
from .gateway_feishu_webhook import Receiver

STATES=frozenset({'created','connecting','listening-tls','connected-ws','storage-unavailable','tls-refused',
    'identity-refused','authentication-refused','source-unavailable','rate-limited','transport-unavailable','revoked','disconnected','closed'})


def build(value,*,parent,connector,policy,inbox):
    from .gateway_runtime import require_runtime_identity
    require_runtime_identity();value=credentials(value,verify_tls=False)
    def snapshot(latest):
        if not isinstance(latest,PreparedFeishuPolicy) or latest.connectors.get(connector,{}).get('platform')!='feishu':
            raise PermissionError('prepared independent Feishu policy required')
        bindings=[row for row in latest.bindings.values() if row['connector']==connector]
        if not bindings or any(row['scope']!=account_scope(value) or row['sender']==value['bot_open_id'] for row in bindings):
            raise PermissionError('explicit timed Feishu sender grants matching exact account required')
        return digest([latest.publication,connector,bindings,value])
    initial=snapshot(policy());publication=authority(connector,value)
    def pinned():
        latest=policy()
        if snapshot(latest)!=initial:raise PermissionError('Feishu profile grant or credential identity changed')
        authority(connector,value,publication);return latest
    from .gateway_line_profile import _directory
    from .gateway_matrix_profile import acquire_lease,scope
    parent=Path(parent);_directory(parent);profile=parent/('feishu-'+digest([connector,value]))
    try:profile.mkdir(mode=0o700)
    except FileExistsError:pass
    fd=acquire_lease(profile);originals=None;receiver=None
    try:
        home=profile/'home'
        try:home.mkdir(mode=0o700)
        except FileExistsError:pass
        _directory(home)
        from .redaction import Redactor
        inbox.redactor=Redactor([*inbox.redactor.secrets,value['app_secret'],value.get('verification_token',''),
            value.get('encrypt_key',''),value.get('tls',{}).get('private_key','')])
        env={'HERMES_SAFE_MODE':'1','FEISHU_APP_ID':value['app_id'],'FEISHU_APP_SECRET':value['app_secret'],
            'FEISHU_DOMAIN':value['domain'],'FEISHU_CONNECTION_MODE':value['connection_mode'],'FEISHU_BOT_OPEN_ID':value['bot_open_id'],
            'FEISHU_ENCRYPT_KEY':value.get('encrypt_key',''),'FEISHU_VERIFICATION_TOKEN':value.get('verification_token',''),
            'FEISHU_GROUP_POLICY':'allowlist','FEISHU_ALLOWED_USERS':','.join(sorted({row['sender'] for row in pinned().bindings.values() if row['connector']==connector})),
            'FEISHU_ALLOW_ALL_USERS':'false','GATEWAY_ALLOW_ALL_USERS':'false','FEISHU_ALLOW_BOTS':'none',
            'FEISHU_REQUIRE_MENTION':'false','FEISHU_REACTIONS':'false','FEISHU_BOT_USER_ID':'','FEISHU_BOT_NAME':''}
        with scope(home,env):
            from plugins.platforms.feishu import adapter as native
            if not native._load_lark_oapi():raise RuntimeError('pinned Feishu SDK unavailable; no automatic installation')
            from gateway.config import PlatformConfig
            from .gateway_ingress import durable_adapter
            adapter=install(durable_adapter(native.FeishuAdapter(PlatformConfig(enabled=True))))
        adapter._haos_native=SimpleNamespace(connector=connector,policy=pinned,inbox=inbox)
        adapter._haos_feishu_value=value;adapter._haos_feishu_home=home;adapter._haos_feishu_environment=env
        adapter._haos_feishu_closed=False
        def current():
            if adapter._haos_feishu_closed:raise PermissionError('private Feishu profile closed')
            pinned()
            for field,key in [('app_id','app_id'),('app_secret','app_secret'),('domain_name','domain'),
                    ('encrypt_key','encrypt_key'),('verification_token','verification_token'),('bot_open_id','bot_open_id')]:
                if getattr(adapter,'_'+field)!=value.get(key,''):raise PermissionError('native Feishu credential identity changed')
        adapter._haos_feishu_check=current
        originals=RawEvents(profile/'originals.db',inbox.redactor,current);adapter._haos_feishu_raw=originals
        receiver=Receiver(adapter,profile/'webhooks.db') if value['connection_mode']=='webhook' else None
        adapter._haos_feishu_receiver=receiver;adapter._haos_feishu_socket=None
        return _install(adapter,fd,profile,initial)
    except BaseException:
        if receiver is not None:receiver.close()
        if originals is not None:originals.close()
        os.close(fd);raise


def _install(adapter,fd,profile,identity):
    from .gateway_matrix_profile import scope as private_scope
    native=adapter._haos_native;value=adapter._haos_feishu_value;db=native.inbox.db;current=adapter._haos_feishu_check
    from .gateway_feishu_delivery import Publisher
    publisher=Publisher(adapter) if any(row['connector']==native.connector and 'read' in row['capabilities'] for row in native.policy().bindings.values()) else None
    adapter._haos_feishu_publisher=publisher
    from .gateway_feishu_output import Output
    from .gateway_feishu_media_delivery import MediaPublisher
    adapter._haos_feishu_output=Output(adapter) if publisher is not None else None
    adapter._haos_feishu_media_publisher=MediaPublisher(adapter) if publisher is not None else None
    scope=digest([native.connector,value]);lifecycle=asyncio.Lock();adapter._haos_feishu_runner=None;adapter._haos_feishu_task=None
    db.execute('''CREATE TABLE IF NOT EXISTS feishu_profile_status(identity TEXT PRIMARY KEY,connector TEXT NOT NULL,
        credential_scope TEXT NOT NULL,status TEXT NOT NULL,updated_at REAL NOT NULL,next_attempt REAL NOT NULL)''')
    prior=db.execute('SELECT status,next_attempt FROM feishu_profile_status WHERE connector=? AND credential_scope=?',(native.connector,scope)).fetchall()
    blocked=next((row['status'] for row in prior if row['status'] in {'authentication-refused','identity-refused'}),None)
    deadline=max([row['next_attempt'] for row in prior]+[0])
    db.execute('INSERT OR IGNORE INTO feishu_profile_status VALUES(?,?,?,?,?,?)',
        (identity,native.connector,scope,blocked or 'created',time.time(),deadline))
    def status(state,delay=0):
        if state not in STATES:raise ValueError('finite private Feishu status required')
        db.execute('UPDATE feishu_profile_status SET status=?,updated_at=?,next_attempt=? WHERE identity=?',
            (state,time.time(),time.time()+delay if delay else 0,identity))
    def health(self):return dict(db.execute('SELECT connector,status,updated_at,next_attempt FROM feishu_profile_status WHERE identity=?',(identity,)).fetchone())
    async def stop():
        task=adapter._haos_feishu_task;adapter._haos_feishu_task=None
        if task is not None and task is not asyncio.current_task():task.cancel();await asyncio.gather(task,return_exceptions=True)
        socket=adapter._haos_feishu_socket;adapter._haos_feishu_socket=None
        if socket is not None:await socket.close()
        runner=adapter._haos_feishu_runner;adapter._haos_feishu_runner=None
        if runner is not None:await runner.cleanup()
        with private_scope(adapter._haos_feishu_home,adapter._haos_feishu_environment):adapter._mark_disconnected()
    async def open_socket():
        from .gateway_feishu_ws_process import Session
        from .gateway_feishu_ingress import capture
        adapter._haos_feishu_socket=Session(value,native.connector,current,lambda raw:capture(adapter,raw))
        await adapter._haos_feishu_socket.start();current()
        with private_scope(adapter._haos_feishu_home,adapter._haos_feishu_environment):adapter._mark_connected()
        status('connected-ws')
    async def replay():
        backoff=2
        try:
            while True:
                current()
                if value['connection_mode']=='websocket':
                    socket=adapter._haos_feishu_socket
                    if socket is not None and not socket.active:
                        kind=socket.failure;adapter._haos_feishu_socket=None;await socket.close()
                        with private_scope(adapter._haos_feishu_home,adapter._haos_feishu_environment):adapter._mark_disconnected()
                        state=kind if kind in {'authentication-refused','identity-refused','rate-limited','tls-refused'} else 'transport-unavailable'
                        status(state,60 if state=='rate-limited' else backoff)
                        backoff=min(60,backoff*2)
                    row=health(adapter)
                    if adapter._haos_feishu_socket is None and row['status'] not in {'authentication-refused','identity-refused','tls-refused'} and row['next_attempt']<=time.time():
                        try:await open_socket()
                        except asyncio.CancelledError:raise
                        except PermissionError:raise
                        except Exception:
                            socket=adapter._haos_feishu_socket;adapter._haos_feishu_socket=None
                            kind=socket.failure if socket is not None else None
                            if socket is not None:await socket.close()
                            state=kind if kind in {'authentication-refused','identity-refused','rate-limited','tls-refused'} else 'transport-unavailable'
                            status(state,60 if state=='rate-limited' else backoff);backoff=min(60,backoff*2)
                try:
                    if adapter._haos_feishu_receiver is not None:adapter._haos_feishu_receiver.recover()
                    key=native.inbox.due(native.connector)
                    if key is not None:await dispatch_stored(adapter,key)
                    if health(adapter)['status'] in {'storage-unavailable','source-unavailable'}:
                        if value['connection_mode']=='webhook':status('listening-tls')
                        elif adapter._haos_feishu_socket is not None and adapter._haos_feishu_socket.active:status('connected-ws')
                except Refused:
                    current();status('source-unavailable')  # Retain the bounded durable input retry.
                except PermissionError:raise
                except Exception:
                    current();status('storage-unavailable')
                await asyncio.sleep(.2)
        except PermissionError:
            status('revoked')
            async with lifecycle:await stop()
    async def connect(self,**_kwargs):
        from aiohttp import web
        from .gateway_line_tls import context
        from .gateway_feishu_listener import application
        from .gateway_feishu_process import account
        async with lifecycle:
            if self._haos_feishu_closed:raise PermissionError('private Feishu profile closed')
            await stop();current()
            if not callable(getattr(self,'_haos_ingress',None)):
                raise PermissionError('private durable Feishu handler required before listener activation')
            row=health(self)
            if row['status'] in {'identity-refused','authentication-refused'} or row['next_attempt']>time.time():return False
            status('connecting')
            if value['connection_mode']=='webhook':
                try:tls=context(value['tls'],profile,webhook_path='/feishu/webhook')
                except Exception:status('tls-refused');return False
            try:
                result=await account(value,native.connector,current);current()
                if 'error' in result:
                    kind=result['error'];state=kind if kind in STATES else 'transport-unavailable'
                    status(state,60 if state=='rate-limited' else 0);return False
                if value['connection_mode']=='webhook':
                    runner=web.AppRunner(application(self._haos_feishu_receiver),access_log=None,auto_decompress=False,shutdown_timeout=5)
                    self._haos_feishu_runner=runner;await runner.setup()
                    await web.TCPSite(runner,value['tls']['bind_host'],value['port'],ssl_context=tls).start()
                else:
                    await open_socket()
                current()
                with private_scope(self._haos_feishu_home,self._haos_feishu_environment):self._mark_connected()
                status('listening-tls' if value['connection_mode']=='webhook' else 'connected-ws');self._haos_feishu_task=asyncio.create_task(replay());return True
            except asyncio.CancelledError:await stop();raise
            except PermissionError:await stop();status('revoked');raise
            except Exception:
                socket=self._haos_feishu_socket;kind=socket.failure if socket is not None else None
                await stop();state=kind if kind in {'authentication-refused','identity-refused','rate-limited','tls-refused'} else 'transport-unavailable'
                status(state,60 if state=='rate-limited' else 2);return False
    async def disconnect(self):
        async with lifecycle:
            await stop()
            if health(self)['status'] not in {'revoked','closed','identity-refused','authentication-refused','rate-limited','tls-refused'}:status('disconnected')
    async def send(self,chat_id,content,reply_to=None,metadata=None):
        from .gateway_delivery_authority import current_delivery
        if self._haos_feishu_publisher is None:raise PermissionError('creation-only Feishu profile has no outbound authority')
        async with lifecycle:
            authority=current_delivery(self,'feishu',chat_id,metadata)
            binding=native.policy().current_binding(metadata['haos_binding'])
            prepared=metadata.get('haos_output')
            if prepared is not None:
                if not isinstance(prepared,dict) or set(prepared)!={'items','text'} or not isinstance(prepared['items'],list):
                    raise ValueError('exact prepared Feishu output batch required')
                if prepared['items']:
                    return await self._haos_feishu_media_publisher.send(binding,metadata.get('haos_delivery_id'),metadata.get('haos_delivery_attempt'),
                        reply_to,prepared,authority)
                content=prepared['text']
            return await self._haos_feishu_publisher.send(binding,metadata.get('haos_delivery_id'),metadata.get('haos_delivery_attempt'),
                content,reply_to,authority)
    async def close(self):
        async with lifecycle:
            if self._haos_feishu_closed:return
            self._haos_feishu_closed=True;await stop()
            if self._haos_feishu_media_publisher is not None:await self._haos_feishu_media_publisher.close()
            if self._haos_feishu_publisher is not None:await self._haos_feishu_publisher.close()
            if self._haos_feishu_receiver is not None:self._haos_feishu_receiver.close()
            self._haos_feishu_raw.close();os.close(fd)
            if health(self)['status'] not in {'identity-refused','authentication-refused','rate-limited','tls-refused'}:status('closed')
    adapter.connect=MethodType(connect,adapter);adapter.disconnect=MethodType(disconnect,adapter);adapter.send=MethodType(send,adapter)
    adapter.close_profile=MethodType(close,adapter);adapter.native_health=MethodType(health,adapter)
    return adapter
