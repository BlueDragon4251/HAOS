"""Regression: Fedora sudo use_pty must not reject a real owner on tty3.

This guard protects the fixed initial-setup fallback; it must never accept
SSH, arbitrary PTYs, device symlinks, or another sudo identity.
"""
import os
import stat
from types import SimpleNamespace

import pytest

from haos import owner, owner_recovery


@pytest.fixture
def authenticated_vt3(monkeypatch):
    monkeypatch.setattr(owner_recovery, "require_console", lambda: None)
    monkeypatch.setattr(owner_recovery, "enrolled_owner",
                        lambda username: SimpleNamespace(pw_uid=1001) if username == "blue" else
                        (_ for _ in ()).throw(PermissionError("not enrolled")))
    monkeypatch.setattr(owner.os, "ttyname", lambda _: "/dev/pts/7")
    monkeypatch.setattr(owner, "_kernel_virtual_terminal", lambda path: path == "/dev/tty3")
    monkeypatch.setenv("SUDO_TTY", "/dev/tty3")
    monkeypatch.setenv("SUDO_USER", "blue")
    monkeypatch.setenv("SUDO_UID", "1001")
    for key in ("SSH_CONNECTION", "SSH_CLIENT", "SSH_TTY"):
        monkeypatch.delenv(key, raising=False)


def test_real_login_vt_survives_sudo_use_pty(authenticated_vt3):
    # The actual child is attached to /dev/pts/7, but the invoking owner
    # authenticated sudo from the physical /dev/tty3.
    owner.require_physical_setup_console()


@pytest.mark.parametrize("alter", [
    lambda m: m.setenv("SUDO_TTY", "/dev/pts/7"),
    lambda m: m.delenv("SUDO_TTY"),
    lambda m: m.setenv("SUDO_TTY", "/dev/tty"),
    lambda m: m.setenv("SUDO_USER", "not-an-owner"),
    lambda m: m.setenv("SUDO_UID", "1002"),
    lambda m: m.setenv("SUDO_UID", "not-a-number"),
    lambda m: m.delenv("SUDO_USER"),
    lambda m: m.setenv("SSH_CONNECTION", "10.1.1.2 1234 10.1.1.3 22"),
    lambda m: m.setenv("SSH_TTY", "/dev/pts/7"),
])
def test_unverified_origin_is_denied(authenticated_vt3, monkeypatch, alter):
    alter(monkeypatch)
    with pytest.raises(PermissionError):
        owner.require_physical_setup_console()


def test_physical_stdin_allows_direct_local_root_console(authenticated_vt3, monkeypatch):
    monkeypatch.setattr(owner.os, "ttyname", lambda _: "/dev/tty3")
    monkeypatch.delenv("SUDO_TTY")
    owner.require_physical_setup_console()


def test_ssh_rejected_even_if_stdin_is_kernel_vt(authenticated_vt3, monkeypatch):
    monkeypatch.setattr(owner.os, "ttyname", lambda _: "/dev/tty3")
    monkeypatch.setenv("SSH_CLIENT", "10.1.1.2 1234 22")
    with pytest.raises(PermissionError, match="local physical console"):
        owner.require_physical_setup_console()


@pytest.mark.parametrize("device,mode,major,minor,expected", [
    ("/dev/tty3", stat.S_IFCHR, 4, 3, True),
    ("/dev/tty8", stat.S_IFCHR, 4, 8, True),
    ("/dev/tty0", stat.S_IFCHR, 4, 0, False),
    ("/dev/tty64", stat.S_IFCHR, 4, 64, False),
    ("/dev/pts/3", stat.S_IFCHR, 136, 3, False),
    ("/dev/tty3", stat.S_IFLNK, 4, 3, False),
    ("/dev/tty3", stat.S_IFREG, 4, 3, False),
    ("/dev/tty3", stat.S_IFCHR, 136, 3, False),
    ("/dev/tty3", stat.S_IFCHR, 4, 4, False),
    ("/dev/ttyS3", stat.S_IFCHR, 4, 67, False),
])
def test_physical_vt_is_real_kernel_character_device(monkeypatch, device, mode, major, minor, expected):
    monkeypatch.setattr(owner.os, "stat", lambda path, **kwargs:
                        SimpleNamespace(st_mode=mode, st_rdev=os.makedev(major, minor)))
    assert owner._kernel_virtual_terminal(device) is expected


def test_missing_kernel_device_is_denied(monkeypatch):
    def missing(path, **kwargs):
        raise FileNotFoundError(path)
    monkeypatch.setattr(owner.os, "stat", missing)
    assert owner._kernel_virtual_terminal("/dev/tty3") is False
