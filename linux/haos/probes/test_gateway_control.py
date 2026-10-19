"""Real Unix ingress; no external provider or gateway success is inferred."""

import asyncio
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from haos.controller import Controller
from haos.gateway import GatewayPolicy
from haos.store import MissionStore


def test_real_kernel_peer_gateway_socket_and_persistent_admission(tmp_path):
    async def exercise():
        store = MissionStore(tmp_path / "missions.db")
        controller = Controller(store, "ws://127.0.0.1:9119", set())
        controller.gateway_uids = {os.geteuid()}
        controller.gateway_policy = lambda: GatewayPolicy({"version": 1,
            "connectors": [{"id": "test-telegram", "platform": "telegram"}],
            "bindings": [{"id": "paired", "connector": "test-telegram", "sender": "42", "chat": "42",
                          "scope": "", "thread": "", "identity": "principal-1", "capabilities": ["create", "read"]}]})
        async def gateway(reader, writer):
            await controller.client(reader, writer, gateway=True)
        path = tmp_path / "gateway.sock"
        server = await asyncio.start_unix_server(gateway, path=path)
        async def request(method, params):
            reader, writer = await asyncio.open_unix_connection(path)
            writer.write(json.dumps({"method": method, "params": params}).encode() + b"\n")
            await writer.drain()
            result = json.loads(await reader.readline())
            writer.close()
            await writer.wait_closed()
            return result
        try:
            params = {"connector": "test-telegram", "envelope": {"platform": "telegram", "sender": "42", "chat": "42",
                "scope": "", "thread": "", "is_bot": False, "message_id": "11", "text": "Admit offline test only"}}
            first = await request("gateway.receive", params)
            assert first["ok"] is True
            assert await request("gateway.receive", params) == first
            params["envelope"]["sender"] = "unpaired"
            assert (await request("gateway.receive", params))["ok"] is False
            assert (await request("owner.reconcile", {}))["ok"] is False
            controller.gateway_uids = set()
            assert (await request("gateway.next", {}))["ok"] is False
            assert len(store.list()) == 1 and store.list()[0]["actor"] == "gateway:principal-1"
            mid = first["result"]["mission_id"]
        finally:
            server.close()
            await server.wait_closed()
            store.close()
        reopened = MissionStore(tmp_path / "missions.db")
        assert reopened.get(mid)["state"] == "queued"
        assert reopened.db.execute("SELECT COUNT(*) FROM gateway_inbox").fetchone()[0] == 1
        reopened.close()
    asyncio.run(exercise())
