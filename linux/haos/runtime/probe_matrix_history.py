#!/usr/bin/env python3
"""Actual native Matrix history HTTP into private retained pages and HAOS missions."""
import asyncio
from copy import deepcopy
import json
import os
import sqlite3
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
    from mautrix.types import UserID,DeviceID
    from gateway.config import PlatformConfig
    from plugins.platforms.matrix.adapter import MatrixAdapter
    from haos.gateway import GatewayEngine
    from haos.gateway_matrix_policy import PreparedMatrixPolicy,snapshot
    from haos.gateway_matrix_http import HTTPBoundary
    from haos.gateway_matrix_sync import SyncJournal,dispatch_page,DeferredDispatch
    from haos.gateway_matrix_history import install_reads,recover_one
    from haos.gateway_matrix_ingress import install,attach_client
    from haos.gateway_ingress import durable_adapter
    from haos.gateway_runtime import adapter_envelope
    from haos.gateway_raw import NativeInbox
    from haos.gateway_relay import RelayInbox
    from haos.redaction import Redactor
    from haos.store import MissionStore
    cases=[]
    async def exercise(directory):
        os.environ['HERMES_HOME']=str(directory/'home');now=int(time.time()*1000)
        bot,peer,room='@haos:owner.invalid','@owner:owner.invalid','!private:owner.invalid'
        config={'version':1,'connectors':[{'id':'bot','platform':'matrix'}],'bindings':[
            {'id':'paired','connector':'bot','sender':peer,'chat':room,'scope':'','thread':'',
             'identity':'principal','capabilities':['create','read'],'generation':'a'*64,'since':now-10000,
             'allow_plaintext':True,'require_mention':False,'matrix_devices':[]}]}
        current=lambda:PreparedMatrixPolicy(deepcopy(config))
        state={'pages':{},'calls':[],'fail_receiver':False,'status':200,'bad_start':False,'bad_room':False}
        def event(identity,**changes):
            value={'type':'m.room.message','event_id':identity,'room_id':room,'sender':peer,'origin_server_ts':now,
                'content':{'msgtype':'m.text','body':'local history fixture '+identity}}
            value.update(changes);return value
        async def api(request):
            assert request.headers['Authorization']=='Bearer disposable-local-private-token'
            if request.path.endswith('/account/whoami'):return web.json_response({'user_id':bot,'device_id':'HAOS'})
            assert request.path.endswith('/messages') and request.method=='GET'
            assert request.query['dir']=='b' and request.query['limit']=='100'
            start=request.query['from'];state['calls'].append(start)
            if state['status']!=200:return web.json_response({'errcode':'M_LIMIT_EXCEEDED' if state['status']==429 else 'M_FORBIDDEN',
                'error':'disposable-local-private-token','retry_after_ms':19000},status=state['status'])
            end,chunk=state['pages'][start];chunk=deepcopy(chunk)
            if state['bad_room'] and chunk:chunk[0]['room_id']='!foreign:owner.invalid'
            return web.json_response({'start':'foreign' if state['bad_start'] else start,'end':end,'chunk':chunk})
        app=web.Application();app.router.add_route('*','/_matrix/client/v3/{tail:.*}',api)
        runner=web.AppRunner(app);await runner.setup();site=web.TCPSite(runner,'127.0.0.1',0);await site.start()
        port=site._server.sockets[0].getsockname()[1]
        journal=SyncJournal(directory/'sync.db','a'*64)
        # A real old-schema database migration preserves its transport cursor.
        journal.db.execute("UPDATE matrix_sync_cursor SET cursor='legacy-retained'")
        journal.db.executescript('DROP TABLE matrix_history_progress; DROP TABLE matrix_history_steps; PRAGMA user_version=1;')
        journal.close();journal=SyncJournal(directory/'sync.db','a'*64)
        assert journal.cursor=='legacy-retained';cases.append('actual_v1_migration_preserves_existing_sync_cursor')
        raw=NativeInbox(directory/'raw.db',Redactor());relay=RelayInbox(directory/'relay.db',Redactor())
        missions=MissionStore(directory/'missions.db');engine=GatewayEngine(missions)
        try:
            async with ClientSession(trust_env=False) as session:
                client=Client(mxid=UserID(bot),device_id=DeviceID('HAOS'),api=HTTPAPI(base_url=f'http://127.0.0.1:{port}',
                    token='disposable-local-private-token',client_session=session))
                boundary=HTTPBoundary('https://owner.invalid',bot,'HAOS');boundary._target=f'http://127.0.0.1:{port}'
                boundary.bind(client);boundary.confirm(client,await client.whoami())
                adapter=install(durable_adapter(MatrixAdapter(PlatformConfig(enabled=True,token='disposable-local-private-token',extra={
                    'homeserver':'https://owner.invalid','user_id':bot,'device_id':'HAOS','e2ee_mode':'required'}))))
                adapter._client=client;adapter._haos_native=SimpleNamespace(inbox=raw,policy=current,connector='bot')
                attach_client(adapter,client);install_reads(adapter,boundary)
                def receive(native):
                    if state['fail_receiver']:raise ConnectionError('local retained receiver failure')
                    relay.admit(current(),'bot',adapter_envelope(native,'matrix'));return True
                adapter.set_durable_message_handler(receive)
                from mautrix.types import EventType
                client.add_event_handler(EventType.ROOM_MESSAGE,adapter._on_room_message,wait_sync=True)
                async def drain():
                    while (item:=relay.next(current())) is not None:
                        result=await engine.receive(current(),'bot',item['envelope'],None);relay.admitted(item['id'],result['mission_id'])
                async def gap(start,events=None):
                    payload={'next_batch':'sync-'+start,'rooms':{'join':{room:{'timeline':{
                        'limited':True,'prev_batch':start,'events':events or []}}}}}
                    key=journal.capture(payload,snapshot(current(),'bot'),from_batch=journal.cursor)
                    await dispatch_page(adapter,client,journal,key);await drain()
                    return journal.history_gap()
                await gap('back-0',[event('$live')]);assert len(missions.list())==1
                sync_health=adapter._last_sync_ts
                state['pages']['back-0']=('back-1',[event('$older'),event('$live'),event('$stranger',sender='@stranger:owner.invalid'),
                    event('$expired',origin_server_ts=now-86401000),event('$thread',content={'msgtype':'m.text','body':'wrong thread',
                    'm.relates_to':{'rel_type':'m.thread','event_id':'$foreign'}})])
                result=await recover_one(adapter,client,journal)
                assert result,([dict(row) for row in journal.db.execute('SELECT state,last_error FROM matrix_history_progress')],state['calls'])
                await drain();assert len(missions.list())==2
                assert journal.cursor=='sync-back-0'
                assert adapter._last_sync_ts==sync_health
                cases.append('actual_sdk_pagination_native_raw_relay_and_missions_keep_sync_cursor')
                cases.append('history_replay_unknown_sender_wrong_thread_and_original_age_do_not_create_missions')
                state['pages']['back-1']=('back-2',[])
                assert await recover_one(adapter,client,journal)
                assert journal.history_gap()['resume_token']=='back-2'
                cases.append('empty_page_with_new_token_does_not_erase_remaining_history')
                state['pages']['back-2']=(None,[event('$recovered')]);state['fail_receiver']=True
                try:await recover_one(adapter,client,journal)
                except DeferredDispatch:pass
                else:raise AssertionError('receiver failure erased retained history')
                assert journal.history_gap() is None
                pending=journal.db.execute("SELECT id FROM matrix_sync_pages WHERE state='pending'").fetchone()[0]
                journal.close();raw.close();relay.close();missions.close()
                journal=SyncJournal(directory/'sync.db','a'*64);raw=NativeInbox(directory/'raw.db',Redactor())
                relay=RelayInbox(directory/'relay.db',Redactor());missions=MissionStore(directory/'missions.db');engine=GatewayEngine(missions)
                adapter._haos_native.inbox=raw;state['fail_receiver']=False
                await asyncio.sleep(2.05)
                calls=len(state['calls']);assert await dispatch_page(adapter,client,journal,pending);await drain()
                assert len(missions.list())==3 and len(state['calls'])==calls and journal.cursor=='sync-back-0'
                cases.append('reopened_history_page_recovers_after_cursor_commit_without_another_http_read')
                for status in [401,403,404,429,500]:
                    retained=await gap('error-'+str(status));state['status']=status
                    assert await recover_one(adapter,client,journal) is False
                    progress=journal.db.execute('SELECT * FROM matrix_history_progress WHERE gap_id=?',(retained['id'],)).fetchone()
                    assert progress['next_token']==retained['resume_token'] and progress['last_error']==('rate-limited' if status==429 else 'source-unavailable')
                    if status==429:assert progress['next_attempt']>time.time()+17
                    cases.append('safe_persisted_single_http_error_'+str(status))
                state['status']=200
                for label in ['start','room','loop']:
                    retained=await gap('invalid-'+label);state['pages'][retained['resume_token']]=(
                        retained['resume_token'] if label=='loop' else 'next-invalid-'+label,[event('$invalid-'+label)])
                    state['bad_start']=label=='start';state['bad_room']=label=='room'
                    assert await recover_one(adapter,client,journal) is False
                    progress=journal.db.execute('SELECT * FROM matrix_history_progress WHERE gap_id=?',(retained['id'],)).fetchone()
                    assert progress['next_token']==retained['resume_token'] and progress['last_error']=='invalid-page'
                    cases.append('refuse_wrong_'+label+'_without_advancing_gap')
                state['bad_start']=state['bad_room']=False
                retained=await gap('atomic');state['pages']['atomic']=(None,[event('$atomic')])
                pages=journal.db.execute('SELECT COUNT(*) FROM matrix_sync_pages').fetchone()[0]
                journal.db.executescript("CREATE TRIGGER fixture_progress_failure BEFORE INSERT ON matrix_history_progress BEGIN SELECT RAISE(ABORT,'fixture interrupted cursor commit'); END;")
                try:await recover_one(adapter,client,journal)
                except sqlite3.IntegrityError:pass
                else:raise AssertionError('actual SQLite transaction failure was lost')
                assert journal.history_gap()['resume_token']=='atomic'
                assert journal.db.execute('SELECT COUNT(*) FROM matrix_sync_pages').fetchone()[0]==pages
                assert journal.cursor=='sync-atomic'
                journal.db.execute('DROP TRIGGER fixture_progress_failure')
                assert await recover_one(adapter,client,journal);await drain();assert len(missions.list())==4
                cases.append('actual_sqlite_failure_rolls_back_history_input_and_cursor_together')
                retained=await gap('cycle-a');state['pages']['cycle-a']=('cycle-b',[event('$cycle')])
                assert await recover_one(adapter,client,journal);await drain();assert len(missions.list())==5
                state['pages']['cycle-b']=('cycle-a',[event('$cycle-new')])
                assert await recover_one(adapter,client,journal) is False
                progress=journal.db.execute('SELECT * FROM matrix_history_progress WHERE gap_id=?',(retained['id'],)).fetchone()
                assert progress['next_token']=='cycle-b' and progress['last_error']=='invalid-page'
                cases.append('multi_page_cursor_cycle_cannot_restart_history')
                retained=await gap('revoked');before=len(state['calls']);config['bindings'][0]['generation']='b'*64
                assert await recover_one(adapter,client,journal) is False and len(state['calls'])==before
                progress=journal.db.execute('SELECT * FROM matrix_history_progress WHERE gap_id=?',(retained['id'],)).fetchone()
                assert progress['state']=='revoked';cases.append('old_gap_snapshot_cannot_read_under_new_owner_generation')
                assert len(missions.list())==5
        finally:
            journal.close();raw.close();relay.close();missions.close();await runner.cleanup()
    with tempfile.TemporaryDirectory() as temporary:
        previous=os.umask(0o077)
        try:asyncio.run(exercise(Path(temporary)))
        finally:os.umask(previous)
    output=json.dumps({'passed':len(cases),'cases':cases,'external_connections':False,'installed_service_accepted':False},indent=2)+'\n'
    if len(sys.argv)>2:Path(sys.argv[2]).write_text(output)
    print(output,end='')


if __name__=='__main__':main()
