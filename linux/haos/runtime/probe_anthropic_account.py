#!/usr/bin/env python3
"""Actual pinned Anthropic PKCE login, private pool and broker expiry refresh."""
import base64
import builtins
from contextlib import redirect_stdout
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import io
import json
import os
import pty
from pathlib import Path
import secrets
import sys
import tempfile
import termios
from types import SimpleNamespace
import urllib.request
from urllib.parse import parse_qs, urlsplit

from probe_http_provider_matrix import serving


def main():
    root = Path(sys.argv[1]).resolve()
    sys.path.insert(0, str(root))
    from agent import anthropic_credentials as native
    from agent.credential_pool import load_pool
    from hermes_cli import auth
    from hermes_cli.auth_commands import auth_logout_command
    from haos.provider_auth import anthropic_login
    from haos.provider_policy import ProviderPolicy
    from haos.provider_proxy import Credentials
    state, cases, failures = {}, [], []
    class Fixture(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass
        def do_POST(self):
            try:
                assert self.path == "/v1/oauth/token"
                assert self.headers["User-Agent"] == "axios/1.7.9"
                value = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                assert value["client_id"] == native._OAUTH_CLIENT_ID
                state["requests"] += 1
                refreshing = value["grant_type"] == "refresh_token"
                if refreshing:
                    assert value["refresh_token"] == state["refresh"]
                    state["refreshes"] += 1
                else:
                    assert value["grant_type"] == "authorization_code" and value["code"] == state["code"]
                    assert value["state"] == state["state"] and value["redirect_uri"] == native._OAUTH_REDIRECT_URI
                    challenge = base64.urlsafe_b64encode(hashlib.sha256(value["code_verifier"].encode()).digest()).rstrip(b"=").decode()
                    assert challenge == state["challenge"]
                    state["verifier"] = value["code_verifier"]
                payload = {"access_token": state["next_access"] if refreshing else state["access"],
                    "refresh_token": state["next_refresh"] if refreshing else state["refresh"],
                    "expires_in": 7200 if refreshing else -1}
                if state["case"] == "missing-token":
                    payload.pop("access_token")
                status = 400 if state["case"] == "denied" else 200
                if status == 400:
                    payload = {"error": "invalid_grant", "error_description": "fixture denial"}
                body = b"invalid JSON" if state["case"] == "non-json" else json.dumps(payload).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body) + (20 if state["case"] == "short-body" else 0)))
                self.send_header("Connection", "close")
                self.end_headers()
                self.wfile.write(body)
                self.close_connection = True
            except BaseException as error:
                failures.append(type(error).__name__)
                raise
    old_open, old_input = urllib.request.urlopen, builtins.input
    with serving(ThreadingHTTPServer(("127.0.0.1", 0), Fixture)) as port, tempfile.TemporaryDirectory() as parent:
        def open_local(request, **kwargs):
            assert request.full_url in native._OAUTH_TOKEN_URLS
            local = urllib.request.Request(f"http://127.0.0.1:{port}/v1/oauth/token", data=request.data,
                headers=dict(request.header_items()), method=request.get_method())
            return old_open(local, **kwargs)
        urllib.request.urlopen = open_local
        try:
            for case in ("success", "bad-state", "empty-code", "denied", "missing-token", "non-json", "short-body"):
                home = Path(parent) / case
                home.mkdir(mode=0o700)
                os.environ["HOME"], os.environ["HERMES_HOME"] = str(home), str(home / "hermes")
                state.update(case=case, access="sk-ant-oat01-" + secrets.token_urlsafe(40),
                    next_access="sk-ant-oat01-" + secrets.token_urlsafe(40), refresh=secrets.token_urlsafe(40),
                    next_refresh=secrets.token_urlsafe(40), code=secrets.token_urlsafe(40), verifier="", requests=0, refreshes=0)
                output = io.StringIO()
                def code_input(_):
                    assert not termios.tcgetattr(sys.stdin.fileno())[3] & (termios.ECHO | termios.ECHONL)
                    urls = [line.strip() for line in output.getvalue().splitlines() if line.strip().startswith("https://claude.ai/")]
                    assert len(urls) == 1
                    parsed = urlsplit(urls[0])
                    assert parsed.netloc == "claude.ai" and parsed.path == "/oauth/authorize"
                    query = parse_qs(parsed.query)
                    assert query["client_id"] == [native._OAUTH_CLIENT_ID]
                    assert query["code_challenge_method"] == ["S256"]
                    state["state"], state["challenge"] = query["state"][0], query["code_challenge"][0]
                    return "" if case == "empty-code" else state["code"] + "#" + ("wrong" if case == "bad-state" else state["state"])
                builtins.input = code_input
                succeeded = False
                master, slave = pty.openpty()
                previous_input = sys.stdin
                protected_input = os.fdopen(os.dup(slave))
                sys.stdin = protected_input
                terminal_before = termios.tcgetattr(slave)
                try:
                    with redirect_stdout(output):
                        anthropic_login()
                    succeeded = True
                except SystemExit:
                    assert case != "success"
                finally:
                    assert termios.tcgetattr(slave) == terminal_before, "terminal echo state was not restored"
                    sys.stdin = previous_input
                    protected_input.close()
                    os.close(master)
                    os.close(slave)
                assert succeeded == (case == "success")
                if succeeded:
                    policy = ProviderPolicy({"version": 1, "provider": "anthropic", "endpoint": "https://api.anthropic.com",
                        "models": ["claude-fixture"], "default_model": "claude-fixture", "api_mode": "anthropic_messages",
                        "requests_per_day": 200, "requests_per_minute": 30})
                    headers, redactor = Credentials(policy, {"api_key": None}).headers()
                    assert headers["Authorization"] == "Bearer " + state["next_access"]
                    assert state["next_access"] not in redactor.text(state["next_access"])
                    assert state["next_refresh"] not in json.dumps(headers)
                    assert state["refreshes"] == 1
                    entries = load_pool("anthropic").entries()
                    assert len(entries) == 1 and entries[0].refresh_token == state["next_refresh"]
                    assert auth.get_auth_status("anthropic")["logged_in"]
                    with redirect_stdout(output):
                        auth_logout_command(SimpleNamespace(provider="anthropic"))
                    assert not load_pool("anthropic").entries()
                else:
                    assert not load_pool("anthropic").entries()
                    assert state["requests"] == 0 if case in {"bad-state", "empty-code"} else state["requests"] >= 1
                assert all(not state[name] or state[name] not in output.getvalue() for name in
                    ("access", "next_access", "refresh", "next_refresh", "code", "verifier"))
                assert all(p.stat().st_mode & 0o077 == 0 for p in home.rglob("*.json"))
                cases.append(case)
        finally:
            urllib.request.urlopen, builtins.input = old_open, old_input
    assert not failures, failures
    receipt = {"actual_native_anthropic_account_cases": cases, "case_count": len(cases),
        "actual_pkce_state_private_pool_expiry_refresh_broker_status_logout": True,
        "live_account_tested": False, "source_files": [{"path": str(p.relative_to(root)),
        "sha256": hashlib.sha256(p.read_bytes()).hexdigest()} for p in (Path(__file__).resolve(), root / "haos/provider_proxy.py")]}
    Path(sys.argv[2]).write_text(json.dumps(receipt, indent=2) + "\n")
    print(json.dumps({"case_count": len(cases), "live_account_tested": False}))


if __name__ == "__main__":
    main()
