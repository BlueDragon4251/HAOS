#!/usr/bin/env python3
"""Actual Matrix SDK/native codec into independent HAOS grants and durable mission engine."""
import asyncio
from copy import deepcopy
import json
import os
from pathlib import Path
import sqlite3
import sys
import tempfile
import time
from types import SimpleNamespace


def main():
    root=Path(sys.argv[1]).resolve();sys.path.insert(0,str(root))
    from aiohttp import ClientSession,web
    from mautrix.api import HTTPAPI
    from mautrix.client import Client
    from mautrix.client.state_store import MemoryStateStore
    from mautrix.crypto import OlmMachine
    from mautrix.crypto.store.asyncpg import PgCryptoStore
    from mautrix.types import UserID,DeviceID,RoomID,EventType,DeviceIdentity,TrustState,RoomEncryptionStateEventContent,EncryptionAlgorithm,Event
    from mautrix.util.async_db import Database
    from gateway.config import PlatformConfig
    from plugins.platforms.matrix.adapter import MatrixAdapter,_CryptoStateStore
    from haos.gateway import GatewayPolicy,GatewayEngine,digest
    from haos.gateway_matrix_policy import PreparedMatrixPolicy,snapshot
    from haos.gateway_matrix_sync import SyncJournal,receive_sync,dispatch_page,DeferredDispatch,verified_crypto
    from haos.gateway_matrix_ingress import install,attach_client,capture,dispatch_stored
    from haos.gateway_ingress import durable_adapter
    from haos.gateway_runtime import adapter_envelope
    from haos.gateway_raw import NativeInbox
    from haos.gateway_relay import RelayInbox
    from haos.redaction import Redactor
    from haos.store import MissionStore
    cases=[]
    async def exercise(directory):
        os.environ['HERMES_HOME']=str(directory/'home')
        bot='@haos:owner.invalid';peer='@owner:owner.invalid';room='!private:owner.invalid';thread='$root'
        device='OWNER_PHONE';now=int(time.time()*1000)
        state={'payload':None,'fail_receiver':False};dbs=[]
        async def api(request):
            assert request.headers['Authorization']=='Bearer disposable-private-token'
            if request.path.endswith('/sync'):return web.json_response(state['payload'])
            if request.path.endswith('/keys/upload'):
                await request.json();return web.json_response({'one_time_key_counts':{'signed_curve25519':50}})
            raise AssertionError('unapproved private Matrix API '+request.path)
        app=web.Application();app.router.add_route('*','/_matrix/client/v3/{tail:.*}',api)
        runner=web.AppRunner(app);await runner.setup();site=web.TCPSite(runner,'127.0.0.1',0);await site.start()
        port=site._server.sockets[0].getsockname()[1]
        async def store(name,user):
            db=Database.create('sqlite:///'+str(directory/name),upgrade_table=PgCryptoStore.upgrade_table)
            await db.start();dbs.append(db)
            value=PgCryptoStore(account_id=user,pickle_key='disposable-fixture-key',db=db);await value.open();return value
        journal=SyncJournal(directory/'sync.db','a'*64);raw=NativeInbox(directory/'native.db',Redactor())
        relay=RelayInbox(directory/'relay.db',Redactor());missions=MissionStore(directory/'missions.db');engine=GatewayEngine(missions)
        counter=0;observed=[]
        try:
            async with ClientSession(trust_env=False) as session:
                def client(user,dev):
                    return Client(mxid=UserID(user),device_id=DeviceID(dev),api=HTTPAPI(base_url=f'http://127.0.0.1:{port}',
                        token='disposable-private-token',client_session=session),state_store=MemoryStateStore())
                sender=client(peer,device);sender_store=await store('sender-crypto.db',peer)
                await sender.state_store.set_encryption_info(RoomID(room),RoomEncryptionStateEventContent(algorithm=EncryptionAlgorithm.MEGOLM_V1))
                peer_crypto=OlmMachine(sender,sender_store,_CryptoStateStore(sender.state_store,{RoomID(room)},sender))
                await peer_crypto.load();await peer_crypto.share_group_session(RoomID(room),[])
                actual=client(bot,'HAOS');receiver_store=await store('receiver-crypto.db',bot)
                receiver_crypto=OlmMachine(actual,receiver_store,_CryptoStateStore(actual.state_store,{RoomID(room)},actual))
                await receiver_crypto.load();actual.crypto=receiver_crypto
                await receiver_store.put_devices(UserID(peer),{DeviceID(device):DeviceIdentity(user_id=UserID(peer),device_id=DeviceID(device),
                    identity_key=peer_crypto.account.identity_key,signing_key=peer_crypto.account.signing_key,
                    trust=TrustState.VERIFIED,deleted=False,name='Explicit local fixture owner device')})
                pin={'device_id':device,'ed25519':str(peer_crypto.account.signing_key),'curve25519':str(peer_crypto.account.identity_key)}
                config={'version':1,'connectors':[{'id':'bot','platform':'matrix'}],'bindings':[
                    {'id':'paired','connector':'bot','sender':peer,'chat':room,'scope':'','thread':'',
                     'identity':'principal','capabilities':['create','read'],'generation':'a'*64,'since':now-10000,
                     'allow_plaintext':False,'require_mention':True,'matrix_devices':[pin]}]}
                current=lambda:PreparedMatrixPolicy(deepcopy(config))
                assert GatewayPolicy(config).bindings==current().bindings
                cases.append('installed_controller_enforces_same_exact_owner_matrix_grants')
                adapter=install(durable_adapter(MatrixAdapter(PlatformConfig(enabled=True,token='disposable-private-token',extra={
                    'homeserver':'https://owner.invalid','user_id':bot,'device_id':'HAOS','e2ee_mode':'required'}))))
                adapter._client=actual;adapter._haos_native=SimpleNamespace(inbox=raw,connector='bot',policy=current)
                attach_client(adapter,actual)
                def receive(event):
                    envelope=adapter_envelope(event,'matrix')
                    with sqlite3.connect(directory/'native.db') as observer:
                        assert observer.execute('SELECT state FROM native_inbox WHERE message_id=?',(envelope['message_id'],)).fetchone()[0]=='processing'
                    if state['fail_receiver']:raise ConnectionError('fixture relay write interrupted')
                    relay.admit(current(),'bot',envelope);observed.append(envelope);return True
                adapter.set_durable_message_handler(receive)
                actual.add_event_handler(EventType.ROOM_MESSAGE,adapter._on_room_message,wait_sync=True)
                async def proof_identity(event):
                    if verified_crypto(event) is not None:
                        assert verified_crypto(Event.deserialize(event.serialize())) is None
                actual.add_event_handler(EventType.ROOM_MESSAGE,proof_identity,wait_sync=True)
                async def encrypted(identity,body=None,root_thread='',mention=True,**changes):
                    content={'msgtype':'m.text','body':body or bot+' perform local fixture work','m.mentions':{'user_ids':[bot] if mention else []}}
                    if root_thread:content['m.relates_to']={'rel_type':'m.thread','event_id':root_thread}
                    wire=await peer_crypto.encrypt_megolm_event(RoomID(room),EventType.ROOM_MESSAGE,content)
                    inbound=await sender_store.get_group_session(RoomID(room),wire.session_id)
                    await receiver_store.put_group_session(RoomID(room),peer_crypto.account.identity_key,wire.session_id,inbound)
                    event={'type':'m.room.encrypted','event_id':identity,'sender':peer,'origin_server_ts':now,'content':wire.serialize()}
                    event.update(changes);return event
                async def step(event,authority=None,target_room=room):
                    nonlocal counter
                    counter+=1;state['payload']={'next_batch':'page-'+str(counter),'device_one_time_keys_count':{'signed_curve25519':50},
                        'rooms':{'join':{target_room:{'timeline':{'events':[event]}}}}}
                    return await receive_sync(adapter,actual,journal,authority or snapshot(current(),'bot'))
                async def drain():
                    while (item:=relay.next(current())) is not None:
                        result=await engine.receive(current(),'bot',item['envelope'],None)
                        relay.admitted(item['id'],result['mission_id'])
                original=await encrypted('$one');assert await step(original);await drain()
                assert len(missions.list())==1 and observed[0]['scope']=='' and observed[0]['thread']==''
                assert observed[0]['text']=='perform local fixture work'
                cases.append('actual_crypto_native_codec_and_raw_relay_create_one_real_haos_mission')
                cases.append('copied_wire_event_cannot_inherit_private_crypto_proof')
                assert await step(original);await drain();assert len(missions.list())==1
                cases.append('provider_replay_has_one_durable_mission')
                for label,changes in [('unknown_sender',{'sender':'@stranger:owner.invalid'}),
                    ('wrong_thread',{'root_thread':thread}),('old_original',{'origin_server_ts':now-20000})]:
                    event=await encrypted('$'+label,**changes)
                    assert await step(event);await drain();assert len(missions.list())==1
                    cases.append(label+'_cannot_gain_haos_authority')
                assert await step(await encrypted('$foreign-room'),target_room='!other:owner.invalid');await drain()
                assert len(missions.list())==1
                cases.append('foreign_room_refused_before_crypto_or_profile_lookup')
                assert await step(await encrypted('$unaddressed',body='ordinary unaddressed',mention=False));await drain()
                assert len(missions.list())==1
                cases.append('explicit_mention_requirement_is_not_bypassed')
                media={'type':'m.room.message','event_id':'$media','sender':peer,'origin_server_ts':now,
                    'content':{'msgtype':'m.image','body':'unsupported media','url':'mxc://unknown.invalid/unapproved'}}
                assert await step(media);await drain();assert len(missions.list())==1
                cases.append('media_does_not_download_before_an_approved_media_path_exists')
                plain={'type':'m.room.message','event_id':'$forged','sender':peer,'origin_server_ts':now,
                    'content':{'msgtype':'m.text','body':bot+' forged encryption flag','m.mentions':{'user_ids':[bot]}},
                    'mautrix':{'was_encrypted':True,'trust_state':300},'haos_crypto':pin}
                assert await step(plain);await drain();assert len(missions.list())==1
                cases.append('network_encryption_flags_cannot_replace_private_crypto_proof')
                old=snapshot(current(),'bot');config['bindings'][0]['generation']='b'*64
                assert await step(await encrypted('$revoked'),old);await drain();assert len(missions.list())==1
                cases.append('old_capture_snapshot_cannot_reauthorize_new_grant_generation')
                saved=deepcopy(config['bindings'][0]['matrix_devices']);config['bindings'][0]['matrix_devices'][0]['device_id']='OTHER'
                assert await step(await encrypted('$device'));await drain();assert len(missions.list())==1
                config['bindings'][0]['matrix_devices']=saved
                cases.append('unapproved_actual_device_cannot_create_mission')
                config['bindings'][0].update(thread=thread,generation='c'*64)
                assert await step(await encrypted('$threaded',root_thread=thread));await drain()
                assert len(missions.list())==2 and observed[-1]['thread']==thread
                cases.append('exact_owner_thread_survives_actual_native_builder')
                config['bindings'][0].update(thread='',generation='d'*64)
                state['fail_receiver']=True
                try:await step(await encrypted('$recover'))
                except DeferredDispatch:pass
                else:raise AssertionError('failed receiver was swallowed')
                row=raw.db.execute("SELECT * FROM native_inbox WHERE message_id='$recover'").fetchone()
                assert row['state']=='pending';key=row['id']
                raw.close();raw=NativeInbox(directory/'native.db',Redactor());adapter._haos_native.inbox=raw
                raw.db.execute('UPDATE native_inbox SET next_attempt=0 WHERE id=?',(key,))
                state['fail_receiver']=False
                assert await dispatch_stored(adapter,adapter._haos_native_dispatch,key);await drain()
                assert len(missions.list())==3
                cases.append('actual_reopened_raw_input_recovers_native_decoder_and_real_mission')
                config['bindings'][0].update(allow_plaintext=True,matrix_devices=[],generation='e'*64)
                plain['event_id']='$explicit-plain';assert await step(plain);await drain();assert len(missions.list())==4
                cases.append('plaintext_requires_explicit_new_owner_grant')
                # Retain but never execute a recovered original older than 24h.
                config['bindings'][0]['since']=now-90000000
                plain['event_id']='$expired';plain['origin_server_ts']=now-87000000
                assert await step(plain);await drain();assert len(missions.list())==4
                assert raw.db.execute("SELECT state FROM native_inbox WHERE message_id='$expired'").fetchone()[0]=='expired'
                cases.append('original_age_is_not_renewed_by_native_recovery')
                config['bindings'][0].update(capabilities=['read'],generation='f'*64,since=now-10000)
                plain['event_id']='$read-only';plain['origin_server_ts']=now
                assert await step(plain)
                item=relay.next(current());assert item is not None
                try:await engine.receive(current(),'bot',item['envelope'],None)
                except PermissionError:pass
                else:raise AssertionError('read capability became create authority')
                assert len(missions.list())==4
                cases.append('shared_haos_mission_engine_enforces_capabilities_after_native_decode')
        finally:
            for db in dbs:await db.stop()
            journal.close();raw.close();relay.close();missions.close();await runner.cleanup()
    old=os.umask(0o077)
    try:
        with tempfile.TemporaryDirectory() as value:asyncio.run(exercise(Path(value)))
    finally:os.umask(old)
    output=json.dumps({'passed':len(cases),'cases':cases,'external_connections':False,
        'installed_service_accepted':False,'live_account_accepted':False},indent=2)+'\n'
    if len(sys.argv)>2:Path(sys.argv[2]).write_text(output)
    else:print(output,end='')


if __name__=='__main__':main()
