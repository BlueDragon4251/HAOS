#!/usr/bin/env python3
"""Actual native Slack SDK HTTP calls and reopened HAOS outbox certainty."""
import asyncio
import copy
import hashlib
import json
import os
from pathlib import Path
import socket
import sys
import tempfile
import time
from types import SimpleNamespace


def main():
    root=Path(sys.argv[1]).resolve();sys.path.insert(0,str(root))
    from aiohttp import web
    from slack_bolt.async_app import AsyncApp
    from haos.gateway_runtime import build_adapter,delivery_metadata
    from haos.gateway import GatewayPolicy,GatewayEngine
    from haos.gateway_delivery import delivery_result
    from haos.store import MissionStore
    results=[];state={'case':'','requests':[],'auth':[]}
    token='xoxb-'+'x'*24;app_token='xapp-'+'y'*24
    async def api(request):
        method=request.match_info['method']
        if method=='auth.test':
            state['auth'].append(request.headers['Authorization'])
            return web.json_response({'ok':True,'team_id':'T999','user_id':'UBOT','bot_id':'B1'})
        assert method=='chat.postMessage','unapproved API call: '+method
        assert request.headers['Authorization']=='Bearer '+token
        payload=await request.json();state['requests'].append(payload)
        case=state['case'];attempt=len(state['requests'])
        if case=='revoke-between-chunks' and attempt==1:
            state['policy'].bindings['paired']['generation']='b'*64
        if case=='revoke-before-format-fallback' and attempt==1:
            state['policy'].bindings['paired']['generation']='b'*64
            return web.json_response({'ok':False,'error':'invalid_blocks'})
        if case=='disconnect':request.transport.close();return web.Response()
        if case=='server-format':return web.json_response({'ok':False,'error':'invalid_blocks'},status=500)
        if case=='rate-limit':return web.json_response({'ok':False,'error':'ratelimited'},status=429,headers={'Retry-After':'120'})
        if case=='forbidden':return web.json_response({'ok':False,'error':'missing_scope'})
        if case=='unknown-error':return web.json_response({'ok':False,'error':'internal_error','message':'invalid_blocks'})
        if case=='format-refused' and attempt==1:return web.json_response({'ok':False,'error':'invalid_blocks'})
        return web.json_response({'ok':True,'channel':'C999' if case=='wrong-receipt' else payload['channel'],
            'ts':None if case=='malformed' else 'invalid' if case=='invalid-ts' else state['reply_ts']})
    async def exercise(directory):
        os.environ['HERMES_HOME']=str(directory/'hermes')
        for name in ('HTTP_PROXY','HTTPS_PROXY','ALL_PROXY','http_proxy','https_proxy','all_proxy'):os.environ.pop(name,None)
        app=web.Application();app.router.add_route('*','/api/{method}',api)
        runner=web.AppRunner(app);await runner.setup();site=web.TCPSite(runner,'127.0.0.1',0);await site.start()
        port=site._server.sockets[0].getsockname()[1]
        try:
            for case,expected,count in [('success','delivered',1),('server-format','uncertain',1),('format-refused','delivered',2),
                    ('rate-limit','pending',1),('forbidden','failed',1),('unknown-error','uncertain',1),
                    ('malformed','uncertain',1),('invalid-ts','uncertain',1),('wrong-receipt','uncertain',1),
                    ('disconnect','uncertain',1),('connect-refused','pending',0),('wrong-team','failed',0),
                    ('wrong-channel','failed',0),('thread-success','delivered',1),
                    ('forged-binding','failed',0),('missing-binding','failed',0),
                    ('policy-unavailable','failed',0),('revoke-between-chunks','uncertain',1),
                    ('revoke-before-format-fallback','failed',1)]:
                state.update(case=case,requests=[],reply_ts=f'{int(time.time())}.000055')
                adapter=build_adapter('slack',{'token':token,'app_token':app_token,'extra':{'rich_blocks':True}})
                client=adapter._new_web_client(token,None);client.base_url=f'http://127.0.0.1:{port}/api/'
                auth=await client.auth_test();adapter._team_clients[auth['team_id']]=client
                # SDK copies must retain their own identity, not a closure bound
                # to the primary client's token, URL or proxy attributes.
                if case=='success':
                    other=copy.copy(client);other.token='xoxb-'+'z'*24
                    await other.auth_test()
                    assert state['auth'][-2:]==['Bearer '+token,'Bearer '+other.token]
                adapter._app=AsyncApp(client=client)
                thread=f'{int(time.time())}.000010' if case=='thread-success' else ''
                policy=GatewayPolicy({'version':1,'connectors':[{'id':'bot','platform':'slack'}],'bindings':[
                    {'id':'paired','connector':'bot','sender':'U42','chat':'C123','scope':'T999','thread':thread,
                     'identity':'principal','capabilities':['create','read']}]})
                state['policy']=policy
                def current():
                    if state['case']=='policy-unavailable':raise PermissionError('fixture owner policy unavailable')
                    return policy
                adapter._haos_native=SimpleNamespace(connector='bot',policy=current)
                path=directory/(case+'.db');store=MissionStore(path);engine=GatewayEngine(store)
                try:
                    await engine.receive(policy,'bot',{'platform':'slack','sender':'U42','chat':'C123','scope':'T999','thread':thread,
                        'message_id':f'{int(time.time())}.000011','is_bot':False,'text':'fixture mission'},None)
                    delivery=engine.next_delivery(policy)
                    metadata=delivery_metadata(delivery,'slack')
                    if case=='wrong-team':metadata['slack_team_id']='T998'
                    if case=='forged-binding':metadata['haos_binding']['binding_digest']='0'*64
                    if case=='missing-binding':metadata.pop('haos_binding')
                    with socket.socket() as unused:
                        if case=='connect-refused':
                            unused.bind(('127.0.0.1',0));client.base_url=f'http://127.0.0.1:{unused.getsockname()[1]}/api/'
                        receipt=await adapter.send('U42' if case=='wrong-channel' else 'C123',
                            'r'*50000 if case=='revoke-between-chunks' else delivery['content'],
                            reply_to=delivery['reply_to'],metadata=metadata)
                    translated=delivery_result(receipt)
                    if case in {'revoke-between-chunks','revoke-before-format-fallback'}:policy.bindings['paired'].pop('generation')
                    engine.acknowledge(policy,delivery['id'],{**translated,'attempt':delivery['attempt']})
                    actual=store.db.execute('SELECT state FROM gateway_outbox WHERE id=?',(delivery['id'],)).fetchone()['state']
                    assert actual==expected,(case,translated,actual)
                    assert len(state['requests'])==count,(case,len(state['requests']))
                    for payload in state['requests']:
                        assert payload['channel']=='C123' and (payload.get('thread_ts') or '')==thread
                        assert not payload.get('reply_broadcast')
                    if case in {'server-format','format-refused','unknown-error'}:assert state['requests'][0].get('blocks')
                    if case=='format-refused':assert 'blocks' not in state['requests'][1]
                    store.close();store=MissionStore(path)
                    assert store.db.execute('SELECT state FROM gateway_outbox WHERE id=?',(delivery['id'],)).fetchone()['state']==expected
                    results.append({'case':case,'actual_http_posts':count,'reopened_outbox_state':expected})
                finally:
                    store.close()
                    if client.session is not None:await client.session.close()
        finally:await runner.cleanup()
    with tempfile.TemporaryDirectory() as directory:asyncio.run(exercise(Path(directory)))
    receipt={'actual_native_sdk_http_outbox_cases':results,'external_slack_connected':False,
        'source_files':[{'path':p.name,'sha256':hashlib.sha256(p.read_bytes()).hexdigest()} for p in
            (Path(__file__),root/'haos/gateway_slack.py',root/'haos/gateway_ingress.py',root/'haos/gateway_runtime.py')]}
    Path(sys.argv[2]).write_text(json.dumps(receipt,indent=2)+'\n');print(json.dumps(receipt))


if __name__=='__main__':main()
