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
from haos.policy import agent_directory, atomic_json


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
