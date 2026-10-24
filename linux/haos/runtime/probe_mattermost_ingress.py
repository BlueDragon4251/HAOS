#!/usr/bin/env python3
"""Actual pinned Mattermost aiohttp/WebSocket/native decoder plus durable HAOS journals."""
import asyncio
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
    from aiohttp import web, ClientSession
    from haos.gateway import GatewayPolicy
    from haos.gateway_raw import NativeInbox
    from haos.gateway_relay import RelayInbox
    from haos.gateway_runtime import build_adapter,adapter_envelope
    from haos.gateway_mattermost import APIError,capture,dispatch_stored
    from haos.redaction import Redactor
    cases=[]
    async def exercise(directory):
        os.environ['HERMES_HOME']=str(directory/'hermes')
        for name in ('HTTP_PROXY','HTTPS_PROXY','ALL_PROXY','http_proxy','https_proxy','all_proxy'):
            os.environ.pop(name,None)
        bot,user,chat,team,thread=('b'*26,'u'*26,'c'*26,'s'*26,'t'*26)
        token='x'*26
        config={'version':1,'connectors':[{'id':'bot','platform':'mattermost'}],'bindings':[
            {'id':'paired','connector':'bot','sender':user,'chat':chat,'scope':team,'thread':'',
             'identity':'principal','capabilities':['create','read'],'generation':'a'*64,'since':int(time.time()*1000)-10000}]}
        current=lambda:GatewayPolicy(config)
        native=NativeInbox(directory/'native.db',Redactor([token]))
        relay=RelayInbox(directory/'relay.db',Redactor([token]))
        state={'auth':'OK','bot':False,'team':team,'sockets':[],'ack':asyncio.Event(),'redirect':False,'leaked':0,'calls':[]}
        accepted=[]
        async def api(request):
            state['calls'].append(request.path)
            assert request.headers['Authorization']=='Bearer '+token
            if request.path.endswith('/posts/'+thread):return web.json_response({'id':thread,'channel_id':chat,'root_id':''})
            if request.path.endswith('/users/me'):return web.json_response({'id':bot,'username':'herald'})
            if request.path.endswith('/users/'+user):return web.json_response({'id':user,'is_bot':state['bot']})
            if request.path.endswith('/channels/'+chat):
                if state['redirect']:return web.Response(status=302,headers={'Location':'/leak'})
                return web.json_response({'id':chat,'team_id':state['team'],'type':'O'})
            raise AssertionError('unapproved native Mattermost API call '+request.path)
        async def ws(request):
            if state.get('ws_redirect'):return web.Response(status=302,headers={'Location':'/leak'})
            socket=web.WebSocketResponse();await socket.prepare(request);state['sockets'].append(socket)
            challenge=await socket.receive_json()
            assert challenge=={'seq':1,'action':'authentication_challenge','data':{'token':token}}
            # A posted frame before authentication must never reach authority/decoder.
            await socket.send_json(event('z'*26))
            await state['ack'].wait()
            await socket.send_json({'seq_reply':1,'status':state['auth']})
            async for _message in socket:pass
            return socket
        async def leak(request):state['leaked']+=1;return web.json_response({})
        app=web.Application();app.router.add_get('/api/v4/websocket',ws)
        app.router.add_route('*','/api/v4/{tail:.*}',api);app.router.add_route('*','/leak',leak)
        runner=web.AppRunner(app);await runner.setup();site=web.TCPSite(runner,'127.0.0.1',0);await site.start()
        port=site._server.sockets[0].getsockname()[1]
        def event(identity,**changes):
            post={'id':identity,'user_id':user,'channel_id':chat,'root_id':'','message':'@herald native input',
                  'create_at':int(time.time()*1000),'props':{},'type':'','file_ids':[]}
            post.update(changes)
            return {'event':'posted','data':{'post':json.dumps(post),'channel_type':'O'}}
        def build():
            adapter=build_adapter('mattermost',{'token':token,'server_url':'https://owner.invalid'})
            adapter._base_url=f'http://127.0.0.1:{port}'
            adapter._haos_native=SimpleNamespace(inbox=native,connector='bot',policy=current)
            def receive(message):
                envelope=adapter_envelope(message,'mattermost')
                # Actual native decoding runs only after an independent reader sees COMMIT.
                with sqlite3.connect(directory/'native.db') as observer:
                    row=observer.execute('SELECT state FROM native_inbox WHERE message_id=?',(envelope['message_id'],)).fetchone()
                    assert row is not None and row[0]=='processing'
                relay.admit(current(),'bot',envelope);accepted.append(envelope)
                return True
            adapter.set_durable_message_handler(receive)
            return adapter
        async def eventually(predicate):
            async with asyncio.timeout(4):
                while not predicate():await asyncio.sleep(.01)
        adapter=build()
        try:
            connection=asyncio.create_task(adapter.connect())
            await eventually(lambda:bool(state['sockets']))
            assert not adapter.is_connected and not accepted
            cases.append('native_ws_requires_real_auth_ack_before_healthy')
            state['ack'].set();assert await connection and adapter.is_connected
            assert native.db.execute('SELECT COUNT(*) FROM native_inbox').fetchone()[0]==0
            cases.append('unauthenticated_post_has_no_haos_authority')
            first=event('p'*26)
            await state['sockets'][-1].send_json(first)
            await eventually(lambda:len(accepted)==1)
            assert accepted[0]['scope']==team and accepted[0]['text']=='native input'
            assert native.db.execute('SELECT state FROM native_inbox').fetchone()[0]=='committed'
            cases.append('actual_ws_decoder_commits_raw_before_relay_with_actual_scope')
            await state['sockets'][-1].send_json(first);await asyncio.sleep(.05)
            assert len(accepted)==1
            cases.append('native_duplicate_does_not_repeat_durable_admission')
            key=await capture(adapter,event('n'*26,message='@herald '+('漢'*12000)))
            assert key is not None and await dispatch_stored(adapter,adapter._haos_native_dispatch,key)
            assert accepted[-1]['text']=='漢'*12000
            accepted.pop()
            cases.append('large_escaped_unicode_post_preserves_native_text')
            await adapter.disconnect()
            assert not adapter.is_connected
            assert await adapter.connect() and adapter.is_connected
            await state['sockets'][-1].send_json(first);await asyncio.sleep(.05)
            assert len(accepted)==1
            cases.append('actual_same_adapter_reconnect_keeps_durable_dedup')
            for name,frame in [
                ('unknown_sender',event('q'*26,user_id='v'*26)),('wrong_thread',event('q'*26,root_id=thread)),
                ('media',event('q'*26,file_ids=['f'*26])),('system',event('q'*26,type='system_join_channel')),
                ('missing_mention',event('q'*26,message='unaddressed')),('edited',event('q'*26,edit_at=1)),
                ('malformed_props',event('q'*26,props=[]))]:
                assert await capture(adapter,frame) is None
                assert len(accepted)==1
                cases.append(name+'_refused_before_native_preparation')
            state['bot']=True;assert await capture(adapter,event('q'*26)) is None;state['bot']=False
            cases.append('actual_server_bot_identity_refused')
            state['team']='w'*26
            try:await capture(adapter,event('q'*26))
            except PermissionError:pass
            else:raise AssertionError('wrong team accepted')
            state['team']=team;cases.append('actual_server_team_mismatch_refused')
            # Capture survives a decoder crash and a daemon restart without another WS event.
            key=await capture(adapter,event('r'*26))
            async def crashed(_adapter,_event):raise ConnectionError('fixture decoder interruption')
            try:await dispatch_stored(adapter,crashed,key)
            except ConnectionError:pass
            else:raise AssertionError('decoder crash must propagate')
            assert native.db.execute('SELECT state FROM native_inbox WHERE id=?',(key,)).fetchone()[0]=='pending'
            native.close();native=NativeInbox(directory/'native.db',Redactor([token]))
            adapter._haos_native.inbox=native
            native.db.execute('UPDATE native_inbox SET next_attempt=0 WHERE id=?',(key,))
            assert await dispatch_stored(adapter,adapter._haos_native_dispatch,key)
            assert len(accepted)==2;cases.append('reopened_raw_decoder_recovery')
            key=await capture(adapter,event('h'*26));config['bindings'][0]['generation']='d'*64
            assert not await dispatch_stored(adapter,adapter._haos_native_dispatch,key)
            assert len(accepted)==2;cases.append('revoked_generation_cannot_execute_retained_input')
            state['redirect']=True
            try:await capture(adapter,event('j'*26))
            except APIError as error:assert error.status==302
            else:raise AssertionError('redirect must fail closed')
            assert state['leaked']==0;state['redirect']=False
            cases.append('native_session_redirect_rejected_before_forwarding')
            await adapter.disconnect()
            adapter=build();state['auth']='FAIL'
            assert not await adapter.connect() and not adapter.is_connected and adapter.has_fatal_error
            cases.append('real_ws_auth_refusal_is_fatal_and_unhealthy')
            from haos.gateway_raw_recovery import unresolved
            safe_status=unresolved(native)['transport']
            assert safe_status[0]['status']=='authentication-refused' and safe_status[0]['connector']=='bot'
            assert token not in json.dumps(safe_status)
            cases.append('owner_receives_safe_persisted_auth_status_without_token')
            await adapter.disconnect()
            adapter=build();state['ws_redirect']=True
            adapter._session=ClientSession(trust_env=False)
            try:await adapter._ws_connect_and_listen()
            except PermissionError:pass
            else:raise AssertionError('WebSocket redirect must be refused')
            assert state['leaked']==0
            cases.append('actual_ws_redirect_refused_before_token_challenge')
        finally:
            await adapter.disconnect();await runner.cleanup();native.close();relay.close()
    with tempfile.TemporaryDirectory() as value:asyncio.run(exercise(Path(value)))
    data={'passed':len(cases),'cases':cases,'external_connections':False,'source_files':[
        {'path':str(path.relative_to(root.parents[1])),'sha256':hashlib.sha256(path.read_bytes()).hexdigest()} for path in [
            root/'haos/gateway_mattermost.py',root/'haos/gateway_ingress.py',root/'haos/gateway_runtime.py']]}
    output=json.dumps(data,indent=2)+'\n'
    if len(sys.argv)>2:Path(sys.argv[2]).write_text(output)
    else:print(output,end='')


if __name__=='__main__':main()
