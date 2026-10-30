#!/usr/bin/env python3
"""Native Mattermost REST history with real HTTP/SQLite crash and authority boundaries."""
import asyncio
from copy import deepcopy
from email.utils import formatdate
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
    from haos.gateway import GatewayPolicy,digest
    from haos.gateway_raw import NativeInbox
    from haos.gateway_relay import RelayInbox
    from haos.gateway_runtime import build_adapter,adapter_envelope
    from haos.gateway_mattermost import APIError,dispatch_stored
    from haos.gateway_mattermost_history import recover_one
    from haos.redaction import Redactor
    cases=[]
    async def exercise(directory):
        os.environ['HERMES_HOME']=str(directory/'hermes')
        bot,user,chat,team,thread=('b'*26,'u'*26,'c'*26,'s'*26,'t'*26)
        token='x'*26;base=int(time.time()*1000)-100000
        config={'version':1,'connectors':[{'id':'bot','platform':'mattermost'}],'bindings':[
            {'id':'paired','connector':'bot','sender':user,'chat':chat,'scope':team,'thread':'',
             'identity':'principal','capabilities':['create','read'],'generation':'a'*64,'since':base-1}]}
        current=lambda:GatewayPolicy(config)
        def post(i,**changes):
            value={'id':str(i).zfill(26),'user_id':user,'channel_id':chat,'root_id':'',
                'message':'@herald recover '+str(i),'create_at':base+i*100,'props':{},'file_ids':[]}
            value.update(changes);return value
        state={'posts':[post(i) for i in range(1,251)],'calls':[],'status':200,'revoke':False,'malformed':False}
        async def api(request):
            assert request.headers['Authorization']=='Bearer '+token
            path=request.path;state['calls'].append((path,dict(request.query)))
            if path.endswith('/posts/'+thread):return web.json_response({'id':thread,'channel_id':chat,'root_id':''})
            if path.endswith('/channels/'+chat):return web.json_response({'id':chat,'team_id':team,'type':'O'})
            if path.endswith('/users/'+user):return web.json_response({'id':user,'is_bot':False})
            assert path.endswith('/channels/'+chat+'/posts') and request.query['per_page']=='100'
            if state['status']!=200:return web.json_response({'message':'fixture refusal'},status=state['status'],headers={'Retry-After':state.get('retry_after','17')})
            if state['revoke']:config['bindings'][0]['generation']='d'*64
            ordered=sorted(state['posts'],key=lambda p:p['create_at'],reverse=True)
            before=request.query.get('before')
            if before:
                if state.get('expired_anchor'):
                    state['expired_anchor']=False
                    return web.json_response({'message':'post not found'},status=404)
                ordered=ordered[next(i for i,p in enumerate(ordered) if p['id']==before)+1:]
            ordered=ordered[:100]
            ids=[p['id'] for p in ordered]
            return web.json_response({'order':ids+ids[:1] if state['malformed'] else ids,'posts':{p['id']:p for p in ordered}})
        app=web.Application();app.router.add_get('/api/v4/{tail:.*}',api)
        runner=web.AppRunner(app);await runner.setup();site=web.TCPSite(runner,'127.0.0.1',0);await site.start()
        port=site._server.sockets[0].getsockname()[1]
        native=NativeInbox(directory/'native.db',Redactor([token]));relay=RelayInbox(directory/'relay.db',Redactor([token]))
        adapter=build_adapter('mattermost',{'token':token,'server_url':'https://owner.invalid'})
        adapter._base_url=f'http://127.0.0.1:{port}';adapter._bot_user_id=bot;adapter._bot_username='herald'
        adapter._haos_native=SimpleNamespace(inbox=native,connector='bot',policy=current)
        accepted=[]
        def receive(event):
            envelope=adapter_envelope(event,'mattermost');relay.admit(current(),'bot',envelope);accepted.append(envelope);return True
        adapter.set_durable_message_handler(receive)
        clock=time.time()
        async def step():
            nonlocal clock
            clock+=30
            return await recover_one(adapter,current,'bot',now=clock)
        try:
            async with ClientSession(trust_env=False) as session:
                adapter._session=session
                assert await step()==100
                row=dict(native.db.execute('SELECT * FROM mattermost_history').fetchone());assert row['before_id']==post(151)['id']
                first_ceiling=row['ceiling'];assert await step()==100
                assert native.db.execute('SELECT ceiling FROM mattermost_history').fetchone()[0]==first_ceiling
                assert await step()==50
                assert native.db.execute('SELECT COUNT(*) FROM native_inbox').fetchone()[0]==250
                cases.append('three_actual_http_pages_retain_every_original')
                # Finished-window overlap must not duplicate retained receipts.
                for _ in range(3):await step()
                assert native.db.execute('SELECT COUNT(*) FROM native_inbox').fetchone()[0]==250
                cases.append('inclusive_overlap_is_idempotent')
                key=native.due('bot');assert await dispatch_stored(adapter,adapter._haos_native_dispatch,key)
                assert accepted[0]['scope']==team and accepted[0]['text'].startswith('recover ')
                cases.append('history_uses_actual_native_decoder_and_relay')
                state['posts']=[post(300)]
                original=native.admit
                def interrupted(*args,**kwargs):
                    original(*args,**kwargs);raise OSError('fixture crash after real raw COMMIT')
                native.admit=interrupted
                try:await step()
                except OSError:pass
                else:raise AssertionError('raw crash did not propagate')
                native.admit=original
                row=dict(native.db.execute('SELECT * FROM mattermost_history').fetchone());assert row['ceiling']==post(300)['create_at'] and row['before_id']==''
                native.close();native=NativeInbox(directory/'native.db',Redactor([token]));adapter._haos_native.inbox=native
                assert await step()==0
                assert native.db.execute('SELECT COUNT(*) FROM native_inbox WHERE message_id=?',(post(300)['id'],)).fetchone()[0]==1
                cases.append('crash_after_raw_commit_reopens_without_duplicate')
                # Fail the actual persistent history cursor update after 100 raw commits.
                state['posts']=[post(i) for i in range(400,501)]
                original_db=native.db
                class InterruptedCursor:
                    failed=False
                    def execute(self,sql,*args):
                        if sql.startswith('UPDATE mattermost_history SET before_id=') and not self.failed:
                            self.failed=True;raise sqlite3.OperationalError('fixture cursor write interruption')
                        return original_db.execute(sql,*args)
                    def __getattr__(self,key):return getattr(original_db,key)
                native.db=InterruptedCursor()
                try:await step()
                except sqlite3.OperationalError:pass
                else:raise AssertionError('cursor crash did not propagate')
                native.db=original_db
                assert await step()==0 and await step()==1
                assert native.db.execute('SELECT COUNT(*) FROM native_inbox WHERE message_id>=? AND message_id<=?',
                    (post(400)['id'],post(500)['id'])).fetchone()[0]==101
                cases.append('crash_before_cursor_commit_repeats_safely')
                state['posts']=[post(i) for i in range(600,701)]
                assert await step()==100
                state['expired_anchor']=True
                try:await step()
                except APIError as error:assert error.status==404
                else:raise AssertionError('expired remote anchor must remain a real HTTP failure')
                row=native.db.execute('SELECT * FROM mattermost_history').fetchone()
                assert row['before_id']=='' and row['ceiling'] is None
                assert await step()==0 and await step()==1
                assert native.db.execute('SELECT COUNT(*) FROM native_inbox WHERE message_id>=? AND message_id<=?',
                    (post(600)['id'],post(700)['id'])).fetchone()[0]==101
                cases.append('deleted_remote_anchor_restarts_same_floor_without_duplicate')
                for status,kind in [(429,'rate-limited'),(403,'permission-denied')]:
                    state['status']=status
                    try:await step()
                    except APIError:pass
                    else:raise AssertionError('real HTTP refusal must propagate')
                    row=native.db.execute('SELECT * FROM mattermost_history').fetchone()
                    assert row['status']==kind
                    if status==429:assert row['next_attempt']==clock+17
                    cases.append('actual_http_'+kind+'_is_persisted')
                state['status']=429;state['retry_after']=formatdate(time.time()+3600,usegmt=True)
                try:await step()
                except APIError as error:assert error.status==429
                else:raise AssertionError('dated history rate limit unexpectedly succeeded')
                row=dict(native.db.execute('SELECT * FROM mattermost_history').fetchone())
                assert row['status']=='rate-limited' and 3598<=row['next_attempt']-clock<=3600
                calls=len(state['calls']);native.close();native=NativeInbox(directory/'native.db',Redactor([token]))
                adapter._haos_native.inbox=native;del adapter._haos_mm_history_after
                assert await recover_one(adapter,current,'bot',now=clock+1)==0 and len(state['calls'])==calls
                cases.append('actual_http_date_history_deadline_survives_sqlite_reopen_without_early_get')
                clock=row['next_attempt']+1  # Advance only the fixture's explicit recovery clock.
                state['retry_after']='17';state['status']=200;state['malformed']=True
                before=dict(native.db.execute('SELECT * FROM mattermost_history').fetchone())
                try:await step()
                except ValueError:pass
                else:raise AssertionError('duplicate order identity accepted')
                after=dict(native.db.execute('SELECT * FROM mattermost_history').fetchone())
                assert before['before_id']==after['before_id'] and before['floor']==after['floor']
                state['malformed']=False;cases.append('malformed_page_never_advances_cursor')
                state['posts']=[post(900,create_at=int(time.time()*1000)+400000)]
                try:await step()
                except ValueError:pass
                else:raise AssertionError('future post accepted')
                cases.append('future_history_rejected_before_raw_admission')
                # A revoked publication cannot commit history after in-flight HTTP.
                state['posts']=[post(705)];state['revoke']=True
                count=native.db.execute('SELECT COUNT(*) FROM native_inbox').fetchone()[0]
                try:await step()
                except PermissionError:pass
                else:raise AssertionError('revocation during HTTP accepted')
                assert native.db.execute('SELECT COUNT(*) FROM native_inbox').fetchone()[0]==count
                state['revoke']=False;cases.append('revoke_during_http_has_no_raw_authority')
                # New grant generation starts its own boundary; old history never becomes fresh input.
                config['bindings'][0]['since']=int(time.time()*1000)
                state['posts']=[post(700)]
                assert await step()==0
                cases.append('repaired_grant_starts_at_new_owner_boundary')
                del config['bindings'][0]['since']
                before=len(state['calls']);assert await step()==0 and len(state['calls'])==before
                cases.append('legacy_grant_without_time_has_no_history_read')
                # Original 24h age is retained in SQLite, never reset by recovery time.
                binding=config['bindings'][0];binding['since']=int(time.time()*1000)-90000000;binding['generation']='e'*64
                state['posts']=[post(701,create_at=int(time.time()*1000)-87000000)]
                assert await step()==1
                key=native.db.execute('SELECT id FROM native_inbox WHERE message_id=?',(post(701)['id'],)).fetchone()[0]
                assert native.claim(key,current()) is None
                assert native.db.execute('SELECT state FROM native_inbox WHERE id=?',(key,)).fetchone()[0]=='expired'
                cases.append('original_age_retains_expired_input_without_execution')
                binding['since']=base-1;binding['generation']='f'*64;binding['thread']=thread
                state['posts']=[post(710,root_id=thread),post(711),post(712,root_id='w'*26)]
                assert await step()==1
                assert native.db.execute('SELECT COUNT(*) FROM native_inbox WHERE message_id IN (?,?)',
                    (post(711)['id'],post(712)['id'])).fetchone()[0]==0
                cases.append('only_exact_owner_thread_is_retained')
        finally:
            await runner.cleanup();native.close();relay.close()
    with tempfile.TemporaryDirectory() as value:asyncio.run(exercise(Path(value)))
    output=json.dumps({'passed':len(cases),'cases':cases,'external_connections':False},indent=2)+'\n'
    if len(sys.argv)>2:Path(sys.argv[2]).write_text(output)
    else:print(output,end='')


if __name__=='__main__':main()
