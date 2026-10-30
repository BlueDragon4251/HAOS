"""Private Buzz text lifecycle; public registration/media/output remain separate."""
import asyncio
import json
import os
from pathlib import Path
import sqlite3
import time
from types import MethodType,SimpleNamespace

from .gateway import Conflict,digest,GatewayPolicy
from .gateway_buzz import credentials,scope as account_scope
from .gateway_buzz_cli import Reader,QueryFailed
from .gateway_buzz_cache import RawEvents
from .gateway_buzz_history import History
from .gateway_buzz_ingress import install,capture,dispatch_stored
from .gateway_buzz_socket import Transport
from .gateway_buzz_admission import Refused

STATES=frozenset({'created','connecting','connected-ws','connected-poll','disconnected','closed','revoked',
    'authentication-refused','identity-refused','rate-limited','transport-unavailable','source-unavailable','storage-unavailable'})
BLOCKS=frozenset({'authentication-refused','identity-refused'})


def build(value,*,parent,connector,policy,inbox):
    from .gateway_runtime import require_runtime_identity
    require_runtime_identity();value=credentials(value)
    def snapshot(latest):
        if not isinstance(latest,GatewayPolicy) or latest.connectors.get(connector,{}).get('platform')!='buzz':
            raise PermissionError('independent prepared Buzz owner policy required')
        bindings=[row for row in latest.bindings.values() if row['connector']==connector]
        if not bindings or any(row['scope']!=account_scope(value) or row['chat'] not in value['channels']
                or row['sender']==value['public_key'] for row in bindings):
            raise PermissionError('exact timed independent Buzz relay account channel and peer grants required')
        if {row['chat'] for row in bindings}!=set(value['channels']):raise PermissionError('each selected Buzz channel requires an independent grant')
        return digest([latest.publication,connector,sorted(bindings,key=lambda row:row['id']),value])
    identity=snapshot(policy())
    def pinned():
        latest=policy()
        if snapshot(latest)!=identity:raise PermissionError('Buzz publication account or grants changed')
        return latest
    from .gateway_line_profile import _directory
    from .gateway_matrix_profile import acquire_lease,scope
    parent=Path(parent);_directory(parent)
    # Identity lease is shared across connector IDs: the same relay identity
    # cannot be driven by two private adapters with split replay state.
    profile=parent/('buzz-'+digest([value['relay_url'],value['public_key']]))
    try:profile.mkdir(mode=0o700)
    except FileExistsError:pass
    lease=acquire_lease(profile);originals=None;history=None
    try:
        home=profile/'home'
        try:home.mkdir(mode=0o700)
        except FileExistsError:pass
        _directory(home)
        from .redaction import Redactor
        aliases=[value['private_key'],value.get('auth_tag','')]
        if value.get('auth_tag'):
            tag=json.loads(value['auth_tag']);aliases.extend([repr(tag),*[json.dumps(tag,ensure_ascii=ascii) for ascii in (True,False)]])
        # Preserve the shared formatter/relay Redactor object. Replace its list
        # atomically, so an existing logger iterator retains all previous aliases.
        inbox.redactor.secrets=Redactor([*inbox.redactor.secrets,*aliases]).secrets
        environment={'HERMES_SAFE_MODE':'1','BUZZ_PRIVATE_KEY':value['private_key'],'BUZZ_RELAY_URL':value['relay_url'],
            'BUZZ_AUTH_TAG':value.get('auth_tag',''),'BUZZ_ALLOWED_USERS':','.join(sorted({row['sender'] for row in pinned().bindings.values() if row['connector']==connector})),
            'BUZZ_CHANNELS':','.join(value['channels']),'BUZZ_CLI_PATH':'/usr/lib/haos/buzz/buzz','BUZZ_REQUIRE_MENTION':'false',
            'BUZZ_TRANSPORT':'websocket','BUZZ_HOME_CHANNEL':'','GATEWAY_ALLOW_ALL_USERS':'false'}
        with scope(home,environment):
            from gateway.config import PlatformConfig
            from plugins.platforms.buzz import adapter as native
            from .gateway_ingress import durable_adapter
            adapter=install(durable_adapter(native.BuzzAdapter(PlatformConfig(enabled=True,extra={
                'relay_url':value['relay_url'],'channels':value['channels'],'cli_path':'/usr/lib/haos/buzz/buzz',
                'require_mention':False,'transport':'websocket'}))))
        adapter._haos_native=SimpleNamespace(connector=connector,policy=pinned,inbox=inbox)
        adapter._haos_buzz_value=value;adapter._haos_buzz_home=home;adapter._haos_buzz_environment=environment
        adapter._haos_buzz_closed=False;adapter._haos_buzz_stop_requested=False
        adapter._private_key=value['private_key'];adapter._auth_tag=value.get('auth_tag','')
        adapter._self_pubkey=value['public_key'];adapter._self_npub=native.hex_to_npub(value['public_key'])
        adapter._allowed_pubkeys={row['sender'] for row in pinned().bindings.values() if row['connector']==connector}
        def current():
            if adapter._haos_buzz_closed or adapter._haos_buzz_stop_requested:raise PermissionError('private Buzz profile stopped')
            latest=pinned()
            if (adapter.relay_url!=value['relay_url'] or adapter.channels!=value['channels'] or adapter._private_key!=value['private_key']
                    or adapter._self_pubkey!=value['public_key'] or adapter._auth_tag!=value.get('auth_tag','')
                    or adapter.cli_path!='/usr/lib/haos/buzz/buzz' or adapter.require_mention is not False):
                raise PermissionError('native Buzz credential relay or selected channels changed')
            return latest
        adapter._haos_buzz_check=current
        reader=Reader(connector,value,current,inbox.redactor);reader.home=home
        adapter._haos_buzz_reader=reader;adapter._run_cli=reader.run
        # Include the native decoded scalar too when owner input used nsec.
        from plugins.platforms.buzz.nostr_auth import decode_private_key
        inbox.redactor.secrets=Redactor([*inbox.redactor.secrets,format(decode_private_key(value['private_key']),'064x')]).secrets
        originals=RawEvents(profile/'originals.db',inbox.redactor,current);adapter._haos_buzz_raw=originals
        async def original(channel,event):
            if channel is None:return False  # Membership is not an independent owner grant.
            return await capture(adapter,channel,event)
        transport=Transport(value,current,original);adapter._haos_buzz_transport=transport;adapter._open_websocket=transport.open
        history=History(profile/'history.db',reader,inbox.redactor,original);adapter._haos_buzz_history=history
        return _lifecycle(adapter,lease,identity)
    except BaseException:
        if history is not None:history.close()
        if originals is not None:originals.close()
        os.close(lease);raise


