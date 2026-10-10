#!/usr/bin/env python3
"""Acceptance probe injected only into an explicitly marked, disposable QEMU guest."""

import grp
import hashlib
import json
import os
import pwd
import pty
import secrets
import select
import socket
import sqlite3
import stat
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
C = "42514251-0000-4000-8000-000000000003"


def require_disposable_guest():
    if os.geteuid() != 0 or Path("/sys/class/dmi/id/product_name").read_text().strip() != "haos-acceptance":
        raise PermissionError("this test may run only in the explicitly marked acceptance VM")
    marker = ROOT / "disposable-ci-guest"
    metadata = marker.lstat()
    if not stat.S_ISREG(metadata.st_mode) or metadata.st_uid != 0 or metadata.st_mode & 0o022:
        raise PermissionError("missing or untrusted disposable guest marker")


def drive_owner_console(argv, exchanges):
    require_disposable_guest()
    master, slave = pty.openpty()
    process = subprocess.Popen(argv, stdin=slave, stdout=slave, stderr=slave,
                               close_fds=True, env={"PATH": "/usr/sbin:/usr/bin:/sbin:/bin", "LANG": "C.UTF-8"})
    os.close(slave)
    output, prompts = b"", 0
    deadline = time.monotonic() + 60
    try:
        while time.monotonic() < deadline:
            ready, _, _ = select.select([master], [], [], 0.2)
            if ready:
                try:
                    block = os.read(master, 4096)
                except OSError:
                    break
                if not block:
                    break
                output += block
                if len(output) > 65536:
                    raise RuntimeError("owner enrollment console output exceeded its limit")
                if prompts < len(exchanges) and exchanges[prompts][0] in output and output.rstrip().endswith(b":"):
                    os.write(master, exchanges[prompts][1].encode() + b"\n")
                    prompts += 1
            if process.poll() is not None and not ready:
                break
        try:
            code = process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            code = process.wait(timeout=5)
        # Never put captured conversations or submitted credentials into a diagnostic exception.
        if prompts != len(exchanges):
            raise RuntimeError("installed owner console did not finish its authentication exchange")
        for prompt, answer in exchanges:
            if b"password" in prompt.lower() or b"code" in prompt.lower():
                if answer.encode() in output:
                    raise RuntimeError("installed owner console echoed a credential")
        return code, output
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=5)
        os.close(master)


def enroll_owner_at_console(username, password):
    code, output = drive_owner_console(["/usr/bin/haos-owner", "enroll", username], [
        (b"New owner password", password), (b"Repeat owner password", password)])
    if code != 0:
        raise RuntimeError("installed owner console enrollment failed")
    import re
    codes = re.findall(rb"(?m)^[A-Za-z0-9_-]{43}\r?$", output)
    if len(codes) != 10:
        raise RuntimeError("installed owner console did not issue ten recovery codes")
    return codes[0].strip().decode()


