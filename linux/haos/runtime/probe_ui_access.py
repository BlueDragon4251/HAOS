#!/usr/bin/env python3
"""Actual pinned providerless HTTP/WS access mediation in private fixture state."""
import argparse
import asyncio
import json
import os
from pathlib import Path
import re
import secrets
import signal
import subprocess
import tempfile
import time
import urllib.error
import urllib.request

from probe_backend import session


def http(base, path, token):
    headers = {"X-Hermes-Session-Token": token} if token else {}
    request = urllib.request.Request(base + path, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=10) as reply:
            return reply.status, reply.read(4 * 1024 * 1024)
    except urllib.error.HTTPError as error:
        return error.code, error.read(4096)


async def observer_socket(base, token, method):
    from websockets.asyncio.client import connect
    from websockets.exceptions import ConnectionClosed
    async with connect(base.replace("http:", "ws:") + "/api/ws?token=" + token,
                       open_timeout=10, max_size=4 * 1024 * 1024, proxy=None) as socket:
        await socket.send(json.dumps({"jsonrpc": "2.0", "id": "haos-observer", "method": method, "params": {}}))
        try:
            async with asyncio.timeout(30):
                async for text in socket:
                    for line in text.splitlines():
                        value = json.loads(line)
                        if value.get("id") == "haos-observer":
                            return value
        except ConnectionClosed as error:
            return {"closed": error.rcvd.code if error.rcvd else None}
    return {"closed": None}


def probe(python, haos_source, upstream_source):
    with tempfile.TemporaryDirectory(prefix="haos-real-ui-access-") as directory:
        root = Path(directory)
        workspace = root / "workspace"
        workspace.mkdir()
        backend, observer = secrets.token_urlsafe(48), secrets.token_urlsafe(48)
        credential = root / "fixture-credentials.json"
        credential.write_text(json.dumps({"backend": backend, "observer": observer}))
        credential.chmod(0o600)
        env = {"HOME": str(root), "HERMES_HOME": str(root / ".hermes"), "PATH": str(python.parent) + ":/usr/bin:/bin",
               "LANG": "C.UTF-8", "PYTHONUNBUFFERED": "1", "PYTHONDONTWRITEBYTECODE": "1",
               "PYTHONPATH": os.pathsep.join([str(haos_source), str(upstream_source)])}
        code = ("import json,sys; from pathlib import Path; from haos.serve import run; "
                "c=json.loads(Path(sys.argv[1]).read_text()); "
                "run(c['backend'],c['observer'],port=0,isolated=True)")
        with (root / "backend.log").open("w") as log:
            process = subprocess.Popen([str(python), "-c", code, str(credential)], cwd=workspace, env=env,
                                       stdout=log, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                                       start_new_session=True)
            try:
                deadline = time.monotonic() + 120
                while time.monotonic() < deadline:
                    if process.poll() is not None:
                        raise RuntimeError("actual mediated Hermes exited before readiness")
                    ready = re.search(r"HERMES_(?:BACKEND|DASHBOARD)_READY port=(\d+)",
                                      (root / "backend.log").read_text(errors="replace"))
                    if ready:
                        break
                    time.sleep(.2)
                else:
                    raise TimeoutError("actual mediated Hermes readiness deadline")
                base = "http://127.0.0.1:" + ready[1]
                assert http(base, "/api/health", None)[0] == 200
                for invalid in (None, secrets.token_urlsafe(48)):
                    assert http(base, "/api/host/identity", invalid)[0] == 401
                status, data = http(base, "/api/host/identity", observer)
                identity = json.loads(data)
                assert status == 200 and identity["pid"] == process.pid and not identity["servesSpa"]
                for path in ("/api/config", "/api/env", "/api/providers/oauth/openai-codex/start", "/api/pty"):
                    status, body = http(base, path, observer)
                    assert status == 403 and backend.encode() not in body and observer.encode() not in body
                ping = asyncio.run(observer_socket(base, observer, "gateway.ping"))
                assert ping.get("result", {}).get("ok") is True
                listing = asyncio.run(observer_socket(base, observer, "session.list"))
                assert "result" in listing and "error" not in listing
                for method in ("prompt.submit", "session.create", "model.save_key", "config.get"):
                    assert asyncio.run(observer_socket(base, observer, method)) == {"closed": 4403}
                proof = asyncio.run(session(base, backend, workspace))
                assert process.poll() is None
                journal = (root / "backend.log").read_text(errors="replace")
                assert backend not in journal and observer not in journal, "dashboard credential entered the process log"
                return {"actual_pinned_backend": True, "observer_identity_matches_child": True,
                        "observer_read_rpc_works": True, "observer_config_credentials_terminal_denied": True,
                        "observer_direct_turn_and_session_mutations_denied": True,
                        "wrong_or_missing_identity_denied": True, "controller_session_creation_preserved": True,
                        "dashboard_credentials_absent_from_process_log": True,
                        **proof, "real_model_turn": False, "installed_owner_ui_acceptance": False}
            except BaseException:
                # Startup diagnostics belong to disposable fixture state only;
                # redact both capabilities before printing a bounded tail.
                tail = (root / "backend.log").read_text(errors="replace")[-16000:]
                print(tail.replace(backend, "[REDACTED]").replace(observer, "[REDACTED]"), flush=True)
                raise
            finally:
                if process.poll() is None:
                    os.killpg(process.pid, signal.SIGTERM)
                    try:
                        process.wait(timeout=10)
                    except subprocess.TimeoutExpired:
                        os.killpg(process.pid, signal.SIGKILL)
                        process.wait(timeout=10)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("python", type=Path)
    parser.add_argument("haos_source", type=Path)
    parser.add_argument("upstream_source", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    # Resolving a venv interpreter symlink would silently run base Python.
    result = probe(args.python.absolute(), args.haos_source.resolve(), args.upstream_source.resolve())
    args.output.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result))
