"""Unprivileged mission supervisor and peer-authenticated local API."""

from __future__ import annotations

import asyncio
import fcntl
import grp
import json
import os
import pwd
import signal
import socket
import struct
import time
from pathlib import Path

from .hermes import HermesConnection, mission_prompt, outcome, websocket_url
from .store import ACTIVE, Conflict, MissionStore
from .gateway import GatewayEngine, GatewayPolicy
from .sandbox import trusted_json

MAX_FRAME = 131072


def peer_actor(sock, allowed_uids: set[int]) -> str:
    _, uid, _ = struct.unpack("3i", sock.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, 12))
    if uid not in allowed_uids:
        raise PermissionError("control peer is not authorized")
    return f"uid:{uid}"


class Controller:
    def __init__(self, store: MissionStore, url: str, allowed_uids: set[int]):
        self.store, self.url, self.allowed_uids = store, url, allowed_uids
        self.connection: HermesConnection | None = None
        self.current: str | None = None
        self.questions: dict[str, dict] = {}
        self.finished = asyncio.Event()
        self.stop = asyncio.Event()
        self.gateway = GatewayEngine(store)
        self.gateway_uids: set[int] = set()
        self.gateway_policy = lambda: GatewayPolicy(trusted_json(Path("/etc/haos/gateways.json")))
        self.system_health: dict | None = None

    async def monitor(self):
        from .health import HealthSampler
        sampler = HealthSampler()
        previous = None
        while not self.stop.is_set():
            try:
                self.system_health = await asyncio.to_thread(sampler.sample)
            except Exception:
                self.system_health = {"at": time.time(), "status": "unavailable", "can_dispatch": False,
                                      "errors": ["monitor"], "alerts": []}
            signature = (self.system_health["status"], tuple(self.system_health["alerts"]), tuple(self.system_health["errors"]))
            if signature != previous:
                # No chat, journal excerpts, credentials, commands or filenames.
                print(json.dumps({"event": "system.health", "status": signature[0],
                                  "alerts": signature[1], "errors": signature[2]}), flush=True)
                previous = signature
            try:
                await asyncio.wait_for(self.stop.wait(), 5)
            except TimeoutError:
                pass

    async def gateway_dispatch(self, request: dict):
        policy = self.gateway_policy()
        params = request.get("params", {})
        if not isinstance(params, dict):
            raise ValueError("params must be an object")
        if request.get("method") == "gateway.receive":
            return await self.gateway.receive(policy, params["connector"], params["envelope"], self)
        if request.get("method") == "gateway.next":
            return self.gateway.next_delivery(policy)
        if request.get("method") == "gateway.ack":
            return self.gateway.acknowledge(policy, params["id"], params["result"])
        raise PermissionError("gateway method denied")

    async def event(self, event: dict, epoch: str | None):
        if not self.current or event.get("session_id") != self.store.get(self.current)["session_id"]:
            return
        self.store.record(self.current, event, epoch)
        if event.get("type") == "message.complete":
            row = self.store.get(self.current)
            if row["state"] in ACTIVE:
                payload = event.get("payload") or {}
                state, error = outcome(payload, bool(row["cancel_requested"]))
                self.store.settle(row["id"], state, error=error, result=payload.get("text") if isinstance(payload.get("text"), str) else None)
                self.finished.set()

    async def question(self, frame: dict):
        if not self.connection:
            return
        params = frame.get("params") or {}
        row = self.store.get(self.current) if self.current else None
        if row is None or params.get("session_id") != row["session_id"]:
            await self.connection.reject(frame["id"])
            return
        # Agent-visible sudo, vault and secret requests cannot elevate into the owner's account.
        if frame["method"] not in {"approval", "clarify"}:
            await self.connection.reject(frame["id"])
            self.store.record(row["id"], {"type": "capability.denied", "payload": {"method": frame["method"]}}, None)
            return
        rid = str(frame["id"])
        self.questions[rid] = frame
        self.store.waiting(row["id"], {"id": rid, "method": frame["method"], "params": params})

    async def dispatch(self, actor: str, request: dict):
        method = request.get("method")
        params = request.get("params", {})
        if not isinstance(params, dict):
            raise ValueError("params must be an object")
        if method == "health":
            return {"service": "haos-controller", "backend_connected": self.connection is not None,
                    "current_mission": self.current,
                    "system": self.system_health,
                    "pending_requests": self.store.redactor.clean(list(self.questions.values()))}
        if method == "missions.list":
            return self.store.list()
        if method == "missions.create":
            return self.store.create(actor, params.get("idempotency_key"), params.get("goal"),
                                     timeout=params.get("timeout", 3600), max_attempts=params.get("max_attempts", 3))
        if method == "missions.lookup":
            return self.store.lookup(actor, params.get("idempotency_key"))
        if method == "missions.get":
            return self.store.get(params["id"])
        if method == "missions.events":
            after = params.get("after", 0)
            if type(after) is not int or after < 0:
                raise ValueError("after must be a nonnegative event cursor")
            return self.store.events(params["id"], after)
        if method == "missions.cancel":
            return self.store.request_cancel(params["id"], actor)
        if method == "missions.answer":
            frame = self.questions.get(params["request_id"])
            if not frame or not self.connection or not self.current:
                raise Conflict("request is no longer pending")
            if frame["method"] == "approval":
                choice = params.get("choice")
                if choice not in {"once", "deny"}:
                    raise PermissionError("only once or deny is permitted; no session/permanent grants")
                offered = frame["params"].get("choices", [])
                if choice not in offered:
                    raise ValueError("choice was not offered by Hermes")
                result = {"choice": choice}
            else:
                answer = params.get("answer")
                if not isinstance(answer, str) or len(answer) > 16000:
                    raise ValueError("clarification answer must be at most 16000 characters")
                result, choice = {"answer": answer}, "clarify"
            await self.connection.respond(frame["id"], result)
            self.questions.pop(str(frame["id"]), None)
            self.store.answered(self.current, actor, choice)
            return {"accepted": True}
        raise ValueError("unknown control method")

    async def client(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter, *, gateway=False):
        actor = "unverified"
        try:
            actor = peer_actor(writer.get_extra_info("socket"), self.gateway_uids if gateway else self.allowed_uids)
            line = await asyncio.wait_for(reader.readline(), 10)
            if len(line) > MAX_FRAME or not line.endswith(b"\n"):
                raise ValueError("invalid control frame")
            request = json.loads(line)
            if not isinstance(request, dict):
                raise ValueError("request must be an object")
            result = await self.gateway_dispatch(request) if gateway else await self.dispatch(actor, request)
            reply = {"ok": True, "result": result}
        except (ValueError, KeyError, PermissionError, Conflict, TimeoutError) as exc:
            print(json.dumps({"event": "control.denied", "actor": actor, "reason": type(exc).__name__}), flush=True)
            reply = {"ok": False, "error": self.store.redactor.text(str(exc))}
        except Exception:
            # Exceptions can embed request text, URLs and credentials; journal only their type.
            print(json.dumps({"event": "control.error", "actor": actor}), flush=True)
            reply = {"ok": False, "error": "control service error"}
        try:
            writer.write(json.dumps(reply, ensure_ascii=False).encode() + b"\n")
            await writer.drain()
        finally:
            writer.close()
            await writer.wait_closed()

    async def execute(self, row: dict):
        from websockets.asyncio.client import connect
        self.current = row["id"]
        self.finished.clear()
        cancelled_at = None
        try:
            async with connect(self.url, open_timeout=15, max_size=4 * 1024 * 1024, proxy=None) as ws:
                self.connection = HermesConnection(ws, self.event, self.question)
                session = await self.connection.request("session.create", {
                    "source": "herald_os", "cwd": "/workspace", "title": row["goal"][:60],
                    "close_on_disconnect": False})
                self.store.session(row["id"], session["session_id"], session["stored_session_id"])
                if self.store.get(row["id"])["cancel_requested"]:
                    self.store.settle(row["id"], "cancelled")
                    return
                self.store.dispatching(row["id"])
                reply = await self.connection.request("prompt.submit", {
                    "session_id": session["session_id"], "text": mission_prompt(row["goal"]), "surface": "herald_os"})
                if not isinstance(reply, dict) or reply.get("status") != "streaming":
                    raise Conflict("Hermes did not acknowledge an exclusive streaming turn")
                while not self.finished.is_set():
                    current = self.store.get(row["id"])
                    if self.connection.reader.done():
                        await self.connection.reader
                        raise ConnectionError("Hermes disconnected before a terminal receipt")
                    if time.time() >= current["deadline"] or current["cancel_requested"]:
                        if cancelled_at is None:
                            await self.connection.request("session.interrupt", {"session_id": session["session_id"]}, timeout=10)
                            cancelled_at = time.time()
                        elif time.time() - cancelled_at > 20:
                            raise TimeoutError("no terminal receipt after interrupt")
                    if self.stop.is_set():
                        raise ConnectionError("controller stopping with a possible in-flight turn")
                    try:
                        await asyncio.wait_for(self.finished.wait(), 0.5)
                    except TimeoutError:
                        pass
        except Exception as exc:
            if self.store.get(row["id"])["state"] in ACTIVE:
                # Do not put the URL (which contains an authentication token) in the ledger.
                self.store.unavailable(row["id"], type(exc).__name__)
        finally:
            if self.connection:
                await self.connection.close()
            self.connection, self.current = None, None
            self.questions.clear()

    async def worker(self):
        self.store.recover()
        while not self.stop.is_set():
            healthy = self.system_health is not None and self.system_health.get("can_dispatch") is True
            fresh = healthy and 0 <= time.time() - self.system_health.get("at", 0) < 20
            row = self.store.claim() if fresh else None
            if row:
                await self.execute(row)
            else:
                try:
                    await asyncio.wait_for(self.stop.wait(), 1)
                except TimeoutError:
                    pass