def owner_authentication_proof(*, first_boot):
    require_disposable_guest()
    # Never place this generated credential among collected acceptance artifacts.
    private = Path("/var/lib/haos-owner-ci")
    secret_path = private / "credential.json"
    if first_boot:
        assert not private.exists() and not private.is_symlink()
        private.mkdir(mode=0o700)
        assert not secret_path.exists() and not secret_path.is_symlink()
        username = "haos-owner-ci-" + secrets.token_hex(4)
        password = secrets.token_urlsafe(32) + "!Aa42"
        recovery_code = enroll_owner_at_console(username, password)
        entry = pwd.getpwnam(username)
        fd = os.open(secret_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, "w") as stream:
            json.dump({"username": username, "password": password, "recovery_code": recovery_code, "uid": entry.pw_uid}, stream)
            stream.flush()
            os.fsync(stream.fileno())
    else:
        parent = private.lstat()
        if not stat.S_ISDIR(parent.st_mode) or parent.st_uid != 0 or parent.st_mode & 0o077:
            raise PermissionError("untrusted owner acceptance credential directory")
        metadata = secret_path.lstat()
        if not stat.S_ISREG(metadata.st_mode) or metadata.st_uid != 0 or metadata.st_mode & 0o077:
            raise PermissionError("untrusted owner acceptance credential")
        saved = json.loads(secret_path.read_text())
        username, password = saved["username"], saved["password"]
        recovery_code = saved["recovery_code"]
        assert pwd.getpwnam(username).pw_uid == saved["uid"]
    prefix = ["/usr/sbin/runuser", "-u", username, "--", "/usr/bin/sudo"]
    def authentication(*args, supplied=None):
        return subprocess.run([*prefix, *args], input=(supplied + "\n") if supplied is not None else None,
                              stdin=None if supplied is not None else subprocess.DEVNULL,
                              env={"PATH": "/usr/sbin:/usr/bin:/sbin:/bin", "LANG": "C"},
                              capture_output=True, text=True, timeout=30)
    correct = authentication("-S", "-k", "/usr/bin/haos-owner", "status", supplied=password)
    if correct.returncode != 0:
        raise RuntimeError("installed owner PAM authentication failed")
    assert "volumes" in json.loads(correct.stdout)["policy"]
    assert authentication("-n", "/usr/bin/haos-owner", "status").returncode != 0
    assert authentication("-S", "-k", "/usr/bin/haos-owner", "status", supplied="incorrect-acceptance-password").returncode != 0
    arbitrary = authentication("-S", "-k", "/usr/bin/id", "-u", supplied=password)
    assert arbitrary.returncode != 0 and arbitrary.stdout.strip() != "0"
    assert authentication("-S", "-k", "PYTHONPATH=/tmp", "/usr/bin/haos-owner", "status", supplied=password).returncode != 0
    for path in [Path("/var/lib/haos-owner/owners.json"), Path("/var/lib/haos-owner/audit.jsonl")]:
        assert password not in path.read_text()
    assert password not in correct.stdout and password not in correct.stderr
    assert pwd.getpwnam(username).pw_uid != pwd.getpwnam("hermes").pw_uid
    if not first_boot:
        replacement = secrets.token_urlsafe(32) + "!Aa42"
        code, _ = drive_owner_console(["/usr/bin/haos-recovery"], [
            (b"Enrolled owner account", username), (b"Single-use recovery code", recovery_code),
            (b"Action:", "reset-password"), (b"New owner password", replacement), (b"Repeat owner password", replacement)])
        if code != 0:
            raise RuntimeError("installed independent owner recovery failed")
        assert authentication("-S", "-k", "/usr/bin/haos-owner", "status", supplied=password).returncode != 0
        replacement_login = authentication("-S", "-k", "/usr/bin/haos-owner", "status", supplied=replacement)
        if replacement_login.returncode != 0:
            raise RuntimeError("recovered owner password was not accepted")
        # The same code cannot perform a second recovery.
        replay, _ = drive_owner_console(["/usr/bin/haos-recovery"], [
            (b"Enrolled owner account", username), (b"Single-use recovery code", recovery_code)])
        assert replay != 0
        secret_path.unlink()
        private.rmdir()
    return {"installed_owner_console_enrollment": True, "installed_owner_password_authentication": True,
            "installed_owner_wrong_password_denied": True, "installed_owner_cached_auth_denied": True,
            "installed_owner_arbitrary_root_denied": True, "installed_owner_python_override_denied": True,
            "installed_owner_credential_absent_from_audit": True, "installed_owner_authentication_after_reboot": not first_boot,
            "installed_owner_recovery_codes_issued": True, "installed_owner_password_recovery": not first_boot,
            "installed_owner_used_recovery_code_denied": not first_boot}


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


def namespace_probe(grants, script, arguments, label):
    require_disposable_guest()
    credential = ROOT / "probe-credential"
    credential.write_text("acceptance-unused-token")
    fd = os.open(credential, os.O_RDONLY)
    # The root test drops to the service UID before Bubblewrap; the inherited fd
    # still carries only this disposable fixture, never the real service token.
    try:
        args = command(grants, fd, certificates=[])
        args = args[:args.index("--") + 1] + ["/usr/bin/python3.11", "-I", "-c", script, *arguments]
        account = pwd.getpwnam("haos-agent")
        result = subprocess.run(["/usr/bin/setpriv", f"--reuid={account.pw_uid}", f"--regid={account.pw_gid}",
            "--clear-groups", "--no-new-privs", "--bounding-set=-all", "--inh-caps=-all", "--ambient-caps=-all",
            *args], pass_fds=(fd,), capture_output=True, text=True, timeout=60)
    finally:
        os.close(fd)
    if result.returncode:
        from haos.redaction import Redactor
        # Only a disposable credential FD; no command/script or stdout dump.
        detail = Redactor(["acceptance-unused-token"]).text(result.stderr[-2000:])
        raise RuntimeError(f"sandbox {label} probe failed (exit {result.returncode}): {detail}")
    return json.loads(result.stdout)


