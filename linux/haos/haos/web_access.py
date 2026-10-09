"""Observer capabilities at the actual pinned Hermes ASGI boundary.

This middleware is installed by the image-owned launcher, outside model output
and UI controls. Controller requests keep their independent private credential.
"""
import hmac
import json
import re
from urllib.parse import parse_qsl, urlencode

TOKEN = re.compile(r"[A-Za-z0-9_-]{43,128}")
READ_HTTP = {"/api/health", "/api/host/identity", "/api/status", "/api/system/stats",
             "/api/sessions", "/api/sessions/search", "/api/sessions/stats"}
SESSION_READ = re.compile(r"/api/sessions/[A-Za-z0-9_-]{1,128}/(?:messages|timeline)")
# These names exist in the pinned upstream. No config, keys, model turns,
# session mutations, terminal, browser control or server-request answers.
READ_RPC = {"gateway.ping", "session.list", "session.active_list",
            "session.events.since", "session.events.stats"}
MAX_FRAME = 131072


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("ambiguous JSON object")
        result[key] = value
    return result


def readable_frame(text):
    if not isinstance(text, str) or len(text.encode()) > MAX_FRAME:
        return False
    try:
        value = json.loads(text, object_pairs_hook=unique_object,
                           parse_constant=lambda _: (_ for _ in ()).throw(ValueError("invalid constant")))
        if (not isinstance(value, dict) or set(value) - {"jsonrpc", "id", "method", "params"}
                or value.get("jsonrpc") != "2.0" or value.get("method") not in READ_RPC
                or not isinstance(value.get("params", {}), dict)):
            return False
        identifier = value.get("id")
        return ((isinstance(identifier, str) and 0 < len(identifier) <= 128)
                or (type(identifier) is int and -(2 ** 63) <= identifier < 2 ** 63))
    except (ValueError, TypeError, RecursionError, UnicodeError):
        return False


