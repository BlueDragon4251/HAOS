#!/usr/bin/env python3
"""Actual native Mattermost posts classified into reopened real mission outbox states."""
import asyncio
from email.utils import formatdate
import json
import os
from pathlib import Path
import sys
import tempfile
import time
from types import SimpleNamespace


def main():
    root=Path(sys.argv[1]).resolve();sys.path.insert(0,str(root))
    from aiohttp import ClientSession,web
    from haos.gateway import GatewayEngine,GatewayPolicy,digest
    from haos.gateway_runtime import build_adapter,delivery_metadata
    from haos.gateway_delivery import delivery_result
    from haos.store import MissionStore
    cases=[]
    async def exercise(directory):
        os.environ['HERMES_HOME']=str(directory/'hermes')
        chat,user,team,thread='c'*26,'u'*26,'s'*26,'t'*26
        config={'version':1,'connectors':[{'id':'bot','platform':'mattermost'}],'bindings':[
            {'id':'paired','connector':'bot','sender':user,'chat':chat,'scope':team,'thread':'',
                'identity':'principal','capabilities':['create','read'],'generation':'a'*64}]}
        current=lambda:GatewayPolicy(config)
        state={'status':201,'posts':0,'root':'','team':team,'wrong':False,'disconnect':False,'partial':False,'revoke':False}
        async def api(request):
            assert request.headers['Authorization']=='Bearer '+'x'*26
            if request.path.endswith('/posts/'+thread):return web.json_response({'id':thread,'channel_id':chat,'root_id':''})
            if request.path.endswith('/channels/'+chat):
                return web.json_response({'id':chat,'team_id':state['team'],'type':'O'})
            assert request.path=='/api/v4/posts' and request.method=='POST'
            state['posts']+=1;body=await request.json()
            assert body['channel_id']==chat and body.get('root_id','')==state['root']
            assert body['props']=={'disable_mentions':True}
            if state['disconnect']:request.transport.close();return web.Response()
            if state['status']==302:return web.Response(status=302,headers={'Location':'/leak'})
            status=403 if state['partial'] and state['posts']==2 else state['status']
            if status!=201:return web.json_response({'message':'root_id missing invalid post'},status=status,headers={'Retry-After':state.get('retry_after','19')})
            if state['revoke']:config['bindings'][0]['generation']='d'*64
            return web.json_response({'id':str(state['posts']).zfill(26),'channel_id':'w'*26 if state['wrong'] else chat,
                'root_id':body.get('root_id','')},status=201)
        app=web.Application();app.router.add_route('*','/api/v4/{tail:.*}',api)
        runner=web.AppRunner(app);await runner.setup();site=web.TCPSite(runner,'127.0.0.1',0);await site.start()
        port=site._server.sockets[0].getsockname()[1]
        adapter=build_adapter('mattermost',{'token':'x'*26,'server_url':'https://owner.invalid'})
        adapter._base_url=f'http://127.0.0.1:{port}';adapter._haos_native=SimpleNamespace(policy=current,connector='bot')
        async def run(name, expected, *, content=None, forged=None):
            path=directory/(name+'.db');store=MissionStore(path);engine=GatewayEngine(store)
            binding=config['bindings'][0]
            envelope={'platform':'mattermost','sender':user,'chat':chat,'scope':team,'thread':binding['thread'],
                'message_id':str(len(cases)+100).zfill(26),'is_bot':False,'text':'native outbox fixture'}
            await engine.receive(current(),'bot',envelope,None)
            obligation=engine.next_delivery(current())
            metadata=delivery_metadata(obligation,'mattermost')
            if forged:metadata.update(forged)
            try:
                result=delivery_result(await adapter.send(chat,content or obligation['content'],obligation['reply_to'],metadata))
            except Exception:result={'status':'uncertain'}
            # Revocation deliberately prevents acknowledgement under the old grant.
            if state['revoke']:config['bindings'][0]['generation']='a'*64
            engine.acknowledge(current(),obligation['id'],{'attempt':obligation['attempt'],**result})
            store.close();store=MissionStore(path)
            row=store.db.execute('SELECT * FROM gateway_outbox WHERE id=?',(obligation['id'],)).fetchone()
            assert row['state']==expected,(name,dict(row),result)
            store.close();cases.append(name);return result
        try:
            async with ClientSession(trust_env=False) as session:
                adapter._session=session
                await run('native_exact_flat_receipt','delivered')
                config['bindings'][0]['thread']=thread;state['root']=thread;state['posts']=0
                await run('native_exact_thread_receipt','delivered')
                for status,expected in [(400,'failed'),(401,'failed'),(403,'failed'),(404,'failed'),(413,'failed'),(429,'pending'),(500,'uncertain'),(302,'uncertain')]:
                    state['status']=status;state['posts']=0
                    result=await run('native_single_post_'+str(status),expected)
                    assert state['posts']==1
                    if status==429:assert result['retry_after']==19
                state['status']=429;state['posts']=0;state['retry_after']=formatdate(time.time()+3600,usegmt=True)
                result=await run('native_http_date_retry_after_retains_reopened_pending_outbox','pending')
                assert state['posts']==1 and 3598<=result['retry_after']<=3600
                state['retry_after']='19';state['status']=201;state['wrong']=True
                await run('wrong_route_201_stays_uncertain','uncertain');state['wrong']=False
                state['disconnect']=True;state['posts']=0
                await run('lost_http_receipt_stays_uncertain','uncertain');assert state['posts']==1;state['disconnect']=False
                state['partial']=True;state['posts']=0
                await run('partial_chunk_then_refusal_stays_uncertain','uncertain',content='p'*4100)
                assert state['posts']==2;state['partial']=False
                state['revoke']=True;state['posts']=0
                await run('revoke_between_chunks_never_posts_again','uncertain',content='r'*4100)
                assert state['posts']==1;state['revoke']=False
                state['team']='w'*26;state['posts']=0
                await run('actual_team_mismatch_no_post','failed');assert state['posts']==0;state['team']=team
                await run('forged_binding_generation_no_post','failed',forged={'haos_binding':{'binding_id':'paired','binding_digest':'0'*64}})
                assert state['posts']==0
                # A real refused TCP connection during destination verification is known not dispatched.
                adapter._base_url='http://127.0.0.1:1'
                await run('real_connector_refusal_before_post_can_retry','pending')
        finally:await runner.cleanup()
    with tempfile.TemporaryDirectory() as value:asyncio.run(exercise(Path(value)))
    output=json.dumps({'passed':len(cases),'cases':cases,'external_connections':False},indent=2)+'\n'
    if len(sys.argv)>2:Path(sys.argv[2]).write_text(output)
    else:print(output,end='')


if __name__=='__main__':main()