def sandbox_probe(mode):
    require_disposable_guest()
    grants = trusted_json(Path("/run/haos-policy/sandbox.json"))["grants"]
    key = hashlib.sha256(f"UUID:{A}".encode()).hexdigest()
    removable = hashlib.sha256(f"UUID:{C}".encode()).hexdigest()
    script = r'''
import ctypes, errno, json, os, pathlib, sys
volume, mode, blocked = pathlib.Path(sys.argv[1]), sys.argv[2], sys.argv[3]
removable = pathlib.Path(sys.argv[4])
assert os.getuid() != 0
status = pathlib.Path('/proc/self/status').read_text()
assert 'NoNewPrivs:\t1' in status and 'CapEff:\t0000000000000000' in status
assert (volume / 'canary').read_text() == 'approved fixture'
for path in [pathlib.Path('/home/hermes/haos-owner-canary'), pathlib.Path(blocked),
             pathlib.Path('/dev/vda'), pathlib.Path('/dev/vdb'), pathlib.Path('/dev/vdc'), pathlib.Path('/dev/vdd'),
             pathlib.Path('/etc/haos/volumes.json'), pathlib.Path('/run/haos-policy/sandbox.json'),
             pathlib.Path('/run/haos-control/control.sock'), pathlib.Path('/run/docker.sock'),
             pathlib.Path('/sys/kernel'), volume / 'escape']:
    try: path.read_bytes()
    except OSError: pass
    else: raise AssertionError(f'forbidden read: {path}')
try: pathlib.Path('/etc/haos/volumes.json').write_text('{}')
except OSError: pass
else: raise AssertionError('agent rewrote owner policy')
assert (removable / 'canary').read_text() in ('removable fixture', 'edited removable fixture')
(removable / 'canary').write_text('edited removable fixture')
if mode == 'rw':
    foreign = volume / 'foreign-private' / 'foreign-file'
    # Host ownership is verified by the root fixture below. Only the service
    # UID is mapped by Bubblewrap; other host UIDs appear as overflow UID here.
    assert foreign.stat().st_uid != os.getuid()
    assert foreign.read_text() == 'foreign owner fixture'
    foreign.write_text('edited foreign owner fixture')
    renamed = foreign.with_name('renamed')
    foreign.rename(renamed)
    renamed.unlink()
    sticky = volume / 'sticky' / 'foreign-delete'
    assert sticky.stat().st_uid != os.getuid()
    sticky.unlink()
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
                  'connected_removable_volume_read_write': True,
                  'foreign_owner_write_rename_delete': mode == 'rw',
                  'owner_policy_immutable': True, 'raw_devices_hidden': True,
                  'mount_denied': True, 'nested_userns_denied': True}))
'''
    return namespace_probe(grants, script,
        [f"/volumes/{key}", mode, str(ROOT / "blocked" / "canary"), f"/volumes/{removable}"], mode)


def disconnected_volume_probe():
    require_disposable_guest()
    policy = trusted_json(Path("/etc/haos/volumes.json"))
    assert {"id": f"UUID:{C}", "mode": "full-data-access"} in policy["volumes"]
    runtime = trusted_json(Path("/run/haos-policy/sandbox.json"))
    key = hashlib.sha256(f"UUID:{C}".encode()).hexdigest()
    assert runtime["unavailable"] == [{"id": f"UUID:{C}", "mode": "full-data-access", "key": key,
                                        "reason": "not-connected"}]
    assert all(grant["key"] != key for grant in runtime["grants"])
    script = r'''
import json, os, pathlib, sys
assert os.getuid() != 0
volume = pathlib.Path('/volumes') / sys.argv[1]
assert not volume.exists()
assert str(volume) not in {line.split()[4] for line in pathlib.Path('/proc/self/mountinfo').read_text().splitlines()}
for operation in (lambda: (volume / 'canary').read_bytes(), lambda: (volume / 'canary').write_text('forbidden')):
    try: operation()
    except OSError: pass
    else: raise AssertionError('disconnected volume remained accessible')
assert pathlib.Path('/workspace/acceptance-result').read_text() == 'actual workspace write'
print(json.dumps({'installed_disconnected_volume_namespace_denied': True,
                  'installed_remaining_workspace_access_preserved': True}))
'''
    return {**namespace_probe(runtime["grants"], script, [key], "disconnected-volume"),
            "installed_disconnected_volume_owner_policy_preserved": True,
            "installed_disconnected_volume_compiled_bind_absent": True}


