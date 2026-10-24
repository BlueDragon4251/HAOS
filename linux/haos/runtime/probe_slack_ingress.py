#!/usr/bin/env python3
"""Actual Slack SDK HTTP/Bolt/Socket Mode ACK must follow private durable capture."""
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
    from aiohttp import web
    from slack_bolt.async_app import AsyncApp
    from slack_bolt.adapter.socket_mode.async_handler import AsyncSocketModeHandler
    from haos.gateway import GatewayPolicy
    from haos.gateway_raw import NativeInbox
    from haos.gateway_relay import RelayInbox
    from haos.gateway_runtime import build_adapter,adapter_envelope
    from haos import gateway_slack
    from haos.redaction import Redactor
    cases=[]
    async def exercise(directory):
        os.environ['HERMES_HOME']=str(directory/'hermes')
        # Every fixture target is loopback. SDK-created Bolt client copies must
        # not send these local-only requests through an inherited egress proxy.
        for name in ('HTTP_PROXY','HTTPS_PROXY','ALL_PROXY','http_proxy','https_proxy','all_proxy'):
            os.environ.pop(name,None)
        token='xoxb-'+'x'*24;app_token='xapp-'+'y'*24
        config={'version':1,'connectors':[{'id':'bot','platform':'slack'}],'bindings':[
            {'id':'paired','connector':'bot','sender':'U42','chat':'C123','scope':'T999','thread':'',
                'identity':'principal','capabilities':['create','read']}]}
        current=lambda:GatewayPolicy(config)
        native=NativeInbox(directory/'native.db',Redactor([token,app_token]))
        relay=RelayInbox(directory/'relay.db',Redactor([token,app_token]))
        acknowledgements=asyncio.Queue();api_calls=[]
        async def api(request):
            method=request.match_info['method'];api_calls.append(method)
            if method=='auth.test':return web.json_response({'ok':True,'team_id':'T999','user_id':'UBOT','bot_id':'B1','team':'Fixture'})
            if method=='users.info':return web.json_response({'ok':True,'user':{'id':'U42','is_bot':False,'name':'fixture'}})
            raise AssertionError('unapproved Slack API call: '+method)
        async def websocket(request):
            socket=web.WebSocketResponse();await socket.prepare(request)
            async for message in socket:
                ack=json.loads(message.data)
                # Independent reader proves the SDK ACK cannot race an uncommitted raw input.
                if ack['envelope_id'].startswith('approved'):
                    with sqlite3.connect(directory/'native.db') as observer:
                        assert observer.execute('SELECT COUNT(*) FROM native_inbox').fetchone()[0]>0
                await acknowledgements.put(ack)
            return socket
        app=web.Application();app.router.add_route('*','/api/{method}',api);app.router.add_get('/socket',websocket)
        runner=web.AppRunner(app);await runner.setup();site=web.TCPSite(runner,'127.0.0.1',0);await site.start()
        port=site._server.sockets[0].getsockname()[1]
        adapter=build_adapter('slack',{'token':token,'app_token':app_token})
        adapter._haos_native=SimpleNamespace(inbox=native,connector='bot',policy=current)
        adapter.set_durable_message_handler(lambda event:bool(relay.admit(current(),'bot',adapter_envelope(event,'slack'))))
        client=adapter._new_web_client(token,None);client.base_url=f'http://127.0.0.1:{port}/api/'
        # Real SDK auth.test pins this fixture's authenticated workspace.
        auth=await client.auth_test();adapter._team_clients[auth['team_id']]=client
        adapter._team_bot_user_ids['T999']='UBOT';adapter._bot_user_id='UBOT'
        adapter._app=AsyncApp(client=client,token=token)
        adapter._register_bolt_handlers()
        handler=AsyncSocketModeHandler(adapter._app,app_token,web_client=client)
        adapter._handler=handler
        handler.client.current_session=await handler.client.aiohttp_client_session.ws_connect(f'http://127.0.0.1:{port}/socket')
        timestamp=f'{int(time.time())}.000001'
        def frame(identity,sender='U42',channel='C123',team='T999',ts=None):
            event={'type':'message','channel':channel,'channel_type':'channel','user':sender,
                'text':'<@UBOT> fixture task','ts':ts or timestamp,'client_msg_id':identity}
            return {'type':'events_api','envelope_id':identity,'accepts_response_payload':False,
                'payload':{'type':'event_callback','team_id':team,'api_app_id':'A1','event_id':identity,
                    'event':event,'authorizations':[{'team_id':team,'user_id':'UBOT','is_bot':True}]}}
        async def deliver(value):
            await handler.client.run_message_listeners(value,json.dumps(value))
        async def wait_relay(count):
            for _ in range(100):
                if relay.db.execute('SELECT COUNT(*) FROM inbox').fetchone()[0]==count:return
                await asyncio.sleep(.01)
            raise AssertionError('native Slack handler did not durably route expected input')
        try:
            from agent.secret_scope import get_secret
            other=build_adapter('slack',{'token':'xoxb-'+'b'*24,'app_token':'xapp-'+'c'*24})
            os.environ['SLACK_APP_TOKEN']='xapp-'+'ambient'*5
            os.environ['OPENAI_API_KEY']='fixture-ambient-provider-canary'
            async def scoped(item):
                with gateway_slack.secret_scope(item._haos_secrets,item._haos_secret_home):
                    await asyncio.sleep(0)
                    assert get_secret('OPENAI_API_KEY') is None
                    return get_secret('SLACK_APP_TOKEN')
            assert await asyncio.gather(scoped(adapter),scoped(other))==[app_token,'xapp-'+'c'*24]
            assert os.environ['SLACK_APP_TOKEN']=='xapp-'+'ambient'*5
            cases.append('real Hermes task-local secret scopes isolate app tokens and refuse ambient provider credentials')
            with gateway_slack.secret_scope(adapter._haos_secrets,adapter._haos_secret_home):
                await deliver(frame('approved-one'))
            ack=await asyncio.wait_for(acknowledgements.get(),2);assert ack['envelope_id']=='approved-one'
            await wait_relay(1)
            cases.append('actual SDK Socket Mode ACK follows independent-reader-visible capture; native Bolt reaches relay')
            # Different Socket Mode delivery envelopes still describe the same source-scoped message.
            with gateway_slack.secret_scope(adapter._haos_secrets,adapter._haos_secret_home):
                await deliver(frame('approved-replay'))
            await asyncio.wait_for(acknowledgements.get(),2);await asyncio.sleep(.02)
            assert relay.db.execute('SELECT COUNT(*) FROM inbox').fetchone()[0]==1
            cases.append('different transport envelopes for same Slack message remain idempotent')
            for value in [frame('denied-user',sender='U43'),frame('denied-channel',channel='C124'),frame('denied-team',team='T998')]:
                await deliver(value);await asyncio.wait_for(acknowledgements.get(),2)
            assert relay.db.execute('SELECT COUNT(*) FROM inbox').fetchone()[0]==1
            cases.append('unknown sender channel or workspace acknowledged as refused without HAOS authority')
            native.db.execute("CREATE TRIGGER fixture_raw_failure BEFORE INSERT ON native_inbox BEGIN SELECT RAISE(ABORT,'fixture capture failed'); END")
            failed=frame('approved-storage',ts=f'{int(time.time())}.000002')
            await deliver(failed)
            try:await asyncio.wait_for(acknowledgements.get(),.1)
            except TimeoutError:pass
            else:raise AssertionError('failed durable Slack capture was acknowledged')
            native.db.execute('DROP TRIGGER fixture_raw_failure')
            await deliver(failed);await asyncio.wait_for(acknowledgements.get(),2);await wait_relay(2)
            cases.append('real SQLite capture failure suppresses SDK ACK and same source can retry')
            relay.db.execute("CREATE TRIGGER fixture_decoder_failure BEFORE INSERT ON inbox BEGIN SELECT RAISE(ABORT,'fixture relay unavailable'); END")
            replay=frame('approved-restart',ts=timestamp.split('.')[0]+'.000003')
            await deliver(replay);await asyncio.wait_for(acknowledgements.get(),2)
            source=gateway_slack.envelope(adapter,replay['payload']['event'],replay['payload'])
            key=native.key('bot',source)
            for _ in range(100):
                row=native.db.execute('SELECT state,attempt FROM native_inbox WHERE id=?',(key,)).fetchone()
                if row['state']=='pending' and row['attempt']==1:break
                await asyncio.sleep(.01)
            else:raise AssertionError('decoder failure lost retained input after ACK')
            relay.db.execute('DROP TRIGGER fixture_decoder_failure')
            native.close();native=NativeInbox(directory/'native.db',Redactor([token,app_token]));adapter._haos_native.inbox=native
            native.db.execute('UPDATE native_inbox SET next_attempt=0 WHERE id=?',(key,))
            assert await gateway_slack.dispatch_stored(adapter,adapter._haos_native_dispatch,key) is True
            assert await gateway_slack.dispatch_stored(adapter,adapter._haos_native_dispatch,key) is False
            assert relay.db.execute('SELECT COUNT(*) FROM inbox').fetchone()[0]==3
            cases.append('actual Bolt decoder failure after ACK survives reopen and reaches relay once')
            root_ts=timestamp.split('.')[0]+'.000010'
            config['bindings'].append({**config['bindings'][0],'id':'thread','thread':root_ts})
            threaded=frame('approved-thread',ts=timestamp.split('.')[0]+'.000011')
            threaded['payload']['event']['thread_ts']=root_ts
            await deliver(threaded);await asyncio.wait_for(acknowledgements.get(),2);await wait_relay(4)
            assert json.loads(relay.db.execute('SELECT envelope FROM inbox ORDER BY created_at DESC LIMIT 1').fetchone()[0])['thread']==root_ts
            denied=frame('denied-thread',ts=timestamp.split('.')[0]+'.000012');denied['payload']['event']['thread_ts']=timestamp.split('.')[0]+'.000020'
            await deliver(denied);await asyncio.wait_for(acknowledgements.get(),2)
            assert relay.db.execute('SELECT COUNT(*) FROM inbox').fetchone()[0]==4
            cases.append('exact Slack thread admitted through native builder; other thread refused')
            assert gateway_slack.allowed(adapter,'U42','C123') is False
            config['bindings']=[]
            await deliver(frame('denied-revoked',ts=timestamp.split('.')[0]+'.000030'))
            await asyncio.wait_for(acknowledgements.get(),2)
            assert relay.db.execute('SELECT COUNT(*) FROM inbox').fetchone()[0]==4
            cases.append('current grant revocation and out-of-context native authority fail closed')
            adapter._haos_stopping=True
            native.close()
            assert await gateway_slack.dispatch_stored(adapter,adapter._haos_native_dispatch,'0'*64) is False
            await deliver(frame('denied-stopping',ts=timestamp.split('.')[0]+'.000040'))
            try:await asyncio.wait_for(acknowledgements.get(),.1)
            except TimeoutError:pass
            else:raise AssertionError('stopping gateway acknowledged input without durable capture')
            cases.append('late SDK callbacks cannot touch closed journal or acknowledge fresh input during shutdown')
        finally:
            await handler.client.close()
            if client.session is not None:await client.session.close()
            await runner.cleanup();native.close();relay.close()
    with tempfile.TemporaryDirectory() as directory:asyncio.run(exercise(Path(directory)))
    receipt={'actual_sdk_socket_bolt_cases':cases,'external_slack_connected':False,
        'full_slack_owner_setup_and_delivery_complete':False,'source_files':[{'path':p.name,'sha256':hashlib.sha256(p.read_bytes()).hexdigest()}
            for p in (Path(__file__),root/'haos/gateway_slack.py',root/'haos/gateway_ingress.py',root/'haos/gateway_runtime.py')]}
    Path(sys.argv[2]).write_text(json.dumps(receipt,indent=2)+'\n');print(json.dumps(receipt))


if __name__=='__main__':main()
