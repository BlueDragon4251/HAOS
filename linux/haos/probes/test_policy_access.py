"""Real root-owned fixtures and dropped-UID access; no disks/accounts are changed."""

import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import sys
import tempfile

import pytest

sys.path.insert(0, str(Path(__file__).parents[1]))
from haos import policy
from haos.policy import agent_directory, atomic_json
from haos.sandbox import command


def read_as_service(root, gid=65534):
    code = '''
import json, sys
from pathlib import Path
sys.path.insert(0, sys.argv[1])
from sandbox import trusted_json
path = Path(sys.argv[2])
value = trusted_json(path)
for action in (lambda: path.write_text('forbidden'), lambda: path.unlink(),
               lambda: (path.parent / 'forbidden').write_text('forbidden')):
    try: action()
    except PermissionError: pass
    else: raise AssertionError('service modified owner policy')
print(json.dumps(value))
'''
    return subprocess.run(["/usr/bin/setpriv", "--reuid=65534", f"--regid={gid}", "--clear-groups",
                           "/usr/bin/python3", "-I", "-c", code, str(root / "lib"), str(root / "policy" / "sandbox.json")],
                          env={"PATH": "/usr/bin:/bin"}, capture_output=True, text=True, timeout=10)


def test_restrictive_service_umask_policy_can_be_read_but_not_changed():
    assert os.geteuid() == 0, "this suite uses only disposable root-owned filesystem fixtures"
    with tempfile.TemporaryDirectory(prefix="haos-policy-access-") as directory:
        root = Path(directory)
        root.chmod(0o755)
        lib = root / "lib"
        lib.mkdir(mode=0o755)
        shutil.copy2(Path(__file__).parents[1] / "haos" / "sandbox.py", lib / "sandbox.py")
        (lib / "sandbox.py").chmod(0o644)
        runtime = root / "policy"
        previous = os.umask(0o077)
        try:
            # Reproduce the exact old production setup under systemd UMask=0077.
            runtime.mkdir(mode=0o750)
            os.chown(runtime, 0, 65534)
            atomic_json(runtime / "sandbox.json", {"version": 1, "grants": []}, mode=0o640, gid=65534)
            assert stat.S_IMODE(runtime.stat().st_mode) == 0o700
            denied = read_as_service(root)
            assert denied.returncode != 0 and "PermissionError" in denied.stderr
            agent_directory(runtime, 65534)
            assert stat.S_IMODE(runtime.stat().st_mode) == 0o750
            allowed = read_as_service(root)
            assert allowed.returncode == 0, allowed.stderr
            assert json.loads(allowed.stdout) == {"version": 1, "grants": []}
            other_group = read_as_service(root, 65533)
            assert other_group.returncode != 0 and "PermissionError" in other_group.stderr
            assert (runtime / "sandbox.json").stat().st_uid == 0
            assert stat.S_IMODE((runtime / "sandbox.json").stat().st_mode) == 0o640
        finally:
            os.umask(previous)


@pytest.mark.parametrize("kind", ["symlink", "writable", "non-root"])
def test_untrusted_runtime_directory_is_never_repaired_into_authority(tmp_path, kind):
    assert os.geteuid() == 0
    target = tmp_path / "target"
    target.mkdir()
    path = target
    if kind == "symlink":
        path = tmp_path / "link"
        path.symlink_to(target, target_is_directory=True)
    elif kind == "writable":
        target.chmod(0o777)
    else:
        os.chown(target, 65534, 65534)
    before = (target.stat().st_uid, target.stat().st_gid, target.stat().st_mode)
    with pytest.raises((PermissionError, OSError)):
        agent_directory(path, 65534)
    assert (target.stat().st_uid, target.stat().st_gid, target.stat().st_mode) == before


def test_actual_disconnected_policy_publishes_no_bind_and_keeps_owner_file(monkeypatch):
    """Real lsblk, root-owned publication and dropped UID; no devices modified."""
    from types import SimpleNamespace
    import uuid
    assert os.geteuid() == 0
    with tempfile.TemporaryDirectory(prefix="haos-absent-policy-") as directory:
        root = Path(directory)
        root.chmod(0o755)
        lib = root / "lib"
        lib.mkdir(mode=0o755)
        shutil.copy2(Path(__file__).parents[1] / "haos/sandbox.py", lib / "sandbox.py")
        (lib / "sandbox.py").chmod(0o644)
        authority = root / "authority"
        authority.mkdir(mode=0o700)
        owner = authority / "volumes.json"
        missing = [{"id": "UUID:" + str(uuid.uuid4()), "mode": "full-data-access"},
                   {"id": "PARTUUID:" + str(uuid.uuid4()), "mode": "read-only"}]
        original = {"version": 1, "volumes": missing}
        atomic_json(owner, original)
        before = owner.read_bytes()
        runtime = root / "policy"
        mounts = root / "mounts"
        paths = {"/etc/haos/volumes.json": owner, "/run/haos-policy": runtime,
                 "/run/haos-policy/sandbox.json": runtime / "sandbox.json", "/run/haos-volumes": mounts}
        monkeypatch.setattr(policy, "Path", lambda path: paths.get(str(path), Path(path)))
        monkeypatch.setattr("pwd.getpwnam", lambda user: SimpleNamespace(pw_uid=65534, pw_gid=65534))
        # Both selected identities are actually absent from kernel inventory.
        devices = policy.inventory()
        assert not any(d.get("uuid") == missing[0]["id"][5:] or d.get("partuuid") == missing[1]["id"][9:]
                       for d in devices)
        policy.prepare()
        report = json.loads((runtime / "sandbox.json").read_text())
        assert report["grants"] == [] and len(report["unavailable"]) == 2
        assert all(row["reason"] == "not-connected" for row in report["unavailable"])
        assert list(mounts.iterdir()) == [] and owner.read_bytes() == before
        args = command(report["grants"], 3, certificates=[])
        assert all(str(mounts / row["key"]) not in args and "/volumes/" + row["key"] not in args
                   for row in report["unavailable"])
        # The real service UID can inspect but cannot modify the published plan.
        allowed = read_as_service(root)
        assert allowed.returncode == 0, allowed.stderr
        assert json.loads(allowed.stdout) == report
        policy.cleanup()
        assert not (runtime / "sandbox.json").exists() and owner.read_bytes() == before
