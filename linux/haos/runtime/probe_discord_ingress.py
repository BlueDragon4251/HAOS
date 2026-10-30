#!/usr/bin/env python3
"""Actual Discord SDK messages through native admission and HAOS durable routing."""
import asyncio
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import sys
import tempfile


def main():
    root=Path(sys.argv[1]).resolve();sys.path.insert(0,str(root))
    from haos.gateway_runtime import build_adapter,adapter_envelope
    from haos.gateway import GatewayPolicy
    from haos.gateway_relay import RelayInbox
    from haos.redaction import Redactor
    import discord
    bot={'id':'123456','username':'fixture_bot','discriminator':'0','avatar':None,'bot':True}
    user={'id':'42','username':'fixture_user','discriminator':'0','avatar':None,'bot':False}
    config={'version':1,'connectors':[{'id':'bot','platform':'discord'}],'bindings':[
        {'id':'paired','connector':'bot','sender':'42','chat':'123','scope':'999','thread':'',
         'identity':'principal','capabilities':['create','read']}]}
    cases=[]
    async def run(directory):
        old=os.environ.get('HERMES_HOME');old_open=os.environ.get('DISCORD_ALLOW_ALL_USERS');os.environ['HERMES_HOME']=str(Path(directory)/'hermes')
        client=discord.Client(intents=discord.Intents.none())
        await client._async_setup_hook()
        client._connection.user=discord.ClientUser(state=client._connection,data=bot)
        adapter=build_adapter('discord',{'token':'fixture-discord-private-token','extra':{'auto_thread':False,'history_backfill':False}})
        adapter._client=client;adapter._ready_event.set()
        inbox=RelayInbox(Path(directory)/'relay.db',Redactor())
        def authorize(envelope):
            try: GatewayPolicy(config).authorize('bot',envelope);return True
            except PermissionError:return False
        # Private receiving-adapter callback; ignored on the predecessor, where
        # native empty allowlists reject even the exact HAOS-owned route.
        adapter._haos_source_authorizer=authorize
        adapter.set_durable_message_handler(lambda event: bool(inbox.admit(GatewayPolicy(config),'bot',adapter_envelope(event,'discord'))))
        def message(identity,sender='42',guild='999',channel='123',thread=False,media=False):
            data={'id':guild,'name':'Fixture guild','owner_id':'42','roles':[], 'members':[],
                'channels':[{'id':channel,'type':0,'name':'fixture','position':0,'permission_overwrites':[]}],
                'emojis':[],'features':[],'unavailable':False}
            actual_guild=discord.Guild(data=data,state=client._connection)
            actual_channel=actual_guild.get_channel(int(channel))
            if thread:
                actual_channel=discord.Thread(guild=actual_guild,state=client._connection,data={
                    'id':channel,'type':11,'parent_id':'123','owner_id':'42','name':'Fixture thread',
                    'message_count':1,'member_count':1,'thread_metadata':{'archived':False,'auto_archive_duration':60,
                        'archive_timestamp':'2026-10-24T00:00:00+00:00','locked':False}})
            author={**user,'id':sender}
            payload={'id':identity,'type':0,'channel_id':channel,'guild_id':guild,'content':'<@123456> fixture request',
                'author':author,'mentions':[bot],'mention_roles':[],'attachments':[],'embeds':[],
                'timestamp':'2026-10-24T00:00:00+00:00','edited_timestamp':None,'flags':0,'pinned':False,'tts':False}
            if media:
                payload['attachments']=[{'id':'77','filename':'fixture.jpg','size':1,'content_type':'image/jpeg',
                    'url':'http://127.0.0.1:1/fixture.jpg','proxy_url':'http://127.0.0.1:1/fixture.jpg'}]
            return discord.Message(state=client._connection,channel=actual_channel,data=payload)
        try:
            assert await adapter._dispatch_discord_message(message('1001')) is True
            assert inbox.db.execute('SELECT COUNT(*) FROM inbox').fetchone()[0]==1
            assert json.loads(inbox.db.execute('SELECT envelope FROM inbox').fetchone()[0])['scope']=='999'
            cases.append('exact owner sender guild channel')
            os.environ['DISCORD_ALLOW_ALL_USERS']='true'
            for args in [('1002','43','999','123'),('1003','42','998','123'),('1004','42','999','124')]:
                await adapter._dispatch_discord_message(message(*args))
            assert inbox.db.execute('SELECT COUNT(*) FROM inbox').fetchone()[0]==1
            cases.append('unknown sender guild channel refused')
            inbox.db.execute("CREATE TRIGGER fixture_failure BEFORE INSERT ON inbox BEGIN SELECT RAISE(ABORT, 'fixture storage failure'); END")
            try: await adapter._dispatch_discord_message(message('1005'))
            except sqlite3.DatabaseError:pass
            else:raise AssertionError('native Discord admission hid durable storage failure')
            inbox.db.execute('DROP TRIGGER fixture_failure')
            assert await adapter._dispatch_discord_message(message('1005')) is True
            assert inbox.db.execute('SELECT COUNT(*) FROM inbox').fetchone()[0]==2,'native precommit dedup lost retry'
            cases.append('failed admission can retry same actual SDK message')
            await adapter._dispatch_discord_message(message('1005'))
            assert inbox.db.execute('SELECT COUNT(*) FROM inbox').fetchone()[0]==2
            cases.append('committed duplicate remains idempotent')
            assert await adapter._dispatch_discord_message(message('1010',media=True)) is False
            assert inbox.db.execute('SELECT COUNT(*) FROM inbox').fetchone()[0]==2
            cases.append('unsupported media refused before native download')
            # Native environment/pairing/role helpers are never a receiving grant.
            from haos import gateway_discord
            assert gateway_discord.allowed(adapter,'42',guild=None,is_dm=True) is False
            config['bindings'].append({'id':'thread','connector':'bot','sender':'42','chat':'125','scope':'999','thread':'125',
                'identity':'principal','capabilities':['create','read']})
            assert await adapter._dispatch_discord_message(message('1007',channel='125',thread=True)) is True
            row=inbox.db.execute('SELECT envelope FROM inbox ORDER BY created_at DESC LIMIT 1').fetchone()
            assert json.loads(row[0])['chat']=='125' and json.loads(row[0])['thread']=='125'
            assert await adapter._dispatch_discord_message(message('1008',channel='126',thread=True)) is False
            assert inbox.db.execute('SELECT COUNT(*) FROM inbox').fetchone()[0]==3
            cases.append('actual SDK thread exact route admitted and other thread refused')
            config['bindings']=[]
            assert await adapter._dispatch_discord_message(message('1006')) is False
            assert inbox.db.execute('SELECT COUNT(*) FROM inbox').fetchone()[0]==3
            cases.append('revocation and out-of-context native auth refused')
        finally:
            inbox.close();await client.close()
            if old is None:os.environ.pop('HERMES_HOME',None)
            else:os.environ['HERMES_HOME']=old
            if old_open is None:os.environ.pop('DISCORD_ALLOW_ALL_USERS',None)
            else:os.environ['DISCORD_ALLOW_ALL_USERS']=old_open
    with tempfile.TemporaryDirectory() as directory:asyncio.run(run(directory))
    receipt={'actual_sdk_native_discord_cases':cases,'external_discord_connected':False,'websocket_ack_durability_tested':False,
        'source_files':[{'path':p.name,'sha256':hashlib.sha256(p.read_bytes()).hexdigest()} for p in
            (Path(__file__),root/'haos/gateway_discord.py',root/'haos/gateway_ingress.py',root/'haos/gateway_runtime.py')]}
    Path(sys.argv[2]).write_text(json.dumps(receipt,indent=2)+'\n');print(json.dumps(receipt))


if __name__=='__main__':main()
