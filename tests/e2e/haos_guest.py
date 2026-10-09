#!/usr/bin/env python3
"""Acceptance probe injected only into an explicitly marked, disposable QEMU guest."""

import grp
import hashlib
import json
import os
import pwd
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

sys.path.insert(0, "/usr/lib/haos")
from haos.sandbox import command, trusted_json

ROOT = Path("/var/lib/haos-acceptance")
A = "42514251-0000-4000-8000-000000000001"
B = "42514251-0000-4000-8000-000000000002"


def run(*args, **kwargs):
    return subprocess.run(args, check=True, text=True, **kwargs)


def wait_for(fn, seconds=180):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        try:
            result = fn()
            if result:
                return result
        except (OSError, ValueError, subprocess.CalledProcessError):
            pass
        time.sleep(2)
    raise TimeoutError("acceptance condition was not met")


def health():
    with urllib.request.urlopen("http://127.0.0.1:9119/api/health", timeout=5) as response:
        return json.load(response).get("ok") is True


def active(unit):
    return subprocess.run(["systemctl", "is-active", "--quiet", unit]).returncode == 0


def sandbox_probe(mode):
    grants = trusted_json(Path("/run/haos-policy/sandbox.json"))["grants"]
    credential = ROOT / "probe-credential"
    credential.write_text("acceptance-unused-token")
    fd = os.open(credential, os.O_RDONLY)
    # The root test drops to the service UID before Bubblewrap; the inherited fd
    # still carries only this disposable fixture, never the real service token.
    args = command(grants, fd, certificates=[])
    key = hashlib.sha256(f"UUID:{A}".encode()).hexdigest()
    script = r'''
import ctypes, errno, json, os, pathlib, sys
volume, mode, blocked = pathlib.Path(sys.argv[1]), sys.argv[2], sys.argv[3]
assert os.getuid() != 0
status = pathlib.Path('/proc/self/status').read_text()
assert 'NoNewPrivs:\t1' in status and 'CapEff:\t0000000000000000' in status
assert (volume / 'canary').read_text() == 'approved fixture'
for path in [pathlib.Path('/home/hermes/haos-owner-canary'), pathlib.Path(blocked),
             pathlib.Path('/dev/vda'), pathlib.Path('/dev/vdb'), pathlib.Path('/dev/vdc'),
             pathlib.Path('/etc/haos/volumes.json'), pathlib.Path('/run/haos-policy/sandbox.json'),
             pathlib.Path('/run/haos-control/control.sock'), pathlib.Path('/run/docker.sock'),
             pathlib.Path('/sys/kernel'), volume / 'escape']:
    try: path.read_bytes()
    except OSError: pass
    else: raise AssertionError(f'forbidden read: {path}')
try: pathlib.Path('/etc/haos/volumes.json').write_text('{}')
except OSError: pass
else: raise AssertionError('agent rewrote owner policy')
if mode == 'rw':
    (volume / 'agent-result').write_text('actual write')
    (pathlib.Path('/workspace') / 'acceptance-result').write_text('actual workspace write')
else:
    try: (volume / 'agent-result').write_text('forbidden')
    except OSError: pass
    else: raise AssertionError('read-only write succeeded')
libc = ctypes.CDLL(None, use_errno=True)
assert libc.unshare(0x10000000) == -1 and ctypes.get_errno() in (errno.EPERM, errno.ENOSPC)
assert libc.mount(b'/usr', b'/workspace', None, 4096, None) == -1 and ctypes.get_errno() == errno.EPERM
assert not pathlib.Path('/proc/1/root/home/hermes/haos-owner-canary').exists()
print(json.dumps({'mode': mode, 'data_access': True, 'blocked_volume_hidden': True,
                  'owner_policy_immutable': True, 'raw_devices_hidden': True,
                  'mount_denied': True, 'nested_userns_denied': True}))
'''
    args = args[:args.index("--") + 1] + ["/usr/bin/python3.11", "-I", "-c", script,
        f"/volumes/{key}", mode, str(ROOT / "blocked" / "canary")]
    account = pwd.getpwnam("haos-agent")
    try:
        result = run("/usr/bin/setpriv", f"--reuid={account.pw_uid}", f"--regid={account.pw_gid}",
            "--clear-groups", "--no-new-privs", "--bounding-set=-all", "--inh-caps=-all", "--ambient-caps=-all",
            *args, pass_fds=(fd,), capture_output=True)
    finally:
        os.close(fd)
    return json.loads(result.stdout)