def main():
    require_disposable_guest()
    devices = json.loads(subprocess.check_output(["lsblk", "-J", "-o", "PATH,UUID,SERIAL"], text=True))["blockdevices"]
    assert any(d.get("uuid") == A and d.get("serial") == "HAOS-CI-DATA-A" for d in devices)
    assert any(d.get("uuid") == B and d.get("serial") == "HAOS-CI-DATA-B" for d in devices)
    stamp = ROOT / "mission.json"
    if not stamp.exists():
        assert any(d.get("uuid") == C and d.get("serial") == "HAOS-CI-DATA-C" for d in devices)
    else:
        assert not any(d.get("uuid") == C or d.get("serial") == "HAOS-CI-DATA-C" for d in devices)
    if not stamp.exists():
        # Fresh production systems hold execution until the owner is enrolled.
        run("haos-owner", "stop")
        installed_owner_proof = owner_authentication_proof(first_boot=True)
        run("haos-owner", "start")
    else:
        installed_owner_proof = owner_authentication_proof(first_boot=False)
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
    wait_for(lambda: active("haos-dashboard-policy.service"))
    descriptor = json.loads(Path("/etc/haos/backend.json").read_text())
    assert descriptor == {"version": 2, "baseUrl": "http://127.0.0.1:9119", "tokenFile": "/etc/haos/ui-token"}
    observer_dashboard_code = "\n".join([
        "import json,pathlib,urllib.request,urllib.error",
        "try:",
        " pathlib.Path('/etc/haos/backend-token').read_bytes()",
        "except PermissionError:",
        " pass",
        "else:",
        " raise RuntimeError('observer read the private backend credential')",
        "token=pathlib.Path('/etc/haos/ui-token').read_text().strip()",
        "headers={'X-Hermes-Session-Token':token}",
        "base='http://127.0.0.1:9119'",
        "with urllib.request.urlopen(urllib.request.Request(base+'/api/host/identity',headers=headers),timeout=10) as response:",
        " identity=json.load(response)",
        "assert identity['ok'] is True and not identity['servesSpa']",
        "for path in ('/api/config','/api/env','/api/providers/oauth/openai-codex/start','/api/pty'):",
        " try:",
        "  urllib.request.urlopen(urllib.request.Request(base+path,headers=headers),timeout=10)",
        " except urllib.error.HTTPError as error:",
        "  assert error.code==403",
        " else:",
        "  raise RuntimeError('observer reached a protected dashboard route')",
        "print(json.dumps({'observer_backend_credential_denied':True,'observer_dashboard_read_authenticated':True,'observer_privileged_dashboard_routes_denied':True}))",
    ])
    dashboard = subprocess.run(["runuser", "-u", "hermes", "--", "python3", "-I", "-c", observer_dashboard_code],
                               capture_output=True, text=True, timeout=50)
    assert dashboard.returncode == 0, "installed observer dashboard boundary failed"
    observer_proof.update(json.loads(dashboard.stdout))
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
        # Actual installed timer/job, production hardening and encrypted snapshot.
        # Recreate only our disposable project; disable scheduling before reboot.
        project.write_bytes(payload)
        project.chmod(0o600)
        try:
            run("haos-owner", "backup", "schedule", "daily", capture_output=True)
            assert run("systemctl", "is-enabled", "haos-backup-schedule.timer", capture_output=True).stdout.strip() == "enabled"
            run("systemctl", "start", "haos-backup-schedule.service")
            scheduled = json.loads(run("haos-owner", "backup", "schedule-status", capture_output=True).stdout)
            assert scheduled["phase"] == "idle" and scheduled["last_success"] is not None and scheduled["due"] is False
            staged = json.loads(run("haos-owner", "backup", "restore", scheduled["snapshot_id"], capture_output=True).stdout)
            recovered_schedule = Path(staged["staging_directory"]) / project.relative_to("/")
            assert recovered_schedule.read_bytes() == payload and staged["live_state_replaced"] is False
            backup_proof.update(installed_encrypted_scheduler=True, installed_scheduled_snapshot_restored=True,
                                installed_schedule_retention_preview=True)
            # A second owner-selected scope checkpoints the WAL-aware mission
            # ledger under the actual read-only hardened systemd job while both
            # runtime services stay active. No provider turn is inferred here.
            run('haos-owner', 'start')
            wait_for(health)
            wait_for(lambda: active('haos-controller.service'))
            pids = {unit: run('systemctl', 'show', '--value', '--property=MainPID', unit, capture_output=True).stdout.strip()
                    for unit in ('haos-controller.service', 'haos-hermes.service')}
            assert all(pid.isdigit() and int(pid) > 0 for pid in pids.values())
            run('haos-owner', 'backup', 'schedule', 'daily', '--scope', 'mission-ledger', capture_output=True)
            run('systemctl', 'start', 'haos-backup-schedule.service')
            online = json.loads(run('haos-owner', 'backup', 'schedule-status', capture_output=True).stdout)
            assert online['phase'] == 'idle' and online['last_success'] is not None and online['configuration']['scope'] == 'mission-ledger'
            for unit, pid in pids.items():
                assert active(unit) and run('systemctl', 'show', '--value', '--property=MainPID', unit, capture_output=True).stdout.strip() == pid
            run('haos-owner', 'stop')
            restored_online = json.loads(run('haos-owner', 'backup', 'restore', online['snapshot_id'], capture_output=True).stdout)
            exported = Path(restored_online['staging_directory']) / 'var/lib/haos-owner/live-mission-checkpoint'
            manifest = json.loads((exported / 'checkpoint.json').read_text())
            assert manifest['database_sha256'] == hashlib.sha256((exported / 'missions.db').read_bytes()).hexdigest()
            with sqlite3.connect(exported / 'missions.db') as database:
                assert database.execute('PRAGMA integrity_check').fetchone()[0] == 'ok'
                assert not database.execute('PRAGMA foreign_key_check').fetchall()
            assert restored_online['live_state_replaced'] is False and manifest['complete_system_backup'] is False
            backup_proof.update(installed_live_ledger_scheduler=True, installed_live_ledger_restore_verified=True,
                                installed_live_backup_runtime_pids_preserved=True)
        finally:
            run("haos-owner", "backup", "schedule", "off", capture_output=True)
            run('haos-owner', 'stop')
            project.unlink(missing_ok=True)
        assert subprocess.run(("systemctl", "is-enabled", "haos-backup-schedule.timer"), capture_output=True).returncode != 0
        # Prepare foreign-owned, restrictive fixtures BEFORE any ACL grant. Only
        # the serial/UUID-verified disposable data disk is formatted/mounted.
        fixture_data = ROOT / "foreign-owner-fixture"
        fixture_data.mkdir()
        run("mount", "-o", "nodev,nosuid,noexec", f"/dev/disk/by-uuid/{A}", str(fixture_data))
        try:
            fixture_data.chmod(0o700)
            (fixture_data / "canary").write_text("approved fixture")
            (fixture_data / "canary").chmod(0o600)
            os.chown(fixture_data / "canary", 65533, 65533)
            foreign = fixture_data / "foreign-private"
            foreign.mkdir(mode=0o700)
            (foreign / "foreign-file").write_text("foreign owner fixture")
            (foreign / "foreign-file").chmod(0o600)
            os.chown(foreign / "foreign-file", 65533, 65533)
            os.chown(foreign, 65533, 65533)
            sticky = fixture_data / "sticky"
            sticky.mkdir(mode=0o1770)
            sticky.chmod(0o1770)
            (sticky / "foreign-delete").write_text("foreign delete fixture")
            os.chown(sticky / "foreign-delete", 65533, 65533)
            (fixture_data / "escape").symlink_to("/home/hermes/haos-owner-canary")
        finally:
            run("umount", str(fixture_data))
        run("haos-owner", "volume", f"UUID:{A}", "full-data-access")
        run("haos-owner", "volume", f"UUID:{B}", "blocked")
        removable_fixture = ROOT / "removable-fixture"
        removable_fixture.mkdir()
        run("mount", "-o", "nodev,nosuid,noexec", f"/dev/disk/by-uuid/{C}", str(removable_fixture))
        try:
            (removable_fixture / "canary").write_text("removable fixture")
            (removable_fixture / "canary").chmod(0o600)
            os.chown(removable_fixture / "canary", 65533, 65533)
        finally:
            run("umount", str(removable_fixture))
        run("haos-owner", "volume", f"UUID:{C}", "full-data-access")
        run("haos-owner", "prepare")
        key = hashlib.sha256(f"UUID:{A}".encode()).hexdigest()
        data = Path("/run/haos-volumes") / key
        assert (data / "foreign-private" / "foreign-file").stat().st_uid == 65533
        assert (data / "sticky" / "foreign-delete").stat().st_uid == 65533
        owner_canary = Path("/home/hermes/haos-owner-canary")
        owner_canary.write_text("owner canary")
        owner_canary.chmod(0o644)
        blocked = ROOT / "blocked"
        blocked.mkdir()
        run("mount", "-o", "nodev,nosuid,noexec", f"/dev/disk/by-uuid/{B}", str(blocked))
        (blocked / "canary").write_text("blocked canary")
        proof = {"write": sandbox_probe("rw"), **observer_proof, **backup_proof, **installed_owner_proof}
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
        disconnected_proof = disconnected_volume_probe()
        print("HAOS_ACCEPTANCE_JSON=" + json.dumps({"stage": 2, "journal_survives_reboot": True,
            "backend_healthy_after_reboot": True, "mission_id": row["id"], **observer_proof, **installed_owner_proof,
            **disconnected_proof,
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