class DashboardAccess:
    def __init__(self, app, *, backend_token, observer_token, redact_tokens=()):
        if (not TOKEN.fullmatch(backend_token) or not TOKEN.fullmatch(observer_token)
                or hmac.compare_digest(backend_token, observer_token)):
            raise ValueError("dashboard capabilities must be separate valid credentials")
        self.app, self.backend, self.observer = app, backend_token.encode(), observer_token.encode()
        self.secrets = sorted({self.backend, self.observer, *(v.encode() for v in redact_tokens if isinstance(v, str) and v)},
                              key=len, reverse=True)

    def redact(self, value):
        for secret in self.secrets:
            value = value.replace(secret, b"[REDACTED]")
        return value

    async def deny(self, scope, send, *, unauthorized=False):
        if scope["type"] == "websocket":
            await send({"type": "websocket.close", "code": 4401 if unauthorized else 4403,
                        "reason": "HAOS observer capability denied"})
        else:
            body = b'{"error":"HAOS observer capability denied; use authenticated owner setup or persistent missions"}'
            await send({"type": "http.response.start", "status": 401 if unauthorized else 403,
                        "headers": [(b"content-type", b"application/json"), (b"cache-control", b"no-store")]})
            await send({"type": "http.response.body", "body": body})

    async def __call__(self, scope, receive, send):
        if scope["type"] not in {"http", "websocket"}:
            return await self.app(scope, receive, send)
        headers, candidates = scope.get("headers", []), []
        try:
            query = parse_qsl(scope.get("query_string", b"").decode("ascii"), keep_blank_values=True,
                              max_num_fields=64, errors="strict")
            for name in (b"authorization", b"x-hermes-session-token"):
                values = [v for k, v in headers if k.lower() == name]
                if len(values) > 1:
                    raise ValueError("duplicate authorization")
                if values:
                    value = values[0]
                    if name == b"authorization":
                        if not value.startswith(b"Bearer "):
                            raise ValueError("unsupported authorization")
                        value = value[7:]
                    candidates.append(value)
            tokens = [v.encode() for k, v in query if k == "token"]
            if len(tokens) > 1:
                raise ValueError("duplicate token")
            candidates.extend(tokens)
            if len(candidates) > 1 and any(not hmac.compare_digest(candidates[0], v) for v in candidates[1:]):
                raise ValueError("conflicting credentials")
        except (ValueError, UnicodeError):
            return await self.deny(scope, send, unauthorized=True)
        token = candidates[0] if candidates else b""
        path = scope.get("path", "")
        raw = scope.get("raw_path", path.encode())
        if (b"%" in raw or b"\\" in raw or not raw.startswith(b"/api/")
                or scope.get("client", (None,))[0] not in {"127.0.0.1", "::1"}):
            return await self.deny(scope, send)
        # Preserve the existing public, content-free process liveness check.
        if not candidates and scope["type"] == "http" and scope.get("method") == "GET" and path == "/api/health":
            return await self.app(scope, receive, send)
        if hmac.compare_digest(token, self.backend):
            return await self.app(scope, receive, send)
        if not hmac.compare_digest(token, self.observer):
            return await self.deny(scope, send, unauthorized=True)
        if scope["type"] == "http":
            if scope.get("method") != "GET" or not (path in READ_HTTP or SESSION_READ.fullmatch(path)):
                return await self.deny(scope, send)
        elif path != "/api/ws":
            return await self.deny(scope, send)
        # Translate only after independently checking the scope. Cookies and
        # arbitrary auth/ticket headers cannot provide another identity upstream.
        inner = dict(scope)
        inner["headers"] = [(k, v) for k, v in headers if k.lower() not in
                            {b"authorization", b"x-hermes-session-token", b"cookie", b"sec-websocket-protocol", b"accept-encoding"}]
        inner["headers"].append((b"x-hermes-session-token", self.backend))
        inner["headers"].append((b"accept-encoding", b"identity"))
        inner["query_string"] = urlencode([(k, v) for k, v in query if k != "token"] +
                                           [("token", self.backend.decode())]).encode()
        closed = False
        async def observer_receive():
            nonlocal closed
            if closed:
                return {"type": "websocket.disconnect", "code": 4403}
            message = await receive()
            if message["type"] == "websocket.receive" and not readable_frame(message.get("text")):
                closed = True
                await self.deny(scope, send)
                return {"type": "websocket.disconnect", "code": 4403}
            return message
        # Observer HTTP responses are bounded and buffered before publication so
        # a credential split across ASGI chunks cannot escape redaction.
        start, chunks, size = None, [], 0
        async def observer_send(message):
            nonlocal start, size, closed
            if scope["type"] == "websocket":
                if closed:
                    return
                if message["type"] == "websocket.send":
                    if "text" not in message:
                        closed = True
                        return await self.deny(scope, send)
                    message = {**message, "text": self.redact(message["text"].encode()).decode()}
                return await send(message)
            if message["type"] == "http.response.start":
                start = dict(message)
                if any(k.lower() == b"content-encoding" and v.lower() != b"identity"
                       for k, v in message.get("headers", [])):
                    raise ValueError("observer responses must remain readable for redaction")
                start["headers"] = [(k, self.redact(v))
                                    for k, v in message.get("headers", [])
                                    if k.lower() not in {b"content-length", b"etag", b"set-cookie", b"cache-control"}]
                start["headers"].append((b"cache-control", b"no-store"))
            elif message["type"] == "http.response.body":
                size += len(message.get("body", b""))
                if size > 4 * 1024 * 1024:
                    raise ValueError("observer response exceeds its bound")
                chunks.append(message.get("body", b""))
                if not message.get("more_body", False):
                    body = self.redact(b"".join(chunks))
                    await send(start)
                    await send({"type": "http.response.body", "body": body})
        await self.app(inner, observer_receive, observer_send)
