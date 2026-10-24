#!/usr/bin/env python3
"""Native Discord adapter + real SDK HTTP, nonce retry and durable outbox outcomes."""
import asyncio
import hashlib
import json
import os
import socket
from pathlib import Path
import sys
import tempfile


def main():
    root=Path(sys.argv[1]).resolve();sys.path.insert(0,str(root))
    from aiohttp import web
    import discord
    from discord.http import Route
    from haos.gateway_runtime import build_adapter
    from haos.gateway import GatewayPolicy,GatewayEngine
    from haos.gateway_delivery import delivery_result
    from haos.store import MissionStore
    results=[];state={'case':'','requests':[]}
    bot={'id':'123456','username':'fixture_bot','discriminator':'0','avatar':None,'bot':True}
    def response(value, **kwargs):
        return web.Response(body=json.dumps(value).encode(),content_type='application/json',**kwargs)
    async def me(request):return response(bot)
    async def send(request):
        payload=await request.json();state['requests'].append({'channel':request.match_info['channel'],'payload':payload})
        case=state['case'];attempt=len(state['requests'])
        assert payload['enforce_nonce'] is True and payload['nonce']
        if case=='disconnect':
            request.transport.close();return web.Response()
        if case in {'nonce-retry','ambiguous-forbidden'} and attempt==1:
            return response({'message':'fixture server failure','code':0},status=500)
        if case in {'forbidden','ambiguous-forbidden'}:
            return response({'message':'fixture refusal','code':50013},status=403)
        if case=='server-fake-reply':
            return response({'message':'fixture server failure','code':10008},status=501)
        if case=='rate-limit':
            return response({'message':'fixture rate limit','retry_after':120,'global':False},status=429,headers={'Via':'fixture'})
        if case=='reply-refused' and attempt==1:
            return response({'message':'Unknown Message','code':10008},status=404)
        if case=='partial-rate-limit' and attempt==2:
            return response({'message':'fixture rate limit','retry_after':120,'global':False},status=429,headers={'Via':'fixture'})
        if case=='malformed':return response({})
        return response({'id':'0' if case=='invalid-id' else '55','type':0,'channel_id':request.match_info['channel'],
            'content':payload['content'],'author':bot,'mentions':[],'mention_roles':[],'attachments':[],'embeds':[],
            'timestamp':'2026-10-24T00:00:00+00:00','edited_timestamp':None,'flags':0,'pinned':False,'tts':False})
    async def exercise(directory):
        app=web.Application();app.router.add_get('/api/users/@me',me);app.router.add_post('/api/channels/{channel}/messages',send)
        runner=web.AppRunner(app);await runner.setup();site=web.TCPSite(runner,'127.0.0.1',0);await site.start()
        port=site._server.sockets[0].getsockname()[1]
        old_base=Route.BASE;Route.BASE=f'http://127.0.0.1:{port}/api'
        os.environ['HERMES_HOME']=str(directory/'hermes')
        try:
            for case,expected,count in [('success','delivered',1),('nonce-retry','delivered',2),
                    ('ambiguous-forbidden','uncertain',2),('server-fake-reply','uncertain',1),
                    ('rate-limit','pending',1),('forbidden','failed',1),('reply-refused','delivered',2),
                    ('malformed','uncertain',1),('invalid-id','uncertain',1),('disconnect','uncertain',1),
                    ('wrong-guild','failed',0),('forum','failed',0),('partial-rate-limit','uncertain',2),
                    ('thread-success','delivered',1),('wrong-thread','failed',0),('connect-refused','pending',0)]:
                state.update(case=case,requests=[])
                Route.BASE=f'http://127.0.0.1:{port}/api'
                adapter=build_adapter('discord',{'token':'fixture-discord-private-token','extra':{'auto_thread':False,'history_backfill':False}})
                client=discord.Client(intents=discord.Intents.none(),max_ratelimit_timeout=30)
                await client._async_setup_hook();adapter._client=client
                try:
                    me_data=await client.http.static_login('fixture-discord-private-token')
                except BaseException:
                    await client.close();raise
                client._connection.user=discord.ClientUser(state=client._connection,data=me_data)
                data={'id':'999','name':'Fixture','owner_id':'42','roles':[],'members':[],
                    'channels':[{'id':'123','type':15 if case=='forum' else 0,'name':'fixture','position':0,
                        'permission_overwrites':[]}],'emojis':[],'features':[],'unavailable':False}
                guild=discord.Guild(state=client._connection,data=data);client._connection._add_guild(guild)
                if case=='thread-success':
                    thread=discord.Thread(guild=guild,state=client._connection,data={'id':'125','type':11,
                        'parent_id':'123','owner_id':'42','name':'Fixture thread','message_count':1,'member_count':1,
                        'thread_metadata':{'archived':False,'auto_archive_duration':60,
                            'archive_timestamp':'2026-10-24T00:00:00+00:00','locked':False}})
                    guild._add_thread(thread)
                approved_chat='125' if case=='thread-success' else '123'
                approved_thread='125' if case=='thread-success' else ''
                config={'version':1,'connectors':[{'id':'bot','platform':'discord'}],'bindings':[
                    {'id':'paired','connector':'bot','sender':'42','chat':approved_chat,'scope':'999','thread':approved_thread,
                     'identity':'principal','capabilities':['create','read']}]}
                policy=GatewayPolicy(config);path=directory/(case+'.db');store=MissionStore(path);engine=GatewayEngine(store)
                try:
                    await engine.receive(policy,'bot',{'platform':'discord','sender':'42','chat':approved_chat,'scope':'999',
                        'thread':approved_thread,'message_id':'101','is_bot':False,'text':'fixture mission'},None)
                    delivery=engine.next_delivery(policy)
                    metadata={'notify':True,'haos_scope':'998' if case=='wrong-guild' else '999'}
                    if case in {'thread-success','wrong-thread'}:metadata['thread_id']='125'
                    with socket.socket() as unused:
                        if case=='connect-refused':
                            unused.bind(('127.0.0.1',0))
                            Route.BASE=f'http://127.0.0.1:{unused.getsockname()[1]}/api'
                        receipt=await adapter.send('125' if case=='thread-success' else '123',
                            'x'*4100 if case=='partial-rate-limit' else delivery['content'],reply_to='101',metadata=metadata)
                    translated=delivery_result(receipt)
                    engine.acknowledge(policy,delivery['id'],{**translated,'attempt':delivery['attempt']})
                    row=store.db.execute('SELECT state FROM gateway_outbox WHERE id=?',(delivery['id'],)).fetchone()
                    assert row['state']==expected,(case,translated,row['state'])
                    assert len(state['requests'])==count,(case,len(state['requests']))
                    if case in {'nonce-retry','ambiguous-forbidden'}:
                        assert state['requests'][0]['payload']['nonce']==state['requests'][1]['payload']['nonce']
                    if case=='reply-refused':
                        assert 'message_reference' in state['requests'][0]['payload'] and 'message_reference' not in state['requests'][1]['payload']
                    if case=='thread-success':assert state['requests'][0]['channel']=='125'
                    store.close();store=MissionStore(path)
                    assert store.db.execute('SELECT state FROM gateway_outbox WHERE id=?',(delivery['id'],)).fetchone()['state']==expected
                    results.append({'case':case,'actual_http_requests':count,'reopened_outbox_state':expected})
                finally:store.close();await client.close()
        finally:Route.BASE=old_base;await runner.cleanup()
    with tempfile.TemporaryDirectory() as directory:asyncio.run(exercise(Path(directory)))
    receipt={'actual_native_sdk_http_outbox_cases':results,'external_discord_connected':False,
        'remote_server_nonce_dedup_live_tested':False,'source_files':[
            {'path':p.name,'sha256':hashlib.sha256(p.read_bytes()).hexdigest()} for p in
            (Path(__file__),root/'haos/gateway_discord.py',root/'haos/gateway_ingress.py',root/'haos/gateway_runtime.py')]}
    Path(sys.argv[2]).write_text(json.dumps(receipt,indent=2)+'\n');print(json.dumps(receipt))


if __name__=='__main__':main()
