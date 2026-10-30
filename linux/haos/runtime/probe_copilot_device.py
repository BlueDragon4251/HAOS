#!/usr/bin/env python3
"""Actual pinned Copilot device flow, safe opener and private persistence fixtures."""
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
import urllib.request
from urllib.parse import parse_qs, urlsplit

from probe_http_provider_matrix import serving


def main():
    root = Path(sys.argv[1]).resolve()
    sys.path.insert(0, str(root))
    from hermes_cli import copilot_auth
    from hermes_cli.config import save_env_value, get_env_value_prefer_dotenv
    from haos.provider_auth import copilot_login
    from haos.provider_copilot import bind_transport
    state, cases, failures = {}, [], []
    class Fixture(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass
        def do_POST(self):
            try:
                fields = parse_qs(self.rfile.read(int(self.headers["Content-Length"])).decode())
                assert fields["client_id"] == [copilot_auth.COPILOT_OAUTH_CLIENT_ID]
                if self.path == "/login/device/code":
                    assert fields["scope"] == ["read:user"]
                    value = {"verification_uri": "https://github.com/login/device", "user_code": "ABCD-EFGH",
                        "device_code": state["device"], "interval": 1}
                    if state["case"] == "invalid-device":
                        value.pop("device_code")
                else:
                    assert self.path == "/login/oauth/access_token"
                    assert fields["device_code"] == [state["device"]]
                    assert fields["grant_type"] == ["urn:ietf:params:oauth:grant-type:device_code"]
                    state["polls"] += 1
                    case = state["case"]
                    if case in {"pending", "slow-down"} and state["polls"] == 1:
                        value = {"error": "authorization_pending" if case == "pending" else "slow_down"}
                    elif case in {"denied", "expired"}:
                        value = {"error": "access_denied" if case == "denied" else "expired_token"}
                    else:
                        value = {"access_token": "ghp_" + state["token"] if case == "invalid-token" else state["token"]}
                body = json.dumps(value).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            except BaseException as error:
                failures.append(type(error).__name__)
                raise
    old_urllib, old_time = copilot_auth.urllib, copilot_auth.time
    old_env = {key: os.environ.get(key) for key in copilot_auth.COPILOT_ENV_VARS}
    waits = []
    copilot_auth.time = SimpleNamespace(monotonic=time.monotonic, time=time.time, sleep=lambda delay: waits.append(delay))
    bind_transport()
    original_open = urllib.request.urlopen
    with serving(ThreadingHTTPServer(("127.0.0.1", 0), Fixture)) as port, tempfile.TemporaryDirectory() as parent:
        def open_local(request, **kwargs):
            parsed = urlsplit(request.full_url)
            assert parsed.scheme == "https" and parsed.netloc == "github.com"
            local = urllib.request.Request(f"http://127.0.0.1:{port}" + parsed.path, data=request.data,
                headers=dict(request.header_items()), method=request.get_method())
            return original_open(local, **kwargs)
        copilot_auth.urllib.request.urlopen = open_local
        try:
            for case in ("success", "pending", "slow-down", "denied", "expired", "invalid-device", "invalid-token"):
                home = Path(parent) / case
                home.mkdir(mode=0o700)
                os.environ["HOME"], os.environ["HERMES_HOME"] = str(home), str(home / "hermes")
                for key in copilot_auth.COPILOT_ENV_VARS:
                    os.environ.pop(key, None)
                prior = "ghu_" + secrets.token_urlsafe(40)
                save_env_value("COPILOT_GITHUB_TOKEN", prior)
                state.update(case=case, token="ghu_" + secrets.token_urlsafe(40), device=secrets.token_urlsafe(40), polls=0)
                before = len(waits)
                succeeded, output = False, io.StringIO()
                try:
                    with redirect_stdout(output):
                        copilot_login()
                    succeeded = True
                except PermissionError:
                    assert case not in {"success", "pending", "slow-down"}
                assert succeeded == (case in {"success", "pending", "slow-down"})
                expected = state["token"] if succeeded else prior
                assert get_env_value_prefer_dotenv("COPILOT_GITHUB_TOKEN") == expected
                assert state["token"] not in output.getvalue() and state["device"] not in output.getvalue()
                if case == "slow-down":
                    assert waits[before:] == [4, 9], "native RFC 8628 polling delay was lost"
                assert state["polls"] == (0 if case == "invalid-device" else 2 if case in {"pending", "slow-down"} else 1)
                assert (home / "hermes/.env").stat().st_mode & 0o077 == 0
                cases.append(case)
        finally:
            copilot_auth.urllib, copilot_auth.time = old_urllib, old_time
            for key, value in old_env.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value
    assert not failures, failures
    receipt = {"actual_pinned_device_cases": cases, "case_count": len(cases), "native_pending_slowdown_and_denial": True,
        "invalid_login_preserves_existing_account": True, "private_tokens_not_printed": True, "live_account_tested": False,
        "source_files": [{"path": str(p.relative_to(root)), "sha256": hashlib.sha256(p.read_bytes()).hexdigest()}
            for p in (Path(__file__).resolve(), root / "haos/provider_auth.py", root / "haos/provider_copilot.py")]}
    Path(sys.argv[2]).write_text(json.dumps(receipt, indent=2) + "\n")
    print(json.dumps({"case_count": len(cases), "live_account_tested": False}))


if __name__ == "__main__":
    main()