def _lifecycle(adapter,lease,identity):
    native=adapter._haos_native;db=native.inbox.db;value=adapter._haos_buzz_value
    reader=adapter._haos_buzz_reader;transport=adapter._haos_buzz_transport
    check=adapter._haos_buzz_check;scope=digest([native.connector,value]);lifecycle=asyncio.Lock()
    from .gateway_buzz_delivery import Publisher
    publisher=Publisher(adapter) if any(row['connector']==native.connector and 'read' in row['capabilities'] for row in native.policy().bindings.values()) else None
    adapter._haos_buzz_publisher=publisher
    from .gateway_buzz_output import Output
    adapter._haos_buzz_output=Output(adapter)
    adapter._haos_buzz_monitor=None;adapter._haos_buzz_replay=None
    db.execute('''CREATE TABLE IF NOT EXISTS buzz_profile_status(identity TEXT PRIMARY KEY,connector TEXT NOT NULL,
        credential_scope TEXT NOT NULL,status TEXT NOT NULL,updated_at REAL NOT NULL,next_attempt REAL NOT NULL)''')
    prior=db.execute('SELECT status,next_attempt FROM buzz_profile_status WHERE connector=? AND credential_scope=?',(native.connector,scope)).fetchall()
    blocked=next((row['status'] for row in prior if row['status'] in BLOCKS),None)
    deadline=max([row['next_attempt'] for row in prior]+[0])
    db.execute('INSERT OR IGNORE INTO buzz_profile_status VALUES(?,?,?,?,?,?)',(identity,native.connector,scope,blocked or 'created',time.time(),deadline))
    if blocked:db.execute('UPDATE buzz_profile_status SET status=?,next_attempt=0 WHERE identity=?',(blocked,identity))
    def status(state,delay=0):
        if state not in STATES:raise ValueError('finite private Buzz lifecycle status required')
        db.execute('UPDATE buzz_profile_status SET status=?,updated_at=?,next_attempt=? WHERE identity=?',
            (state,time.time(),time.time()+delay if delay else 0,identity))
    def health(self):
        return dict(db.execute('SELECT connector,status,updated_at,next_attempt FROM buzz_profile_status WHERE identity=?',(identity,)).fetchone())
    async def stop():
        tasks=[]
        for name in ['_haos_buzz_monitor','_haos_buzz_replay']:
            task=getattr(adapter,name);setattr(adapter,name,None)
            if task is not None and task is not asyncio.current_task():task.cancel();tasks.append(task)
        if tasks:await asyncio.gather(*tasks,return_exceptions=True)
        ready=getattr(adapter,'_ws_ready',None)
        if ready is not None:ready.set()
        await transport.close()
        from plugins.platforms.buzz.adapter import BuzzAdapter
        await BuzzAdapter.disconnect(adapter)
    def classify(error):
        if reader.authentication_refused or transport.authentication_refused:return 'authentication-refused'
        if isinstance(error,QueryFailed) and error.category=='identity_mismatch':return 'identity-refused'
        if isinstance(error,QueryFailed) and error.category=='rate_limited':return 'rate-limited'
        if isinstance(error,sqlite3.Error):return 'storage-unavailable'
        if isinstance(error,Conflict):return 'source-unavailable'
        return 'transport-unavailable'
    async def monitor():
        while True:
            if adapter._haos_buzz_stop_requested:return
            try:check()
            except PermissionError:
                status('revoked');adapter._haos_buzz_stop_requested=True;await stop();return
            if reader.authentication_refused or transport.authentication_refused:
                status('authentication-refused');adapter._haos_buzz_stop_requested=True;await stop();return
            state=health(adapter)['status']
            if state in {'connected-ws','connected-poll'}:
                status('connected-ws' if any(connection.authenticated for connection in transport.connections) else 'connected-poll')
            await asyncio.sleep(.1)
    async def recover():
        while True:
            check()
            wait=health(adapter)['next_attempt']-time.time()
            if wait>0:
                await asyncio.sleep(min(wait,2));continue
            try:
                for channel in value['channels']:
                    await adapter._haos_buzz_history.step(channel)
                # Originals and local admission use separate FULL transactions.
                # Recover their gap before any original is declared dispatched.
                rows=adapter._haos_buzz_raw.db.execute('SELECT data FROM buzz_raw_events WHERE connector=? AND admitted_receipt=? ORDER BY created_at LIMIT 128',
                    (native.connector,'')).fetchall()
                for row in rows:
                    if not isinstance(row['data'],bytes) or not row['data']:raise Conflict('Buzz original removed; inspected recovery required')
                    event=json.loads(bytes(row['data']));channels=[tag[1] for tag in event['tags'] if tag[0]=='h' and len(tag)>=2]
                    if len(channels)!=1:raise Conflict('retained Buzz original lost exact channel')
                    await capture(adapter,channels[0],event)
                for _ in range(16):
                    check();key=native.inbox.due(native.connector)
                    if key is None:break
                    await dispatch_stored(adapter,key)
                if (health(adapter)['status'] in {'transport-unavailable','storage-unavailable','rate-limited'}
                        and not native.inbox.db.execute("SELECT 1 FROM native_inbox WHERE connector=? AND state='failed'",(native.connector,)).fetchone()):
                    status('connected-ws' if any(connection.authenticated for connection in transport.connections) else 'connected-poll')
            except asyncio.CancelledError:raise
            except Refused as error:
                check();status('rate-limited' if error.reason=='resource-rate-limited' else 'source-unavailable',error.retry_after or 2)
            except PermissionError:
                # A media source deliberately remains pending, never downgraded
                # into text by this unfinished private text profile.
                check();status('source-unavailable',2)
            except Exception as error:
                check();kind=classify(error);status(kind,60 if kind=='rate-limited' else 2)
                if reader.authentication_refused:return
            await asyncio.sleep(2)
    async def connect(self):
        async with lifecycle:
            if self._haos_buzz_closed:raise PermissionError('private Buzz profile closed')
            row=health(self)
            if row['status'] in BLOCKS|{'revoked'} or row['next_attempt']>time.time():return False
            if self._haos_buzz_monitor is not None:return True
            self._haos_buzz_stop_requested=False;check();status('connecting')
            self._haos_buzz_monitor=asyncio.create_task(monitor())
            try:
                _,out,_=await reader.run(['users','get']);profile=json.loads(out)[0]
                name=profile.get('display_name') or ''
                if not isinstance(name,str) or len(name.encode())>1024:raise QueryFailed('identity_mismatch')
                self._display_name=name
                _,out,_=await reader.run(['channels','list']);channels=json.loads(out)
                self._channel_names={row['channel_id']:str(row.get('name') or row['channel_id']) for row in channels}
                self._channel_meta={row['channel_id']:row for row in channels}
                self._channel_state={channel:self._new_channel_state('group') for channel in value['channels']}
                from .gateway_matrix_profile import scope as private_scope
                from plugins.platforms.buzz.adapter import BuzzAdapter
                with private_scope(self._haos_buzz_home,self._haos_buzz_environment):
                    websocket=await BuzzAdapter._start_websocket(self)
                check()
                if transport.authentication_refused:raise QueryFailed('authentication_refused')
                self._haos_buzz_replay=asyncio.create_task(recover())
                with private_scope(self._haos_buzz_home,self._haos_buzz_environment):self._mark_connected()
                status('connected-ws' if websocket else 'connected-poll');return True
            except asyncio.CancelledError:
                await stop();raise
            except Exception as error:
                await stop()
                if health(self)['status'] not in BLOCKS|{'revoked'}:
                    kind='disconnected' if self._haos_buzz_stop_requested else classify(error)
                    status(kind,60 if kind=='rate-limited' else 2)
                return False
    async def disconnect(self):
        self._haos_buzz_stop_requested=True
        ready=getattr(self,'_ws_ready',None)
        if ready is not None:ready.set()
        async with lifecycle:
            await stop()
            if health(self)['status'] not in BLOCKS|{'revoked','closed'}:status('disconnected')
    async def close(self):
        self._haos_buzz_stop_requested=True
        ready=getattr(self,'_ws_ready',None)
        if ready is not None:ready.set()
        async with lifecycle:
            if self._haos_buzz_closed:return
            await stop();self._haos_buzz_closed=True
            if publisher is not None:await publisher.close()
            self._haos_buzz_history.close();self._haos_buzz_raw.close();os.close(lease)
            if health(self)['status'] not in BLOCKS|{'revoked'}:status('closed')
    async def send(self,chat_id,content,reply_to=None,metadata=None):
        from .gateway_delivery_authority import current_delivery
        authority=current_delivery(self,'buzz',chat_id,metadata)
        if publisher is None:raise PermissionError('creation-only Buzz profile has no reply authority')
        binding=native.policy().current_binding(metadata['haos_binding'])
        return await publisher.send(binding,metadata.get('haos_delivery_id'),metadata.get('haos_delivery_attempt'),content,reply_to,authority,
            prepared=metadata.get('haos_output'))
    for name,method in {'connect':connect,'disconnect':disconnect,'_haos_close':close,'_haos_health':health,
            'close_profile':close,'native_health':health,'send':send}.items():
        setattr(adapter,name,MethodType(method,adapter))
    return adapter
