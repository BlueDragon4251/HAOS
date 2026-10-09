"""Trusted gateway ingress and durable delivery obligations in the mission database."""

from __future__ import annotations

import hashlib
import json
import re
import time

from .store import Conflict, MissionStore

_NAME = re.compile(r"[a-zA-Z0-9][a-zA-Z0-9_.:-]{0,127}\Z")
SUPPORTED = {"telegram", "discord"}
CAPABILITIES = {"create", "read", "cancel", "answer"}


def digest(value) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()


def identifier(value, *, empty=False):
    if not isinstance(value, str) or len(value) > 256 or (not value and not empty) or any(ord(c) < 32 for c in value):
        raise ValueError("invalid transport identifier")
    return value


class GatewayPolicy:
    def __init__(self, config: dict):
        if config.get("version") != 1 or set(config) != {"version", "connectors", "bindings"}:
            raise ValueError("unsupported gateway policy")
        self.connectors, self.bindings = {}, {}
        if (not isinstance(config["connectors"], list) or not isinstance(config["bindings"], list)
                or len(config["connectors"]) > 16 or len(config["bindings"]) > 512):
            raise ValueError("gateway policy exceeds supported limits")
        for connector in config["connectors"]:
            name = connector.get("id")
            if (not isinstance(name, str) or not _NAME.fullmatch(name) or name in self.connectors
                    or connector.get("platform") not in SUPPORTED
                    or set(connector) != {"id", "platform"}):
                raise ValueError("invalid or unsupported gateway connector")
            self.connectors[name] = connector
        routes = set()
        for binding in config["bindings"]:
            if set(binding) != {"id", "connector", "sender", "chat", "scope", "thread", "identity", "capabilities"}:
                raise ValueError("invalid gateway identity binding")
            for key in ("id", "identity"):
                if not isinstance(binding[key], str) or not _NAME.fullmatch(binding[key]):
                    raise ValueError("invalid HAOS identity")
            for key in ("sender", "chat", "scope", "thread"):
                identifier(binding[key], empty=key in {"scope", "thread"})
            capabilities = binding["capabilities"]
            if (not isinstance(capabilities, list) or not capabilities or not set(capabilities) <= CAPABILITIES
                    or len(set(capabilities)) != len(capabilities)):
                raise ValueError("invalid gateway capabilities")
            route = tuple(binding[key] for key in ("connector", "sender", "chat", "scope", "thread"))
            if binding["connector"] not in self.connectors or route in routes or binding["id"] in self.bindings:
                raise ValueError("duplicate or unconfigured gateway route")
            routes.add(route)
            self.bindings[binding["id"]] = binding

    def authorize(self, connector: str, envelope: dict) -> dict:
        if connector not in self.connectors or not isinstance(envelope, dict):
            raise PermissionError("gateway connector denied")
        if set(envelope) != {"platform", "sender", "chat", "scope", "thread", "message_id", "is_bot", "text"}:
            raise ValueError("invalid gateway envelope")
        if envelope["platform"] != self.connectors[connector]["platform"] or envelope["is_bot"] is not False:
            raise PermissionError("gateway source denied")
        for key in ("sender", "chat", "scope", "thread", "message_id"):
            identifier(envelope[key], empty=key in {"scope", "thread"})
        for binding in self.bindings.values():
            if binding["connector"] == connector and all(binding[k] == envelope[k] for k in ("sender", "chat", "scope", "thread")):
                return binding
        raise PermissionError("gateway sender is not paired for this exact route")

    def current_binding(self, route: dict):
        binding = self.bindings.get(route["binding_id"])
        # Binding edits are revocations too: never redirect old private results to a new recipient.
        if binding is None or digest(binding) != route["binding_digest"]:
            raise PermissionError("gateway binding was revoked or changed")
        return binding


