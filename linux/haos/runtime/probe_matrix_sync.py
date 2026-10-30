#!/usr/bin/env python3
"""Actual mautrix sync HTTP/codecs and native Hermes dispatch around private raw COMMIT."""
import asyncio
from copy import deepcopy
import json
import os
from pathlib import Path
import sqlite3
import sys
import tempfile


def main():
    root=Path(sys.argv[1]).resolve();sys.path.insert(0,str(root))
    from aiohttp import ClientSession,web
    from mautrix.api import HTTPAPI
    from mautrix.client import Client
    from mautrix.types import UserID,DeviceID,EventType,RoomID
    from mautrix.client.state_store import MemoryStateStore
    from gateway.config import PlatformConfig
    from plugins.platforms.matrix.adapter import MatrixAdapter
    from haos.gateway_matrix_sync import SyncJournal,receive_sync,dispatch_page,active_page,DeferredDispatch
    from haos.gateway import Conflict
    cases=[]
    async def exercise(directory):
        os.environ['HERMES_HOME']=str(directory/'home')
        room='!local:owner.invalid';sender='@owner:owner.invalid';scope='a'*64
        state={'payload':None,'queries':[],'fail':False,'nested_fail':False}
        async def api(request):
            assert request.headers['Authorization']=='Bearer disposable-private-token'
            if request.path.endswith('/account_data/m.direct'):
                assert request.method=='GET'
                return web.json_response({})
            if request.path=='/_matrix/client/v3/keys/upload':
                await request.json()
                return web.json_response({'one_time_key_counts':{'signed_curve25519':50}})
            assert request.path=='/_matrix/client/v3/sync'
            state['queries'].append(dict(request.query));return web.json_response(state['payload'])
        app=web.Application();app.router.add_route('*','/_matrix/client/v3/{tail:.*}',api)
        runner=web.AppRunner(app);await runner.setup();site=web.TCPSite(runner,'127.0.0.1',0);await site.start()
        port=site._server.sockets[0].getsockname()[1]
        path=directory/'sync.db';journal=SyncJournal(path,scope)
        seen=sqlite3.connect(directory/'decoded.db',isolation_level=None)
        seen.execute('CREATE TABLE decoded(id TEXT PRIMARY KEY,body TEXT NOT NULL)')
        def payload(cursor,identity,body='actual native sync codec'):
            return {'next_batch':cursor,'rooms':{'join':{room:{'timeline':{'events':[
                {'type':'m.room.message','event_id':identity,'sender':sender,'origin_server_ts':1792800000000,
                 'content':{'msgtype':'m.text','body':body}}]}}}}}
        crypto_dbs=[]
        adapter=MatrixAdapter(PlatformConfig(enabled=True,token='disposable-private-token',extra={
            'homeserver':f'http://127.0.0.1:{port}','user_id':'@haos:owner.invalid','device_id':'FIXTURE','e2ee_mode':'off'}))
        authority={'bound_owner_grants':[],'fixture_metadata_only':True}
        try:
            async with ClientSession(trust_env=False) as session:
                client=Client(mxid=UserID('@haos:owner.invalid'),device_id=DeviceID('FIXTURE'),
                    api=HTTPAPI(base_url=f'http://127.0.0.1:{port}',token='disposable-private-token',client_session=session),
                    state_store=MemoryStateStore())
                adapter._client=client
                async def receive(event):
                    row=active_page()
                    # Independent reader sees full raw input and transport cursor
                    # before this actual SDK-deserialized event callback executes.
                    with sqlite3.connect(path) as observer:
                        retained=observer.execute('SELECT payload,state FROM matrix_sync_pages WHERE id=?',(row['id'],)).fetchone()
                        assert retained is not None and retained[1]=='pending'
                        assert json.loads(retained[0])['next_batch']==row['next_batch']
                        assert observer.execute('SELECT cursor FROM matrix_sync_cursor WHERE scope=?',(scope,)).fetchone()[0]==journal.cursor
                    assert str(event.room_id)==room and str(event.sender)==state.get('expected_sender',sender)
                    if state.get('block'):
                        state['entered'].set();await state['release'].wait()
                    if state['fail']:raise ConnectionError('fixture private decoder interruption')
                    if state['nested_fail']:
                        client.dispatch_manual_event(EventType.REACTION,event)
                    seen.execute('INSERT OR IGNORE INTO decoded(id,body) VALUES(?,?)',(str(event.event_id),event.content.body))
                client.add_event_handler(EventType.ROOM_MESSAGE,receive,wait_sync=False)
                state['payload']=payload('batch-1','$one')
                assert await receive_sync(adapter,client,journal,authority,initial=True)
                assert state['queries'][-1]['full_state']=='true'
                assert journal.cursor=='batch-1' and state['queries'][-1].get('since') is None
                assert seen.execute('SELECT COUNT(*) FROM decoded').fetchone()[0]==1
                cases.append('actual_sync_http_and_sdk_callback_follow_independent_raw_commit')
                # Even when the vendor repeats the same opaque token, distinct
                # ephemeral response content can be retained without a false conflict.
                state['payload']=payload('batch-1','$one');state['payload']['ephemeral']={'events':[]}
                assert await receive_sync(adapter,client,journal,authority)
                assert seen.execute('SELECT COUNT(*) FROM decoded').fetchone()[0]==1
                cases.append('same_cursor_response_variants_do_not_duplicate_durable_receiver')
                state['fail']=True;state['payload']=payload('batch-2','$two')
                try:await receive_sync(adapter,client,journal,authority)
                except DeferredDispatch:pass
                else:raise AssertionError('SDK/native swallowed failed handler')
                assert journal.cursor=='batch-2'
                key=journal.due(now=10**12);assert key is not None
                assert journal.page(key)['payload']['next_batch']=='batch-2'
                assert seen.execute('SELECT COUNT(*) FROM decoded').fetchone()[0]==1
                cases.append('swallowed_native_handler_error_retains_page_after_transport_capture')
                journal.close();journal=SyncJournal(path,scope);state['fail']=False
                assert journal.cursor=='batch-2' and await dispatch_page(adapter,client,journal,key)
                assert seen.execute('SELECT COUNT(*) FROM decoded').fetchone()[0]==2
                cases.append('reopened_journal_replays_actual_sdk_event_without_new_http')
                # Sibling SDK handlers and nested dispatchers must not escape the
                # completion boundary even when they normally run in background.
                async def nested(_event):raise OSError('fixture nested callback failure')
                client.add_event_handler(EventType.REACTION,nested,wait_sync=False)
                state['nested_fail']=True;state['payload']=payload('batch-3','$three')
                try:await receive_sync(adapter,client,journal,authority)
                except DeferredDispatch:pass
                else:raise AssertionError('nested dispatch failure lost')
                key=journal.due(now=10**12);assert journal.page(key)['state']=='pending'
                state['nested_fail']=False
                assert await dispatch_page(adapter,client,journal,key)
                assert seen.execute('SELECT COUNT(*) FROM decoded').fetchone()[0]==3
                cases.append('nested_background_dispatch_failure_remains_recoverable')
                # Failed older raw pages cannot block capturing newer protocol
                # responses (which may contain the very missing to-device keys).
                state['fail']=True;state['payload']=payload('batch-4','$four')
                try:await receive_sync(adapter,client,journal,authority)
                except DeferredDispatch:pass
                else:raise AssertionError('fixture failure lost')
                old_key=journal.due(now=10**12)
                state['fail']=False;state['payload']=payload('batch-5','$five')
                assert await receive_sync(adapter,client,journal,authority)
                assert state['queries'][-1]['since']=='batch-4'
                assert await dispatch_page(adapter,client,journal,old_key)
                cases.append('new_protocol_pages_advance_while_failed_old_decode_is_retained')
                state['payload']={'rooms':{}}
                before=journal.cursor
                try:await receive_sync(adapter,client,journal,authority)
                except ValueError:pass
                else:raise AssertionError('missing next_batch accepted')
                assert journal.cursor==before;cases.append('malformed_transport_cursor_cannot_acknowledge_input')
                # Force a real SQLite trigger failure: raw row and checkpoint
                # must roll back together, never one without the other.
                journal.db.execute("CREATE TRIGGER fixture_raw_failure BEFORE INSERT ON matrix_sync_pages BEGIN SELECT RAISE(ABORT,'fixture raw storage unavailable'); END")
                state['payload']=payload('batch-6','$six')
                try:await receive_sync(adapter,client,journal,authority)
                except sqlite3.DatabaseError:pass
                else:raise AssertionError('raw storage failure lost')
                assert journal.cursor==before
                assert not journal.db.execute("SELECT 1 FROM matrix_sync_pages WHERE next_batch='batch-6'").fetchone()
                journal.db.execute('DROP TRIGGER fixture_raw_failure')
                cases.append('actual_sqlite_failure_rolls_back_raw_row_and_checkpoint')
                try:journal.capture(payload('batch-7','$seven'),authority,from_batch='stale')
                except Conflict:pass
                else:raise AssertionError('stale request cursor accepted')
                assert journal.cursor==before;cases.append('stale_transport_request_cannot_replace_captured_cursor')
                other=SyncJournal(path,'b'*64)
                try:assert other.cursor is None and other.due(now=10**12) is None
                finally:other.close()
                cases.append('another_private_identity_does_not_inherit_cursor_or_pending_pages')
                state['payload']=payload('limited-batch','$limited')
                state['payload']['rooms']['join'][room]['timeline'].update(limited=True,prev_batch='private-history-marker')
                assert await receive_sync(adapter,client,journal,authority)
                gap=journal.db.execute('SELECT * FROM matrix_sync_gaps WHERE scope=?',(scope,)).fetchone()
                assert gap is not None and gap['room_id']==room and gap['before_token']=='private-history-marker'
                assert json.loads(gap['authority'])==authority
                cases.append('limited_timeline_marker_retained_before_raw_page_compaction')
                state['payload']=payload('cancelled-batch','$cancelled')
                state.update(block=True,entered=asyncio.Event(),release=asyncio.Event())
                operation=asyncio.create_task(receive_sync(adapter,client,journal,authority))
                await asyncio.wait_for(state['entered'].wait(),2)
                operation.cancel()
                try:await operation
                except asyncio.CancelledError:pass
                else:raise AssertionError('cancellation did not propagate')
                assert journal.cursor=='cancelled-batch'
                key=journal.due(now=10**12);assert journal.page(key)['state']=='pending'
                assert not seen.execute('SELECT 1 FROM decoded WHERE id=?',('$cancelled',)).fetchone()
                state['block']=False
                assert await dispatch_page(adapter,client,journal,key)
                assert seen.execute('SELECT COUNT(*) FROM decoded WHERE id=?',('$cancelled',)).fetchone()[0]==1
                cases.append('cancelled_actual_sdk_callback_retains_input_and_cleans_up_for_retry')


                from mautrix.crypto import OlmMachine
                from mautrix.crypto.store.asyncpg import PgCryptoStore
                from mautrix.util.async_db import Database
                from mautrix.types import RoomEncryptionStateEventContent,EncryptionAlgorithm
                from plugins.platforms.matrix.adapter import _CryptoStateStore
                async def crypto_store(name):
                    db=Database.create('sqlite:///'+str(directory/name),upgrade_table=PgCryptoStore.upgrade_table)
                    await db.start();crypto_dbs.append(db)
                    store=PgCryptoStore(account_id='@haos:owner.invalid',pickle_key='disposable-key',db=db)
                    await store.open();return store
                source_store=await crypto_store('source-crypto.db')
                source_client=Client(mxid=UserID('@haos:owner.invalid'),device_id=DeviceID('FIXTURE'),
                    api=HTTPAPI(base_url=f'http://127.0.0.1:{port}',token='disposable-private-token',client_session=session),state_store=MemoryStateStore())
                await source_client.state_store.set_encryption_info(RoomID(room),RoomEncryptionStateEventContent(algorithm=EncryptionAlgorithm.MEGOLM_V1))
                source_crypto=OlmMachine(source_client,source_store,_CryptoStateStore(source_client.state_store,{RoomID(room)},source_client))
                await source_crypto.load();await source_crypto.share_group_session(RoomID(room),[])
                encrypted=await source_crypto.encrypt_megolm_event(RoomID(room),EventType.ROOM_MESSAGE,{'msgtype':'m.text','body':'actual recovered ciphertext'})
                incoming=await source_store.get_group_session(RoomID(room),encrypted.session_id)
                target_store=await crypto_store('target-crypto.db')
                await target_store.put_account(source_crypto.account)
                client=Client(mxid=UserID('@haos:owner.invalid'),device_id=DeviceID('FIXTURE'),
                    api=HTTPAPI(base_url=f'http://127.0.0.1:{port}',token='disposable-private-token',client_session=session),state_store=MemoryStateStore())
                target_crypto=OlmMachine(client,target_store,_CryptoStateStore(client.state_store,{RoomID(room)},client))
                await target_crypto.load();client.crypto=target_crypto;adapter._client=client
                client.add_event_handler(EventType.ROOM_MESSAGE,receive,wait_sync=False)
                state['expected_sender']='@haos:owner.invalid'
                state['payload']={'next_batch':'encrypted-batch','device_one_time_keys_count':{'signed_curve25519':50},'rooms':{'join':{room:{'timeline':{'events':[
                    {'type':'m.room.encrypted','event_id':'$encrypted','sender':'@haos:owner.invalid','origin_server_ts':1792800000000,'content':encrypted.serialize()}]}}}}}
                count=seen.execute('SELECT COUNT(*) FROM decoded').fetchone()[0]
                try:await receive_sync(adapter,client,journal,authority)
                except DeferredDispatch:pass
                else:raise AssertionError('missing crypto session was silently acknowledged as decoded')
                key=journal.due(now=10**12)
                assert journal.page(key)['state']=='pending' and seen.execute('SELECT COUNT(*) FROM decoded').fetchone()[0]==count
                cases.append('actual_missing_crypto_session_retains_encrypted_page')
                # Deliver only local fixture key material through the actual SDK
                # store. This is not remote device trust or a live key exchange.
                await target_store.put_group_session(RoomID(room),source_crypto.account.identity_key,encrypted.session_id,incoming)
                assert await dispatch_page(adapter,client,journal,key)
                assert seen.execute('SELECT body FROM decoded WHERE id=?',('$encrypted',)).fetchone()[0]=='actual recovered ciphertext'
                cases.append('late_fixture_key_unblocks_actual_decryption_and_nested_decoder')

        finally:
            for db in crypto_dbs:await db.stop()
            journal.close();seen.close();await runner.cleanup()
    old=os.umask(0o077)
    try:
        with tempfile.TemporaryDirectory() as value:asyncio.run(exercise(Path(value)))
    finally:os.umask(old)
    output=json.dumps({'passed':len(cases),'cases':cases,'external_connections':False,
        'haos_matrix_gateway_enabled':False,'mission_authorization_or_execution_tested':False},indent=2)+'\n'
    if len(sys.argv)>2:Path(sys.argv[2]).write_text(output)
    else:print(output,end='')


if __name__=='__main__':main()