async def serve():
    config = json.loads(Path("/etc/haos/controller.json").read_text())
    uids = {pwd.getpwnam(user).pw_uid for user in config["control_users"]}
    from .credentials import private_credential
    token = private_credential(Path(os.environ["CREDENTIALS_DIRECTORY"]) / "backend-token").strip()
    lock = open("/var/lib/haos-control/controller.lock", "a")
    fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    from .redaction import Redactor
    from .provider_proxy import private_credential
    model_capability = json.loads(private_credential(Path(os.environ["CREDENTIALS_DIRECTORY"]) / "provider-token"))["token"]
    store = MissionStore(Path("/var/lib/haos-control/missions.db"), redactor=Redactor([token, model_capability]))
    controller = Controller(store, websocket_url(config["backend_url"], token), uids)
    controller.gateway_uids = {pwd.getpwnam("haos-gateway").pw_uid}
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, controller.stop.set)
    path = Path("/run/haos-control/control.sock")
    path.unlink(missing_ok=True)
    server = await asyncio.start_unix_server(controller.client, path=path, limit=MAX_FRAME)
    os.chmod(path, 0o660)
    gateway_dir = Path("/run/haos-gateway-control")
    gateway_gid = grp.getgrnam("haos-gateway").gr_gid
    os.chown(gateway_dir, -1, gateway_gid)
    gateway_path = gateway_dir / "gateway.sock"
    gateway_path.unlink(missing_ok=True)
    async def gateway_client(reader, writer):
        await controller.client(reader, writer, gateway=True)
    gateway_server = await asyncio.start_unix_server(gateway_client, path=gateway_path, limit=MAX_FRAME)
    os.chown(gateway_path, -1, gateway_gid)
    os.chmod(gateway_path, 0o660)
    try:
        async with server, gateway_server:
            monitor = asyncio.create_task(controller.monitor())
            try:
                await controller.worker()
            finally:
                controller.stop.set()
                await monitor
    finally:
        server.close()
        await server.wait_closed()
        gateway_server.close()
        await gateway_server.wait_closed()
        store.close()
        lock.close()


if __name__ == "__main__":
    asyncio.run(serve())
