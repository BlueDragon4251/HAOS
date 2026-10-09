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

from .provider_policy import PORT, ProviderPolicy
from .redaction import Redactor
from .sandbox import trusted_json

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


class Credentials:
    def __init__(self, policy, credentials):
        self.policy, self.credentials = policy, credentials
        self.lock = threading.Lock()

    def headers(self):
        if self.policy.provider == "openai-codex":
            # The pinned upstream owns OAuth validation, locking and refresh. It
            # runs under the separate provider UID and its own private HOME.
            with self.lock:
                from hermes_cli.auth_codex import resolve_codex_runtime_credentials
                from agent.codex_headers import codex_cloudflare_headers
                token = resolve_codex_runtime_credentials()["api_key"]
                headers = codex_cloudflare_headers(token)
        else:
            token = self.credentials.get("api_key")
            if self.policy.provider != "local" and not token:
                raise PermissionError("provider credentials are not configured")
            headers = {}
        if token:
            if not isinstance(token, str) or not 1 <= len(token) <= 16384 or any(ord(c) < 33 or ord(c) > 126 for c in token):
                raise PermissionError("invalid provider credential")
            headers["Authorization"] = "Bearer " + token
        return headers, Redactor([token] if token else [])


class Broker(ThreadingHTTPServer):
    daemon_threads = True
    block_on_close = True

    def __init__(self, address, policy, token, credentials, ledger, *, bind_and_activate=True):
        if not re.fullmatch(r"[A-Za-z0-9_-]{43,128}", token):
            raise ValueError("invalid scoped model capability")
        self.policy, self.token, self.credentials, self.ledger = policy, token, credentials, ledger
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
        self.reply(405, "only authorized model POST requests are supported")

    def do_POST(self):
        self.close_connection = True
        supplied = self.headers.get_all("Authorization", [])
        if len(supplied) != 1 or not hmac.compare_digest(supplied[0].encode(), ("Bearer " + self.server.token).encode()):
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
            payload = self.server.policy.request(self.path, json.loads(raw))
        except (ValueError, TypeError, PermissionError, UnicodeError):
            self.reply(403, "request refused by owner model policy")
            return
        if not self.server.turns.acquire(blocking=False):
            self.reply(429, "concurrent model limit reached")
            return
        request_id, status, usage = None, 502, {}
        try:
            request_id = self.server.ledger.admit(self.server.policy, payload["model"])
            headers, redactor = self.server.credentials.headers()
            redactor.secrets = (*redactor.secrets, self.server.token)
            status, usage = self.forward(payload, headers, redactor)
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

    def forward(self, payload, headers, redactor):
        endpoint = urlsplit(self.server.policy.endpoint)
        conn = (http.client.HTTPSConnection(endpoint.hostname, endpoint.port or 443, timeout=180,
                                            context=ssl.create_default_context()) if endpoint.scheme == "https"
                else http.client.HTTPConnection(endpoint.hostname, endpoint.port, timeout=180))
        try:
            body = json.dumps(payload, ensure_ascii=False).encode()
            route = "/responses" if self.server.policy.api_mode == "codex_responses" else "/chat/completions"
            # Never forward caller URLs, Host/Authorization, cookies, user IDs,
            # arbitrary headers, redirects or SDK credential overrides.
            conn.request("POST", endpoint.path + route, body=body,
                         headers={**headers, "Content-Type": "application/json", "Accept": "text/event-stream, application/json"})
            response = conn.getresponse()
            if not 200 <= response.status < 300:
                # Keep the real provider status (including 401/403/429/5xx), but
                # never expose its body or redirect location to the model/log.
                self.reply(response.status if 400 <= response.status <= 599 else 502, "provider rejected the request")
                return response.status, {}
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
                        terminal = terminal or event.get("type") in {"response.completed", "response.failed", "response.incomplete"}
                        candidate = event.get("response", event)
                        if isinstance(candidate, dict) and isinstance(candidate.get("usage"), dict):
                            usage = candidate["usage"]
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


def private_credential(path):
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_uid not in {0, os.geteuid()} or info.st_mode & 0o077 or info.st_size > 32768:
            raise PermissionError("untrusted provider service credential")
        with os.fdopen(fd) as stream:
            fd = -1
            return stream.read()
    finally:
        if fd >= 0:
            os.close(fd)


def main():
    if os.geteuid() == 0:
        raise PermissionError("model broker requires its separate unprivileged UID")
    if os.environ.get("LISTEN_PID") != str(os.getpid()) or os.environ.get("LISTEN_FDS") != "1":
        raise PermissionError("model broker requires its root-bound activation socket")
    policy = ProviderPolicy(trusted_json(Path("/etc/haos/provider.json")))
    directory = Path(os.environ["CREDENTIALS_DIRECTORY"])
    token = json.loads(private_credential(directory / "provider-token"))["token"]
    secrets = json.loads(private_credential(directory / "provider-credentials"))
    if set(secrets) != {"api_key"}:
        raise ValueError("invalid provider credential envelope")
    ledger = UsageLedger("/var/lib/haos-provider/usage.db")
    server = Broker(("127.0.0.1", PORT), policy, token, Credentials(policy, secrets), ledger, bind_and_activate=False)
    server.socket.close()
    server.socket = socket.socket(fileno=3)
    if server.socket.getsockname() != ("127.0.0.1", PORT) or not server.socket.getsockopt(socket.SOL_SOCKET, socket.SO_ACCEPTCONN):
        raise PermissionError("unexpected model broker activation socket")
    server.serve_forever(poll_interval=0.5)


if __name__ == "__main__":
    main()
