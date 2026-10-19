"""Actual root-file migration and kernel UID denial, disposable files only."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

import pytest

from haos.ui_credentials import prepare

pytestmark = pytest.mark.skipif(os.geteuid() != 0, reason="requires isolated root credential fixture")


@pytest.fixture
def config():
    directory = Path(tempfile.mkdtemp(prefix="haos-ui-authority-"))
    directory.chmod(0o755)
    try:
        yield directory
    finally:
        shutil.rmtree(directory)


def read_as_observer(path):
    def drop():
        os.setgroups([61001])
        os.setgid(61001)
        os.setuid(61002)
    return subprocess.run([sys.executable, "-I", "-c", "import pathlib,sys; pathlib.Path(sys.argv[1]).read_bytes()", str(path)],
                          capture_output=True, preexec_fn=drop, timeout=5)


def test_actual_migration_revokes_old_token_and_observer_cannot_read_controller(config):
    old = "l" * 64
    (config / "backend-token").write_text(old)
    os.chown(config / "backend-token", 0, 61001)
    (config / "backend-token").chmod(0o640)
    (config / "backend.json").write_text(json.dumps({"version": 1, "baseUrl": "http://127.0.0.1:9119",
                                                   "tokenFile": "/etc/haos/backend-token"}))
    assert read_as_observer(config / "backend-token").returncode == 0
    prepare(config, 61001)
    private = (config / "backend-token").read_text().strip()
    observer = (config / "ui-token").read_text().strip()
    assert old != private != observer and old != observer
    assert (config / "backend-token").stat().st_mode & 0o777 == 0o600
    assert read_as_observer(config / "backend-token").returncode != 0
    assert read_as_observer(config / "ui-token").returncode == 0
    prepare(config, 61001)
    assert (config / "backend-token").read_text().strip() == private
    assert (config / "ui-token").read_text().strip() == observer


@pytest.mark.parametrize("kind", ["symlink", "hardlink", "foreign-owner", "writable"])
def test_actual_untrusted_credentials_cannot_replace_authority(config, kind):
    target = config / "backend-token"
    other = config / "other"
    other.write_text("x" * 64)
    if kind == "symlink":
        target.symlink_to(other)
    elif kind == "hardlink":
        os.link(other, target)
    else:
        target.write_text("x" * 64)
        if kind == "foreign-owner":
            os.chown(target, 61002, 61001)
        else:
            target.chmod(0o666)
    before = other.read_bytes()
    with pytest.raises(PermissionError):
        prepare(config, 61001)
    assert other.read_bytes() == before and not (config / "backend.json").exists()


def test_actual_exposed_v2_token_is_rotated_not_merely_chmodded(config):
    prepare(config, 61001)
    private = (config / "backend-token").read_bytes()
    (config / "backend-token").chmod(0o644)
    prepare(config, 61001)
    assert (config / "backend-token").read_bytes() != private
    assert read_as_observer(config / "backend-token").returncode != 0
