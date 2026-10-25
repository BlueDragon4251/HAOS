#!/usr/bin/env python3
"""Actual signed device keys, Olm distribution and Megolm answers through local HTTP."""
import asyncio
from copy import deepcopy
import json
import os
from pathlib import Path
import sys
import tempfile
import time
from types import SimpleNamespace


def main():
    sys.path.insert(0,str(Path(sys.argv[1]).resolve()))
    from aiohttp import ClientSession,web
    from mautrix.api import HTTPAPI
    from mautrix.client import Client
    from mautrix.client.state_store import MemoryStateStore
    from mautrix.crypto import OlmMachine
    from mautrix.crypto.store.memory import MemoryCryptoStore
    from mautrix.crypto.store.asyncpg import PgCryptoStore
    from mautrix.util.async_db import Database
    from mautrix.types import UserID,DeviceID,RoomID,EventType,DeviceIdentity,TrustState,ToDeviceEvent,EncryptedEvent,EncryptionAlgorithm
    from gateway.config import PlatformConfig
    from plugins.platforms.matrix.adapter import MatrixAdapter,_CryptoStateStore
    from haos.gateway import GatewayEngine
    from haos.gateway_matrix_policy import PreparedMatrixPolicy
    from haos.gateway_matrix_http import HTTPBoundary
    from haos.gateway_matrix_delivery import install
    from haos.gateway_matrix_recipients import RecipientGuard
    from haos.gateway_delivery import delivery_result
    from haos.store import MissionStore
    cases=[]
    async def exercise(directory):
        os.environ['HERMES_HOME']=str(directory/'home');bot=UserID('@haos:owner.invalid');peer=UserID('@owner:owner.invalid')
        room=RoomID('!private:owner.invalid');device=DeviceID('PHONE');bot_device=DeviceID('HAOS')
        state={'posts':0,'key_posts':0,'next_event':0,'status':200,'disconnect':False,'key_disconnect':False,
            'unknown_device':False,'invalid_signature':False,'no_otk':False,'joined':True,'revoke':False,'algorithm':'m.megolm.v1.aes-sha2',
            'plaintext':[],'sessions':[]}
        peer_crypto=None;keys={};one_time={};config={};bot_db=None
        async def api(request):
            assert request.headers['Authorization']=='Bearer disposable-local-private-token'
            if request.path.endswith('/account/whoami'):return web.json_response({'user_id':bot,'device_id':bot_device})
            if request.path.rstrip('/').endswith('/state/m.room.encryption'):
                return web.json_response({'algorithm':state['algorithm']})
            if request.path.endswith('/joined_members'):
                return web.json_response({'joined':{bot:{},**({peer:{}} if state['joined'] else {})}})
            if request.path.endswith('/keys/query'):
                body=await request.json();assert body['device_keys']=={peer:[]}
                value=deepcopy(keys[peer])
                if state['unknown_device']:value['UNAPPROVED']=deepcopy(keys['other'])
                if state['invalid_signature']:
                    value[device]['signatures'][peer]['ed25519:'+device]='A'*86
                return web.json_response({'device_keys':{peer:value},'failures':{}})
            if request.path.endswith('/keys/claim'):
                body=await request.json();assert set(body['one_time_keys'])=={peer}
                return web.json_response({'one_time_keys':{peer:{} if state['no_otk'] else {device:one_time}},'failures':{}})
            if '/sendToDevice/m.room.encrypted/' in request.path:
                state['key_posts']+=1;body=await request.json()
                assert set(body['messages'])=={peer} and set(body['messages'][peer])=={device}
                value=ToDeviceEvent.deserialize({'type':'m.room.encrypted','sender':bot,'content':body['messages'][peer][device]})
                await peer_crypto.handle_to_device_event(value)
                if state['key_disconnect']:request.transport.close();return web.Response()
                return web.json_response({})
            assert '/send/m.room.encrypted/' in request.path and request.method=='PUT',request.path
            state['posts']+=1;state['next_event']+=1;body=await request.json()
            assert body['algorithm']=='m.megolm.v1.aes-sha2' and 'body' not in body
            if state['status']==429:
                return web.json_response({'errcode':'M_LIMIT_EXCEEDED','error':'disposable-local-private-token','retry_after_ms':19000},status=429)
            identity='$wire-'+str(state['next_event'])
            decrypted=await peer_crypto.decrypt_megolm_event(EncryptedEvent.deserialize({'type':'m.room.encrypted',
                'room_id':room,'event_id':identity,'sender':bot,'origin_server_ts':int(time.time()*1000),'content':body}))
            content=decrypted.content.serialize();assert content['msgtype']=='m.text' and content['m.mentions']=={}
            assert (content.get('m.relates_to') or {}).get('event_id','')==config['bindings'][0]['thread']
            state['plaintext'].append(content['body']);state['sessions'].append(body['session_id'])
            if state['revoke']:config['bindings'][0]['generation']='b'*64
            if state['disconnect']:request.transport.close();return web.Response()
            if state['status']!=200:return web.json_response({'errcode':'M_LIMIT_EXCEEDED' if state['status']==429 else 'M_UNKNOWN',
                'error':'disposable-local-private-token','retry_after_ms':19000},status=state['status'])
            return web.json_response({'event_id':identity})
        app=web.Application();app.router.add_route('*','/_matrix/client/v3/{tail:.*}',api)
        runner=web.AppRunner(app);await runner.setup();site=web.TCPSite(runner,'127.0.0.1',0);await site.start()
        port=site._server.sockets[0].getsockname()[1]
        try:
            async with ClientSession(trust_env=False) as session:
                def client(user,dev):return Client(mxid=user,device_id=dev,api=HTTPAPI(base_url=f'http://127.0.0.1:{port}',
                    token='disposable-local-private-token',client_session=session),state_store=MemoryStateStore())
                actual=client(bot,bot_device);remote=client(peer,device)
                bot_db=Database.create('sqlite:///'+str(directory/'bot-crypto.db'),upgrade_table=PgCryptoStore.upgrade_table)
                await bot_db.start();bot_store=PgCryptoStore(account_id=bot,pickle_key='disposable-bot-key',db=bot_db);await bot_store.open()
                crypto=OlmMachine(actual,bot_store,_CryptoStateStore(actual.state_store,{room},actual))
                peer_crypto=OlmMachine(remote,MemoryCryptoStore(peer,'disposable-peer-key'),_CryptoStateStore(remote.state_store,{room},remote))
                await crypto.load();await peer_crypto.load();actual.crypto=crypto;remote.crypto=peer_crypto
                keys[peer]={device:peer_crypto.account.get_device_keys(peer,device).serialize()}
                from mautrix.crypto.account import OlmAccount
                extra_account=OlmAccount();keys['other']=extra_account.get_device_keys(peer,DeviceID('UNAPPROVED')).serialize()
                one_time=peer_crypto.account.get_one_time_keys(peer,device,0)
                await peer_crypto.crypto_store.put_devices(bot,{bot_device:DeviceIdentity(user_id=bot,device_id=bot_device,
                    identity_key=crypto.account.identity_key,signing_key=crypto.account.signing_key,trust=TrustState.VERIFIED,deleted=False,name='Local fixture bot')})
                pin={'device_id':device,'ed25519':str(peer_crypto.account.signing_key),'curve25519':str(peer_crypto.account.identity_key)}
                config.update({'version':1,'connectors':[{'id':'bot','platform':'matrix'}],'bindings':[
                    {'id':'paired','connector':'bot','sender':peer,'chat':room,'scope':'','thread':'',
                     'identity':'principal','capabilities':['create','read'],'generation':'a'*64,'since':int(time.time()*1000)-1000,
                     'allow_plaintext':False,'require_mention':True,'matrix_devices':[pin]}]})
                current=lambda:PreparedMatrixPolicy(deepcopy(config))
                boundary=HTTPBoundary('https://owner.invalid',bot,bot_device);boundary._target=f'http://127.0.0.1:{port}'
                boundary.bind(actual);boundary.confirm(actual,await actual.whoami())
                adapter=MatrixAdapter(PlatformConfig(enabled=True,token='disposable-local-private-token',extra={
                    'homeserver':'https://owner.invalid','user_id':bot,'device_id':bot_device,'e2ee_mode':'required'}))
                adapter._client=actual;adapter._haos_native=SimpleNamespace(policy=current,connector='bot')
                install(adapter,boundary);guard=RecipientGuard(adapter,actual,boundary)
                async def run(name,expected,content=None,forged=None):
                    path=directory/(name+'.db');store=MissionStore(path);engine=GatewayEngine(store);binding=config['bindings'][0]
                    await engine.receive(current(),'bot',{'platform':'matrix','sender':peer,'chat':room,'scope':'','thread':binding['thread'],
                        'message_id':'$input-'+str(len(cases)),'is_bot':False,'text':'local encrypted native fixture'},None)
                    obligation=engine.next_delivery(current());metadata={'haos_scope':'','thread_id':binding['thread'],
                        'haos_binding':{'binding_id':obligation['binding_id'],'binding_digest':obligation['binding_digest']}}
                    if forged:metadata.update(forged)
                    receipt=await adapter.send(room,content or obligation['content'],obligation['reply_to'],metadata)
                    assert 'disposable-local-private-token' not in (receipt.error or '')
                    result=delivery_result(receipt)
                    if state['revoke']:config['bindings'][0]['generation']='a'*64
                    engine.acknowledge(current(),obligation['id'],{'attempt':obligation['attempt'],**result});store.close();store=MissionStore(path)
                    row=store.db.execute('SELECT state FROM gateway_outbox WHERE id=?',(obligation['id'],)).fetchone()
                    assert row['state']==expected,(name,row['state'],result)
                    store.close();cases.append(name);return result
                state['no_otk']=True
                await run('missing_actual_one_time_key_cannot_be_treated_as_completed_distribution','failed')
                assert state['posts']==0 and state['key_posts']==0;state['no_otk']=False
                await run('actual_signed_device_olm_key_distribution_and_megolm_answer','delivered')
                assert state['posts']==1 and state['key_posts']==1 and len(state['plaintext'])==1
                first_session=state['sessions'][-1]
                config['bindings'][0]['thread']='$root';state['posts']=0
                await run('actual_encrypted_native_thread_kept_and_new_grant_rotates_session','delivered')
                assert state['sessions'][-1]!=first_session
                state['posts']=0;state['unknown_device']=True;before=state['key_posts']
                await run('unapproved_remote_device_cannot_receive_keys_or_results','failed');assert state['posts']==0 and state['key_posts']==before
                state['unknown_device']=False;pin['ed25519']=str(extra_account.signing_key)
                await run('owner_fingerprint_mismatch_refuses_before_key_share','failed');assert state['posts']==0
                pin['ed25519']=str(peer_crypto.account.signing_key);state['invalid_signature']=True
                await run('actual_native_signed_key_validation_is_required','failed');assert state['posts']==0
                state['invalid_signature']=False;state['joined']=False
                await run('departed_recipient_is_not_sent_keys_or_results','failed');assert state['posts']==0
                state['joined']=True
                stored=await crypto.crypto_store.get_devices(peer)
                # Restore the actual signed remote device after the preceding
                # invalid-signature fixture, then explicitly blacklist it.
                if not stored:
                    response=await actual.query_keys([peer]);stored=await crypto._process_fetched_keys(peer,response.device_keys[peer],response)
                stored[device].trust=TrustState.BLACKLISTED;await crypto.crypto_store.put_devices(peer,stored)
                await run('local_device_blacklist_is_not_overridden_by_cached_owner_fingerprints','failed');assert state['posts']==0
                stored=await crypto.crypto_store.get_devices(peer);stored[device].trust=TrustState.UNVERIFIED
                await crypto.crypto_store.put_devices(peer,stored)
                for status,expected in [(429,'pending'),(500,'uncertain')]:
                    state['status']=status;state['posts']=0;result=await run('single_encrypted_send_'+str(status),expected)
                    assert state['posts']==1
                    if status==429:assert result['retry_after']==19
                state['status']=200;state['disconnect']=True;state['posts']=0
                await run('lost_encrypted_receipt_has_one_wire_send','uncertain');assert state['posts']==1
                state['disconnect']=False;state['revoke']=True;state['posts']=0
                await run('encrypted_revocation_between_native_chunks_stops_second_send','uncertain','r'*33000);assert state['posts']==1
                state['revoke']=False;state['posts']=0
                await run('forged_owner_generation_cannot_share_or_send','failed',forged={'haos_binding':{'binding_id':'paired','binding_digest':'0'*64}});assert state['posts']==0
                config['bindings'][0]['generation']='c'*64;state['key_disconnect']=True;before=state['key_posts']
                await run('uncertain_key_share_does_not_send_the_private_result','uncertain');assert state['posts']==0 and state['key_posts']==before+1
                state['key_disconnect']=False
                await run('next_authorized_obligation_rotates_after_uncertain_key_share','delivered');assert state['posts']==1
                previous=state['sessions'][-1];identity_key=crypto.account.identity_key
                # Actually close/reopen SQLite and load a fresh SDK identity and
                # guard. Clearing a dictionary would not prove persisted keys.
                await bot_db.stop()
                bot_db=Database.create('sqlite:///'+str(directory/'bot-crypto.db'),upgrade_table=PgCryptoStore.upgrade_table)
                await bot_db.start();bot_store=PgCryptoStore(account_id=bot,pickle_key='disposable-bot-key',db=bot_db);await bot_store.open()
                actual=client(bot,bot_device)
                crypto=OlmMachine(actual,bot_store,_CryptoStateStore(actual.state_store,{room},actual));await crypto.load();actual.crypto=crypto
                assert crypto.account.identity_key==identity_key
                boundary=HTTPBoundary('https://owner.invalid',bot,bot_device);boundary._target=f'http://127.0.0.1:{port}'
                boundary.bind(actual);boundary.confirm(actual,await actual.whoami());adapter._client=actual
                install(adapter,boundary);guard=RecipientGuard(adapter,actual,boundary)
                await run('reopened_guard_does_not_inherit_unproven_outbound_session','delivered');assert state['sessions'][-1]!=previous
                before=state['key_posts']
                try:await actual.send_to_device(EventType.TO_DEVICE_ENCRYPTED,{})
                except PermissionError:pass
                else:raise AssertionError('unsolicited SDK key distribution was authorized')
                assert state['key_posts']==before;cases.append('key_distribution_outside_private_owner_context_is_refused')
        finally:
            if bot_db is not None:await bot_db.stop()
            await runner.cleanup()
    with tempfile.TemporaryDirectory() as temporary:
        previous=os.umask(0o077)
        try:asyncio.run(exercise(Path(temporary)))
        finally:os.umask(previous)
    output=json.dumps({'passed':len(cases),'cases':cases,'external_connections':False,'live_device_trust_accepted':False,
        'installed_matrix_gateway_enabled':False},indent=2)+'\n'
    if len(sys.argv)>2:Path(sys.argv[2]).write_text(output)
    print(output,end='')


if __name__=='__main__':main()
