"""Exercise peer credentials and the controller's actual Unix transport."""

import asyncio
import json
import os
import socket
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from haos.controller import Controller, peer_actor
from haos.store import MissionStore


def test_kernel_peer_identity_and_mission_roundtrip(tmp_path):
    async def exercise():
        a, b = socket.socketpair(socket.AF_UNIX, socket.SOCK_STREAM)
        try:
            assert peer_actor(a, {os.getuid()}) == f"uid:{os.getuid()}"
        finally:
            a.close()
            b.close()
        store = MissionStore(tmp_path / "missions.db")
        controller = Controller(store, "ws://127.0.0.1:9119/api/ws", {os.getuid()})
        path = tmp_path / "control.sock"
        server = await asyncio.start_unix_server(controller.client, path=path)
        async with server:
            async def request(method, params):
                reader, writer = await asyncio.open_unix_connection(path)
                writer.write(json.dumps({"method": method, "params": params}).encode() + b"\n")
                await writer.drain()
                reply = json.loads(await reader.readline())
                writer.close()
                await writer.wait_closed()
                return reply
            created = await request("missions.create", {"goal": "Real Unix roundtrip", "idempotency_key": "probe", "actor": "owner:0"})
            assert created["ok"] and created["result"]["actor"] == f"uid:{os.getuid()}"
            repeated = await request("missions.create", {"goal": "Real Unix roundtrip", "idempotency_key": "probe"})
            assert repeated["result"]["id"] == created["result"]["id"]
            denied = await request("volume.unlock", {"id": "UUID:blocked"})
            assert not denied["ok"]
            events = await request("missions.events", {"id": created["result"]["id"]})
            assert events["result"][0]["kind"] == "mission.queued"
        server.close()
        await server.wait_closed()
        store.close()
    asyncio.run(exercise())
