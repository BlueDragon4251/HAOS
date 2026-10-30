#!/usr/bin/env python3
"""Actual SDK history windows/pages, SQLite failure recovery and owner boundaries."""
import asyncio
from decimal import Decimal
import hashlib
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
    from aiohttp import web
    from slack_sdk.errors import SlackApiError
    from haos.gateway import GatewayPolicy,digest
    from haos.gateway_raw import NativeInbox
    from haos.gateway_relay import RelayInbox
    from haos.gateway_raw_recovery import unresolved
    from haos.gateway_runtime import build_adapter,adapter_envelope
    from haos.gateway_slack_history import recover_one,boundary
    from haos import gateway_slack
    from haos.redaction import Redactor
    cases=[]
    async def exercise(directory):
        os.environ['HERMES_HOME']=str(directory/'hermes')
        for name in ('HTTP_PROXY','HTTPS_PROXY','ALL_PROXY','http_proxy','https_proxy','all_proxy'):os.environ.pop(name,None)
        since=time.time_ns()//1_000_000-60000
        binding={'id':'paired','connector':'bot','sender':'U42','chat':'C123','scope':'T999','thread':'',
            'identity':'principal','capabilities':['create','read'],'generation':'a'*64,'since':since}
        config={'version':1,'connectors':[{'id':'bot','platform':'slack'}],'bindings':[binding]}
        current=lambda:GatewayPolicy(config);floor=Decimal(boundary(binding))
        def message(when,user='U42',**extra):
            return {'type':'message','user':user,'text':'<@UBOT> fixture recovery','ts':f'{when:.6f}',**extra}
        state={'messages':[message(floor),message(floor+Decimal('.000010')),
            message(floor+Decimal('.000020'),'U43'),message(floor+Decimal('.000030'))],
            'requests':[],'page_size':2,'error':None,'revoke':False,'invalid_cursor':False}
        token='xoxb-'+'x'*24;app_token='xapp-'+'y'*24
        async def api(request):
            method=request.match_info['method']
            assert request.headers['Authorization']=='Bearer '+token
            if method=='auth.test':return web.json_response({'ok':True,'team_id':'T999','user_id':'UBOT','bot_id':'B1'})
            if method=='users.info':return web.json_response({'ok':True,'user':{'id':'U42','is_bot':False,'name':'fixture'}})
            assert method in {'conversations.history','conversations.replies'},method
            params=dict(request.query);state['requests'].append({'method':method,**params})
            assert params['limit']=='15' and params.get('inclusive') in {'1','true','True'}
            if state['revoke']:config['bindings']=[]
            if state['error']=='rate':return web.json_response({'ok':False,'error':'ratelimited'},status=429,headers={'Retry-After':'120'})
            if state['error']=='permission':return web.json_response({'ok':False,'error':'missing_scope'})
            if state['invalid_cursor'] and params.get('cursor'):
                state['invalid_cursor']=False
                return web.json_response({'ok':False,'error':'invalid_cursor'})
            messages=sorted([m for m in state['messages'] if Decimal(params['oldest'])<=Decimal(m['ts'])<=Decimal(params['latest'])],
                key=lambda m:Decimal(m['ts']),reverse=True)
            if state.get('force_invalid'):messages=state['messages']
            offset=int(params.get('cursor','page-0').split('-')[1]);size=state['page_size']
            page=messages[offset:offset+size];more=offset+size<len(messages)
            return web.json_response({'ok':True,'messages':page,'has_more':more,
                'response_metadata':{'next_cursor':f'page-{offset+size}' if more else ''}})
        app=web.Application();app.router.add_route('*','/api/{method}',api)
        runner=web.AppRunner(app);await runner.setup();site=web.TCPSite(runner,'127.0.0.1',0);await site.start()
        port=site._server.sockets[0].getsockname()[1]
        adapter=build_adapter('slack',{'token':token,'app_token':app_token})
        client=adapter._new_web_client(token,None);client.base_url=f'http://127.0.0.1:{port}/api/'
        auth=await client.auth_test();adapter._team_clients[auth['team_id']]=client
        adapter._team_bot_user_ids['T999']='UBOT';adapter._bot_user_id='UBOT'
        native=NativeInbox(directory/'native.db',Redactor([token,app_token]));relay=RelayInbox(directory/'relay.db',Redactor())
        adapter._haos_native=SimpleNamespace(inbox=native,connector='bot',policy=current)
        adapter.set_durable_message_handler(lambda event:bool(relay.admit(current(),'bot',adapter_envelope(event,'slack'))))
        logical=time.time()
        async def step():
            nonlocal logical
            logical+=121
            return await recover_one(adapter,current,'bot',now=logical)
        try:
            native.db.execute("CREATE TRIGGER fixture_capture_failure BEFORE INSERT ON native_inbox BEGIN SELECT RAISE(ABORT,'fixture raw unavailable'); END")
            try:await step()
            except sqlite3.DatabaseError:pass
            else:raise AssertionError('history page cursor advanced without durable input')
            assert native.db.execute('SELECT page_cursor FROM slack_history').fetchone()[0]==''
            assert native.db.execute('SELECT COUNT(*) FROM native_inbox').fetchone()[0]==0
            native.db.execute('DROP TRIGGER fixture_capture_failure')
            assert await step()==1
            assert await step()==1
            assert native.db.execute('SELECT COUNT(*) FROM native_inbox').fetchone()[0]==2
            assert state['requests'][0]['latest']==state['requests'][1]['latest']==state['requests'][2]['latest']
            assert state['requests'][2]['cursor']=='page-2'
            cases.append('real SDK descending pages retain one window; failed raw commit cannot advance page cursor')
            cases.append('only exact authorized post-grant messages are captured; boundary equality and unknown sender refused')
            native.close();native=NativeInbox(directory/'native.db',Redactor([token,app_token]));adapter._haos_native.inbox=native
            for row in native.db.execute('SELECT id FROM native_inbox').fetchall():
                assert await gateway_slack.dispatch_stored(adapter,adapter._haos_native_dispatch,row['id']) is True
            assert relay.db.execute('SELECT COUNT(*) FROM inbox').fetchone()[0]==2
            assert await step()==0
            assert await step()==0
            assert relay.db.execute('SELECT COUNT(*) FROM inbox').fetchone()[0]==2
            cases.append('reopened raw input uses actual native decoder once; overlapping inclusive windows remain idempotent')
            state['messages'].append(message(floor+Decimal('.000040')))
            native.db.execute("CREATE TRIGGER fixture_cursor_failure BEFORE UPDATE ON slack_history WHEN NEW.page_cursor!=OLD.page_cursor BEGIN SELECT RAISE(ABORT,'fixture cursor unavailable'); END")
            try:await step()
            except sqlite3.DatabaseError:pass
            else:raise AssertionError('fixture failed to interrupt cursor write after raw commit')
            assert native.db.execute('SELECT COUNT(*) FROM native_inbox').fetchone()[0]==3
            native.db.execute('DROP TRIGGER fixture_cursor_failure')
            native.close();native=NativeInbox(directory/'native.db',Redactor([token,app_token]));adapter._haos_native.inbox=native
            assert await step()==0
            assert await step()==0
            assert await step()==0
            assert native.db.execute('SELECT COUNT(*) FROM native_inbox').fetchone()[0]==3
            cases.append('crash after raw commit before provider cursor write replays without duplicate retained input')
            state['invalid_cursor']=True
            assert await step()==0
            assert await step()==0
            assert native.db.execute('SELECT page_cursor FROM slack_history').fetchone()[0]==''
            assert await step()==0
            assert await step()==0
            assert await step()==0
            cases.append('actual SDK invalid-cursor refusal restarts the same retained window safely')
            state['error']='rate'
            try:await step()
            except SlackApiError:pass
            else:raise AssertionError('fixture rate limit was not enforced')
            count=len(state['requests'])
            assert await recover_one(adapter,current,'bot',now=logical+119)==0 and len(state['requests'])==count
            assert any(row['status']=='rate-limited' for row in unresolved(native)['history'])
            state['error']='permission'
            try:await step()
            except SlackApiError:pass
            else:raise AssertionError('actual SDK missing-scope error disappeared')
            assert any(row['status']=='permission-denied' for row in unresolved(native)['history'])
            cases.append('real SDK rate-limit delay survives scheduling and fixed permission status is owner-visible')
            state.update(error=None,revoke=True)
            try:await step()
            except PermissionError:pass
            else:raise AssertionError('revocation during HTTP did not stop recovery')
            assert native.db.execute('SELECT COUNT(*) FROM native_inbox').fetchone()[0]==3
            cases.append('root grant is rechecked after real HTTP completes, before admission or cursor advancement')
            state['revoke']=False;config['bindings']=[{**binding,'generation':'b'*64,'since':time.time_ns()//1_000_000-1000}]
            assert await step()==0
            assert Decimal(state['requests'][-1]['oldest'])>floor
            config['bindings']=[{key:value for key,value in binding.items() if key!='since'}]
            count=len(state['requests']);assert await step()==0 and len(state['requests'])==count
            cases.append('repaired grants start a fresh boundary and legacy grants do not fetch historic conversations')
            old_since=time.time_ns()//1_000_000-3*86400000
            config['bindings']=[{**binding,'generation':'c'*64,'since':old_since}]
            old=Decimal(str(time.time()-2*86400)).quantize(Decimal('.000001'))
            state['messages']=[message(old)];state['page_size']=15
            assert await step()==1
            stored=native.db.execute('SELECT id,created_at FROM native_inbox WHERE message_id=?',(f'{old:.6f}',)).fetchone()
            assert stored['created_at']==float(old)
            assert await gateway_slack.dispatch_stored(adapter,adapter._haos_native_dispatch,stored['id']) is False
            assert native.db.execute('SELECT state FROM native_inbox WHERE id=?',(stored['id'],)).fetchone()[0]=='expired'
            cases.append('original provider timestamp is atomic and expired missed messages stay retained without execution')
            state['force_invalid']=True;state['messages']=[message(Decimal(str(time.time()+600)).quantize(Decimal('.000001')))]
            previous=native.db.execute('SELECT floor,page_cursor FROM slack_history WHERE binding_digest=?',(digest(config['bindings'][0]),)).fetchone()
            try:await step()
            except ValueError:pass
            else:raise AssertionError('out-of-window/future message advanced provider cursor')
            after=native.db.execute('SELECT floor,page_cursor FROM slack_history WHERE binding_digest=?',
                (digest(config['bindings'][0]),)).fetchone()
            assert tuple(after)==tuple(previous)
            cases.append('future or out-of-window provider data cannot advance committed history floor')
            state['force_invalid']=False
            parent=floor+Decimal('.000100');child=parent+Decimal('.000001')
            config['bindings']=[{**binding,'generation':'d'*64,'thread':f'{parent:.6f}'}]
            state['messages']=[message(parent,thread_ts=f'{parent:.6f}'),message(child,thread_ts=f'{parent:.6f}')]
            assert await step()==1
            assert state['requests'][-1]['method']=='conversations.replies' and state['requests'][-1]['ts']==f'{parent:.6f}'
            thread_row=native.db.execute('SELECT id FROM native_inbox WHERE message_id=?',(f'{child:.6f}',)).fetchone()
            assert await gateway_slack.dispatch_stored(adapter,adapter._haos_native_dispatch,thread_row['id']) is True
            assert relay.db.execute('SELECT COUNT(*) FROM inbox').fetchone()[0]==3
            cases.append('actual SDK replies endpoint and native decoder preserve exact thread grant; parent is not a flat grant')
        finally:
            native.close();relay.close()
            if client.session is not None:await client.session.close()
            await runner.cleanup()
    with tempfile.TemporaryDirectory() as directory:asyncio.run(exercise(Path(directory)))
    receipt={'actual_sdk_http_history_cases':cases,'external_slack_connected':False,
        'remote_retention_deleted_messages_recoverable':False,'source_files':[{'path':p.name,'sha256':hashlib.sha256(p.read_bytes()).hexdigest()}
            for p in (Path(__file__),root/'haos/gateway_slack_history.py',root/'haos/gateway_runtime.py',root/'haos/gateway_raw_recovery.py')]}
    Path(sys.argv[2]).write_text(json.dumps(receipt,indent=2)+'\n');print(json.dumps(receipt))


if __name__=='__main__':main()
