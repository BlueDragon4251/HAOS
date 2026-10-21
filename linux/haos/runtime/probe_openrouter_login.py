#!/usr/bin/env python3
"""Actual pinned headless PKCE exchange and native pool; no real account."""
import base64
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
from urllib.parse import parse_qs, urlsplit

from probe_http_provider_matrix import serving
from probe_account_model_http import exercise


def main():
    model_checks = []
    root = Path(sys.argv[1]).resolve()
    sys.path.insert(0, str(root))
    import httpx
    import anthropic
    import openai
    from hermes_cli import auth, secret_prompt
    from agent.credential_pool import load_pool, PooledCredential
    from haos.provider_auth import openrouter_login, openrouter_status, openrouter_logout
    from haos.provider_policy import ProviderPolicy
    from haos.provider_proxy import Credentials
    state, failures, cases = {}, [], []
    class Fixture(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass
        def do_POST(self):
            try:
                assert self.path == "/api/v1/auth/keys"
                data = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                assert set(data) == {"code", "code_verifier", "code_challenge_method"}
                assert data["code"] == state["code"] and data["code_challenge_method"] == "S256"
                challenge = base64.urlsafe_b64encode(hashlib.sha256(data["code_verifier"].encode()).digest()).rstrip(b"=").decode()
                assert challenge == state["challenge"]
                state["verifier"] = data["code_verifier"]
                state["requests"] += 1
                status = {"denied": 403, "rate-limit": 429}.get(state["case"], 200)
                payload = {} if state["case"] == "missing-key" else {"key": state["key"]}
                if state["case"] == "invalid-key":
                    payload = {"key": "invalid\nheader"}
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
    original_post, original_prompt = httpx.post, secret_prompt.masked_secret_prompt
    with serving(ThreadingHTTPServer(("127.0.0.1", 0), Fixture)) as port, tempfile.TemporaryDirectory() as parent:
        def post(url, **kwargs):
            assert url == "https://openrouter.ai/api/v1/auth/keys"
            return original_post(f"http://127.0.0.1:{port}/api/v1/auth/keys", trust_env=False, **kwargs)
        httpx.post = post
        try:
            for case in ("success", "denied", "rate-limit", "missing-key", "invalid-key", "non-json", "empty-code", "cancel", "short-body"):
                home = Path(parent) / case
                home.mkdir(mode=0o700)
                os.environ["HOME"], os.environ["HERMES_HOME"] = str(home), str(home / "hermes")
                state.update(case=case, key=secrets.token_urlsafe(40), code=secrets.token_urlsafe(40), verifier="", requests=0)
                old_key = secrets.token_urlsafe(40)
                if case != "success":
                    load_pool("openrouter").add_entry(PooledCredential(provider="openrouter", id="prior",
                        label="existing-owner-account", auth_type="api_key", priority=0,
                        source="manual:openrouter_pkce", access_token=old_key,
                        base_url="https://openrouter.ai/api/v1"))
                output = io.StringIO()
                def prompt(_):
                    urls = [line.strip() for line in output.getvalue().splitlines() if line.strip().startswith("https://")]
                    assert len(urls) == 1
                    parsed = urlsplit(urls[0])
                    assert parsed.scheme == "https" and parsed.netloc == "openrouter.ai" and parsed.path == "/auth"
                    query = parse_qs(parsed.query)
                    assert set(query) == {"code_challenge", "code_challenge_method", "key_label"}
                    assert query["code_challenge_method"] == ["S256"]
                    state["challenge"] = query["code_challenge"][0]
                    if case == "cancel":
                        raise KeyboardInterrupt
                    return "" if case == "empty-code" else state["code"]
                secret_prompt.masked_secret_prompt = prompt
                succeeded = False
                try:
                    with redirect_stdout(output):
                        openrouter_login()
                    succeeded = True
                except (auth.AuthError, KeyboardInterrupt, ValueError):
                    assert case != "success"
                assert succeeded == (case == "success")
                assert state["requests"] == (0 if case in {"empty-code", "cancel"} else 1)
                assert all(not state[name] or state[name] not in output.getvalue() for name in ("key", "code", "verifier"))
                entries = load_pool("openrouter").entries()
                if succeeded:
                    assert len(entries) == 1 and entries[0].access_token == state["key"]
                    assert entries[0].refresh_token is None and entries[0].auth_type == "api_key"
                    assert openrouter_status()
                    policy = ProviderPolicy({"version": 1, "provider": "openrouter", "endpoint": "https://openrouter.ai/api/v1",
                        "models": ["fixture-model"], "default_model": "fixture-model", "api_mode": "chat_completions",
                        "requests_per_day": 200, "requests_per_minute": 30})
                    headers, redactor = Credentials(policy, {"api_key": None}).headers()
                    assert headers["Authorization"] == "Bearer " + state["key"]
                    assert state["key"] not in redactor.text(state["key"])
                    import httpx
                    model_checks.extend(exercise(policy, Credentials(policy, {"api_key": None}), state["key"], httpx.Client))
                    with redirect_stdout(output):
                        openrouter_logout()
                    assert not load_pool("openrouter").entries()
                    assert not openrouter_status()
                else:
                    assert len(entries) == 1 and entries[0].id == "prior" and entries[0].access_token == old_key
                    assert openrouter_status(), "failed login damaged the previous owner account"
                assert all(path.stat().st_mode & 0o077 == 0 for path in home.rglob("*.json"))
                cases.append(case)
        finally:
            httpx.post, secret_prompt.masked_secret_prompt = original_post, original_prompt
    assert not failures, failures
    assert len(model_checks) == 5
    receipt = {"model_fixture_source_sha256": {
        p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in (Path(__file__),
        Path(__file__).with_name("probe_account_model_http.py"),
        Path(__file__).with_name("probe_http_provider_matrix.py"))},"actual_authorized_account_broker_sdk_model_cases": model_checks, "model_case_count": len(model_checks),"actual_native_pkce_cases": cases, "case_count": len(cases),
        "native_private_pool_status_broker_logout": True, "authorization_code_and_tokens_not_printed": True,
        "failed_login_preserves_existing_account": True,
        "live_account_tested": False, "source_files": [{"path": str(p.relative_to(root)),
        "sha256": hashlib.sha256(p.read_bytes()).hexdigest()} for p in (Path(__file__).resolve(), root / "haos/provider_auth.py")]}
    Path(sys.argv[2]).write_text(json.dumps(receipt, indent=2) + "\n")
    print(json.dumps({"case_count": len(cases), "live_account_tested": False}))


if __name__ == "__main__":
    main()
