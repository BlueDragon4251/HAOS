"""Trusted gateway ingress and durable delivery obligations in the mission database."""

from __future__ import annotations

import hashlib
import json
import re
import time

from .store import Conflict, MissionStore, PAUSED_PHASE
from .gateway_source_cancel import SourceCancellation

_NAME = re.compile(r"[a-zA-Z0-9][a-zA-Z0-9_.:-]{0,127}\Z")
SUPPORTED = {"telegram", "discord", "slack", "mattermost", "matrix", "ntfy", "homeassistant", "irc", "line", "sms", "email", "feishu", "dingtalk", "a2a", "buzz", "google_chat"}
CAPABILITIES = {"create", "read", "cancel", "answer", "pause", "resume"}


def digest(value) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()


def identifier(value, *, empty=False):
    if not isinstance(value, str) or len(value) > 256 or (not value and not empty) or any(ord(c) < 32 for c in value):
        raise ValueError("invalid transport identifier")
    return value


class GatewayPolicy:
    platforms = SUPPORTED

    def __init__(self, config: dict):
        fields = {"version", "connectors", "bindings"}
        if config.get("version") != 1 or set(config) not in (fields, fields | {"publication"}):
            raise ValueError("unsupported gateway policy")
        self.publication = config.get("publication")
        if "publication" in config and (not isinstance(self.publication, str)
                or not re.fullmatch(r"[a-f0-9]{64}", self.publication)):
            raise ValueError("invalid gateway publication")
        self.connectors, self.bindings = {}, {}
        if (not isinstance(config["connectors"], list) or not isinstance(config["bindings"], list)
                or len(config["connectors"]) > 32 or len(config["bindings"]) > 512):
            raise ValueError("gateway policy exceeds supported limits")
        for connector in config["connectors"]:
            name = connector.get("id")
            if (not isinstance(name, str) or not _NAME.fullmatch(name) or name in self.connectors
                    or connector.get("platform") not in self.platforms
                    or set(connector) != {"id", "platform"}):
                raise ValueError("invalid or unsupported gateway connector")
            self.connectors[name] = connector
        routes = set()
        for binding in config["bindings"]:
            fields = {"id", "connector", "sender", "chat", "scope", "thread", "identity", "capabilities"}
            connector = self.connectors.get(binding.get('connector'))
            extras=({'matrix_devices','allow_plaintext','require_mention'} if connector and connector['platform']=='matrix'
                else {'trust_topic_publishers'} if connector and connector['platform']=='ntfy'
                else {'homeassistant_shared_notifications','homeassistant_trust_system'} if connector and connector['platform']=='homeassistant'
                else {'allow_media','allow_voice','allow_video','allow_outbound_media','require_mention','all_threads'} if connector and connector['platform']=='google_chat'
                else {'allow_media','allow_voice','allow_video','allow_outbound_media','all_threads'} if connector and connector['platform']=='photon'
                else {'allow_media','allow_voice','allow_video','allow_outbound_media','require_mention'} if connector and connector['platform'] in {'feishu','dingtalk','buzz'}
                else {'allow_media','allow_voice','allow_video','allow_outbound_media','allow_callback'} if connector and connector['platform']=='a2a'
                else {'allow_media','allow_voice','allow_video','allow_outbound_media'} if connector and connector['platform'] in {'line','sms','email','a2a'} else set())
            if not fields <= set(binding) <= fields | {'generation','since'} | extras:
                raise ValueError("invalid gateway identity binding")
            if 'since' in binding and (type(binding['since']) is not int or not 0 < binding['since'] < 2**53):
                raise ValueError('invalid gateway grant time boundary')
            if "generation" in binding and (not isinstance(binding["generation"], str)
                    or not re.fullmatch(r"[a-f0-9]{64}", binding["generation"])):
                raise ValueError("invalid gateway binding generation")
            for key in ("id", "identity"):
                if not isinstance(binding[key], str) or not _NAME.fullmatch(binding[key]):
                    raise ValueError("invalid HAOS identity")
            for key in ("sender", "chat", "scope", "thread"):
                identifier(binding[key], empty=key in {"scope", "thread"})
            connector = self.connectors.get(binding['connector'])
            if connector and connector['platform']=='slack':
                if (not re.fullmatch('[UW][A-Z0-9]+',binding['sender'])
                        or not re.fullmatch('[CDG][A-Z0-9]+',binding['chat'])
                        or not re.fullmatch('T[A-Z0-9]+',binding['scope'])
                        or binding['thread'] and not re.fullmatch(r'[1-9][0-9]{0,15}\.[0-9]{6}',binding['thread'])):
                    raise ValueError('Slack requires exact user, conversation, workspace and optional thread timestamp IDs')
            if connector and connector['platform']=='mattermost':
                if any(not re.fullmatch('[a-z0-9]{26}',binding[key]) for key in ('sender','chat')) or any(
                        binding[key] and not re.fullmatch('[a-z0-9]{26}',binding[key]) for key in ('scope','thread')):
                    raise ValueError('Mattermost requires exact user, channel, optional team and root-post IDs')
            if connector and connector['platform']=='ntfy':
                from .gateway_ntfy import validate_binding
                validate_binding(binding)
            if connector and connector['platform']=='irc':
                from .gateway_irc_ingress import validate_binding
                validate_binding(binding)
            if connector and connector['platform']=='line':
                from .gateway_line_ingress import validate_binding
                validate_binding(binding)
            if connector and connector['platform']=='a2a':
                from .gateway_a2a import validate_binding
                validate_binding(binding)
            if connector and connector['platform']=='buzz':
                from .gateway_buzz import validate_binding
                validate_binding(binding)
            if connector and connector['platform']=='dingtalk':
                from .gateway_dingtalk import validate_binding
                validate_binding(binding)
            if connector and connector['platform']=='feishu':
                from .gateway_feishu import validate_binding
                validate_binding(binding)
            if connector and connector['platform']=='email':
                from .gateway_email import validate_binding
                validate_binding(binding)
            if connector and connector['platform']=='sms':
                from .gateway_sms import validate_binding
                validate_binding(binding)
            if connector and connector['platform']=='homeassistant':
                from .gateway_homeassistant_ingress import validate_binding
                validate_binding(binding)
            if connector and connector['platform']=='matrix':
                from .gateway_matrix_policy import validate_binding
                validate_binding(binding)
            capabilities = binding["capabilities"]
            if (not isinstance(capabilities, list) or not capabilities or not set(capabilities) <= CAPABILITIES
                    or len(set(capabilities)) != len(capabilities)):
                raise ValueError("invalid gateway capabilities")
            route = tuple(binding[key] for key in ("connector", "sender", "chat", "scope", "thread"))
            if binding["connector"] not in self.connectors or route in routes or binding["id"] in self.bindings:
                raise ValueError("duplicate or unconfigured gateway route")
            routes.add(route)
            self.bindings[binding["id"]] = binding
        if any(row['platform']=='google_chat' for row in self.connectors.values()):
            from .gateway_google_chat import validate_binding,validate_overlaps
            for binding in self.bindings.values():
                if self.connectors[binding['connector']]['platform']=='google_chat':validate_binding(binding)
            validate_overlaps(self)
            self._google_policy_fingerprint=digest([self.publication,self.connectors,self.bindings])

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
            if binding["connector"] == connector and all(binding[k] == envelope[k] for k in ("sender", "chat", "scope")):
                if binding['thread']==envelope['thread']:return binding
                if envelope['platform']=='google_chat':
                    from .gateway_google_chat import thread_allowed
                    if thread_allowed(binding,envelope['thread']):return binding
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
        from .gateway_media import GatewayMedia
        self.media=GatewayMedia(store)
        self.source_cancellations=SourceCancellation(store)
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
            CREATE TABLE IF NOT EXISTS gateway_delivery_context(
                delivery_id TEXT PRIMARY KEY REFERENCES gateway_outbox(id),metadata TEXT NOT NULL,sha256 TEXT NOT NULL
            );
            COMMIT;
        """)
        versions = store.db.execute("SELECT version FROM gateway_schema").fetchall()
        if len(versions) != 1 or versions[0][0] not in {1, 2}:
            raise RuntimeError("unsupported gateway schema")
        if versions[0][0] == 1:
            with store.transaction():
                # Preserve legacy rows. Their original grant cannot be proved
                # after an owner publishes a fresh generation, so replay fails
                # closed rather than executing an old message again.
                store.db.execute("ALTER TABLE gateway_inbox ADD COLUMN binding_digest TEXT")
                store.db.execute("UPDATE gateway_schema SET version=2")

    def _queue(self, route_id: str, key: str, content: str, *, limit=1800,context=None):
        content = self.store.redactor.text(content)
        # Bound native platform chunks; each part has a stable durable identity.
        groups=[content]
        if limit==1600:
            from .gateway_outbound import marked
            try:paths,caption=marked(content)
            except ValueError:paths,caption=[],content
            if paths:
                # Keep full caption text in its own durable text obligations;
                # media-only obligations reserve room for up to four URLs even
                # at the maximum accepted DNS hostname length.
                groups=([caption] if caption else [])+['\n'.join('MEDIA:'+path for path in paths)]
        chunks=[]
        for group in groups:
            remaining=group
            while remaining:
                end=min(limit,len(remaining))
                if end<len(remaining):
                    line=remaining.rfind('\n',0,end)+1
                    if line and remaining[line:end].lstrip().startswith('MEDIA:'):end=line
                chunks.append(remaining[:end]);remaining=remaining[end:]
        if context is not None:
            total_bytes=sum(len(item.encode()) for item in chunks);group_sha256=digest([route_id,key,chunks])
        for part, chunk in enumerate(chunks):
            delivery_id=digest([route_id,key,part])
            self.store.db.execute("INSERT OR IGNORE INTO gateway_outbox(id,route_id,content) VALUES(?,?,?)",
                                  (delivery_id, route_id, chunk))
            if context is not None:
                from .gateway_event_context import retain
                retain(self.store,delivery_id,{**context,'part':part,'parts':len(chunks),
                    'total_bytes':total_bytes,'content_sha256':hashlib.sha256(chunk.encode()).hexdigest(),
                    'group_sha256':group_sha256},chunk)

    async def receive(self, policy: GatewayPolicy, connector: str, envelope: dict, controller, *, media=None) -> dict:
        from .gateway_media import references,authorize as authorize_media
        media=references([] if media is None else media)
        binding = policy.authorize(connector, envelope)
        if media:authorize_media(policy,connector,envelope)
        text = envelope["text"]
        if not isinstance(text, str) or not 1 <= len(text.strip()) <= 32000:
            raise ValueError("gateway text must contain 1–32000 characters")
        key = digest([connector, envelope["scope"], envelope["chat"], envelope["thread"], envelope["message_id"]])
        fingerprint = digest([envelope,media]) if media else digest(envelope)
        actor = "gateway:" + binding["identity"]
        answer_request = None
        with self.store.transaction():
            if policy.connectors[connector]['platform']=='a2a':self.source_cancellations.before_admission(key)
            old = self.store.db.execute("SELECT * FROM gateway_inbox WHERE key=?", (key,)).fetchone()
            if old:
                if (old["fingerprint"] != fingerprint or old["identity"] != binding["identity"]
                        or old["binding_id"] != binding["id"] or old["binding_digest"] != digest(binding)):
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
                if command not in {"/status", "/cancel", "/answer", "/pause", "/resume"} or len(parts) < 2:
                    raise ValueError("supported commands: /status ID, /cancel ID, /pause ID, /resume ID, /answer ID REQUEST_ID ANSWER")
                mid = parts[1]
                mission = self.store.get(mid)
                if mission["actor"] != actor:
                    raise PermissionError("gateway identity does not own this mission")
                capability = {"/status": "read", "/cancel": "cancel", "/answer": "answer",
                              "/pause": "pause", "/resume": "resume"}[command]
                if capability not in binding["capabilities"]:
                    raise PermissionError("gateway action denied")
                if command == "/cancel":
                    mission = self.store.request_cancel(mid, actor)
                elif command in {"/pause", "/resume"}:
                    if len(parts) != 2:
                        raise ValueError("pause/resume requires only an exact mission ID")
                    mission = (self.store.pause if command == "/pause" else self.store.resume)(mid, actor)
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
                state = "paused" if mission["state"] == "blocked" and mission["phase"] == PAUSED_PHASE else mission["state"]
                content = f"Mission {mid}: {state}\n{mission['result'] or mission['error'] or ''}"
            else:
                if "create" not in binding["capabilities"]:
                    raise PermissionError("gateway mission creation denied")
                mission = self.store.create(actor, key, text)
                mid = mission["id"]
                self.media.attach(policy,connector,envelope,media,mid)
                content = f"Mission {mid}: queued"
            # Explicit Google whole-space consent still preserves the actual
            # source thread for each mission/query route and every reply.
            route_thread=envelope['thread'] if envelope['platform']=='google_chat' else binding['thread']
            route_parts=[mid,binding['id'],digest(binding)]
            if envelope['platform']=='google_chat':route_parts.append(route_thread)
            route_id=digest(route_parts)
            self.store.db.execute("""INSERT OR IGNORE INTO gateway_routes
                (id,mission_id,binding_id,binding_digest,connector,chat,thread,scope,reply_to)
                VALUES(?,?,?,?,?,?,?,?,?)""", (route_id, mid, binding["id"], digest(binding), connector,
                                              binding["chat"], route_thread, binding["scope"], envelope["message_id"]))
            state = "paused" if mission["state"] == "blocked" and mission["phase"] == PAUSED_PHASE else mission["state"]
            reply = {"mission_id": mid, "state": state}
            self.store.db.execute("""INSERT INTO gateway_inbox
                (key,fingerprint,binding_id,identity,received_at,mission_id,response,binding_digest)
                VALUES(?,?,?,?,?,?,?,?)""",
                (key, fingerprint, binding["id"], binding["identity"], time.time(), mid, json.dumps(reply), digest(binding)))
            self.store._event(mid, "gateway.received", {"connector": connector, "binding": binding["id"], "message_id": envelope["message_id"]})
            if policy.connectors[connector]['platform'] in {'a2a','buzz','google_chat'}:
                from .gateway_event_context import snapshot
                self._queue(route_id,key,content,context=snapshot(self.store,mid,'gateway.receipt',key))
            elif policy.connectors[connector]['platform']=='sms':self._queue(route_id,key,content,limit=1600)
            else:self._queue(route_id,key,content)
        # Commit admission BEFORE a network response to Hermes. A replay never repeats that side effect.
        if answer_request is not None:
            try:
                await controller.dispatch(actor, answer_request)
            except Exception as error:
                with self.store.transaction():
                    self.store._event(mid, "gateway.answer-unconfirmed", {"error": type(error).__name__})
                    context=None
                    if policy.connectors[connector]['platform'] in {'a2a','buzz','google_chat'}:
                        from .gateway_event_context import snapshot
                        context=snapshot(self.store,mid,'gateway.answer-unconfirmed',key+':answer')
                    self._queue(route_id, key + ":answer", "Answer delivery unconfirmed; inspect the live question in Herald before retrying.",context=context)
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
                    elif kind in {"mission.claimed", "mission.completed", "mission.failed", "mission.blocked", "mission.cancelled",
                                  "mission.paused", "mission.resumed"}:
                        content = f"Mission {route['mission_id']}: {kind.removeprefix('mission.')}\n{payload.get('result') or payload.get('error') or ''}"
                    else:
                        continue
                    if policy.connectors[route['connector']]['platform'] in {'a2a','buzz','google_chat'}:
                        from .gateway_event_context import snapshot
                        context=snapshot(self.store,route['mission_id'],kind,str(event['seq']),
                            request_id=payload.get('id') if kind=='mission.request' else None,
                            request_method=payload.get('method') if kind=='mission.request' else None)
                        self._queue(route['id'],str(event['seq']),content,context=context)
                    elif policy.connectors[route['connector']]['platform']=='sms':self._queue(route['id'],str(event['seq']),content,limit=1600)
                    else:self._queue(route['id'],str(event['seq']),content)
                if events:
                    self.store.db.execute("UPDATE gateway_routes SET cursor=? WHERE id=?", (events[-1]["seq"], route["id"]))

    def next_delivery(self, policy: GatewayPolicy, now: float | None = None, *, ready_connectors=None):
        if ready_connectors is not None and (not isinstance(ready_connectors,list)
                or len(ready_connectors)>len(policy.connectors)
                or any(not isinstance(name,str) or name not in policy.connectors for name in ready_connectors)
                or len(set(ready_connectors))!=len(ready_connectors)):
            raise ValueError('exact distinct configured ready connectors required')
        ready=list(policy.connectors) if ready_connectors is None else ready_connectors
        now = time.time() if now is None else now
        self.refresh(policy)
        with self.store.transaction():
            # No transport idempotency contract: crashed sends are uncertain, never blindly repeated.
            self.store.db.execute("UPDATE gateway_outbox SET state='uncertain',error='sender lost before delivery receipt' WHERE state='sending' AND lease_until<=?", (now,))
            if not ready:return None
            placeholders=",".join("?" for _ in ready)
            row = self.store.db.execute(f"""SELECT o.*,r.connector,r.chat,r.thread,r.scope,r.reply_to,r.binding_id,r.binding_digest
                FROM gateway_outbox o JOIN gateway_routes r ON o.route_id=r.id
                WHERE o.state='pending' AND o.next_attempt<=? AND r.connector IN ({placeholders})
                ORDER BY o.rowid LIMIT 1""", (now,*ready)).fetchone()
            if row is None:
                return None
            self.store.db.execute("UPDATE gateway_outbox SET state='sending',attempt=attempt+1,lease_until=? WHERE id=?", (now + 120, row["id"]))
            result={**dict(row), "attempt": row["attempt"] + 1}
            if policy.connectors[row['connector']]['platform'] in {'a2a','buzz','google_chat'}:
                from .gateway_event_context import load
                try:result['event_context']=load(self.store,result)
                except Conflict:
                    self.store.db.execute("UPDATE gateway_outbox SET state='failed',error='controller-event-context-damaged',lease_until=NULL WHERE id=?",(row['id'],))
                    mission=self.store.db.execute('SELECT mission_id FROM gateway_routes WHERE id=?',(row['route_id'],)).fetchone()[0]
                    self.store._event(mission,'gateway.delivery-context-refused',{'delivery':row['id'],'reason':'controller-event-context-damaged'})
                    return None
            return result

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
            reason=result.get('reason')
            if reason is not None and reason not in {'media-export-unavailable','media-export-or-format-refused'}:
                raise ValueError('unknown public delivery failure reason')
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
                                  (state, receipt, time.time() + delay, None if state == "delivered" else reason or status, delivery_id))
            self.store._event(row["mission_id"], "gateway.delivery", {"delivery": delivery_id, "state": state, "receipt": receipt})
            return {"state": state}
