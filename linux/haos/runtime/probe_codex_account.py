#!/usr/bin/env python3
"""Pinned Codex device authorization, rotating refresh and private broker fixtures."""
from contextlib import redirect_stdout
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import io
import json
import os
from pathlib import Path
import secrets
import sys
import tempfile
import time
from types import SimpleNamespace
from urllib.parse import parse_qs

from probe_http_provider_matrix import serving


def main():
    root = Path(sys.argv[1]).resolve()
    sys.path.insert(0, str(root))
    import httpx
    import jwt
    import anthropic
    import openai
    from hermes_cli import auth, auth_codex
    from hermes_cli.auth_commands import auth_logout_command
    from haos.provider_policy import ProviderPolicy
    from haos.provider_proxy import Credentials
    state, failures, cases = {}, [], []
    signing_key = secrets.token_urlsafe(40)
    class Fixture(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass
        def reply(self, status, payload):
            body = json.dumps(payload).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        def do_POST(self):
            try:
                raw = self.rfile.read(int(self.headers["Content-Length"]))
                data = json.loads(raw) if self.headers["Content-Type"].startswith("application/json") else parse_qs(raw.decode())
                state["requests"] += 1
                if self.path == "/api/accounts/deviceauth/usercode":
                    assert data == {"client_id": auth_codex.CODEX_OAUTH_CLIENT_ID}
                    if state["case"] == "device-rate-limit":
                        self.reply(429, {"error": "rate_limit"})
                    else:
                        self.reply(200, {} if state["case"] == "invalid-device" else
                            {"user_code": "ABCD-EFGH", "device_auth_id": state["device"], "interval": 3})
                elif self.path == "/api/accounts/deviceauth/token":
                    assert data == {"device_auth_id": state["device"], "user_code": "ABCD-EFGH"}
                    state["polls"] += 1
                    if state["case"] == "pending" and state["polls"] == 1:
                        self.reply(403, {"error": "pending"})
                    elif state["case"] == "denied":
                        self.reply(401, {"error": "denied"})
                    else:
                        self.reply(200, {} if state["case"] == "missing-code" else
                            {"authorization_code": state["code"], "code_verifier": state["verifier"]})
                else:
                    assert self.path == "/oauth/token" and data["client_id"] == [auth_codex.CODEX_OAUTH_CLIENT_ID]
                    if data["grant_type"] == ["authorization_code"]:
                        assert data["code"] == [state["code"]] and data["code_verifier"] == [state["verifier"]]
                        assert data["redirect_uri"] == ["https://auth.openai.com/deviceauth/callback"]
                        self.reply(200, {} if state["case"] == "missing-token" else
                            {"access_token": state["access"], "refresh_token": state["refresh"]})
                    else:
                        assert data["grant_type"] == ["refresh_token"] and data["refresh_token"] == [state["refresh"]]
                        state["refreshes"] += 1
                        if state["case"] == "refresh-denied":
                            self.reply(400, {"error": "invalid_grant"})
                        elif state["case"] == "refresh-rate-limit":
                            self.reply(429, {"error": "rate_limit"})
                        else:
                            self.reply(200, {"access_token": state["next_access"], "refresh_token": state["next_refresh"]})
            except BaseException as error:
                failures.append(type(error).__name__)
                raise
    original_client, old_time = httpx.Client, auth_codex.time
    waits = []
    auth_codex.time = SimpleNamespace(time=time.time, monotonic=time.monotonic, sleep=lambda delay: waits.append(delay))
    with serving(ThreadingHTTPServer(("127.0.0.1", 0), Fixture)) as port, tempfile.TemporaryDirectory() as parent:
        class Loopback(httpx.BaseTransport):
            def __init__(self):
                self.transport = httpx.HTTPTransport(trust_env=False)
            def handle_request(self, request):
                assert request.url.scheme == "https" and request.url.host == "auth.openai.com"
                rewritten = httpx.Request(request.method, f"http://127.0.0.1:{port}" + request.url.raw_path.decode(),
                    headers=request.headers, content=request.read())
                return self.transport.handle_request(rewritten)
            def close(self):
                self.transport.close()
        def client(**kwargs):
            return original_client(**{**kwargs, "transport": Loopback(), "trust_env": False})
        httpx.Client = client
        try:
            for case in ("success", "pending", "invalid-device", "device-rate-limit", "denied", "missing-code", "missing-token", "refresh-denied", "refresh-rate-limit"):
                home = Path(parent) / case
                home.mkdir(mode=0o700)
                os.environ["HOME"], os.environ["HERMES_HOME"] = str(home), str(home / "hermes")
                def token(nonce):
                    return jwt.encode({"exp": int(time.time()) + 7200, "nonce": nonce}, signing_key, algorithm="HS256")
                state.update(case=case, access=token(case), next_access=token(case + "-refreshed"),
                    refresh=secrets.token_urlsafe(40), next_refresh=secrets.token_urlsafe(40),
                    device=secrets.token_urlsafe(40), code=secrets.token_urlsafe(40), verifier=secrets.token_urlsafe(40),
                    requests=0, polls=0, refreshes=0)
                succeeded, output = False, io.StringIO()
                try:
                    with redirect_stdout(output):
                        value = auth_codex._codex_device_code_login()
                        auth_codex._save_codex_tokens(value["tokens"], last_refresh=value["last_refresh"])
                        updated = auth_codex.refresh_codex_oauth_pure(state["access"], state["refresh"])
                        assert updated["refresh_token"] == state["next_refresh"]
                        auth_codex._save_codex_tokens(updated)
                        policy = ProviderPolicy({"version": 1, "provider": "openai-codex", "endpoint": "https://chatgpt.com/backend-api/codex",
                            "models": ["fixture-model"], "default_model": "fixture-model", "api_mode": "codex_responses",
                            "requests_per_day": 200, "requests_per_minute": 30})
                        headers, redactor = Credentials(policy, {"api_key": None}).headers()
                        assert headers["Authorization"] == "Bearer " + state["next_access"]
                        assert state["next_access"] not in redactor.text(state["next_access"])
                        assert state["next_refresh"] not in json.dumps(headers), "refresh grant escaped into model HTTP headers"
                        assert auth.get_auth_status("openai-codex")["logged_in"]
                        succeeded = True
                except auth.AuthError:
                    assert case not in {"success", "pending"}
                assert succeeded == (case in {"success", "pending"})
                assert state["refreshes"] == (1 if case in {"success", "pending", "refresh-denied", "refresh-rate-limit"} else 0)
                assert all(state[name] not in output.getvalue() for name in ("access", "next_access", "refresh", "next_refresh", "device", "code", "verifier"))
                assert all(p.stat().st_mode & 0o077 == 0 for p in home.rglob("*.json"))
                if succeeded:
                    stored = auth.get_provider_auth_state("openai-codex")["tokens"]
                    assert stored["refresh_token"] == state["next_refresh"]
                    with redirect_stdout(output):
                        auth_logout_command(SimpleNamespace(provider="openai-codex"))
                    assert not auth.get_auth_status("openai-codex")["logged_in"]
                cases.append(case)
        finally:
            httpx.Client, auth_codex.time = original_client, old_time
    assert not failures, failures
    receipt = {"actual_codex_account_cases": cases, "case_count": len(cases), "actual_device_pkce_refresh_rotation": True,
        "native_private_storage_status_broker_logout": True, "live_account_tested": False,
        "source_files": [{"path": str(p.relative_to(root)), "sha256": hashlib.sha256(p.read_bytes()).hexdigest()}
            for p in (Path(__file__).resolve(), root / "haos/provider_proxy.py")]}
    Path(sys.argv[2]).write_text(json.dumps(receipt, indent=2) + "\n")
    print(json.dumps({"case_count": len(cases), "live_account_tested": False}))


if __name__ == "__main__":
    main()
