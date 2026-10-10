"""Actual umask/mode behavior; service UID/group access is a separate root probe."""

import os
import stat
from types import SimpleNamespace

import pytest

from haos import policy


def broker_identity(monkeypatch, uid=0):
    original = os.fstat
    identity = {"gid": 0}
    def metadata(fd):
        real = original(fd)
        return SimpleNamespace(st_uid=uid, st_gid=identity["gid"], st_mode=real.st_mode)
    def chown(fd, owner, group):
        assert owner == 0
        identity["gid"] = group
    monkeypatch.setattr(policy.os, "geteuid", lambda: 0)
    monkeypatch.setattr(policy.os, "fstat", metadata)
    monkeypatch.setattr(policy.os, "fchown", chown)


def test_verified_directory_mode_survives_restrictive_umask(monkeypatch, tmp_path):
    broker_identity(monkeypatch)
    previous = os.umask(0o077)
    try:
        path = tmp_path / "policy"
        path.mkdir(mode=0o750)
        assert stat.S_IMODE(path.stat().st_mode) == 0o700
        policy.agent_directory(path, 1200)
        assert stat.S_IMODE(path.stat().st_mode) == 0o750
    finally:
        os.umask(previous)


@pytest.mark.parametrize("kind", ["symlink", "writable", "foreign-owner", "mounted"])
def test_unsafe_existing_directory_is_rejected_before_authority_changes(monkeypatch, tmp_path, kind):
    broker_identity(monkeypatch, uid=1200 if kind == "foreign-owner" else 0)
    target = tmp_path / "target"
    target.mkdir()
    path = target
    if kind == "symlink":
        path = tmp_path / "link"
        path.symlink_to(target, target_is_directory=True)
    elif kind == "writable":
        target.chmod(0o777)
    elif kind == "mounted":
        monkeypatch.setattr(policy.os.path, "ismount", lambda _: True)
    before = stat.S_IMODE(target.stat().st_mode)
    monkeypatch.setattr(policy.os, "fchown", lambda *a: pytest.fail("untrusted inode was given service authority"))
    with pytest.raises((PermissionError, OSError)):
        policy.agent_directory(path, 1200)
    assert stat.S_IMODE(target.stat().st_mode) == before
