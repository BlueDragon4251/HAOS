"""Fixed-route model broker; real provider credentials never enter the agent namespace."""

from __future__ import annotations

import hmac
import http.client
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import re
import socket
import sqlite3
import ssl
import stat
import threading
import time
from urllib.parse import urlsplit
import uuid
import ipaddress

from .provider_policy import PORT, ProviderPolicy
from .redaction import Redactor
from .sandbox import trusted_json
from .credentials import private_credential
from .provider_registry import descriptor, oauth_providers
from .provider_routes import ProviderRoutes

MAX_INPUT = 4 * 1024 * 1024
MAX_LINE = 1024 * 1024
MAX_OUTPUT = 32 * 1024 * 1024


class UsageLedger:
    """Persist admission before dispatch: restarting the broker cannot reset quotas."""
    def __init__(self, path):
        path = Path(path)
        if path.exists() or path.is_symlink():
            info = path.lstat()
            if not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid() or info.st_mode & 0o077:
                raise PermissionError("provider usage database must be private")
        self.path = path
        self.lock = threading.Lock()
        self.db = sqlite3.connect(path, check_same_thread=False)
        os.chmod(path, 0o600)
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA synchronous=FULL")
        self.db.execute("CREATE TABLE IF NOT EXISTS requests (id TEXT PRIMARY KEY, at REAL NOT NULL, route TEXT NOT NULL, model TEXT NOT NULL, status INTEGER, input_tokens INTEGER, output_tokens INTEGER)")
        self.db.execute("CREATE INDEX IF NOT EXISTS requests_at ON requests(at)")
        self.db.commit()

    def admit(self, policy, model, *, now=None):
        now = time.time() if now is None else now
        with self.lock:
            with self.db:
                self.db.execute("DELETE FROM requests WHERE at < ?", (now - 30 * 86400,))
                counts = self.db.execute("SELECT SUM(at >= ?), SUM(at >= ?) FROM requests", (now - 60, now - 86400)).fetchone()
                if (counts[0] or 0) >= policy.data["requests_per_minute"] or (counts[1] or 0) >= policy.data["requests_per_day"]:
                    raise PermissionError("owner-defined model request limit reached")
                request_id = uuid.uuid4().hex
                self.db.execute("INSERT INTO requests(id,at,route,model) VALUES(?,?,?,?)", (request_id, now, policy.provider, model))
                return request_id

    def finish(self, request_id, status, usage):
        def count(key, alternative):
            value = usage.get(key, usage.get(alternative)) if isinstance(usage, dict) else None
            return value if type(value) is int and 0 <= value < 10**12 else None
        with self.lock, self.db:
            self.db.execute("UPDATE requests SET status=?,input_tokens=?,output_tokens=? WHERE id=?",
                            (status, count("input_tokens", "prompt_tokens"), count("output_tokens", "completion_tokens"), request_id))

    def close(self):
        self.db.close()

    def snapshot(self, policy, *, now=None):
        now = time.time() if now is None else now
        with self.lock:
            row = self.db.execute("""SELECT COUNT(*),COALESCE(SUM(at>=?),0),COUNT(status),
                COALESCE(SUM(status>=200 AND status<300),0),COALESCE(SUM(status>=400),0),
                COALESCE(SUM(input_tokens IS NOT NULL AND output_tokens IS NOT NULL),0),
                SUM(input_tokens),SUM(output_tokens) FROM requests WHERE at>=?""", (now - 60, now - 86400)).fetchone()
        return {"snapshot_at": now, "scope": "broker", "window_seconds": 86400,
                "requests_day": row[0], "requests_minute": row[1],
                "requests_per_day": policy.data["requests_per_day"], "requests_per_minute": policy.data["requests_per_minute"],
                "finished_requests_day": row[2], "unfinished_requests_day": row[0] - row[2],
                "http_success_day": row[3], "http_error_day": row[4], "usage_reported_requests_day": row[5],
                "input_tokens_reported_day": row[6], "output_tokens_reported_day": row[7],
                "cost_available": False, "monetary_cost": None}


