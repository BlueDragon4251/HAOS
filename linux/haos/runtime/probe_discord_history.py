#!/usr/bin/env python3
"""Actual SDK REST history into durable ingress across outage and commit failures."""
import asyncio
import copy
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
    import discord
    from discord.http import Route
    from haos.gateway import GatewayPolicy
    from haos.gateway_raw import NativeInbox
    from haos.gateway_relay import RelayInbox
    from haos.gateway_runtime import build_adapter,adapter_envelope
    from haos.gateway_discord_history import boundary,recover_one,maintain,DISCORD_EPOCH
    from haos.gateway_raw_recovery import unresolved
    from haos import gateway_discord
    from haos.redaction import Redactor
    cases=[]
    async def exercise(directory):
        since=time.time_ns()//1_000_000-60000
        binding={'id':'paired','connector':'bot','sender':'42','chat':'123','scope':'999','thread':'',
            'identity':'principal','capabilities':['create','read'],'generation':'a'*64,'since':since}
        floor=boundary(binding)
        config={'version':1,'connectors':[{'id':'bot','platform':'discord'}],'bindings':[binding]}
        current=lambda:GatewayPolicy(config)
        bot={'id':'123456','username':'fixture_bot','discriminator':'0','avatar':None,'bot':True}
        def payload(identity,sender='42'):
            return {'id':str(identity),'type':0,'channel_id':'123','content':'<@123456> fixture recovery',
                'author':{'id':sender,'username':'fixture_user','discriminator':'0','avatar':None,'bot':False},
                'mentions':[bot],'mention_roles':[],'attachments':[],'embeds':[],
                'timestamp':'2026-10-24T00:00:00+00:00','edited_timestamp':None,'flags':0,'pinned':False,'tts':False}
        state={'messages':[payload(floor-1),payload(floor+10),payload(floor+20,'43'),payload(floor+30)],'requests':[],'revoke':False}
        def response(value,**kwargs):return web.Response(body=json.dumps(value).encode(),content_type='application/json',**kwargs)
        async def me(request):return response(bot)
        async def history(request):
            after=int(request.query['after']);state['requests'].append(after)
            assert request.query['limit']=='100'
            assert request.headers['Authorization']=='Bot fixture-discord-private-token'
            if state.get('deny'):
                state['stop'].set()
                return response({'message':'Missing Permissions','code':50013},status=403)
            if state['revoke']:config['bindings']=[]
            return response(sorted([p for p in state['messages'] if int(p['id'])>after],key=lambda p:int(p['id']))[:100][::-1])
        app=web.Application();app.router.add_get('/api/users/@me',me);app.router.add_get('/api/channels/123/messages',history)
        runner=web.AppRunner(app);await runner.setup();site=web.TCPSite(runner,'127.0.0.1',0);await site.start()
        port=site._server.sockets[0].getsockname()[1];old_base=Route.BASE;Route.BASE=f'http://127.0.0.1:{port}/api'
        os.environ['HERMES_HOME']=str(directory/'hermes')
        adapter=build_adapter('discord',{'token':'fixture-discord-private-token','extra':{'auto_thread':False,'history_backfill':False}})
        client=discord.Client(intents=discord.Intents.none());await client._async_setup_hook();adapter._client=client
        inbox=NativeInbox(directory/'native.db',Redactor());relay=RelayInbox(directory/'relay.db',Redactor())
        adapter._haos_native=SimpleNamespace(inbox=inbox,connector='bot',policy=current)
        def authorize(envelope):
            try:current().authorize('bot',envelope);return True
            except PermissionError:return False
        adapter._haos_source_authorizer=authorize
        adapter.set_durable_message_handler(lambda event:bool(relay.admit(current(),'bot',adapter_envelope(event,'discord'))))
        try:
            me_data=await client.http.static_login('fixture-discord-private-token')
            client._connection.user=discord.ClientUser(state=client._connection,data=me_data)
            guild=discord.Guild(state=client._connection,data={'id':'999','name':'Fixture','owner_id':'42','roles':[],
                'members':[],'channels':[{'id':'123','type':0,'name':'fixture','position':0,'permission_overwrites':[]}],
                'emojis':[],'features':[],'unavailable':False})
            client._connection._add_guild(guild);adapter._ready_event.set()
            inbox.db.execute("CREATE TRIGGER fixture_storage_failure BEFORE INSERT ON native_inbox BEGIN SELECT RAISE(ABORT,'fixture storage failure'); END")
            try:await recover_one(adapter,current,'bot')
            except sqlite3.DatabaseError:pass
            else:raise AssertionError('history advanced after failed raw commit')
            assert inbox.db.execute('SELECT COUNT(*) FROM native_inbox').fetchone()[0]==0
            assert inbox.db.execute('SELECT COUNT(*) FROM discord_history').fetchone()[0]==0
            inbox.db.execute('DROP TRIGGER fixture_storage_failure')
            cases.append('failed durable admission leaves actual SDK history cursor unchanged')
            assert await recover_one(adapter,current,'bot')==2
            assert state['requests']==[floor,floor]
            assert inbox.db.execute('SELECT cursor FROM discord_history').fetchone()[0]==str(floor+30)
            assert inbox.db.execute('SELECT COUNT(*) FROM native_inbox').fetchone()[0]==2
            cases.append('only approved post-grant messages admitted; older and unknown-sender messages excluded')
            inbox.close();inbox=NativeInbox(directory/'native.db',Redactor());adapter._haos_native.inbox=inbox
            for row in inbox.db.execute('SELECT id FROM native_inbox ORDER BY created_at').fetchall():
                assert await gateway_discord.dispatch_stored(adapter,adapter._haos_native_dispatch,row['id']) is True
            assert relay.db.execute('SELECT COUNT(*) FROM inbox').fetchone()[0]==2
            assert await recover_one(adapter,current,'bot')==0
            cases.append('reopened durable history input reaches native SDK decoder and HAOS relay once')
            state['messages'].append(payload(floor+40))
            inbox.db.execute("CREATE TRIGGER fixture_cursor_failure BEFORE UPDATE ON discord_history BEGIN SELECT RAISE(ABORT,'fixture cursor failure'); END")
            try:await recover_one(adapter,current,'bot')
            except sqlite3.DatabaseError:pass
            else:raise AssertionError('fixture did not interrupt cursor update')
            assert inbox.db.execute('SELECT COUNT(*) FROM native_inbox').fetchone()[0]==3
            inbox.db.execute('DROP TRIGGER fixture_cursor_failure')
            inbox.close();inbox=NativeInbox(directory/'native.db',Redactor());adapter._haos_native.inbox=inbox
            assert await recover_one(adapter,current,'bot')==0
            assert inbox.db.execute('SELECT COUNT(*) FROM native_inbox').fetchone()[0]==3
            assert inbox.db.execute('SELECT cursor FROM discord_history').fetchone()[0]==str(floor+40)
            cases.append('crash after raw commit before cursor update retains idempotent recovery')
            state['messages'].append(payload(floor+50));state['revoke']=True
            try:await recover_one(adapter,current,'bot')
            except PermissionError:pass
            else:raise AssertionError('revocation during REST recovery was not enforced')
            assert inbox.db.execute('SELECT COUNT(*) FROM native_inbox').fetchone()[0]==3
            cases.append('revocation while actual HTTP request is outstanding prevents admission')
            state['revoke']=False
            config['bindings']=[{**binding,'generation':'b'*64,'since':since+10000}]
            assert await recover_one(adapter,current,'bot')==0
            assert state['requests'][-1]==boundary(config['bindings'][0])
            assert inbox.db.execute('SELECT COUNT(*) FROM native_inbox').fetchone()[0]==3
            cases.append('repaired grant starts after its new boundary and cannot revive historic input')
            config['bindings']=[{key:value for key,value in binding.items() if key!='since'}]
            before=len(state['requests'])
            assert await recover_one(adapter,current,'bot')==0 and len(state['requests'])==before
            cases.append('legacy grant without original boundary performs no automatic history fetch')
            old_since=time.time_ns()//1_000_000-3*86400000
            config['bindings']=[{**binding,'generation':'c'*64,'since':old_since}]
            age_ms=time.time_ns()//1_000_000-2*86400000
            age_id=((age_ms-DISCORD_EPOCH)<<22)+1
            state['messages']=[payload(age_id)]
            assert await recover_one(adapter,current,'bot')==1
            key=inbox.find_discord('bot',str(age_id))
            assert inbox.db.execute('SELECT created_at FROM native_inbox WHERE id=?',(key,)).fetchone()[0]==age_ms/1000
            assert await gateway_discord.dispatch_stored(adapter,adapter._haos_native_dispatch,key) is False
            assert inbox.db.execute('SELECT state FROM native_inbox WHERE id=?',(key,)).fetchone()[0]=='expired'
            assert relay.db.execute('SELECT COUNT(*) FROM inbox').fetchone()[0]==2
            cases.append('original snowflake time survives commit; expired missed input retained without execution')
            future_id=(((time.time_ns()//1_000_000+600000)-DISCORD_EPOCH)<<22)+1
            state['messages']=[payload(future_id)]
            previous_cursor=inbox.db.execute('SELECT cursor FROM discord_history WHERE binding_digest=?',
                (adapter._haos_history_binding,)).fetchone()[0]
            try:await recover_one(adapter,current,'bot')
            except ValueError:pass
            else:raise AssertionError('future history identity advanced durable cursor')
            assert inbox.db.execute('SELECT cursor FROM discord_history WHERE binding_digest=?',
                (adapter._haos_history_binding,)).fetchone()[0]==previous_cursor
            cases.append('future provider identity cannot skip the durable history cursor')
            config['bindings']=[{**binding,'generation':'d'*64,'since':since}]
            state['messages']=[payload(floor+i,'43') for i in range(1,201)]+[payload(floor+201)]
            state['requests']=[]
            assert await recover_one(adapter,current,'bot')==0
            assert await recover_one(adapter,current,'bot')==0
            assert await recover_one(adapter,current,'bot')==1
            assert state['requests']==[floor,floor+100,floor+200]
            cases.append('three actual reversed REST pages advance only across committed or definitively refused input')
            stop=asyncio.Event();state.update(deny=True,stop=stop)
            adapter._mark_connected()
            await asyncio.wait_for(maintain(adapter,stop,current,'bot'),3)
            report=unresolved(inbox)
            assert any(item['status']=='permission-denied' for item in report['history'])
            assert 'fixture-discord-private-token' not in json.dumps(report)
            cases.append('actual SDK permission refusal persists safe status visible to owner recovery')
        finally:inbox.close();relay.close();await client.close();Route.BASE=old_base;await runner.cleanup()
    with tempfile.TemporaryDirectory() as directory:asyncio.run(exercise(Path(directory)))
    receipt={'actual_sdk_http_history_recovery_cases':cases,'external_discord_connected':False,
        'deleted_remote_messages_recoverable':False,'source_files':[{'path':p.name,'sha256':hashlib.sha256(p.read_bytes()).hexdigest()}
            for p in (Path(__file__),root/'haos/gateway_discord_history.py',root/'haos/gateway.py',
                root/'haos/gateway_setup.py',root/'haos/gateway_runtime.py')]}
    Path(sys.argv[2]).write_text(json.dumps(receipt,indent=2)+'\n');print(json.dumps(receipt))


if __name__=='__main__':main()
