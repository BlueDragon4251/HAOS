"""Private installed-identity A2A lifecycle; public owner activation is separate."""
import asyncio
import os
from pathlib import Path
import time
from types import SimpleNamespace

from .gateway import digest,Conflict
from .gateway_a2a import credentials,scope,PreparedA2APolicy,authority
from .gateway_a2a_cache import RawEvents
from .gateway_a2a_tasks import Tasks
from .gateway_a2a_native import build as native_build
from .gateway_a2a_ingress import dispatch
from .gateway_a2a_publisher import Publisher
from .gateway_a2a_server import Server

STATES=frozenset({'created','connecting','listening','disconnected','revoked','storage-unavailable','transport-unavailable','closed'})


def build(value,*,parent,connector,policy,inbox):
    # No upstream import or credential use before the actual dedicated UID gate.
    from .gateway_runtime import require_runtime_identity,prepare_runtime_home
    require_runtime_identity();prepare_runtime_home();value=credentials(value)
    def snapshot():
        latest=policy()
        if not isinstance(latest,PreparedA2APolicy) or latest.connectors.get(connector,{}).get('platform')!='a2a':
            raise PermissionError('prepared independent A2A owner policy required')
        bindings=[row for row in latest.bindings.values() if row['connector']==connector]
        if not bindings or any(row['sender'] not in value['peer_tokens'] or row['scope']!=scope(value,row['sender']) for row in bindings):
            raise PermissionError('exact timed A2A peer/context grants matching saved server identity required')
        return digest([latest.publication,connector,bindings,value])
    initial=snapshot();publication=authority(connector,value)
    closed=[False];stopping=[False];revoke_notice=[None]
    def pinned():
        if closed[0] or stopping[0]:raise PermissionError('private A2A profile stopped')
        try:
            if snapshot()!=initial:raise PermissionError('A2A profile grant or credential epoch changed')
            authority(connector,value,publication);return policy()
        except PermissionError:
            if revoke_notice[0] is not None:revoke_notice[0]()
            raise
    from .gateway_line_profile import _directory
    from .gateway_matrix_profile import acquire_lease,scope as private_scope
    parent=Path(parent);_directory(parent);profile=parent/('a2a-'+digest([connector,value]))
    try:profile.mkdir(mode=0o700)
    except FileExistsError:pass
    try:lease=acquire_lease(profile)
    except PermissionError:raise PermissionError('private A2A profile lease unavailable or already in use') from None
    originals=None;indexes={};peers={};publishers={};homes={}
    try:
        from .redaction import Redactor
        secrets={*value['peer_tokens'].values(),value['tls']['private_key']}
        import json
        for _ in range(2):secrets|={json.dumps(s,ensure_ascii=a)[1:-1] for s in tuple(secrets) for a in (True,False)}
        inbox.redactor=Redactor([*inbox.redactor.secrets,*secrets])
        originals=RawEvents(profile/'originals.db',inbox.redactor,pinned)
        for peer in value['peer_tokens']:
            home=profile/('peer-'+digest(peer))
            try:home.mkdir(mode=0o700)
            except FileExistsError:pass
            _directory(home);homes[peer]=home
            indexes[peer]=Tasks(home/'tasks.db',peer,value,pinned,policy,connector=connector)
        from gateway.config import PlatformConfig,Platform
        from gateway.platforms.base import BasePlatformAdapter
        from .gateway_ingress import durable_adapter
        class Facade(BasePlatformAdapter):
            async def connect(self,**kwargs):return await open_listener()
            async def disconnect(self):await disconnect()
            async def send(self,chat_id,content,reply_to=None,metadata=None):
                from .gateway_delivery_authority import current_delivery
                current=current_delivery(self,'a2a',chat_id,metadata);current();pinned()
                selected=[peer for peer in peers if scope(value,peer)==metadata['haos_scope']]
                if len(selected)!=1:raise PermissionError('exact A2A controller destination peer required')
                result=await publishers[selected[0]].send(chat_id,content,reply_to,metadata)
                current();pinned();return result
            async def get_chat_info(self,chat_id):
                pinned()
                if not any(row['connector']==connector and row['chat']==chat_id for row in policy().bindings.values()):
                    raise PermissionError('independently approved A2A context required')
                return {'name':chat_id,'type':'dm'}
            async def close_profile(self):await close()
            def health(self):return health()
        with private_scope(profile,{'HERMES_SAFE_MODE':'1'}):
            facade=durable_adapter(Facade(PlatformConfig(enabled=True),Platform('a2a')))
        facade._haos_native=SimpleNamespace(connector=connector,policy=pinned,inbox=inbox)
        facade._haos_a2a_profile=profile;facade._haos_a2a_indexes=indexes;facade._haos_a2a_peers=peers
        facade._haos_a2a_originals=originals
        facade._haos_a2a_check=pinned
        from .gateway_a2a_output import Output
        facade._haos_a2a_output=Output(facade)
        def mark(connected):
            with private_scope(profile,{'HERMES_SAFE_MODE':'1'}):
                if connected:facade._mark_connected(listener_base=value['tls']['public_url'])
                else:facade._mark_disconnected()
        db=originals.db
        db.execute('''CREATE TABLE IF NOT EXISTS a2a_profile_status(
            identity TEXT PRIMARY KEY,connector TEXT NOT NULL,status TEXT NOT NULL,updated_at REAL NOT NULL)''')
        db.execute('INSERT OR IGNORE INTO a2a_profile_status VALUES(?,?,?,?)',(initial,connector,'created',time.time()))
        def status(state):
            if state not in STATES:raise ValueError('finite private A2A status required')
            db.execute('UPDATE a2a_profile_status SET status=?,updated_at=? WHERE identity=?',(state,time.time(),initial))
        def health():
            result=dict(db.execute('SELECT connector,status,updated_at FROM a2a_profile_status WHERE identity=?',(initial,)).fetchone())
            failure=listener[0].failure if listener[0] is not None else None
            known={'PermissionError','Conflict','TimeoutError','OSError','RuntimeError','ValueError','AttributeError','KeyError','TypeError','OperationalError','IntegrityError'}
            result['transport_error']=failure if failure is None or failure in known else 'transport-unavailable'
            result['attachment_error']=resource_error[0]
            return result
        announced=[False]
        def revoked():
            if not announced[0]:
                announced[0]=True;status('revoked');mark(False)
        revoke_notice[0]=revoked
        from .gateway_a2a_resources import Resources,Refused as ResourceRefused
        resources=Resources(value,connector,policy,pinned,originals,inbox);resource_error=[None];ingress_locks={}
        listener=[None];worker=[None];lock=asyncio.Lock();close_task=[None]

        async def receive(event,proof,task_id):
            async with ingress_locks.setdefault(proof['source_key'],asyncio.Lock()):
                return await receive_retained(event,proof,task_id)

        async def receive_retained(event,proof,task_id):
            pinned();peer=proof['envelope']['sender'];index=indexes[peer];native=peers[peer]
            actual=originals.get(policy(),connector,value,peer,proof['id'])
            if actual!=proof:raise Conflict('native A2A input no longer matches original custody')
            row=native._haos_a2a_lookup(proof)
            if row is None or row['task_id']!=task_id:raise Conflict('native A2A input changed task/source mapping')
            key=inbox.admit(policy(),connector,proof['envelope'],{'raw_id':proof['id'],'task_id':task_id},received_at=proof['received_at'])
            retained=inbox.db.execute('SELECT state FROM native_inbox WHERE id=?',(key,)).fetchone()
            if retained is not None and retained['state']=='committed':return key
            claimed=inbox.claim(key,policy())
            if claimed is None:raise Conflict('native A2A parent input requires retained-source recovery')
            try:
                parent_event=event
                media=await resources.retained(proof) if proof.get('resources') else []
                if media:
                    from gateway.platforms.event import MessageEvent,MessageType
                    kinds={item['kind'] for item in media}
                    kind=MessageType.PHOTO if kinds=={'image'} else MessageType.VOICE if kinds=={'voice'} else MessageType.VIDEO if kinds=={'video'} else MessageType.DOCUMENT
                    parent_event=MessageEvent(text=event.text,message_type=kind,message_id=event.message_id,source=event.source,
                        media_urls=['haos-media:'+item['id'] for item in media],media_types=[item['mime'] for item in media])
                    from .gateway_media_relay import event_scope
                    with dispatch(native,event,proof,parent_event=parent_event),event_scope(parent_event,[item['id'] for item in media],parent_event.media_types,platform='a2a'):
                        facade._haos_admit(parent_event)
                else:
                    with dispatch(native,event,proof):facade._haos_admit(event)
                if parent_event._gateway_accepted is not True:raise PermissionError('private A2A parent relay did not commit input')
                resource_error[0]=None
                pinned();inbox.complete(key,True);return key
            except ResourceRefused as error:
                resource_error[0]=error.reason;inbox.retry(key);raise
            except BaseException:
                inbox.retry(key);raise

        def rebuild():
            peers.clear();publishers.clear()
            for peer,index in indexes.items():
                peers[peer]=native_build(value,peer,homes[peer],pinned,policy,index,receive)
                publishers[peer]=Publisher(peers[peer],index)
        async def capture(peer,data):
            pinned();return originals.capture(policy(),connector,value,peer,data)
        async def cancel(native,source):
            pinned();peer=source['peer']
            if peers.get(peer) is not native:raise PermissionError('exact current native A2A cancellation peer required')
            from .gateway_a2a_controls import Controls
            result=await Controls(indexes[peer],originals,value,connector,policy).cancel(source)
            pinned();return result
        async def recover():
            while True:
                try:
                    pinned()
                    if listener[0] is None or listener[0].closed:
                        mark(False);return
                    for peer,index in indexes.items():
                        selection=index.selection()
                        if selection is None:continue
                        where,args=selection
                        from plugins.platforms.a2a.protocol import STATE_WORKING
                        # Native create commits SUBMITTED before its anti-loop/
                        # readiness checks. Only WORKING proves preparation got
                        # past those checks; never synthesize an early dispatch
                        # from an intermediate or terminal native record.
                        rows=index.db.execute('SELECT * FROM a2a_tasks WHERE '+where+" AND admitted_receipt='' AND json_extract(record,'$.state')=? "
                            "ORDER BY updated_at LIMIT 128",[*args,STATE_WORKING]).fetchall()
                        holders=','.join('?' for _ in args[3:])
                        rows=[*rows,*index.db.execute("SELECT i.task_id,i.raw_id FROM a2a_task_inputs i JOIN a2a_tasks t ON t.task_id=i.task_id "
                            "WHERE i.admitted_receipt='' AND t.connector=? AND t.peer=? AND t.credential_scope=? AND t.binding_digest IN ("+holders+
                            ") AND json_extract(t.record,'$.state')=? ORDER BY i.created_at LIMIT 32",[*args,STATE_WORKING]).fetchall()]
                        for row in rows:
                            proof=originals.get(policy(),connector,value,peer,row['raw_id'])
                            native=peers[peer]
                            source=native._haos_a2a_lookup(proof)
                            if source is None:raise Conflict('retained A2A input lost its native task mapping')
                            from gateway.platforms.event import MessageEvent,MessageType
                            event=MessageEvent(text=proof['envelope']['text'],message_type=MessageType.TEXT,message_id=row['task_id'],
                                source=native.build_source(chat_id=source['context_id'],user_id=peer,user_name=peer,chat_type='dm',chat_name='a2a:'+peer))
                            with index.source(connector,proof):await native.handle_message(event)
                    status('listening')
                except asyncio.CancelledError:raise
                except PermissionError:
                    try:pinned()
                    except PermissionError:
                        status('revoked');mark(False)
                        if listener[0] is not None:await listener[0].close()
                        return
                    status('storage-unavailable')
                except Exception:status('storage-unavailable')
                await asyncio.sleep(.2)
        async def halt():
            task=worker[0];worker[0]=None
            if task is not None:
                task.cancel();await asyncio.gather(task,return_exceptions=True)
            server=listener[0];listener[0]=None
            if server is not None:await server.close()
            else:
                for native in peers.values():await native.close_profile()
            mark(False)
        async def open_listener():
            async with lock:
                if closed[0]:raise PermissionError('private A2A profile closed')
                stopping[0]=False;pinned()
                if not callable(getattr(facade,'_haos_ingress',None)):
                    raise PermissionError('durable A2A parent relay must be installed before listening')
                if listener[0] is not None and not listener[0].closed:return True
                await halt();status('connecting')
                try:
                    rebuild()
                    from .gateway_line_tls import context
                    tls=context(value['tls'],profile,webhook_path='/a2a')
                    listener[0]=Server(value,connector,dict(peers),pinned,policy,capture,cancel=cancel)
                    listener[0].start(tls);pinned();mark(True);status('listening')
                    worker[0]=asyncio.create_task(recover());return True
                except BaseException:
                    await halt();status('transport-unavailable');raise
        async def disconnect():
            stopping[0]=True
            async with lock:
                await halt()
                if not closed[0]:status('disconnected')
        async def cleanup():
            async with lock:
                try:await halt();status('closed')
                finally:
                    for index in indexes.values():index.close()
                    originals.close();os.close(lease)
        async def close():
            closed[0]=True;stopping[0]=True
            if close_task[0] is None:close_task[0]=asyncio.create_task(cleanup())
            await asyncio.shield(close_task[0])
        pinned();return facade
    except BaseException:
        for index in indexes.values():index.close()
        if originals is not None:originals.close()
        os.close(lease);raise