class GatewayEngine:
    def __init__(self, store: MissionStore):
        self.store = store
        # This additive extension has its own version and preserves the v1 mission contract.
        store.db.executescript("""
            BEGIN IMMEDIATE;
            CREATE TABLE IF NOT EXISTS gateway_schema (version INTEGER NOT NULL);
            INSERT INTO gateway_schema SELECT 1 WHERE NOT EXISTS (SELECT 1 FROM gateway_schema);
            CREATE TABLE IF NOT EXISTS gateway_inbox (
                key TEXT PRIMARY KEY, fingerprint TEXT NOT NULL, binding_id TEXT NOT NULL,
                identity TEXT NOT NULL, received_at REAL NOT NULL, mission_id TEXT NOT NULL,
                response TEXT NOT NULL, FOREIGN KEY(mission_id) REFERENCES missions(id)
            );
            CREATE TABLE IF NOT EXISTS gateway_routes (
                id TEXT PRIMARY KEY, mission_id TEXT NOT NULL REFERENCES missions(id),
                binding_id TEXT NOT NULL, binding_digest TEXT NOT NULL, connector TEXT NOT NULL,
                chat TEXT NOT NULL, thread TEXT NOT NULL, scope TEXT NOT NULL, reply_to TEXT NOT NULL,
                cursor INTEGER NOT NULL DEFAULT 0
            );
            CREATE TABLE IF NOT EXISTS gateway_outbox (
                id TEXT PRIMARY KEY, route_id TEXT NOT NULL REFERENCES gateway_routes(id),
                content TEXT NOT NULL, state TEXT NOT NULL DEFAULT 'pending',
                attempt INTEGER NOT NULL DEFAULT 0, next_attempt REAL NOT NULL DEFAULT 0,
                lease_until REAL, receipt TEXT, error TEXT
            );
            COMMIT;
        """)
        versions = store.db.execute("SELECT version FROM gateway_schema").fetchall()
        if len(versions) != 1 or versions[0][0] != 1:
            raise RuntimeError("unsupported gateway schema")

    def _queue(self, route_id: str, key: str, content: str):
        content = self.store.redactor.text(content)
        # Bound native platform chunks; each part has a stable durable identity.
        for part, offset in enumerate(range(0, len(content), 1800)):
            self.store.db.execute("INSERT OR IGNORE INTO gateway_outbox(id,route_id,content) VALUES(?,?,?)",
                                  (digest([route_id, key, part]), route_id, content[offset:offset + 1800]))

    async def receive(self, policy: GatewayPolicy, connector: str, envelope: dict, controller) -> dict:
        binding = policy.authorize(connector, envelope)
        text = envelope["text"]
        if not isinstance(text, str) or not 1 <= len(text.strip()) <= 32000:
            raise ValueError("gateway text must contain 1–32000 characters")
        key = digest([connector, envelope["scope"], envelope["chat"], envelope["thread"], envelope["message_id"]])
        fingerprint = digest(envelope)
        actor = "gateway:" + binding["identity"]
        answer_request = None
        with self.store.transaction():
            old = self.store.db.execute("SELECT * FROM gateway_inbox WHERE key=?", (key,)).fetchone()
            if old:
                if old["fingerprint"] != fingerprint or old["identity"] != binding["identity"]:
                    raise Conflict("gateway replay changed its content or identity")
                return json.loads(old["response"])
            recent = self.store.db.execute(
                "SELECT COUNT(*) FROM gateway_inbox WHERE identity=? AND received_at>?",
                (binding["identity"], time.time() - 60)).fetchone()[0]
            if recent >= 30:
                raise PermissionError("gateway admission rate limit")
            # Commands are exact syntax; no language-model output participates in authorization.
            parts = text.strip().split(maxsplit=2)
            command = parts[0]
            if command.startswith("/"):
                if command not in {"/status", "/cancel", "/answer"} or len(parts) < 2:
                    raise ValueError("supported commands: /status ID, /cancel ID, /answer ID REQUEST_ID ANSWER")
                mid = parts[1]
                mission = self.store.get(mid)
                if mission["actor"] != actor:
                    raise PermissionError("gateway identity does not own this mission")
                capability = {"/status": "read", "/cancel": "cancel", "/answer": "answer"}[command]
                if capability not in binding["capabilities"]:
                    raise PermissionError("gateway action denied")
                if command == "/cancel":
                    mission = self.store.request_cancel(mid, actor)
                elif command == "/answer":
                    if len(parts) != 3 or controller.current != mid:
                        raise Conflict("mission question is not active")
                    answer_parts = parts[2].split(maxsplit=1)
                    if len(answer_parts) != 2:
                        raise ValueError("answer requires a request ID and an answer")
                    request_id, answer = answer_parts
                    answer_request = {"method": "missions.answer", "params": {
                        "request_id": request_id, "answer": answer, "choice": answer}}
                    self.store._event(mid, "gateway.answer-dispatching", {"request_id": request_id, "actor": actor})
                content = f"Mission {mid}: {mission['state']}\n{mission['result'] or mission['error'] or ''}"
            else:
                if "create" not in binding["capabilities"]:
                    raise PermissionError("gateway mission creation denied")
                mission = self.store.create(actor, key, text)
                mid = mission["id"]
                content = f"Mission {mid}: queued"
            route_id = digest([mid, binding["id"], digest(binding)])
            self.store.db.execute("""INSERT OR IGNORE INTO gateway_routes
                (id,mission_id,binding_id,binding_digest,connector,chat,thread,scope,reply_to)
                VALUES(?,?,?,?,?,?,?,?,?)""", (route_id, mid, binding["id"], digest(binding), connector,
                                              binding["chat"], binding["thread"], binding["scope"], envelope["message_id"]))
            reply = {"mission_id": mid, "state": mission["state"]}
            self.store.db.execute("INSERT INTO gateway_inbox VALUES(?,?,?,?,?,?,?)",
                                  (key, fingerprint, binding["id"], binding["identity"], time.time(), mid, json.dumps(reply)))
            self.store._event(mid, "gateway.received", {"connector": connector, "binding": binding["id"], "message_id": envelope["message_id"]})
            self._queue(route_id, key, content)
        # Commit admission BEFORE a network response to Hermes. A replay never repeats that side effect.
        if answer_request is not None:
            try:
                await controller.dispatch(actor, answer_request)
            except Exception as error:
                with self.store.transaction():
                    self.store._event(mid, "gateway.answer-unconfirmed", {"error": type(error).__name__})
                    self._queue(route_id, key + ":answer", "Answer delivery unconfirmed; inspect the live question in Herald before retrying.")
        return reply

    def refresh(self, policy: GatewayPolicy):
        with self.store.transaction():
            for raw in self.store.db.execute("SELECT * FROM gateway_routes").fetchall():
                route = dict(raw)
                try:
                    binding = policy.current_binding(route)
                    if "read" not in binding["capabilities"]:
                        continue
                except PermissionError:
                    self.store.db.execute("UPDATE gateway_outbox SET state='revoked' WHERE route_id=? AND state IN ('pending','sending')", (route["id"],))
                    continue
                events = self.store.events(route["mission_id"], route["cursor"])
                for event in events:
                    kind, payload = event["kind"], event["payload"]
                    if kind == "mission.request":
                        # Do not send arbitrary tool parameters or command contents off-host.
                        content = (f"Mission {route['mission_id']}: waiting for {payload.get('method')}\n"
                                   f"Request {payload.get('id')}; inspect details in Herald. "
                                   "Reply /answer MISSION_ID REQUEST_ID once|deny (approval) or your clarification.")
                    elif kind in {"mission.claimed", "mission.completed", "mission.failed", "mission.blocked", "mission.cancelled"}:
                        content = f"Mission {route['mission_id']}: {kind.removeprefix('mission.')}\n{payload.get('result') or payload.get('error') or ''}"
                    else:
                        continue
                    self._queue(route["id"], str(event["seq"]), content)
                if events:
                    self.store.db.execute("UPDATE gateway_routes SET cursor=? WHERE id=?", (events[-1]["seq"], route["id"]))

    def next_delivery(self, policy: GatewayPolicy, now: float | None = None):
        now = time.time() if now is None else now
        self.refresh(policy)
        with self.store.transaction():
            # No transport idempotency contract: crashed sends are uncertain, never blindly repeated.
            self.store.db.execute("UPDATE gateway_outbox SET state='uncertain',error='sender lost before delivery receipt' WHERE state='sending' AND lease_until<=?", (now,))
            row = self.store.db.execute("""SELECT o.*,r.connector,r.chat,r.thread,r.scope,r.reply_to
                FROM gateway_outbox o JOIN gateway_routes r ON o.route_id=r.id
                WHERE o.state='pending' AND o.next_attempt<=? ORDER BY o.rowid LIMIT 1""", (now,)).fetchone()
            if row is None:
                return None
            self.store.db.execute("UPDATE gateway_outbox SET state='sending',attempt=attempt+1,lease_until=? WHERE id=?", (now + 120, row["id"]))
            return {**dict(row), "attempt": row["attempt"] + 1}

    def acknowledge(self, policy: GatewayPolicy, delivery_id: str, result: dict):
        with self.store.transaction():
            row = self.store.db.execute("""SELECT o.*,r.binding_id,r.binding_digest,r.mission_id
                FROM gateway_outbox o JOIN gateway_routes r ON o.route_id=r.id WHERE o.id=?""", (delivery_id,)).fetchone()
            if row is None:
                raise KeyError("unknown delivery")
            policy.current_binding(dict(row))
            if row["state"] == "delivered":
                return {"state": "delivered"}
            if row["state"] != "sending":
                raise Conflict("delivery is not in flight")
            if result.get("attempt") != row["attempt"]:
                raise Conflict("stale delivery attempt")
            status = result.get("status")
            if status == "delivered":
                identifier(result.get("message_id"))
                state, receipt = "delivered", result["message_id"]
            elif status == "retry" and row["attempt"] < 5:
                state, receipt = "pending", None
            elif status in {"retry", "failed", "uncertain"}:
                state, receipt = "failed" if status != "uncertain" else "uncertain", None
            else:
                raise ValueError("invalid delivery receipt")
            delay = result.get("retry_after", min(60, 2 ** row["attempt"]))
            if type(delay) not in {int, float} or not 0 <= delay <= 86400:
                raise ValueError("invalid delivery retry delay")
            self.store.db.execute("UPDATE gateway_outbox SET state=?,receipt=?,next_attempt=?,error=? WHERE id=?",
                                  (state, receipt, time.time() + delay, None if state == "delivered" else status, delivery_id))
            self.store._event(row["mission_id"], "gateway.delivery", {"delivery": delivery_id, "state": state, "receipt": receipt})
            return {"state": state}