class Credentials:
    def __init__(self, policy, credentials):
        self.policy, self.credentials = policy, credentials
        self.lock = threading.Lock()
        self.cloud_data, self.cloud_cache = None, {}
        self.query = {}

    def headers(self):
        from .provider_cloud import CLOUD, cloud_headers, credential_data
        if self.policy.provider in CLOUD:
            with self.lock:
                self.cloud_data = credential_data(self.policy.provider, self.credentials.get("api_key"))
                headers, values = cloud_headers(self.policy, self.cloud_data, self.cloud_cache)
                self.query = dict(self.cloud_cache.get("query", {}))
            return headers, Redactor(values)
        if (self.policy.provider in oauth_providers() or
                (self.policy.provider in {"anthropic", "openrouter"} and not self.credentials.get("api_key"))):
            # The pinned upstream owns OAuth validation, locking and refresh. It
            # runs under the separate provider UID and its own private HOME.
            with self.lock:
                from hermes_cli.runtime_provider import resolve_runtime_provider
                resolved = resolve_runtime_provider(requested=self.policy.provider,
                                                     target_model=self.policy.data["default_model"])
                if (resolved["base_url"].rstrip("/") != self.policy.endpoint.rstrip("/")
                        or resolved["api_mode"] != self.policy.api_mode):
                    raise PermissionError("OAuth route changed; owner must approve its endpoint and transport")
                token = resolved["api_key"]
                headers = dict(resolved.get("extra_headers") or {})
                if self.policy.provider == "openai-codex":
                    from agent.codex_headers import codex_cloudflare_headers
                    headers.update(codex_cloudflare_headers(token))
        else:
            token = self.credentials.get("api_key")
            if self.policy.provider not in {"local", "lmstudio", "custom"} and not token:
                raise PermissionError("provider credentials are not configured")
            row = descriptor(self.policy.provider)
            headers = dict(row["headers"]) if row else {}
        if token:
            if not isinstance(token, str) or not 1 <= len(token) <= 16384 or any(ord(c) < 33 or ord(c) > 126 for c in token):
                raise PermissionError("invalid provider credential")
            if self.policy.api_mode == "anthropic_messages":
                # MiniMax/TokenPlan, Claude subscription tokens and API keys
                # deliberately use different authentication headers. Let the
                # pinned native client own that classification and its betas.
                from agent.anthropic_adapter import build_anthropic_client
                with build_anthropic_client(token, self.policy.endpoint) as client:
                    headers.update({key: value for key, value in client.default_headers.items()
                                    if isinstance(value, str)})
                    self.query = dict(client.default_query)
            else:
                headers["Authorization"] = "Bearer " + token
        return headers, Redactor([token] if token else [])


