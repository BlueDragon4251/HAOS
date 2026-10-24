#!/usr/bin/env python3
"""Actual local WebSocket, Discord decoder/heartbeat, and durable HAOS admission."""
import asyncio
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import sys
import tempfile
import threading
from types import SimpleNamespace


def main():
    root = Path(sys.argv[1]).resolve(); sys.path.insert(0, str(root))
    import aiohttp
    from aiohttp import web
    import discord
    from discord.gateway import DiscordWebSocket, KeepAliveHandler
    from haos import gateway_discord
    from haos.gateway import GatewayPolicy
    from haos.gateway_raw import NativeInbox
    from haos.gateway_relay import RelayInbox
    from haos.gateway_runtime import build_adapter, adapter_envelope
    from haos.redaction import Redactor
    cases = []

    async def run(directory):
        os.environ['HERMES_HOME'] = str(directory / 'hermes')
        config = {'version':1, 'connectors':[{'id':'bot','platform':'discord'}], 'bindings':[
            {'id':'paired','connector':'bot','sender':'42','chat':'123','scope':'999','thread':'',
             'identity':'principal','capabilities':['create','read']}]}
        policy = lambda: GatewayPolicy(config)
        native = NativeInbox(directory / 'native.db', Redactor())
        relay = RelayInbox(directory / 'relay.db', Redactor())
        adapter = build_adapter('discord', {'token':'fixture-discord-private-token',
            'extra':{'auto_thread':False,'history_backfill':False}})
        adapter._haos_native = SimpleNamespace(inbox=native,connector='bot',policy=policy)
        captured = []
        def capture(client, payload):
            envelope = gateway_discord.capture_envelope(adapter, client, payload, policy(), 'bot')
            if envelope is None: return False
            key = native.admit(policy(), 'bot', envelope, payload)
            with sqlite3.connect(directory / 'native.db') as independent:
                assert independent.execute('SELECT state FROM native_inbox WHERE id=?',(key,)).fetchone()[0] == 'pending'
            assert client.ws.sequence == 40, 'SDK sequence advanced before durable capture'
            captured.append(key)
            return True
        adapter._haos_native_capture = capture
        client = discord.Client(intents=discord.Intents.none())
        await client._async_setup_hook()
        bot = {'id':'123456','username':'fixture_bot','discriminator':'0','avatar':None,'bot':True}
        client._connection.user = discord.ClientUser(state=client._connection,data=bot)
        guild = discord.Guild(state=client._connection,data={'id':'999','name':'Fixture','owner_id':'42',
            'roles':[],'members':[],'channels':[{'id':'123','type':0,'name':'fixture','position':0,
            'permission_overwrites':[]}],'emojis':[],'features':[],'unavailable':False})
        client._connection._add_guild(guild)
        adapter._client = client  # Actual private-instance setter installs the pre-sequence seam.
        adapter._ready_event.set()
        assert client._enable_debug_events and client._haos_capture_installed
        def authorize(envelope):
            try: policy().authorize('bot',envelope); return True
            except PermissionError: return False
        adapter._haos_source_authorizer = authorize
        adapter.set_durable_message_handler(lambda event: bool(relay.admit(policy(),'bot',adapter_envelope(event,'discord'))))
        payload = {'id':'1001','type':0,'channel_id':'123','guild_id':'999','content':'<@123456> fixture request',
            'author':{'id':'42','username':'fixture_user','discriminator':'0','avatar':None,'bot':False},
            'mentions':[bot],'mention_roles':[],'attachments':[],'embeds':[],
            'timestamp':'2026-10-24T00:00:00+00:00','edited_timestamp':None,'flags':0,'pinned':False,'tts':False}
        frame = {'op':0,'s':41,'t':'MESSAGE_CREATE','d':payload}
        async def handler(request):
            socket = web.WebSocketResponse(); await socket.prepare(request)
            await socket.send_json(frame)
            async for _ in socket: pass
            return socket
        app = web.Application(); app.router.add_get('/gateway',handler)
        runner = web.AppRunner(app); await runner.setup()
        site = web.TCPSite(runner,'127.0.0.1',0); await site.start()
        port = site._server.sockets[0].getsockname()[1]
        try:
            async with aiohttp.ClientSession() as session:
                async def websocket():
                    socket = await session.ws_connect(f'http://127.0.0.1:{port}/gateway')
                    ws = DiscordWebSocket(socket,loop=asyncio.get_running_loop())
                    ws._connection = client._connection; ws._discord_parsers = client._connection.parsers
                    ws._dispatch = client.dispatch; ws.log_receive = ws.debug_log_receive
                    ws.sequence = 40; ws._max_heartbeat_timeout = 60
                    ws.shard_id = None
                    client.ws = ws
                    return ws
                ws = await websocket()
                heartbeat = KeepAliveHandler(ws=ws,interval=60,shard_id=None)
                assert heartbeat.get_payload()['d'] == 40
                native.db.execute("CREATE TRIGGER fixture_failure BEFORE INSERT ON native_inbox BEGIN SELECT RAISE(ABORT, 'fixture disk failure'); END")
                try: await ws.poll_event()
                except OSError: pass
                else: raise AssertionError('SDK acknowledged failed durable capture')
                assert ws.sequence == 40 and heartbeat.get_payload()['d'] == 40
                assert native.db.execute('SELECT COUNT(*) FROM native_inbox').fetchone()[0] == 0
                await ws.close(); await asyncio.sleep(0)
                native.db.execute('DROP TRIGGER fixture_failure')
                cases.append('actual WebSocket storage failure preserves SDK resume and heartbeat sequence')
                ws = await websocket()
                heartbeats = []
                def observe_uncommitted():
                    # The SDK heartbeat reads sequence from a separate thread.
                    # Exercise that same concurrency while SQLite is inserting.
                    worker = threading.Thread(target=lambda: heartbeats.append(
                        KeepAliveHandler(ws=ws,interval=60).get_payload()['d']))
                    worker.start(); worker.join(timeout=5)
                    assert not worker.is_alive()
                    return 1
                native.db.create_function('fixture_observe',0,observe_uncommitted)
                native.db.execute('CREATE TRIGGER fixture_observer BEFORE INSERT ON native_inbox BEGIN SELECT fixture_observe(); END')
                await ws.poll_event()
                assert heartbeats == [40], 'heartbeat observed uncommitted native input'
                native.db.execute('DROP TRIGGER fixture_observer')
                assert ws.sequence == 41 and KeepAliveHandler(ws=ws,interval=60).get_payload()['d'] == 41
                assert len(captured) == 1
                cases.append('concurrent heartbeat stays old during insert; independent reader sees commit before sequence advances')
                await ws.close()
            # Simulate daemon death between raw commit and native asynchronous dispatch.
            assert native.claim(captured[0],policy()) is not None
            native.close(); native = NativeInbox(directory / 'native.db',Redactor())
            adapter._haos_native.inbox = native
            assert await gateway_discord.dispatch_stored(adapter,adapter._haos_native_dispatch,captured[0]) is True
            assert relay.db.execute('SELECT COUNT(*) FROM inbox').fetchone()[0] == 1
            assert native.db.execute('SELECT state FROM native_inbox').fetchone()[0] == 'committed'
            assert await gateway_discord.dispatch_stored(adapter,adapter._haos_native_dispatch,captured[0]) is False
            assert relay.db.execute('SELECT COUNT(*) FROM inbox').fetchone()[0] == 1
            cases.append('reopened raw journal decodes actual SDK message exactly once into HAOS relay')
            retry_payload = {**payload,'id':'1003'}
            retry_key = native.admit(policy(),'bot',gateway_discord.capture_envelope(adapter,client,retry_payload,policy(),'bot'),retry_payload)
            native.db.execute("CREATE TRIGGER fixture_completion_failure BEFORE UPDATE ON native_inbox WHEN NEW.state='committed' BEGIN SELECT RAISE(ABORT, 'fixture completion failure'); END")
            try: await gateway_discord.dispatch_stored(adapter,adapter._haos_native_dispatch,retry_key)
            except sqlite3.DatabaseError: pass
            else: raise AssertionError('fixture did not interrupt raw completion after relay commit')
            assert relay.db.execute('SELECT COUNT(*) FROM inbox').fetchone()[0] == 2
            native.db.execute('DROP TRIGGER fixture_completion_failure')
            native.close(); native = NativeInbox(directory / 'native.db',Redactor())
            adapter._haos_native.inbox = native; adapter._dedup.clear()
            # Advance only the persisted retry clock, without bypassing policy,
            # native decoding or either ledger's duplicate checks.
            native.db.execute('UPDATE native_inbox SET next_attempt=0 WHERE id=?',(retry_key,))
            assert await gateway_discord.dispatch_stored(adapter,adapter._haos_native_dispatch,retry_key) is True
            assert relay.db.execute('SELECT COUNT(*) FROM inbox').fetchone()[0] == 2
            cases.append('crash after relay commit before raw completion replays without duplicate relay admission')
            next_payload = {**payload,'id':'1002'}
            key = native.admit(policy(),'bot',gateway_discord.capture_envelope(adapter,client,next_payload,policy(),'bot'),next_payload)
            config['bindings'] = []
            assert await gateway_discord.dispatch_stored(adapter,adapter._haos_native_dispatch,key) is False
            assert native.db.execute('SELECT state FROM native_inbox WHERE id=?',(key,)).fetchone()[0] == 'revoked'
            assert relay.db.execute('SELECT COUNT(*) FROM inbox').fetchone()[0] == 2
            cases.append('revocation prevents pending raw input from entering relay')
        finally:
            await client.close(); await runner.cleanup(); native.close(); relay.close()

    with tempfile.TemporaryDirectory() as temporary:
        asyncio.run(run(Path(temporary)))
    receipt = {'actual_sdk_local_websocket_cases':cases,'external_discord_connected':False,
        'long_outage_history_recovery_tested':False,'source_files':[
            {'path':path.name,'sha256':hashlib.sha256(path.read_bytes()).hexdigest()}
            for path in (Path(__file__),root/'haos/gateway_raw.py',root/'haos/gateway_discord.py',
                         root/'haos/gateway_ingress.py',root/'haos/gateway_runtime.py')]}
    Path(sys.argv[2]).write_text(json.dumps(receipt,indent=2)+'\n'); print(json.dumps(receipt))


if __name__ == '__main__': main()
