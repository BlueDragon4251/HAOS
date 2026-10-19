#!/usr/bin/env python3
"""Fresh Qwen device/PKCE HTTP, private native storage/refresh; no live account."""
import base64
from contextlib import contextmanager, redirect_stdout
import hashlib
import http.client
import io
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import secrets
import sys
import tempfile
import threading
import time
from types import SimpleNamespace
from urllib.parse import parse_qs


@contextmanager
def serving(server):
    thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True)
    thread.start()
    try:
        yield server.server_port
    finally:
        server.shutdown()
        server.server_close()
        thread.join(5)


def main():
    root = Path(sys.argv[1]).resolve()
    sys.path.insert(0, str(root))
    from haos import provider_qwen as qwen
    from hermes_cli import auth_qwen
    from hermes_cli.auth import get_auth_status
    from hermes_cli.auth_commands import auth_add_command, auth_logout_command
    from agent.credential_pool import load_pool
    from hermes_cli.auth_constants import QWEN_OAUTH_CLIENT_ID
    device, access, refresh = (secrets.token_urlsafe(40) for _ in range(3))
    state, checks, requests, failures = {}, [], [], []
    class Fixture(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass
        def do_POST(self):
            try:
                form = parse_qs(self.rfile.read(int(self.headers["Content-Length"])).decode())
                assert form["client_id"] == [QWEN_OAUTH_CLIENT_ID]
                requests.append(self.path)
                case, status = state["case"], 200
                if self.path == qwen.DEVICE_PATH:
                    import uuid
                    assert str(uuid.UUID(self.headers["x-request-id"])) == self.headers["x-request-id"]
                    assert form["scope"] == [qwen.SCOPE] and form["code_challenge_method"] == ["S256"]
                    state["challenge"] = form["code_challenge"][0]
                    state["polls"] = 0
                    value = {"device_code": device, "user_code": "ABCD-EFGH", "expires_in": 600,
                        "verification_uri_complete": "https://chat.qwen.ai/authorize?user_code=ABCD-EFGH"}
                    if case == "redirect":
                        value["verification_uri_complete"] = "https://attacker.invalid/authorize?user_code=ABCD-EFGH"
                    elif case == "http-redirect":
                        status = 302
                    elif case == "short-expiry":
                        value["expires_in"] = 1
                elif self.path == qwen.TOKEN_PATH:
                    assert form["grant_type"] == [qwen.GRANT] and form["device_code"] == [device]
                    verifier = form["code_verifier"][0]
                    assert 43 <= len(verifier) <= 128 and verifier != state["challenge"]
                    assert base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode() == state["challenge"]
                    state["polls"] += 1
                    value = {"access_token": access, "refresh_token": refresh, "expires_in": 3600,
                        "token_type": "Bearer", "resource_url": "portal.qwen.ai"}
                    if case == "cancel":
                        status, value = 400, {"error": "authorization_pending"}
                    elif case == "pending-slow" and state["polls"] <= 2:
                        status = 400 if state["polls"] == 1 else 429
                        value = {"error": "authorization_pending" if state["polls"] == 1 else "slow_down"}
                    elif case in {"access_denied", "expired_token", "unknown-error"}:
                        status, value = 400, {"error": case, "error_description": access}
                    elif case == "invalid-resource":
                        value["resource_url"] = "https://attacker.invalid"
                    elif case == "missing-refresh":
                        value.pop("refresh_token")
                    elif case == "bad-expiry":
                        value["expires_in"] = True
                    elif case == "oversized":
                        value["padding"] = "x" * qwen.MAX_BODY
                else:
                    raise AssertionError("unapproved Qwen fixture endpoint")
                body = json.dumps(value).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body) + (16 if case == "truncated-http" and self.path == qwen.TOKEN_PATH else 0)))
                if case == "http-redirect":
                    self.send_header("Location", "https://attacker.invalid")
                self.send_header("Connection", "close")
                self.end_headers()
                self.wfile.write(body)
                self.close_connection = True
            except BaseException as error:
                failures.append(type(error).__name__)
                raise
    original_https, original_time = http.client.HTTPSConnection, qwen.time
    clock, waits = [0], []
    def pause(seconds):
        if state.get("case") == "cancel":
            raise KeyboardInterrupt
        waits.append(seconds)
        clock[0] += seconds
    qwen.time = SimpleNamespace(monotonic=lambda: clock[0], time=time.time, sleep=pause)
    with tempfile.TemporaryDirectory() as home, serving(ThreadingHTTPServer(("127.0.0.1", 0), Fixture)) as port:
        os.environ["HOME"] = home
        os.environ["HERMES_HOME"] = str(Path(home) / ".hermes")
        def loopback(host, port_number=443, **kwargs):
            assert host == qwen.HOST and port_number == 443
            return http.client.HTTPConnection("127.0.0.1", port, timeout=kwargs["timeout"])
        http.client.HTTPSConnection = loopback
        try:
            for case in ("success", "pending-slow", "cancel", "redirect", "http-redirect", "truncated-http", "short-expiry", "access_denied", "expired_token",
                    "unknown-error", "invalid-resource", "missing-refresh", "bad-expiry", "oversized"):
                state["case"] = case
                clock[0], waits[:] = 0, []
                shown = []
                path = Path(home) / ".qwen/oauth_creds.json"
                before = path.read_bytes() if path.exists() else None
                try:
                    data = qwen.device_login(notify=shown.append)
                except KeyboardInterrupt:
                    assert case == "cancel" and path.read_bytes() == before
                except qwen.QwenLoginError as error:
                    assert case not in {"success", "pending-slow"}
                    assert access not in str(error) and device not in str(error) and refresh not in str(error)
                    assert (path.read_bytes() if path.exists() else None) == before
                else:
                    assert case in {"success", "pending-slow"}
                    auth_qwen._save_qwen_cli_tokens(data)
                    output = io.StringIO()
                    with redirect_stdout(output):
                        auth_add_command(SimpleNamespace(provider="qwen-oauth", auth_type="oauth", no_browser=True, timeout=600))
                    assert not any(secret in output.getvalue() for secret in (device, access, refresh))
                    assert get_auth_status("qwen-oauth")["logged_in"]
                    assert any(entry.access_token == access for entry in load_pool("qwen-oauth").entries())
                    resolved = auth_qwen.resolve_qwen_runtime_credentials()
                    assert resolved["api_key"] == access and resolved["base_url"] == "https://portal.qwen.ai/v1"
                    assert path.stat().st_mode & 0o777 == 0o600
                    if case == "pending-slow":
                        assert waits == [2, 2, 7] and state["polls"] == 3
                assert not any(secret in " ".join(shown) for secret in (device, access, refresh))
                checks.append(case)
            path.unlink()
            output = io.StringIO()
            with redirect_stdout(output):
                auth_logout_command(SimpleNamespace(provider="qwen-oauth"))
            assert not get_auth_status("qwen-oauth")["logged_in"]
            assert not any(secret in output.getvalue() for secret in (device, access, refresh))
        finally:
            http.client.HTTPSConnection, qwen.time = original_https, original_time
    assert not failures, failures
    receipt = {"actual_local_device_pkce_http_cases": checks, "http_requests": len(requests),
        "pinned_hermes_private_storage_and_resolver": True, "pending_slowdown_denial_expiry_cancellation": True,
        "untrusted_uri_and_resource_refused": True, "secrets_absent_from_owner_output_and_errors": True,
        "failed_login_preserves_existing_credentials": True, "live_account_tested": False,
        "actual_pinned_auth_add_status_logout_pool_lifecycle": True,
        "official_protocol_reference": "QwenLM/qwen-code@c08007668ce01d9282ea702e95ddbc1f5adf57c9:packages/core/src/qwen/qwenOAuth2.ts",
        "python": sys.version.split()[0], "source_files": [{"path": str(path.relative_to(root)),
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest()} for path in
            (root / "haos/provider_qwen.py", root / "haos/provider_auth.py", Path(__file__).resolve())]}
    Path(sys.argv[2]).write_text(json.dumps(receipt, indent=2) + "\n")
    print(json.dumps(receipt))


if __name__ == "__main__":
    main()
