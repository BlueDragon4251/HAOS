"""Actual AF_UNIX/SO_PEERCRED admission. Renderer gate is separate, no model proof."""
import asyncio
import json
import os
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from haos.controller import Controller
from haos.store import MissionStore


def test_real_gui_peer_denial_scope_and_durable_ack(tmp_path):
    async def exercise():
        store = MissionStore(tmp_path / "missions.db")
        controller = Controller(store, "ws://127.0.0.1:9119", {os.geteuid()})
        controller.agent_uid = os.geteuid()
        async def gui(reader, writer):
            await controller.client(reader, writer, gui=True)
        path = tmp_path / "gui.sock"
        server = await asyncio.start_unix_server(gui, path=path)
        async def request(method, params):
            reader, writer = await asyncio.open_unix_connection(path)
            writer.write(json.dumps({"method": method, "params": params}).encode() + b"\n")
            await writer.drain()
            reply = json.loads(await reader.readline())
            writer.close()
            await writer.wait_closed()
            return reply
        try:
            key = str(uuid.uuid4())
            params = {"session": "runtime", "id": key, "action": {"operation": "state"}}
            assert not (await request("missions.create", {"goal": "forged", "idempotency_key": "gui"}))["ok"]
            assert not (await request("gui.attach", {"epoch": key}))["ok"]
            assert not (await request("owner.unlock", {}))["ok"]
            assert not (await request("gui.submit", params))["ok"]
            row = store.create("uid:fixture", "fixture", "offline GUI protocol only")
            store.claim()
            store.session(row["id"], "runtime", "stored")
            store.dispatching(row["id"])
            controller.current = row["id"]
            await controller.dispatch("uid:fixture", {"method": "gui.attach", "params": {"epoch": key}})
            controller.agent_uid = os.geteuid() + 1
            assert not (await request("gui.submit", params))["ok"]
            controller.agent_uid = os.geteuid()
            assert (await request("gui.submit", params))["ok"]
            dispatched = await controller.dispatch("uid:fixture", {"method": "gui.poll", "params": {"epoch": key}})
            assert dispatched["request"]["mission"] == row["id"]
            assert dispatched["request"]["action"] == {"operation": "state"}
            assert not (await request("gui.ack", {"epoch": key, "id": key, "ok": True, "result": {"windows": []}}))["ok"]
            await controller.dispatch("uid:fixture", {"method": "gui.ack", "params": {"epoch": key, "id": key, "ok": True, "result": {"windows": []}}})
            receipt = await request("gui.result", {"session": "runtime", "id": key})
            assert receipt["result"]["state"] == "succeeded"
            assert receipt["result"]["result"] == {"windows": []}
            assert (await request("gui.submit", params))["result"]["state"] == "succeeded"
            store.request_cancel(row["id"], "uid:fixture")
            assert not (await request("gui.submit", params))["ok"]
            assert store.db.execute("SELECT COUNT(*) FROM gui_actions").fetchone()[0] == 1
        finally:
            server.close()
            await server.wait_closed()
            store.close()
    asyncio.run(exercise())
