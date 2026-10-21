#!/usr/bin/env python3
"""Actual upstream OAuth refresh/exchange over loopback, no real accounts."""
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import hashlib
import os
from pathlib import Path
import secrets
import sys
import tempfile
import threading
import time

from probe_account_model_http import exercise


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
    sys.path.insert(0, sys.argv[1])
    from haos.provider_auth import qwen_import
    from haos.provider_proxy import Credentials
    from haos.provider_policy import ProviderPolicy, ENDPOINTS
    from haos.provider_registry import default_mode
    from urllib.parse import parse_qs
    received = []
    model_checks = []
    raw = "ghu_" + secrets.token_urlsafe(40)
    first, second = secrets.token_urlsafe(40), secrets.token_urlsafe(40)
    refresh, refreshed = secrets.token_urlsafe(40), secrets.token_urlsafe(40)
    count = 0
    class Fixture(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass
        def send_json(self, body):
            body = json.dumps(body).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        def do_GET(self):
            nonlocal count
            received.append((self.path, dict(self.headers), None))
            count += 1
            self.send_json({"token": first if count == 1 else second,
                "expires_at": time.time() + (1 if count == 1 else 3600), "endpoints": {"api": "https://api.business.githubcopilot.com"}})
        def do_POST(self):
            body = self.rfile.read(int(self.headers["Content-Length"]))
            received.append((self.path, dict(self.headers), parse_qs(body.decode())))
            self.send_json({"access_token": refreshed, "refresh_token": refresh,
                            "expires_in": 3600, "resource_url": "portal.qwen.ai", "token_type": "Bearer"})
    with tempfile.TemporaryDirectory(prefix="haos-accounts-probe-") as directory:
        os.environ["HOME"] = directory
        os.environ["HERMES_HOME"] = str(Path(directory) / "hermes")
        Path(os.environ["HERMES_HOME"]).mkdir()
        with serving(ThreadingHTTPServer(("127.0.0.1", 0), Fixture)) as port:
            from hermes_cli import copilot_auth, auth_qwen
            old_exchange, old_refresh = copilot_auth._TOKEN_EXCHANGE_URL, auth_qwen.QWEN_OAUTH_TOKEN_URL
            copilot_auth._TOKEN_EXCHANGE_URL = f"http://127.0.0.1:{port}/copilot-exchange"
            auth_qwen.QWEN_OAUTH_TOKEN_URL = f"http://127.0.0.1:{port}/qwen-refresh"
            try:
                def policy(provider, model):
                    return ProviderPolicy({"version": 1, "provider": provider, "endpoint": ENDPOINTS[provider],
                        "models": [model], "default_model": model, "api_mode": default_mode(provider, model),
                        "requests_per_day": 200, "requests_per_minute": 30})
                copilot = Credentials(policy("copilot", "gpt-6-sol"), {"api_key": raw})
                headers, redactor = copilot.headers()
                assert headers["Authorization"] == "Bearer " + first and copilot.effective_endpoint == "https://api.business.githubcopilot.com"
                assert raw not in redactor.text(raw) and first not in redactor.text(first)
                headers, _ = copilot.headers()
                assert headers["Authorization"] == "Bearer " + second and count == 2, "expiring exchanged token must refresh"
                headers, _ = copilot.headers()
                assert headers["Authorization"] == "Bearer " + second and count == 2, "valid exchanged token must be cached"
                assert received[0][1]["Authorization"] == "token " + raw
                data = qwen_import(json.dumps({"access_token": first, "refresh_token": refresh,
                    "expiry_date": int((time.time() - 3600) * 1000), "resource_url": "portal.qwen.ai"}))
                auth_qwen._save_qwen_cli_tokens(data)
                qwen = Credentials(policy("qwen-oauth", "qwen-fixture"), {"api_key": None})
                headers, redactor = qwen.headers()
                assert headers["Authorization"] == "Bearer " + refreshed
                assert refreshed not in redactor.text(refreshed)
                stored = Path(directory) / ".qwen/oauth_creds.json"
                assert stored.stat().st_mode & 0o777 == 0o600
                assert json.loads(stored.read_text())["access_token"] == refreshed
                assert received[-1][2]["refresh_token"] == [refresh]
                assert received[-1][2]["grant_type"] == ["refresh_token"]
                import httpx
                approved_copilot = ProviderPolicy({**copilot.policy.data, "endpoint": "https://api.business.githubcopilot.com"})
                model_checks.extend("copilot:" + case for case in exercise(approved_copilot,
                    Credentials(approved_copilot, {"api_key": raw}), second, httpx.Client))
                model_checks.extend("qwen-oauth:" + case for case in exercise(qwen.policy, qwen, refreshed, httpx.Client))
                for model in ("gpt-6-sol", "gpt-5.4", "gpt-5-mini", "claude-sonnet-5"):
                    assert default_mode("copilot", model) == copilot_auth_mode(model)
            finally:
                copilot_auth._TOKEN_EXCHANGE_URL, auth_qwen.QWEN_OAUTH_TOKEN_URL = old_exchange, old_refresh
    assert len(model_checks) == 10
    receipt = {"model_fixture_source_sha256": {
        p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in (Path(__file__),
        Path(__file__).with_name("probe_account_model_http.py"),
        Path(__file__).with_name("probe_http_provider_matrix.py"))},"actual_refreshed_account_broker_sdk_model_cases": model_checks, "model_case_count": len(model_checks),"actual_upstream_copilot_exchange_refresh_cache": True, "actual_upstream_qwen_refresh_private_persistence": True,
               "actual_loopback_http": True, "live_provider_tested": False}
    Path(sys.argv[2]).write_text(json.dumps(receipt, indent=2) + "\n")
    print(json.dumps(receipt))


def copilot_auth_mode(model):
    from hermes_cli.models import copilot_model_api_mode
    return copilot_model_api_mode(model, catalog=[])


if __name__ == "__main__":
    main()
