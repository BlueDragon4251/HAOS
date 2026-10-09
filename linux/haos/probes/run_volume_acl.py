"""Real ext4/xfs/btrfs file-backed disk fixtures, restricted to disposable CI."""

import json
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
import sys
import tempfile


def run(*args, **kwargs):
    result = subprocess.run(args, capture_output=True, text=True, timeout=90, **kwargs)
    if result.returncode:
        # All commands operate only on generated fixtures; expose bounded failure
        # evidence so a failed filesystem gate can be diagnosed without reruns.
        print((result.stdout + result.stderr)[-16000:], flush=True)
        result.check_returncode()
    return result


def main():
    if os.geteuid() != 0 or os.environ.get("GITHUB_ACTIONS") != "true" or os.environ.get("HAOS_DISPOSABLE_CI") != "1":
        raise PermissionError("file-backed disk probes require explicitly marked disposable GitHub CI")
    source = os.environ.get("GITHUB_SHA", "")
    if not re.fullmatch(r"[0-9a-f]{40}", source):
        raise PermissionError("ACL disk evidence requires an exact source commit")
    root = Path(tempfile.mkdtemp(prefix="haos-acl-disks-", dir="/run"))
    root.chmod(0o755)
    try:
        for filesystem, size in (("ext4", 64), ("xfs", 384), ("btrfs", 256)):
            image, mount = root / (filesystem + ".img"), root / filesystem
            mount.mkdir(mode=0o700)
            fd = os.open(image, os.O_RDWR | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
            try:
                assert stat.S_ISREG(os.fstat(fd).st_mode) and os.fstat(fd).st_nlink == 1
                os.ftruncate(fd, size * 1024 * 1024)
            finally:
                os.close(fd)
            # Format only our new regular file, never a device or existing path.
            run("/usr/sbin/mkfs." + filesystem, "-f" if filesystem != "ext4" else "-F", str(image))
            run("/usr/bin/mount", "--types", filesystem, "--options", "loop,nodev,nosuid,noexec", str(image), str(mount))
            try:
                actual = json.loads(run("/usr/bin/findmnt", "--json", "--first-only", "--mountpoint", str(mount),
                                        "--output", "SOURCE,TARGET,FSTYPE,OPTIONS").stdout)["filesystems"]
                assert len(actual) == 1 and actual[0]["target"] == str(mount) and actual[0]["fstype"] == filesystem
                assert {"nodev", "nosuid", "noexec", "rw"}.issubset(actual[0]["options"].split(","))
                loops = json.loads(run("/usr/sbin/losetup", "--json", "--output", "NAME,BACK-FILE").stdout)["loopdevices"]
                assert any(entry["name"] == actual[0]["source"] and entry["back-file"] == str(image) for entry in loops)
                mount.chmod(0o755)
                environment = {**os.environ, "TMPDIR": str(mount), "HAOS_ACL_DISK_FIXTURE": str(mount), "PYTHONDONTWRITEBYTECODE": "1"}
                run(sys.executable, "-m", "pytest", "-q", "-s", str(Path(__file__).with_name("test_volume_acl.py")), env=environment)
                receipt = json.dumps({"source_commit": source, "filesystem": filesystem,
                                      "file_backed_disk": True, "actual_acl_probe": True})
                print(receipt, flush=True)
                print(f"::notice title=HAOS real {filesystem} ACL gate::{receipt}", flush=True)
            finally:
                run("/usr/bin/umount", str(mount))
            image.unlink()
    finally:
        shutil.rmtree(root)


if __name__ == "__main__":
    main()
