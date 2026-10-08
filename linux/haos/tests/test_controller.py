import asyncio
import json
import socket
import struct

import pytest

from haos.controller import Controller, peer_actor
from haos.hermes import HermesConnection, outcome, websocket_url
from haos.store import MissionStore


def test_peer_identity_comes_from_kernel_not_request_json():
    class Peer:
        def getsockopt(self, level, option, size):
            assert (level, option, size) == (socket.SOL_SOCKET, socket.SO_PEERCRED, 12)
            return struct.pack("3i", 99, 1024, 1024)
    assert peer_actor(Peer(), {1024}) == "uid:1024"
    with pytest.raises(PermissionError):
        peer_actor(Peer(), {1000})


def test_provider_failure_and_missing_terminal_receipts_never_become_success():
    assert outcome({"status": "complete", "text": "Built"}, False)[0] == "completed"
    for payload in ({"text": "Looks good"}, {"status": "complete", "text": ""},
                    {"status": "complete", "text": "Partial", "partial": True},
                    {"status": "error", "text": "No API key"}, {"status": "interrupted"}):
        assert outcome(payload, False)[0] != "completed"
    assert outcome({"status": "complete", "text": "Built"}, True)[0] == "blocked"
    for url in ("https://127.0.0.1:9119", "http://localhost:9119", "http://remote:9119", "http://u@127.0.0.1:9119", "http://127.0.0.1:9119/other"):
        with pytest.raises(ValueError):
            websocket_url(url, "secret")


def test_wire_adapter_matches_responses_and_records_real_frames():
    async def exercise():
        class Wire:
            def __init__(self):
                self.incoming = asyncio.Queue()
                self.sent = []
            def __aiter__(self):
                return self
            async def __anext__(self):
                frame = await self.incoming.get()
                if frame is None:
                    raise StopAsyncIteration
                return frame
            async def send(self, text):
                frame = json.loads(text)
                self.sent.append(frame)
                if frame.get("method") == "session.create":
                    await self.incoming.put(json.dumps({"jsonrpc": "2.0", "id": frame["id"], "result": {"session_id": "s", "stored_session_id": "p"}}))
            async def close(self):
                await self.incoming.put(None)
        wire, events = Wire(), []
        async def event(frame, epoch):
            events.append((frame, epoch))
        async def question(frame):
            raise AssertionError("no question expected")
        client = HermesConnection(wire, event, question)
        result = await client.request("session.create", {"source": "herald_os"})
        assert result["stored_session_id"] == "p"
        await wire.incoming.put(json.dumps({"method": "event", "params": {"type": "gateway.ready", "payload": {"replay_epoch": "e"}}}))
        await wire.incoming.put(json.dumps({"method": "event", "params": {"type": "tool.complete", "session_id": "s", "seq": 1, "payload": {"result": "real wire payload"}}}))
        await client.close()
        assert events[-1][0]["payload"]["result"] == "real wire payload"
        assert events[-1][1] == "e"
    asyncio.run(exercise())


def test_local_api_has_no_owner_policy_or_privileged_execution_endpoint(tmp_path):
    async def exercise():
        store = MissionStore(tmp_path / "missions.db")
        controller = Controller(store, "ws://127.0.0.1:9119/api/ws", {1000})
        row = await controller.dispatch("uid:1000", {"method": "missions.create", "params": {"goal": "Build", "idempotency_key": "a", "actor": "owner:0"}})
        assert row["actor"] == "uid:1000"
        for method in ("policy.write", "volume.unlock", "owner.reconcile", "exec"):
            with pytest.raises(ValueError, match="unknown"):
                await controller.dispatch("uid:1000", {"method": method, "params": {}})
        store.close()
    asyncio.run(exercise())
