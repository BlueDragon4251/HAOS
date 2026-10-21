#!/usr/bin/env python3
"""Actual pinned Nous/xAI/MiniMax login/refresh over loopback; no real accounts."""
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
import time
from types import SimpleNamespace
from urllib.parse import parse_qs

from probe_http_provider_matrix import serving


def main():
    root = Path(sys.argv[1]).resolve()
    sys.path.insert(0, str(root))
    import httpx
    import jwt
    # Load SDK subclasses before replacing only the native auth HTTP client
    # factory; their real class inheritance must remain unchanged.
    import anthropic
    import openai
    from hermes_cli import auth, auth_nous, auth_xai, auth_minimax, auth_device_flow
    from hermes_cli.auth_commands import auth_logout_command
    from hermes_cli.auth_error_copy import SignInCopyError
    from haos.provider_policy import ProviderPolicy
    from haos.provider_proxy import Credentials
    from haos.provider_auth import minimax_login, minimax_status
    from haos.provider_registry import default_mode
    from agent.credential_pool import load_pool
    state, calls, failures, checks = {}, [], [], []
    signing_key = secrets.token_urlsafe(40)
    def token(nonce):
        return jwt.encode({"exp": int(time.time()) + 7200, "scope": "inference:invoke", "nonce": nonce}, signing_key, algorithm="HS256")
    class Fixture(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass
        def reply(self, status, value):
            body = json.dumps(value).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        def do_GET(self):
            assert state["provider"] == "xai-oauth" and self.path == "/.well-known/openid-configuration"
            calls.append((state["id"], "discovery"))
            self.reply(200, {"authorization_endpoint": "https://auth.x.ai/oauth2/authorize", "token_endpoint": "https://auth.x.ai/oauth2/token"})
        def do_POST(self):
            try:
                form = parse_qs(self.rfile.read(int(self.headers["Content-Length"])).decode())
                provider, case = state["provider"], state["case"]
                is_minimax = provider == "minimax-oauth"
                client_id = auth_xai.XAI_OAUTH_CLIENT_ID if provider == "xai-oauth" else auth.PROVIDER_REGISTRY[provider].client_id
                scope = auth_xai.XAI_OAUTH_SCOPE if provider == "xai-oauth" else auth.PROVIDER_REGISTRY[provider].scope
                if self.path.endswith(("/device/code", "/oauth/code")):
                    calls.append((state["id"], "authorize"))
                    assert form["client_id"] == [client_id]
                    assert form.get("scope") == [scope]
                    value = {"user_code": "ABCD-EFGH", "verification_uri": state["portal"] + "/authorize",
                        "verification_uri_complete": state["portal"] + "/authorize?user_code=ABCD-EFGH",
                        "device_code": state["device"], "expires_in": 600, "expired_in": 600, "interval": 1}
                    if is_minimax:
                        assert form["code_challenge_method"] == ["S256"]
                        state["challenge"] = form["code_challenge"][0]
                        value["state"] = form["state"][0] if case != "bad-state" else "mismatch"
                    if case == "invalid-device":
                        value.pop("user_code")
                    self.reply(200, value)
                    return
                assert self.path.endswith("/token")
                grant = form["grant_type"][0]
                calls.append((state["id"], grant))
                assert form["client_id"] == [client_id]
                refreshing = grant == "refresh_token"
                if refreshing:
                    if provider == "nous":
                        assert self.headers["x-nous-refresh-token"] == state["refresh"] and "refresh_token" not in form
                    else:
                        assert form["refresh_token"] == [state["refresh"]]
                elif is_minimax:
                    assert grant == auth_minimax.MINIMAX_OAUTH_GRANT_TYPE and form["user_code"] == ["ABCD-EFGH"]
                    challenge = base64.urlsafe_b64encode(hashlib.sha256(form["code_verifier"][0].encode()).digest()).rstrip(b"=").decode()
                    assert challenge == state["challenge"]
                else:
                    assert grant == "urn:ietf:params:oauth:grant-type:device_code" and form["device_code"] == [state["device"]]
                state["polls"] += 1
                if case == "pending" and state["polls"] == 1 and not refreshing:
                    self.reply(200 if is_minimax else 400, {"status": "pending"} if is_minimax else {"error": "authorization_pending"})
                elif case == "denied":
                    self.reply(200 if is_minimax else 400, {"status": "error"} if is_minimax else {"error": "access_denied"})
                else:
                    value = {"access_token": state["second"] if refreshing else state["first"],
                        "refresh_token": state["refresh"], "expires_in": 7200, "expired_in": 7200,
                        "scope": "inference:invoke", "token_type": "Bearer", "status": "success",
                        "inference_base_url": state["endpoint"]}
                    if case == "missing-token":
                        value.pop("access_token")
                    self.reply(200, value)
            except BaseException as error:
                failures.append(type(error).__name__)
                raise
    original_client, original_get = httpx.Client, httpx.get
    old_device_time, old_minimax_time = auth_device_flow.time, auth_minimax.time
    waits = []
    clock = SimpleNamespace(monotonic=time.monotonic, time=time.time, sleep=lambda seconds: waits.append(seconds))
    auth_device_flow.time, auth_minimax.time = clock, clock
    with serving(ThreadingHTTPServer(("127.0.0.1", 0), Fixture)) as port, tempfile.TemporaryDirectory() as parent:
        class Loopback(httpx.BaseTransport):
            def __init__(self):
                self.transport = httpx.HTTPTransport(trust_env=False)
            def handle_request(self, request):
                assert request.url.scheme == "https" and request.url.host == state["host"]
                rewritten = httpx.Request(request.method, f"http://127.0.0.1:{port}" + request.url.raw_path.decode(),
                    headers=request.headers, content=request.read())
                return self.transport.handle_request(rewritten)
            def close(self):
                self.transport.close()
        def client(**kwargs):
            assert kwargs.get("verify", True) is not False
            return original_client(**{**kwargs, "transport": Loopback(), "trust_env": False})
        def get(url, **kwargs):
            with client() as connection:
                return connection.get(url, **kwargs)
        httpx.Client, httpx.get = client, get
        try:
            for provider, region, host, portal, endpoint in (
                ("nous", "global", "portal.nousresearch.com", "https://portal.nousresearch.com", "https://inference-api.nousresearch.com/v1"),
                ("xai-oauth", "global", "auth.x.ai", "https://auth.x.ai", "https://api.x.ai/v1"),
                ("minimax-oauth", "global", "api.minimax.io", "https://api.minimax.io", "https://api.minimax.io/anthropic"),
                ("minimax-oauth", "cn", "api.minimaxi.com", "https://api.minimaxi.com", "https://api.minimaxi.com/anthropic")):
                for case in ("success", "pending", "denied", "invalid-device", "missing-token", *(["bad-state"] if provider == "minimax-oauth" else [])):
                    identifier = provider + ":" + region + ":" + case
                    print(identifier, flush=True)
                    home = Path(parent) / identifier.replace(":", "-")
                    home.mkdir(mode=0o700)
                    os.environ["HOME"], os.environ["HERMES_HOME"] = str(home), str(home / "hermes")
                    state.update(id=identifier, provider=provider, region=region, case=case, host=host, portal=portal, endpoint=endpoint,
                        device=secrets.token_urlsafe(40), refresh=secrets.token_urlsafe(40), first=token(identifier + "first"), second=token(identifier + "second"), polls=0)
                    output, succeeded = io.StringIO(), False
                    try:
                        with redirect_stdout(output):
                            if provider == "nous":
                                value = auth_nous._nous_device_code_login(open_browser=False)
                                auth_nous.persist_nous_credentials(value)
                                updated = auth_nous.refresh_nous_oauth_from_state(value, force_refresh=True)
                                auth_nous.persist_nous_credentials(updated)
                            elif provider == "xai-oauth":
                                value = auth_xai._xai_oauth_device_code_login(open_browser=False)
                                auth_xai._save_xai_oauth_tokens(value["tokens"], discovery=value["discovery"])
                                auth_xai.resolve_xai_oauth_runtime_credentials(force_refresh=True)
                            else:
                                minimax_login(region)
                                entries = load_pool(provider).entries()
                                assert len(entries) == 1, "fresh login duplicated the single-use refresh grant"
                                assert entries[0].base_url == endpoint
                                value = auth.get_provider_auth_state(provider)
                                value["expires_at"] = "1970-01-01T00:00:00+00:00"
                                auth._save_active_provider_state(provider, value)
                                before = len(calls)
                                saved = {p: p.read_bytes() for p in home.rglob("*.json")}
                                assert minimax_status(region) == {"configured": True, "region": region, "refresh_pending": True}
                                assert len(calls) == before and all(p.read_bytes() == data for p, data in saved.items())
                            succeeded = True
                            policy = ProviderPolicy({"version": 1, "provider": provider, "endpoint": endpoint,
                                "models": ["fixture-model"], "default_model": "fixture-model", "api_mode": default_mode(provider),
                                "requests_per_day": 200, "requests_per_minute": 30})
                            if provider == "minimax-oauth":
                                wrong = ProviderPolicy({**policy.data, "endpoint": "https://api.minimax.io/anthropic" if region == "cn" else "https://api.minimaxi.com/anthropic"})
                                before = len(calls)
                                try:
                                    Credentials(wrong, {"api_key": None}).headers()
                                except PermissionError:
                                    pass
                                else:
                                    raise AssertionError("expired regional grant refreshed before endpoint admission")
                                assert len(calls) == before
                            headers, redactor = Credentials(policy, {"api_key": None}).headers()
                            assert headers["Authorization"] == "Bearer " + state["second"]
                            assert state["second"] not in redactor.text(state["second"])
                            assert auth.get_auth_status(provider)["logged_in"]
                            if provider == "minimax-oauth":
                                wrong = ProviderPolicy({**policy.data, "endpoint": "https://api.minimax.io/anthropic" if region == "cn" else "https://api.minimaxi.com/anthropic"})
                                before = len(calls)
                                try:
                                    Credentials(wrong, {"api_key": None}).headers()
                                except PermissionError:
                                    pass
                                else:
                                    raise AssertionError("regional account escaped its approved endpoint")
                                assert len(calls) == before
                            auth_logout_command(SimpleNamespace(provider=provider))
                            assert not auth.get_auth_status(provider)["logged_in"]
                    except (auth.AuthError, SignInCopyError, ValueError, KeyError):
                        assert case not in {"success", "pending"}, "native success flow failed"
                    assert succeeded == (case in {"success", "pending"})
                    if not succeeded:
                        assert not load_pool(provider).entries(), "failed login published a credential"
                    assert state["polls"] == 0 if case in {"invalid-device", "bad-state"} else state["polls"] >= 1
                    assert not any(state[name] in output.getvalue() for name in ("device", "refresh", "first", "second"))
                    for path in home.rglob("*.json"):
                        assert path.stat().st_mode & 0o077 == 0
                    checks.append(identifier)
        finally:
            httpx.Client, httpx.get = original_client, original_get
            auth_device_flow.time, auth_minimax.time = old_device_time, old_minimax_time
    assert not failures, failures
    assert len(checks) == 22
    receipt = {"actual_pinned_native_account_cases": checks, "case_count": len(checks), "http_requests": len(calls),
        "native_device_pkce_login_refresh_private_storage_status_logout": True,
        "native_minimax_global_and_china_regions": True, "broker_uses_refreshed_native_credentials": True,
        "minimax_status_read_only_and_expired_grant_region_checked_before_refresh": True,
        "invalid_pending_denied_missing_token_and_csrf_checked": True, "private_tokens_not_rendered": True,
        "live_account_tested": False, "python": sys.version.split()[0], "source_files": [
            {"path": str(path.relative_to(root)), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
            for path in (Path(__file__).resolve(), root / "haos/provider_proxy.py", root / "haos/provider_auth.py")]}
    Path(sys.argv[2]).write_text(json.dumps(receipt, indent=2) + "\n")
    print(json.dumps({"case_count": len(checks), "live_account_tested": False}))


if __name__ == "__main__":
    main()
