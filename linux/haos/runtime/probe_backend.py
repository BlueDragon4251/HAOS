#!/usr/bin/env python3
"""Start the real pinned Hermes in disposable state and verify its authenticated API."""

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


def request(base, token=None):
    headers = {"Authorization": "Bearer " + token} if token else {}
    call = urllib.request.Request(base + "/api/host/identity", headers=headers)
    with urllib.request.urlopen(call, timeout=10) as response:
        return json.load(response)


async def session(base, token, workspace):
    from websockets.asyncio.client import connect
    async with connect(base.replace("http:", "ws:") + "/api/ws?token=" + token,
                       open_timeout=10, max_size=4 * 1024 * 1024, proxy=None) as socket:
        await socket.send(json.dumps({"jsonrpc": "2.0", "id": "haos-runtime-probe",
            "method": "session.create", "params": {"source": "herald_os", "cwd": str(workspace),
            "title": "Disposable HAOS API probe", "close_on_disconnect": True}}))
        async with asyncio.timeout(30):
            async for text in socket:
                for line in text.splitlines():
                    reply = json.loads(line)
                    if reply.get("id") == "haos-runtime-probe":
                        if "error" in reply:
                            raise RuntimeError("real Hermes rejected session.create: " + str(reply["error"].get("code")))
                        result = reply["result"]
                        assert result.get("session_id") and result.get("stored_session_id"), result
                        return {"runtime_session_created": True, "durable_session_created": True}
        raise RuntimeError("real Hermes disconnected without a session receipt")


def probe(executable: Path):
    with tempfile.TemporaryDirectory(prefix="haos-real-backend-") as directory:
        root = Path(directory)
        workspace = root / "workspace"
        workspace.mkdir()
        token = secrets.token_urlsafe(48)
        env = {"HOME": str(root), "HERMES_HOME": str(root / ".hermes"),
               "PATH": str(executable.parent) + ":/usr/bin:/bin", "LANG": "C.UTF-8",
               "PYTHONUNBUFFERED": "1", "PYTHONDONTWRITEBYTECODE": "1",
               "HERMES_DASHBOARD_SESSION_TOKEN": token}
        log = root / "backend.log"
        with log.open("w") as output:
            process = subprocess.Popen([str(executable), "serve", "--isolated", "--host", "127.0.0.1",
                "--port", "0", "--no-open"], env=env, cwd=workspace, stdout=output, stderr=subprocess.STDOUT,
                start_new_session=True, stdin=subprocess.DEVNULL)
            try:
                deadline = time.monotonic() + 120
                while time.monotonic() < deadline:
                    if process.poll() is not None:
                        raise RuntimeError("Hermes exited before readiness: " + str(process.returncode))
                    ready = re.search(r"HERMES_(?:BACKEND|DASHBOARD)_READY port=(\d+)", log.read_text(errors="replace"))
                    if ready:
                        break
                    time.sleep(0.2)
                else:
                    raise TimeoutError("actual Hermes backend did not become ready")
                base = "http://127.0.0.1:" + ready[1]
                with urllib.request.urlopen(base + "/api/health", timeout=10) as response:
                    health = json.load(response)
                assert health.get("ok") is True
                for invalid in (None, secrets.token_urlsafe(48)):
                    try:
                        request(base, invalid)
                    except urllib.error.HTTPError as error:
                        assert error.code in {401, 403}, error.code
                    else:
                        raise AssertionError("unauthenticated backend identity accepted")
                identity = request(base, token)
                assert identity.get("ok") is True and identity.get("pid") == process.pid
                assert identity.get("servesSpa") is False
                proof = asyncio.run(session(base, token, workspace))
                assert process.poll() is None, "API probe must not attach to an unrelated process"
                return {"backend_healthy": True, "backend_version": health.get("version"),
                        "unauthenticated_identity_denied": True, "wrong_token_denied": True,
                        "authenticated_identity_matches_child": True, **proof,
                        "limitations": ["providerless API probe; no model turn", "no installed systemd/sandbox proof"]}
            except BaseException:
                print(log.read_text(errors="replace")[-48000:].replace(token, "[REDACTED]"), flush=True)
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
    parser.add_argument("executable", type=Path)
    parser.add_argument("evidence", type=Path)
    args = parser.parse_args()
    proof = probe(args.executable.resolve(strict=True))
    args.evidence.write_text(json.dumps(proof, indent=2) + "\n")
    print(json.dumps(proof), flush=True)