class Broker(ThreadingHTTPServer):
    daemon_threads = True
    block_on_close = True

    def __init__(self, address, policy, token, credentials, ledger, *, bind_and_activate=True):
        if not re.fullmatch(r"[A-Za-z0-9_-]{43,128}", token):
            raise ValueError("invalid scoped model capability")
        self.routes = policy if isinstance(policy, ProviderRoutes) else ProviderRoutes(policy.data)
        self.policy, self.token, self.ledger = self.routes.primary, token, ledger
        self.credentials = credentials
        self.workers = threading.BoundedSemaphore(16)
        self.turns = threading.BoundedSemaphore(2)
        super().__init__(address, Handler, bind_and_activate=bind_and_activate)

    def process_request(self, request, address):
        if not self.workers.acquire(blocking=False):
            self.shutdown_request(request)
            return
        try:
            super().process_request(request, address)
        except BaseException:
            self.workers.release()
            raise

    def process_request_thread(self, request, address):
        try:
            super().process_request_thread(request, address)
        finally:
            self.workers.release()

    def handle_error(self, request, address):
        # Base class tracebacks can contain a credential-bearing HTTP exception.
        print('{"event":"provider.connection-failed"}', flush=True)


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "HAOSModelBroker"
    sys_version = ""

    def log_message(self, *args):
        pass  # No paths, prompts, headers or provider bodies in system logs.

    def setup(self):
        super().setup()
        self.connection.settimeout(30)

    def reply(self, code, message):
        data = json.dumps({"error": {"message": message, "type": "haos_provider_error"}}).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Connection", "close")
        self.end_headers()
        self.wfile.write(data)
        self.close_connection = True

    def do_GET(self):
        if not self.authorized():
            self.reply(401, "model capability required")
            return
        try:
            route, path = self.server.routes.resolve(self.path)
            policy = self.server.routes.routes[route]
        except PermissionError:
            self.reply(403, "provider route is outside owner policy")
            return
        if path not in {"/v1/haos/usage", "/v1/models"}:
            self.reply(405, "only fixed model and aggregate usage routes are supported")
            return
        sizes = self.headers.get_all("Content-Length", [])
        if self.headers.get("Transfer-Encoding") or sizes not in ([], ["0"]):
            self.reply(400, "usage requests cannot carry a body")
            return
        try:
            if path == "/v1/models":
                data = json.dumps({"object": "list", "data": [
                    {"id": model, "object": "model", "owned_by": policy.provider}
                    for model in policy.models]}).encode()
            else:
                from .provider_usage import validate_snapshot
                data = json.dumps(validate_snapshot(self.server.ledger.snapshot(self.server.policy))).encode()
        except Exception:
            self.reply(503, "provider usage unavailable")
            return
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Connection", "close")
        self.end_headers()
        self.wfile.write(data)
        self.close_connection = True

    def authorized(self):
        supplied = self.headers.get_all("Authorization", [])
        native = self.headers.get_all("x-api-key", [])
        if len(supplied) + len(native) != 1:
            return False
        value, expected = (supplied[0], "Bearer " + self.server.token) if supplied else (native[0], self.server.token)
        return hmac.compare_digest(value.encode(), expected.encode())

    def do_POST(self):
        self.close_connection = True
        self.forward_started = False
        if not self.authorized():
            self.reply(401, "model capability required")
            return
        sizes = self.headers.get_all("Content-Length", [])
        if self.headers.get("Transfer-Encoding") or len(sizes) != 1 or not re.fullmatch(r"[0-9]{1,10}", sizes[0]) or not 1 <= int(sizes[0]) <= MAX_INPUT:
            self.reply(413, "bounded Content-Length required")
            return
        try:
            raw = self.rfile.read(int(sizes[0]))
            if len(raw) != int(sizes[0]):
                raise ValueError("incomplete model request")
            route, path = self.server.routes.resolve(self.path)
            self.policy = self.server.routes.routes[route]
            payload = self.policy.request(path, json.loads(raw))
        except (ValueError, TypeError, PermissionError, UnicodeError):
            self.reply(403, "request refused by owner model policy")
            return
        if not self.server.turns.acquire(blocking=False):
            self.reply(429, "concurrent model limit reached")
            return
        request_id, status, usage = None, 502, {}
        try:
            # Only explicitly owner-selected, same-protocol fallbacks may see
            # this prompt. No retry follows a started stream or ambiguous I/O.
            for target in [route, *self.server.routes.fallbacks.get(route, [])]:
                self.policy = self.server.routes.routes[target]
                attempt = dict(payload)
                if target != route:
                    attempt["model"] = self.policy.data["default_model"]
                attempt = self.policy.request(path, attempt)
                request_id = self.server.ledger.admit(self.policy, attempt["model"])
                credentials = self.server.credentials[target] if isinstance(self.server.credentials, dict) else self.server.credentials
                self.route_credentials = credentials
                headers, redactor = credentials.headers()
                redactor.secrets = (*redactor.secrets, self.server.token)
                status, usage = self.forward(attempt, headers, redactor, defer_errors=True)
                if status not in {429, 502, 503, 504} or self.forward_started:
                    break
                self.server.ledger.finish(request_id, status, usage)
                request_id = None
            if not getattr(self, "forward_started", False):
                self.reply(status, "provider rejected the request")
        except PermissionError:
            status = 429 if request_id is None else 503
            self.reply(status, "provider admission or credential setup requires owner attention")
        except Exception:
            # Network/OAuth/HTTP exceptions are never rendered or journaled with
            # headers. A broken stream stays incomplete rather than becoming a
            # successful model receipt. The controller handles that ambiguity.
            if not getattr(self, "forward_started", False):
                self.reply(502, "provider connection failed; no successful model receipt")
        finally:
            if request_id:
                self.server.ledger.finish(request_id, status, usage)
                print(json.dumps({"event": "provider.request-finished", "id": request_id, "status": status}), flush=True)
            self.server.turns.release()

    def forward(self, payload, headers, redactor, *, defer_errors=False):
        if self.policy.provider in {"gemini", "bedrock"}:
            from .provider_native import forward_native
            return forward_native(self, payload, headers, redactor)
        endpoint = urlsplit(self.policy.endpoint)
        conn = (http.client.HTTPSConnection(endpoint.hostname, endpoint.port or 443, timeout=180,
                                            context=ssl.create_default_context()) if endpoint.scheme == "https"
                else http.client.HTTPConnection(endpoint.hostname, endpoint.port, timeout=180))
        if self.policy.provider == "custom":
            addresses = socket.getaddrinfo(endpoint.hostname, endpoint.port or 443, type=socket.SOCK_STREAM)
            if not addresses or any(not ipaddress.ip_address(row[4][0]).is_global for row in addresses):
                raise PermissionError("custom API DNS resolves outside its public network scope")
            # Pin the checked address for this connection. HTTPSConnection
            # retains the original hostname for SNI/certificate verification;
            # a second DNS lookup must not rebind it to a private service.
            address = addresses[0][4][0]
            conn._create_connection = lambda pair, timeout, source_address=None: socket.create_connection(
                (address, endpoint.port or 443), timeout=timeout, source_address=source_address)
        try:
            body = json.dumps(payload, ensure_ascii=False).encode()
            route = {"codex_responses": "/responses", "chat_completions": "/chat/completions",
                     "anthropic_messages": "/messages"}[self.policy.api_mode]
            path = endpoint.path.rstrip("/")
            if self.policy.api_mode == "anthropic_messages" and not path.endswith("/v1"):
                path += "/v1"
            from urllib.parse import urlencode
            query = getattr(self.route_credentials, "query", {})
            if set(query) - {"api-version"} or any(not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9-]{1,40}", value) for value in query.values()):
                raise PermissionError("unsupported SDK query parameter")
            suffix = "?" + urlencode(query) if query else ""
            # Never forward caller URLs, Host/Authorization, cookies, user IDs,
            # arbitrary headers, redirects or SDK credential overrides.
            conn.request("POST", path + route + suffix, body=body,
                         headers={**headers, "Content-Type": "application/json", "Accept": "text/event-stream, application/json"})
            response = conn.getresponse()
            if not 200 <= response.status < 300:
                # Keep the real provider status (including 401/403/429/5xx), but
                # never expose its body or redirect location to the model/log.
                status = response.status if 400 <= response.status <= 599 else 502
                if not defer_errors:
                    self.reply(status, "provider rejected the request")
                return status, {}
            streaming = payload.get("stream") is True
            content_type = response.getheader("Content-Type", "").split(";", 1)[0].strip().lower()
            if content_type != ("text/event-stream" if streaming else "application/json") or response.getheader("Content-Encoding", "identity") != "identity":
                raise ValueError("unexpected provider response format")
            if not streaming:
                data = response.read(MAX_OUTPUT + 1)
                if len(data) > MAX_OUTPUT:
                    raise ValueError("model response exceeds owner broker bound")
                decoded = redactor.clean(json.loads(data))
                self.send_response(response.status)
                self.send_header("Content-Type", content_type)
                clean = json.dumps(decoded).encode()
                self.send_header("Content-Length", str(len(clean)))
                self.send_header("Connection", "close")
                self.end_headers()
                self.forward_started = True
                self.wfile.write(clean)
                return response.status, decoded.get("usage", {})
            self.send_response(response.status)
            self.send_header("Content-Type", content_type)
            self.send_header("Transfer-Encoding", "chunked")
            self.send_header("Connection", "close")
            self.end_headers()
            self.forward_started = True
            total, usage, deadline, terminal = 0, {}, time.monotonic() + 600, False
            while True:
                if time.monotonic() > deadline:
                    raise TimeoutError("model stream exceeded broker deadline")
                line = response.readline(MAX_LINE + 1)
                if not line:
                    break
                total += len(line)
                if len(line) > MAX_LINE or total > MAX_OUTPUT:
                    raise ValueError("model stream exceeded broker bounds")
                # SSE is framed by lines. Buffer complete lines so credentials
                # split across TCP chunks cannot bypass exact-value redaction.
                if line.startswith(b"data:") and line.strip() != b"data: [DONE]":
                    event = redactor.clean(json.loads(line[5:]))
                    if isinstance(event, dict):
                        kind = event.get("type")
                        if kind in {"response.failed", "response.incomplete", "error"}:
                            raise ConnectionError("provider did not complete the model turn")
                        terminal = terminal or kind in {"response.completed", "message_stop"}
                        candidate = event.get("response", event)
                        if kind == "message_start":
                            candidate = event.get("message", {})
                        if isinstance(candidate, dict) and isinstance(candidate.get("usage"), dict):
                            usage.update(candidate["usage"])
                    line = b"data: " + json.dumps(event, ensure_ascii=False).encode() + b"\n"
                else:
                    terminal = terminal or line.strip() == b"data: [DONE]"
                    line = redactor.text(line.decode()).encode()
                self.wfile.write(f"{len(line):x}\r\n".encode() + line + b"\r\n")
                self.wfile.flush()
            if not terminal:
                raise ConnectionError("provider stream ended without a terminal receipt")
            self.wfile.write(b"0\r\n\r\n")
            self.wfile.flush()
            return response.status, usage
        finally:
            conn.close()