def main():
    if os.geteuid() != 0 or Path("/sys/class/dmi/id/product_name").read_text().strip() != "haos-acceptance":
        raise PermissionError("this test may run only in the explicitly marked acceptance VM")
    if not (ROOT / "disposable-ci-guest").is_file():
        raise PermissionError("missing disposable guest marker")
    devices = json.loads(subprocess.check_output(["lsblk", "-J", "-o", "PATH,UUID,SERIAL"], text=True))["blockdevices"]
    assert any(d.get("uuid") == A and d.get("serial") == "HAOS-CI-DATA-A" for d in devices)
    assert any(d.get("uuid") == B and d.get("serial") == "HAOS-CI-DATA-B" for d in devices)
    wait_for(lambda: active("haos-controller.service"))
    wait_for(health)
    wait_for(lambda: active("greetd.service"))
    wait_for(lambda: active("haos-observer-security.service"))
    wait_for(lambda: active("haos-network.service"))
    wait_for(lambda: subprocess.run(["pgrep", "-u", "hermes", "-f", "/usr/share/herald-os/app/"], capture_output=True).returncode == 0)
    observer = pwd.getpwnam("hermes")
    administrator_gids = {g.gr_gid for g in grp.getgrall() if g.gr_name in {"wheel", "sudo", "admin"}}
    assert not administrator_gids.intersection(os.getgrouplist("hermes", observer.pw_gid))
    assert run("passwd", "--status", "hermes", capture_output=True).stdout.split()[1] in {"L", "P"}
    denied = subprocess.run(["runuser", "-u", "hermes", "--", "sudo", "-n", "id", "-u"], capture_output=True, text=True)
    assert denied.returncode != 0 and denied.stdout.strip() != "0"
    observer_proof = {"observer_sudo_denied": True, "observer_administrator_groups_absent": True,
                      "observer_empty_password_denied": True}
    agent = pwd.getpwnam("haos-agent")
    # A real owner-side listener is reachable by root but denied to the service
    # UID. Only fresh sockets and a marked guest are used; no host rule is changed.
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        listener.listen(4)
        port = listener.getsockname()[1]
        with socket.create_connection(("127.0.0.1", port), timeout=2):
            pass
        code = "import socket,sys;\ntry:\n socket.create_connection(('127.0.0.1',int(sys.argv[1])),timeout=2)\nexcept OSError:\n sys.exit(0)\nsys.exit(1)"
        result = subprocess.run(["setpriv", f"--reuid={agent.pw_uid}", f"--regid={agent.pw_gid}",
            "--clear-groups", "--no-new-privs", "python3", "-I", "-c", code, str(port)], timeout=5)
        assert result.returncode == 0, "agent reached a privileged localhost listener"
    observer_proof["installed_agent_local_network_guard"] = True
    stamp = ROOT / "mission.json"
    if not stamp.exists():
        run("haos-owner", "stop")
        # Only this marked guest's own new fixture is deleted. Real owner CLI,
        # fixed state scope and an installed Restic binary perform the recovery.
        project = Path("/var/lib/haos-workspace/haos-deleted-project-fixture")
        assert not project.exists()
        payload = os.urandom(4096)
        project.write_bytes(payload)
        project.chmod(0o600)
        run("haos-owner", "backup", "init", capture_output=True)
        snapshot = json.loads(run("haos-owner", "backup", "create", capture_output=True).stdout)["snapshot_id"]
        project.unlink()
        restored = json.loads(run("haos-owner", "backup", "restore", snapshot, capture_output=True).stdout)
        recovered = Path(restored["staging_directory"]) / project.relative_to("/")
        assert recovered.read_bytes() == payload and recovered.stat().st_mode & 0o777 == 0o600
        assert not project.exists() and restored["live_state_replaced"] is False
        backup_proof = {"installed_owner_backup_restore": True, "restore_live_state_untouched": True}
        run("haos-owner", "volume", f"UUID:{A}", "full-data-access")
        run("haos-owner", "volume", f"UUID:{B}", "blocked")
        run("haos-owner", "prepare")
        key = hashlib.sha256(f"UUID:{A}".encode()).hexdigest()
        data = Path("/run/haos-volumes") / key
        agent = pwd.getpwnam("haos-agent")
        # Only these disposable, serial-verified fixture files receive POSIX ownership.
        os.chown(data, agent.pw_uid, agent.pw_gid)
        (data / "canary").write_text("approved fixture")
        (data / "canary").chmod(0o644)
        (data / "escape").symlink_to("/home/hermes/haos-owner-canary")
        owner_canary = Path("/home/hermes/haos-owner-canary")
        owner_canary.write_text("owner canary")
        owner_canary.chmod(0o644)
        blocked = ROOT / "blocked"
        blocked.mkdir()
        run("mount", "-o", "nodev,nosuid,noexec", f"/dev/disk/by-uuid/{B}", str(blocked))
        (blocked / "canary").write_text("blocked canary")
        proof = {"write": sandbox_probe("rw"), **observer_proof, **backup_proof}
        assert (data / "agent-result").read_text() == "actual write"
        run("haos-owner", "cleanup")
        run("haos-owner", "volume", f"UUID:{A}", "read-only")
        run("haos-owner", "prepare")
        proof["read_only"] = sandbox_probe("ro")
        assert (data / "agent-result").read_text() == "actual write"
        assert (blocked / "canary").read_text() == "blocked canary"
        run("umount", str(blocked))
        run("haos-owner", "cleanup")
        run("haos-owner", "start")
        wait_for(health)
        pid = subprocess.check_output(["systemctl", "show", "-p", "MainPID", "--value", "haos-hermes.service"], text=True).strip()
        assert int(pid) > 0
        run("systemctl", "restart", "greetd.service")
        wait_for(lambda: active("greetd.service"))
        assert subprocess.check_output(["systemctl", "show", "-p", "MainPID", "--value", "haos-hermes.service"], text=True).strip() == pid
        proof["ui_restart_preserves_backend"] = True
        # Offline queue fixture: no fabricated Hermes turn or model-provider output.
        run("systemctl", "stop", "haos-controller.service")
        controller = pwd.getpwnam("haos-control")
        code = "import sys,json;from pathlib import Path;sys.path.insert(0,'/usr/lib/haos');from haos.store import MissionStore;s=MissionStore(Path('/var/lib/haos-control/missions.db'));m=s.create('acceptance:offline','reboot-persistence','Offline persistence probe',timeout=86400);s.request_cancel(m['id'],'acceptance:offline');print(json.dumps(s.get(m['id'])));s.close()"
        mission = json.loads(run("setpriv", f"--reuid={controller.pw_uid}", f"--regid={controller.pw_gid}", "--clear-groups", "python3", "-I", "-c", code, capture_output=True).stdout)
        assert mission["state"] == "cancelled"
        stamp.write_text(json.dumps({"mission": mission, "proof": proof}))
        print("HAOS_ACCEPTANCE_JSON=" + json.dumps({"stage": 1, **proof}), flush=True)
    else:
        from haos.store import MissionStore
        saved = json.loads(stamp.read_text())
        store = MissionStore(Path("/var/lib/haos-control/missions.db"))
        row = store.get(saved["mission"]["id"])
        assert row["state"] == "cancelled" and row["idempotency_key"] == "reboot-persistence"
        assert store.events(row["id"])
        store.close()
        print("HAOS_ACCEPTANCE_JSON=" + json.dumps({"stage": 2, "journal_survives_reboot": True,
            "backend_healthy_after_reboot": True, "mission_id": row["id"], **observer_proof,
            "limitations": ["offline cancelled queue fixture; no real provider mission", "theme/gateway/off-host/whole-system recovery not covered"]}), flush=True)
    run("systemctl", "poweroff")


if __name__ == "__main__":
    try:
        main()
    except BaseException:
        import traceback
        traceback.print_exc()
        print("HAOS_ACCEPTANCE_FAILED", flush=True)
        raise
