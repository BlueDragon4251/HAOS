"""Adapter for the pinned, unmodified Hermes session/prompt JSON-RPC contract."""

from __future__ import annotations

import asyncio
import json
from urllib.parse import urlencode, urlsplit


class RpcError(RuntimeError):
    pass


def websocket_url(base_url: str, token: str) -> str:
    u = urlsplit(base_url)
    if (u.scheme != "http" or u.hostname not in {"127.0.0.1", "::1"}
            or u.username or u.password or u.query or u.fragment or u.path not in {"", "/"}):
        raise ValueError("Hermes must use a literal loopback HTTP origin")
    if not token.strip():
        raise ValueError("Hermes authentication token is empty")
    return f"ws://{u.netloc}/api/ws?{urlencode({'token': token})}"


class HermesConnection:
    def __init__(self, socket, on_event, on_request):
        self.socket = socket
        self.on_event, self.on_request = on_event, on_request
        self.pending: dict[str, asyncio.Future] = {}
        self.counter = 0
        self.epoch = None
        self.reader = asyncio.create_task(self._read())

    async def _read(self):
        try:
            async for text in self.socket:
                for line in text.splitlines():
                    frame = json.loads(line)
                    if frame.get("method") == "event":
                        event = frame.get("params", {})
                        if event.get("type") == "gateway.ready":
                            self.epoch = (event.get("payload") or {}).get("replay_epoch")
                        await self.on_event(event, self.epoch)
                    elif "method" in frame and "id" in frame:
                        await self.on_request(frame)
                    elif str(frame.get("id")) in self.pending:
                        future = self.pending.pop(str(frame["id"]))
                        if not future.done():
                            if "error" in frame:
                                future.set_exception(RpcError(str(frame["error"].get("message", "RPC rejected"))))
                            else:
                                future.set_result(frame.get("result"))
        finally:
            for future in self.pending.values():
                if not future.done():
                    future.set_exception(ConnectionError("Hermes connection closed"))
            self.pending.clear()

    async def request(self, method: str, params: dict, timeout: float = 90):
        self.counter += 1
        rid = f"haos-{self.counter}"
        future = asyncio.get_running_loop().create_future()
        self.pending[rid] = future
        try:
            await self.socket.send(json.dumps({"jsonrpc": "2.0", "id": rid, "method": method, "params": params}))
            return await asyncio.wait_for(future, timeout)
        finally:
            self.pending.pop(rid, None)

    async def respond(self, rid, result: dict):
        await self.socket.send(json.dumps({"jsonrpc": "2.0", "id": rid, "result": result}))

    async def reject(self, rid):
        await self.socket.send(json.dumps({"jsonrpc": "2.0", "id": rid,
                                          "error": {"code": -32601, "message": "HAOS does not grant this capability"}}))

    async def close(self):
        await self.socket.close()
        await asyncio.gather(self.reader, return_exceptions=True)


def mission_prompt(goal: str) -> str:
    return (f"Mission: {goal}\n\nPlan with the todo tool, execute real steps, update the plan and report "
            "the actual result with evidence and any unresolved work. Do not claim success for failed "
            "tools or missing credentials. Owner storage and system policy cannot be changed by an agent.")


def outcome(payload: dict, cancel_requested: bool) -> tuple[str, str | None]:
    status = payload.get("status")
    if status == "interrupted":
        # An interrupted model turn does not prove that background tools stopped touching the workspace.
        return "blocked", "Hermes turn interrupted; owner must inspect remaining processes and side effects"
    if status == "error" or payload.get("error") or payload.get("partial"):
        return "failed", str(payload.get("error") or payload.get("text") or "Hermes turn failed")
    # A completion is a turn receipt, not independent proof that the user's goal was achieved.
    if status == "complete" and isinstance(payload.get("text"), str) and payload["text"].strip():
        if cancel_requested:
            return "blocked", "Hermes completed while cancellation was pending; inspect the result"
        return "completed", None
    return "blocked", "Hermes did not return a verifiable terminal turn receipt"