def main():
    if os.geteuid() == 0:
        raise PermissionError("model broker requires its separate unprivileged UID")
    if os.environ.get("LISTEN_PID") != str(os.getpid()) or os.environ.get("LISTEN_FDS") != "1":
        raise PermissionError("model broker requires its root-bound activation socket")
    policy = ProviderRoutes(trusted_json(Path("/etc/haos/provider.json")))
    directory = Path(os.environ["CREDENTIALS_DIRECTORY"])
    token = json.loads(private_credential(directory / "provider-token"))["token"]
    secrets = json.loads(private_credential(directory / "provider-credentials"))
    if policy.data["version"] == 1:
        if set(secrets) != {"api_key"}:
            raise ValueError("invalid provider credential envelope")
        credentials = Credentials(policy.primary, secrets)
    else:
        if set(secrets) != {"routes"} or set(secrets["routes"]) != set(policy.routes):
            raise ValueError("provider credential routes disagree with owner policy")
        credentials = {key: Credentials(route, secrets["routes"][key]) for key, route in policy.routes.items()}
    ledger = UsageLedger("/var/lib/haos-provider/usage.db")
    server = Broker(("127.0.0.1", PORT), policy, token, credentials, ledger, bind_and_activate=False)
    server.socket.close()
    server.socket = socket.socket(fileno=3)
    if server.socket.getsockname() != ("127.0.0.1", PORT) or not server.socket.getsockopt(socket.SOL_SOCKET, socket.SO_ACCEPTCONN):
        raise PermissionError("unexpected model broker activation socket")
    server.serve_forever(poll_interval=0.5)


if __name__ == "__main__":
    main()
