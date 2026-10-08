"""Real kernel probes. Run explicitly on a Linux host permitting user namespaces."""

import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from haos.policy import validate_policy
from haos.sandbox import command


def test_agent_filesystem_view_cannot_escape_grants(tmp_path):
    home, workspace, ro, rw = [tmp_path / name for name in ("home", "workspace", "ro", "rw")]
    for path in (home, workspace, ro, rw):
        path.mkdir()
    host_secret = tmp_path / "owner-secret"
    host_secret.write_text("owner data outside the agent view")
    (ro / "existing").write_text("readable")
    (rw / "escape").symlink_to(host_secret)
    grants = validate_policy({"version": 1, "volumes": [
        {"id": "UUID:probe-ro", "mode": "read-only"}, {"id": "UUID:probe-rw", "mode": "full-data-access"}]})
    args = command(grants, "probe-credential", certificates=[])
    # Use disposable data directories as mount sources; execute the real production namespace command.
    replacements = {"/var/lib/haos-agent": str(home), "/var/lib/haos-workspace": str(workspace),
                    f"/run/haos-volumes/{grants[0]['key']}": str(ro),
                    f"/run/haos-volumes/{grants[1]['key']}": str(rw)}
    args = [replacements.get(arg, arg) for arg in args]
    probe = """
import json, os, pathlib, sys
ro, rw, secret = map(pathlib.Path, sys.argv[1:])
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
                  'symlink_escape_denied': True, 'owner_and_devices_hidden': True}))
"""
    args = args[:args.index("--") + 1] + ["/usr/bin/python3", "-I", "-c", probe,
            f"/volumes/{grants[0]['key']}", f"/volumes/{grants[1]['key']}", str(host_secret)]
    result = subprocess.run(args, capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["symlink_escape_denied"]
    assert (rw / "result").read_text() == "actual permitted write"
    assert not (ro / "changed").exists()
    assert host_secret.read_text() == "owner data outside the agent view"
