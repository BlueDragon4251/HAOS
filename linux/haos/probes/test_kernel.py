"""Real kernel probes. Run explicitly on a Linux host permitting user namespaces."""

import json
import hashlib
import os
import secrets
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from haos.policy import validate_policy
from haos.sandbox import command


def run_agent_filesystem_probe(tmp_path, launcher=None):
    home, workspace, ro, rw = [tmp_path / name for name in ("home", "workspace", "ro", "rw")]
    for path in (home, workspace, ro, rw):
        path.mkdir()
    host_secret = tmp_path / "owner-secret"
    host_secret.write_text("owner data outside the agent view")
    (ro / "existing").write_text("readable")
    (rw / "escape").symlink_to(host_secret)
    grants = validate_policy({"version": 1, "volumes": [
        {"id": "UUID:probe-ro", "mode": "read-only"}, {"id": "UUID:probe-rw", "mode": "full-data-access"}]})
    credential = tmp_path / "credential"
    credential_value = secrets.token_urlsafe(48)
    credential.write_text(credential_value)
    digest = hashlib.sha256(credential_value.encode()).hexdigest()
    fd = os.open(credential, os.O_RDONLY)
    args = command(grants, fd, certificates=[])
    passwd, group = tmp_path / "passwd", tmp_path / "group"
    passwd.write_text(f"haos-agent:x:{os.getuid()}:{os.getgid()}:HAOS agent:/home/agent:/usr/sbin/nologin\n")
    group.write_text(f"haos-agent:x:{os.getgid()}:\n")
    # Use disposable data directories as mount sources; execute the real production namespace command.
    replacements = {"/var/lib/haos-agent": str(home), "/var/lib/haos-workspace": str(workspace),
                    f"/run/haos-volumes/{grants[0]['key']}": str(ro),
                    f"/run/haos-volumes/{grants[1]['key']}": str(rw),
                    "/usr/lib/haos/passwd": str(passwd), "/usr/lib/haos/group": str(group)}
    args = [replacements.get(arg, arg) for arg in args]
    probe = """
import ctypes, errno, hashlib, json, os, pathlib, pwd, sys
ro, rw, secret = map(pathlib.Path, sys.argv[1:4])
assert os.getuid() != 0
assert pwd.getpwuid(os.getuid()).pw_name == 'haos-agent'
assert len(pwd.getpwall()) == 1
credential = pathlib.Path('/run/haos-credentials/backend-token').read_bytes()
assert hashlib.sha256(credential).hexdigest() == sys.argv[4]
assert credential not in pathlib.Path('/proc/1/cmdline').read_bytes()
status = pathlib.Path('/proc/self/status').read_text().splitlines()
assert 'NoNewPrivs:\t1' in status
assert 'CapEff:\t0000000000000000' in status
assert os.statvfs('/proc').f_flag & os.ST_RDONLY
assert os.statvfs('/proc/sys').f_flag & os.ST_RDONLY
control = pathlib.Path('/proc/self/oom_score_adj')
try:
    control.write_text(control.read_text())
except OSError as error:
    assert error.errno == errno.EROFS
else:
    raise AssertionError('sandbox procfs is writable')
libc = ctypes.CDLL(None, use_errno=True)
assert libc.unshare(0x10000000) == -1 and ctypes.get_errno() in (errno.EPERM, errno.ENOSPC)
assert libc.mount(b'/usr', b'/workspace', None, 4096, None) == -1 and ctypes.get_errno() == errno.EPERM
assert (ro / 'existing').read_text() == 'readable'
for path in [ro / 'changed', secret, rw / 'escape', pathlib.Path('/etc/shadow'),
             pathlib.Path('/run/haos-policy/sandbox.json'), pathlib.Path('/run/haos-control/control.sock'),
             pathlib.Path('/run/docker.sock'), pathlib.Path('/dev/sda'), pathlib.Path('/sys/kernel')]:
    try:
        if path == ro / 'changed': path.write_text('forbidden')
        else: path.read_bytes()
    except OSError: pass
    else: raise AssertionError(f'forbidden access succeeded: {path}')
(rw / 'result').write_text('actual permitted write')
(pathlib.Path('/workspace') / 'result').write_text('workspace write')
assert 'HERMES_PARENT_PID' not in os.environ
assert not pathlib.Path('/proc/1/root' + str(secret)).exists()
print(json.dumps({'read_only_enforced': True, 'write_grant_enforced': True,
                  'symlink_escape_denied': True, 'owner_and_devices_hidden': True,
                  'no_new_privileges': True, 'nested_userns_denied': True, 'mount_denied': True,
                  'kernel_tunables_read_only': True}))
"""
    args = args[:args.index("--") + 1] + ["/usr/bin/python3", "-I", "-c", probe,
            f"/volumes/{grants[0]['key']}", f"/volumes/{grants[1]['key']}", str(host_secret), digest]
    # Exercise the launcher's NoNewPrivileges setting as used by the service.
    try:
        if launcher is None:
            result = subprocess.run(["/usr/bin/setpriv", "--no-new-privs", *args], pass_fds=(fd,), capture_output=True, text=True, timeout=30)
        else:
            result = launcher(args, fd)
    finally:
        os.close(fd)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["symlink_escape_denied"]
    assert (rw / "result").read_text() == "actual permitted write"
    assert not (ro / "changed").exists()
    assert host_secret.read_text() == "owner data outside the agent view"
    return json.loads(result.stdout)


def test_agent_filesystem_view_cannot_escape_grants(tmp_path):
    run_agent_filesystem_probe(tmp_path)
