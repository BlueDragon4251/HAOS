"""Private prepared native Feishu HTTPS profile with durable replay and revocation.

Public registry, outgoing transport and socket-mode activation remain separate.
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

STATES=frozenset({'created','connecting','listening-tls','storage-unavailable','tls-refused',
    'identity-refused','authentication-refused','source-unavailable','rate-limited','transport-unavailable','revoked','disconnected','closed'})


def build(value,*,parent,connector,policy,inbox):
    from .gateway_runtime import require_runtime_identity
    require_runtime_identity();value=credentials(value,verify_tls=False)
    if value['connection_mode']!='webhook':raise PermissionError('only reviewed prepared Feishu HTTPS profile is connected')
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
        inbox.redactor=Redactor([*inbox.redactor.secrets,value['app_secret'],value['verification_token'],
            value['encrypt_key'],value['tls']['private_key']])
        env={'HERMES_SAFE_MODE':'1','FEISHU_APP_ID':value['app_id'],'FEISHU_APP_SECRET':value['app_secret'],
            'FEISHU_DOMAIN':value['domain'],'FEISHU_CONNECTION_MODE':'webhook','FEISHU_BOT_OPEN_ID':value['bot_open_id'],
            'FEISHU_ENCRYPT_KEY':value['encrypt_key'],'FEISHU_VERIFICATION_TOKEN':value['verification_token'],
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
                if getattr(adapter,'_'+field)!=value[key]:raise PermissionError('native Feishu credential identity changed')
        adapter._haos_feishu_check=current
        originals=RawEvents(profile/'originals.db',inbox.redactor,current);adapter._haos_feishu_raw=originals
        receiver=Receiver(adapter,profile/'webhooks.db');adapter._haos_feishu_receiver=receiver
        return _install(adapter,fd,profile,initial)
    except BaseException:
        if receiver is not None:receiver.close()
        if originals is not None:originals.close()
        os.close(fd);raise


def _install(adapter,fd,profile,identity):
    native=adapter._haos_native;value=adapter._haos_feishu_value;db=native.inbox.db;current=adapter._haos_feishu_check
    from .gateway_feishu_delivery import Publisher
    publisher=Publisher(adapter) if any(row['connector']==native.connector and 'read' in row['capabilities'] for row in native.policy().bindings.values()) else None
    adapter._haos_feishu_publisher=publisher
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
        runner=adapter._haos_feishu_runner;adapter._haos_feishu_runner=None
        if runner is not None:await runner.cleanup()
        adapter._mark_disconnected()
    async def replay():
        try:
            while True:
                current()
                try:
                    adapter._haos_feishu_receiver.recover()
                    key=native.inbox.due(native.connector)
                    if key is not None:await dispatch_stored(adapter,key)
                    if health(adapter)['status'] in {'storage-unavailable','source-unavailable'}:status('listening-tls')
                except Refused:
                    current();status('source-unavailable')  # Unsupported owned input keeps its bounded durable retry state.
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
            try:tls=context(value['tls'],profile,webhook_path='/feishu/webhook')
            except Exception:status('tls-refused');return False
            try:
                result=await account(value,native.connector,current);current()
                if 'error' in result:
                    kind=result['error'];state=kind if kind in STATES else 'transport-unavailable'
                    status(state,60 if state=='rate-limited' else 0);return False
                runner=web.AppRunner(application(self._haos_feishu_receiver),access_log=None,auto_decompress=False,shutdown_timeout=5)
                self._haos_feishu_runner=runner;await runner.setup()
                await web.TCPSite(runner,value['tls']['bind_host'],value['port'],ssl_context=tls).start()
                current();self._mark_connected();status('listening-tls');self._haos_feishu_task=asyncio.create_task(replay());return True
            except asyncio.CancelledError:await stop();raise
            except PermissionError:await stop();status('revoked');raise
            except Exception:await stop();status('transport-unavailable');return False
    async def disconnect(self):
        async with lifecycle:
            await stop()
            if health(self)['status'] not in {'revoked','closed','identity-refused','authentication-refused','rate-limited','tls-refused'}:status('disconnected')
    async def send(self,chat_id,content,reply_to=None,metadata=None):
        from .gateway_delivery_authority import current_delivery
        if self._haos_feishu_publisher is None:raise PermissionError('creation-only Feishu profile has no outbound authority')
        if isinstance(metadata,dict) and metadata.get('haos_output') is not None:
            raise PermissionError('Feishu output media is not connected to a private reviewed byte path')
        async with lifecycle:
            authority=current_delivery(self,'feishu',chat_id,metadata)
            binding=native.policy().current_binding(metadata['haos_binding'])
            return await self._haos_feishu_publisher.send(binding,metadata.get('haos_delivery_id'),metadata.get('haos_delivery_attempt'),
                content,reply_to,authority)
    async def close(self):
        async with lifecycle:
            if self._haos_feishu_closed:return
            self._haos_feishu_closed=True;await stop()
            if self._haos_feishu_publisher is not None:await self._haos_feishu_publisher.close()
            self._haos_feishu_receiver.close();self._haos_feishu_raw.close();os.close(fd)
            if health(self)['status'] not in {'identity-refused','authentication-refused','rate-limited','tls-refused'}:status('closed')
    adapter.connect=MethodType(connect,adapter);adapter.disconnect=MethodType(disconnect,adapter);adapter.send=MethodType(send,adapter)
    adapter.close_profile=MethodType(close,adapter);adapter.native_health=MethodType(health,adapter)
    return adapter
