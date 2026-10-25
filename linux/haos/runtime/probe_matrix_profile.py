#!/usr/bin/env python3
"""Actual pinned adapter connect/reconnect with private profile and recovery workers."""
import asyncio
from copy import deepcopy
import json
import fcntl
import os
from pathlib import Path
import sys
import sqlite3
import tempfile
import time


def main():
    sys.path.insert(0,str(Path(sys.argv[1]).resolve()))
    from aiohttp import ClientSession,web
    from haos.gateway import GatewayPolicy,GatewayEngine,digest
    from haos.gateway_matrix_policy import PreparedMatrixPolicy
    from haos.gateway_matrix_profile import build
    from haos.gateway_runtime import adapter_envelope
    from haos.gateway_raw import NativeInbox
    from haos.gateway_relay import RelayInbox
    from haos.gateway_delivery import delivery_result
    from haos.redaction import Redactor
    from haos.store import MissionStore
    cases=[]
    async def exercise(directory):
        home=directory/'global-home';home.mkdir(mode=0o700);os.environ['HERMES_HOME']=str(home)
        parent=directory/'profiles';parent.mkdir(mode=0o700)
        bot,peer,room,device='@haos:owner.invalid','@owner:owner.invalid','!private:owner.invalid','HAOS'
        original_ms=int(time.time()*1000)
        config={'version':1,'connectors':[{'id':'bot','platform':'matrix'}],'bindings':[
            {'id':'paired','connector':'bot','sender':peer,'chat':room,'scope':'','thread':'',
             'identity':'principal','capabilities':['create','read'],'generation':'a'*64,'since':original_ms-10000,
             'allow_plaintext':True,'require_mention':False,'matrix_devices':[]}]}
        current=lambda:GatewayPolicy(deepcopy(config))
        value={'token':'disposable-local-private-token','homeserver':'https://owner.invalid','user_id':bot,'device_id':device}
        state={'token':value['token'],'keys':{},'peer_keys':{},'calls':[],'queue':asyncio.Queue(),'cursor':'start',
            'auth_status':200,'auth_hold':None,'sync_status':200,'whoami_device':device,'posts':0,'revoke':False,
            'encrypted':False,'peer_crypto':None,'encrypted_answers':[]}
        def event(identity,**changes):
            result={'type':'m.room.message','event_id':identity,'sender':peer,'origin_server_ts':original_ms,
                'content':{'msgtype':'m.text','body':'native profile fixture '+identity}}
            result.update(changes);return result
        def page(cursor,events=None,**extra):
            return {'next_batch':cursor,'device_one_time_keys_count':{'signed_curve25519':50},
                'rooms':{'join':{room:{'timeline':{'events':events or []}}}},**extra}
        async def api(request):
            assert request.headers.get('Authorization')=='Bearer '+state['token']
            state['calls'].append((request.method,request.path,dict(request.query)))
            if request.path.endswith('/account/whoami'):
                if state['auth_hold'] is not None:await state['auth_hold'].wait()
                if state['auth_status']!=200:
                    return web.json_response({'errcode':'M_LIMIT_EXCEEDED' if state['auth_status']==429 else 'M_UNKNOWN_TOKEN',
                        'error':state['token'],'retry_after_ms':1000},status=state['auth_status'])
                return web.json_response({'user_id':bot,'device_id':state['whoami_device']})
            if request.path.endswith('/keys/query'):
                body=await request.json()
                assert set(body['device_keys'])<={bot,peer}
                return web.json_response({'device_keys':{user:state['keys'] if user==bot else state['peer_keys']
                    for user in body['device_keys']},'failures':{}})
            if request.path.endswith('/keys/upload'):
                body=await request.json()
                if body.get('device_keys'):state['keys'][device]=body['device_keys']
                return web.json_response({'one_time_key_counts':{'signed_curve25519':50}})
            if request.path.endswith('/keys/claim'):
                body=await request.json();assert body['one_time_keys']=={peer:{'PHONE':'signed_curve25519'}}
                return web.json_response({'one_time_keys':{peer:{'PHONE':state['peer_crypto'].account.get_one_time_keys(peer,'PHONE',0)}},'failures':{}})
            if request.path.endswith('/sync'):
                assert request.query['timeout'] in {'0','30000'}
                try:result=await asyncio.wait_for(state['queue'].get(),0.3)
                except asyncio.TimeoutError:result=page(state['cursor'])
                if request.transport is None or request.transport.is_closing():
                    # A real homeserver retains events until the client's next
                    # since cursor acknowledges them. An abandoned fixture
                    # long-poll must not consume the next connection's input.
                    if result['next_batch']!=state['cursor']:state['queue'].put_nowait(result)
                    return web.json_response({})
                if state['sync_status']!=200:
                    return web.json_response({'errcode':'M_UNKNOWN_TOKEN','error':state['token']},status=state['sync_status'])
                state['cursor']=result['next_batch'];return web.json_response(result)
            if request.path.rstrip('/').endswith('/state/m.room.encryption'):
                if state['encrypted']:return web.json_response({'algorithm':'m.megolm.v1.aes-sha2'})
                return web.json_response({'errcode':'M_NOT_FOUND'},status=404)
            if request.path.endswith('/joined_members'):
                return web.json_response({'joined':{bot:{},peer:{}}})
            if '/sendToDevice/m.room.encrypted/' in request.path:
                from mautrix.types import ToDeviceEvent
                body=await request.json();assert set(body['messages'])=={peer} and set(body['messages'][peer])=={'PHONE'}
                await state['peer_crypto'].handle_to_device_event(ToDeviceEvent.deserialize({'type':'m.room.encrypted',
                    'sender':bot,'content':body['messages'][peer]['PHONE']}))
                return web.json_response({})
            if '/send/m.room.encrypted/' in request.path:
                from mautrix.types import EncryptedEvent
                body=await request.json();assert 'body' not in body and body['algorithm']=='m.megolm.v1.aes-sha2'
                state['posts']+=1;identity='$encrypted-'+str(state['posts'])
                decoded=await state['peer_crypto'].decrypt_megolm_event(EncryptedEvent.deserialize({'type':'m.room.encrypted',
                    'room_id':room,'event_id':identity,'sender':bot,'origin_server_ts':int(time.time()*1000),'content':body}))
                state['encrypted_answers'].append(decoded.content.serialize())
                return web.json_response({'event_id':identity})
            if '/send/m.room.message/' in request.path:
                body=await request.json();assert body['msgtype']=='m.text' and body['m.mentions']=={}
                state['posts']+=1;return web.json_response({'event_id':'$sent-'+str(state['posts'])})
            raise AssertionError('unapproved native profile operation '+request.path)
        app=web.Application();app.router.add_route('*','/_matrix/client/v3/{tail:.*}',api)
        runner=web.AppRunner(app,shutdown_timeout=0.2);await runner.setup()
        site=web.TCPSite(runner,'127.0.0.1',0);await site.start();port=site._server.sockets[0].getsockname()[1]
        raw=NativeInbox(directory/'raw.db',Redactor());relay=RelayInbox(directory/'relay.db',Redactor())
        missions=MissionStore(directory/'missions.db');engine=GatewayEngine(missions);adapters=[]
        def make(source=None):
            from haos.gateway_runtime import build_adapter
            adapter=build_adapter('matrix',source or value,matrix_context={'parent':parent,'connector':'bot','policy':current,'inbox':raw})
            adapters.append(adapter)
            # Only this fixture maps the validated owner HTTPS origin onto its
            # loopback listener. Actual native SDK/client construction is kept.
            adapter._homeserver=f'http://127.0.0.1:{port}';adapter._haos_matrix_http._target=adapter._homeserver
            def receive(native):relay.admit(current(),'bot',adapter_envelope(native,'matrix'));return True
            adapter.set_durable_message_handler(receive)
            adapter.set_authorization_check(lambda *_args,**_kwargs:False)
            return adapter
        async def drain():
            while (item:=relay.next(current())) is not None:
                result=await engine.receive(current(),'bot',item['envelope'],None);relay.admitted(item['id'],result['mission_id'])
        async def until(predicate):
            async with asyncio.timeout(8):
                while not predicate():await asyncio.sleep(0.02)
        try:
            assert GatewayPolicy(config).bindings==current().bindings
            adapter=make()
            try:make()
            except PermissionError:pass
            else:raise AssertionError('same identity acquired two crypto writers')
            cases.append('real_profile_flock_prevents_duplicate_identity_writers')
            state['queue'].put_nowait(page('first',[event('$first')]))
            assert await adapter.connect() and adapter.is_connected
            await drain();assert len(missions.list())==1
            assert adapter._client.crypto is not None and adapter._haos_recovery_task is not None
            assert adapter._haos_matrix_http._client is adapter._client
            cases.append('actual_native_connect_auth_crypto_sync_and_private_recovery_workers')
            assert adapter._haos_profile_home.exists() and not (home/'matrix_threads.json').exists()
            assert os.environ['HERMES_HOME']==str(home)
            assert not list(home.iterdir()),[str(path.relative_to(home)) for path in home.rglob('*')]
            assert adapter.matrix_status()['native_state']=='connected'
            assert adapter._client.crypto.share_keys_min_trust.name=='VERIFIED'
            cases.append('native_home_and_secrets_remain_scoped_without_global_home_mutation')
            # A complete native outgoing path uses the actual shared outbox.
            obligation=engine.next_delivery(current());binding=config['bindings'][0]
            receipt=await adapter.send(room,obligation['content'],obligation['reply_to'],{'haos_scope':'','thread_id':'',
                'haos_binding':{'binding_id':obligation['binding_id'],'binding_digest':obligation['binding_digest']}})
            result=delivery_result(receipt);assert result['status']=='delivered'
            engine.acknowledge(current(),obligation['id'],{'attempt':obligation['attempt'],**result})
            assert state['posts']==1;cases.append('actual_connected_profile_native_text_reaches_real_mission_outbox')
            original_key=str(adapter._client.crypto.account.identity_key);profile=adapter._haos_profile_home.parent
            assert all(path.stat().st_mode&0o077==0 for path in profile.rglob('*') if path.is_file())
            cases.append('profile_crypto_sync_lock_and_native_status_files_are_private')
            old_client=adapter._client
            await adapter.disconnect();assert not adapter.is_connected and adapter._client is None
            assert adapter.matrix_status()['native_state']=='disconnected'
            assert adapter._haos_recovery_task is None
            cases.append('actual_disconnect_closes_sdk_and_stops_recovery_worker')
            state['queue'].put_nowait(page('reconnected',[event('$first'),event('$second')]))
            assert await adapter.connect();await drain()
            assert len(missions.list())==2,{'raw':[dict(r) for r in raw.db.execute('SELECT message_id,state FROM native_inbox')],
                'profile':adapter.matrix_status(),'stopping':adapter._haos_stopping,'cursor':adapter._haos_matrix_journal.cursor}
            assert str(adapter._client.crypto.account.identity_key)==original_key
            assert adapter._haos_matrix_journal.cursor=='reconnected'
            assert any(query.get('since')=='first' for _,path,query in state['calls'] if path.endswith('/sync'))
            cases.append('actual_reconnect_reuses_account_and_retained_cursor_without_replaying_mission')
            before=len(state['calls'])
            try:await old_client.sync(timeout=0)
            except PermissionError:pass
            else:raise AssertionError('superseded SDK client kept profile authority')
            assert len(state['calls'])==before;cases.append('superseded_client_loses_private_http_authority')
            await asyncio.gather(adapter.close_profile(),adapter.close_profile());assert adapter._haos_profile_closed
            assert (profile/'crypto'/'crypto.db').exists() and (profile/'sync.db').exists()
            cases.append('closing_releases_lock_and_preserves_identity_and_recovery_files')
            rotated={**value,'token':'disposable-rotated-private-token'};state['token']=rotated['token']
            adapter=make(rotated);state['queue'].put_nowait(page('rotated',[event('$third')]))
            assert await adapter.connect();await drain();assert len(missions.list())==3
            assert adapter._haos_profile_home.parent==profile and str(adapter._client.crypto.account.identity_key)==original_key
            cases.append('token_rotation_and_fresh_factory_preserve_same_device_account')
            state['sync_status']=401
            state['queue'].put_nowait(page('auth-refused'))
            await until(lambda:not adapter.is_connected)
            assert adapter.has_fatal_error and adapter.matrix_status()['status']=='authentication-refused'
            assert adapter.matrix_status()['last_error']=='authentication-refused'
            from haos.gateway_raw_recovery import unresolved
            metadata=unresolved(raw);row=next(item for item in metadata['transport'] if item['platform']=='matrix')
            assert row['status']=='authentication-refused' and row['last_error']=='authentication-refused'
            assert state['token'] not in json.dumps(metadata) and row['pending_pages']>=0
            cases.append('actual_owner_transport_metadata_retains_safe_auth_error_without_credentials')
            before=len(state['calls']);assert await adapter.connect() is False;assert len(state['calls'])==before
            cases.append('actual_live_auth_refusal_is_fatal_until_owner_restart_or_correction')
            await adapter.close_profile();state['sync_status']=200
            adapter=make(rotated);state['auth_status']=429
            assert adapter.matrix_status()['last_error']=='authentication-refused'
            assert await adapter.connect() is False
            deadline=adapter.matrix_status()['next_sync'];assert deadline>time.time()
            await adapter.close_profile();adapter=make(rotated)
            before=len(state['calls']);assert await adapter.connect() is False;assert len(state['calls'])==before
            assert adapter.matrix_status()['next_sync']==deadline
            cases.append('actual_startup_rate_limit_deadline_survives_close_and_fresh_factory')
            await asyncio.sleep(max(0,deadline-time.time())+0.05);state['auth_status']=200
            state['queue'].put_nowait(page('after-limit'))
            assert await adapter.connect();assert str(adapter._client.crypto.account.identity_key)==original_key
            cases.append('native_owner_corrected_profile_recovers_after_persisted_rate_limit')
            await adapter.disconnect()
            from haos.gateway_runtime import maintain
            stopped=asyncio.Event();supervisor=asyncio.create_task(maintain(adapter,stopped))
            await until(lambda:adapter.is_connected)
            stopped.set();await asyncio.wait_for(supervisor,5)
            assert not adapter.is_connected and adapter._client is None and adapter._haos_recovery_task is None
            cases.append('actual_gateway_service_supervisor_connects_and_stops_native_profile_and_workers')
            await adapter.close_profile();adapter=make(rotated);state['whoami_device']='FOREIGN'
            assert await adapter.connect() is False and not adapter.is_connected
            assert adapter.matrix_status()['status']=='identity-refused'
            assert (profile/'crypto'/'crypto.db').exists()
            cases.append('native_wrong_device_never_resets_or_deletes_stored_crypto')
            await adapter.close_profile();state['whoami_device']=device
            adapter=make(rotated);state['sync_status']=401
            assert await adapter.connect() is False and not adapter.is_connected and adapter._client is None
            before=len(state['calls'])
            try:await adapter.send(room,'failed initial sync must not authorize sends')
            except PermissionError:pass
            else:raise AssertionError('initial sync failure lost the scoped disconnected send guard')
            assert len(state['calls'])==before
            await adapter.close_profile();state['sync_status']=200
            cases.append('actual_initial_sync_refusal_keeps_disconnected_send_guard_and_closes_client')
            # Actual encrypted input is withheld from its real inbound session
            # until after a newer live page has been admitted.
            from mautrix.api import HTTPAPI
            from mautrix.client import Client
            from mautrix.client.state_store import MemoryStateStore
            from mautrix.crypto import OlmMachine
            from mautrix.crypto.store.memory import MemoryCryptoStore
            from mautrix.types import UserID,DeviceID,RoomID,EventType,RoomEncryptionStateEventContent,EncryptionAlgorithm
            from plugins.platforms.matrix.adapter import _CryptoStateStore
            async with ClientSession(trust_env=False) as peer_session:
                peer_client=Client(mxid=UserID(peer),device_id=DeviceID('PHONE'),api=HTTPAPI(base_url=f'http://127.0.0.1:{port}',
                    token=state['token'],client_session=peer_session),state_store=MemoryStateStore())
                peer_store=MemoryCryptoStore(peer,'disposable-local-peer-key')
                peer_crypto=OlmMachine(peer_client,peer_store,_CryptoStateStore(peer_client.state_store,{RoomID(room)},peer_client))
                await peer_crypto.load()
                state['peer_crypto']=peer_crypto
                await peer_client.state_store.set_encryption_info(RoomID(room),RoomEncryptionStateEventContent(algorithm=EncryptionAlgorithm.MEGOLM_V1))
                await peer_crypto.share_group_session(RoomID(room),[])
                wire=await peer_crypto.encrypt_megolm_event(RoomID(room),EventType.ROOM_MESSAGE,{'msgtype':'m.text','body':'real late key profile fixture'})
                inbound=await peer_store.get_group_session(RoomID(room),wire.session_id)
                state['peer_keys']={'PHONE':peer_crypto.account.get_device_keys(UserID(peer),DeviceID('PHONE')).serialize()}
                original_ms=int(time.time()*1000)
                config['bindings'][0].update(generation='d'*64,since=original_ms-1,matrix_devices=[{'device_id':'PHONE',
                    'ed25519':str(peer_crypto.account.signing_key),'curve25519':str(peer_crypto.account.identity_key)}])
                state['queue'].put_nowait(page('held-page',[event('$held',type='m.room.encrypted',content=wire.serialize())]))
                adapter=make(rotated);assert await adapter.connect()
                assert adapter.matrix_status()['pending_pages']>=1
                state['queue'].put_nowait(page('after-held',[event('$after-held')]))
                await until(lambda:raw.db.execute("SELECT 1 FROM native_inbox WHERE message_id='$after-held' AND state='committed'").fetchone())
                await drain();assert len(missions.list())==4
                cases.append('retained_undecryptable_initial_page_does_not_starve_live_sync')
                await adapter._client.crypto.crypto_store.put_group_session(RoomID(room),peer_crypto.account.identity_key,wire.session_id,inbound)
                await until(lambda:raw.db.execute("SELECT 1 FROM native_inbox WHERE message_id='$held' AND state='committed'").fetchone())
                await drain();assert len(missions.list())==5
                row=raw.db.execute("SELECT created_at FROM native_inbox WHERE message_id='$held'").fetchone()
                assert row['created_at']==original_ms/1000
                cases.append('actual_late_session_unblocks_independent_recovery_worker_once_with_original_time')
                state['encrypted']=True
                obligation=engine.next_delivery(current());assert obligation is not None
                receipt=await adapter.send(room,obligation['content'],obligation['reply_to'],{'haos_scope':'','thread_id':'',
                    'haos_binding':{'binding_id':obligation['binding_id'],'binding_digest':obligation['binding_digest']}})
                result=delivery_result(receipt);assert result['status']=='delivered'
                engine.acknowledge(current(),obligation['id'],{'attempt':obligation['attempt'],**result})
                assert state['encrypted_answers'][-1]['body']==obligation['content']
                assert state['encrypted_answers'][-1]['m.mentions']=={}
                cases.append('actual_connected_profile_distributes_olm_keys_and_peer_decrypts_megolm_outbox_answer')
            await adapter.close_profile();adapter=make(rotated);state['auth_hold']=asyncio.Event()
            before=len(state['calls']);connecting=asyncio.create_task(adapter.connect())
            await until(lambda:any(path.endswith('/account/whoami') for _,path,_ in state['calls'][before:]))
            await asyncio.gather(adapter.close_profile(),adapter.close_profile())
            assert connecting.cancelled() and adapter._haos_profile_closed and not adapter.is_connected
            state['auth_hold'].set();state['auth_hold']=None
            adapter=make(rotated);state['queue'].put_nowait(page('after-cancel'))
            assert await adapter.connect() and str(adapter._client.crypto.account.identity_key)==original_key
            cases.append('concurrent_close_cancels_actual_pending_native_auth_and_releases_profile')
            config['connectors']=[];config['bindings']=[]
            await until(lambda:not adapter.is_connected)
            before=len(state['calls'])
            try:await adapter.send(room,'revoked owner result')
            except PermissionError:pass
            else:raise AssertionError('revoked profile still had send authority')
            assert len(state['calls'])==before and adapter.matrix_status()['status']=='policy-unavailable'
            cases.append('owner_connector_revocation_stops_worker_and_prevents_native_send')
            adapter._haos_matrix_journal.db.executescript("CREATE TRIGGER fixture_close_status_failure BEFORE UPDATE ON matrix_profile_status BEGIN SELECT RAISE(ABORT,'fixture status persistence interrupted'); END;")
            try:await adapter.close_profile()
            except sqlite3.IntegrityError:pass
            else:raise AssertionError('actual status write failure was hidden')
            assert adapter._haos_profile_closed and adapter._client is None
            locked=os.open(profile/'profile.lock',os.O_RDWR|os.O_NOFOLLOW)
            try:fcntl.flock(locked,fcntl.LOCK_EX|fcntl.LOCK_NB)
            finally:os.close(locked)
            assert (profile/'crypto'/'crypto.db').exists()
            cases.append('actual_sqlite_status_failure_still_closes_sdk_journal_and_profile_lock')
        finally:
            for adapter in adapters:await adapter.close_profile()
            raw.close();relay.close();missions.close();await runner.cleanup()
    with tempfile.TemporaryDirectory() as temporary:
        previous=os.umask(0o077)
        try:asyncio.run(exercise(Path(temporary)))
        finally:os.umask(previous)
    output=json.dumps({'passed':len(cases),'cases':cases,'external_connections':False,
        'installed_service_accepted':False,'live_account_accepted':False},indent=2)+'\n'
    if len(sys.argv)>2:Path(sys.argv[2]).write_text(output)
    print(output,end='')


if __name__=='__main__':main()
