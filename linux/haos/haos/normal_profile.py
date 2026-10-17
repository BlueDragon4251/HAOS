"""Owner-controlled transfer of firstboot display preferences to the locked observer.

No shell, home directory or uid is supplied by the GUI, agent, or model. Writes
are bounded to the existing HAOS observer account, preserving prior user data.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import pwd
import stat
import tempfile

from .region import LOCALES, CONSOLE_MAP

OBSERVER = "hermes"
HOME = Path("/home/hermes")


def _observer():
    if os.geteuid() != 0:
        raise PermissionError("normal session setup is a privileged firstboot operation")
    entry = pwd.getpwnam(OBSERVER)
    if entry.pw_uid < 1000 or entry.pw_gid == 0 or Path(entry.pw_dir) != HOME:
        raise PermissionError("unexpected HAOS observer account")
    return entry


def _directory(path: Path, entry):
    """Reject symlinks/writable parent directories, never follow an attacker path."""
    if path != HOME and HOME not in path.parents:
        raise PermissionError("write is outside the fixed HAOS observer home")
    if not path.exists():
        if path == HOME:
            raise PermissionError("observer home not provisioned")
        _directory(path.parent, entry)
        path.mkdir(mode=0o700)
        os.chown(path, entry.pw_uid, entry.pw_gid)
    info = path.lstat()
    if (not stat.S_ISDIR(info.st_mode) or info.st_uid != entry.pw_uid
            or info.st_mode & 0o022):
        raise PermissionError("unsafe observer configuration directory")


def _write(relative: str, content: str, entry, *, replace=False):
    target = HOME / relative
    _directory(target.parent, entry)
    if target.is_symlink():
        raise PermissionError("configuration symlinks are forbidden")
    if target.exists():
        old = target.lstat()
        if not stat.S_ISREG(old.st_mode) or old.st_uid != entry.pw_uid:
            raise PermissionError("existing observer data must remain owned by its user")
        if not replace:
            return False
    fd, temp = tempfile.mkstemp(prefix=".haos-setup-", dir=target.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            os.fchmod(handle.fileno(), 0o600)
            os.fchown(handle.fileno(), entry.pw_uid, entry.pw_gid)
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp, target)
        directory_fd = os.open(target.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        Path(temp).unlink(missing_ok=True)
    return True


def configure_name(display_name: str):
    entry = _observer()
    if (not isinstance(display_name, str) or not 1 <= len(display_name.strip()) <= 64
            or len(display_name.encode("utf-8")) > 192
            or any(ord(char) < 32 or ord(char) == 127 for char in display_name)):
        raise ValueError("invalid user display name")
    _write(".config/herald-os/name", display_name.strip() + "\n", entry, replace=True)
    return {"display_name_configured": True}


def name_exists() -> bool:
    entry = _observer()
    file = HOME / ".config/herald-os/name"
    if file.is_symlink() or not file.is_file() or file.stat().st_uid != entry.pw_uid:
        return False
    value = file.read_text(encoding="utf-8")[:193]
    return bool(value.strip()) and len(value) <= 192


def configure_region(language: str, keyboard: str):
    entry = _observer()
    if language not in LOCALES or keyboard not in CONSOLE_MAP:
        raise ValueError("unsupported regional configuration")
    settings = json.dumps({"language": language, "keyboard": keyboard}, separators=(",", ":")) + "\n"
    _write(".config/herald-os/region.json", settings, entry, replace=True)
    _write(".config/herald-os/locale", language + "\n", entry, replace=True)
    _write(".config/environment.d/90-haos-locale.conf",
           f"LANG={language}\nLANGUAGE={language.split('_')[0]}\n", entry, replace=True)
    return {"region_configured": True, "restart_session": True}


def mark_ready():
    entry = _observer()
    if not name_exists():
        raise PermissionError("a normal user display name must be chosen first")
    # Never overwrite a prior migrated setup receipt. Does not enable login or
    # change the user's locked-password observer privilege.
    _write(".config/herald-os/setup-done", "Graphical owner setup complete\n", entry)
    return {"normal_user_ready": True}
