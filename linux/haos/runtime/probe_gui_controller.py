"""Disposable providerless controller fixture for actual native/socket GUI tests.

Session IDs are explicit test fixtures, never claimed as actual Hermes/model turns.
No host accounts, installed service paths, disks or external APIs are modified.
"""
import asyncio
import json
import os
import signal
import stat
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from haos.controller import Controller
from haos.store import MissionStore


async def main():
    if os.environ.get("HAOS_DISPOSABLE_SCREEN_TEST") != "1" or os.geteuid() == 0:
        raise PermissionError("explicit non-root disposable fixture required")
    root = Path(sys.argv[1])
    info = root.lstat()
    if (root.parent != Path("/tmp") or not root.name.startswith("haos-gui-integration-")
            or root.is_symlink() or not stat.S_ISDIR(info.st_mode) or info.st_uid != os.geteuid() or info.st_mode & 0o077):
        raise PermissionError("private disposable fixture directory required")
    store = MissionStore(root / "missions.db")
    controller = Controller(store, "ws://127.0.0.1:9119", {os.geteuid()})
    controller.agent_uid = os.geteuid()
    actor, request_key = f"uid:{os.geteuid()}", "explicit-offline-gui-fixture"
    row = store.lookup(actor, request_key)
    if row:
        store.recover()  # interrupted dispatch blocks; no fabricated turn/result
        row = store.get(row["id"])
    else:
        row = store.create(actor, request_key, "Providerless native/socket GUI fixture")
        store.claim()
        store.session(row["id"], "offline-runtime-fixture", "offline-stored-fixture")
        store.dispatching(row["id"])
        controller.current = row["id"]
        row = store.get(row["id"])
    async def agent(reader, writer):
        await controller.client(reader, writer, gui=True)
    servers = []
    for filename, callback in (("control.sock", controller.client), ("gui.sock", agent)):
        path = root / filename
        if path.exists():
            metadata = path.lstat()
            if not stat.S_ISSOCK(metadata.st_mode) or metadata.st_uid != os.geteuid():
                raise PermissionError("foreign fixture socket")
            path.unlink()
        servers.append(await asyncio.start_unix_server(callback, path=path, limit=131072))
        path.chmod(0o600)
    stopped = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stopped.set)
    print(json.dumps({"ready": True, "mission": row["id"], "state": row["state"], "fixture_session": "offline-runtime-fixture", "real_model_turn": False}), flush=True)
    try:
        await stopped.wait()
    finally:
        for server in servers:
            server.close()
            await server.wait_closed()
        store.close()


if __name__ == "__main__":
    asyncio.run(main())
