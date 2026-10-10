"""Root-only boot migration: revoke the observer's full backend credential."""
import grp
import json
import os
from pathlib import Path
import secrets
import stat
import tempfile

from .policy import atomic_json
from .web_access import TOKEN


def existing(path):
    try:
        metadata = path.lstat()
    except FileNotFoundError:
        return None
    if (not stat.S_ISREG(metadata.st_mode) or metadata.st_uid != 0
            or metadata.st_nlink != 1 or metadata.st_mode & 0o022 or metadata.st_size > 4096):
        raise PermissionError("untrusted dashboard credential or descriptor")
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        info = os.fstat(fd)
        if (info.st_dev, info.st_ino) != (metadata.st_dev, metadata.st_ino):
            raise PermissionError("dashboard authority changed during inspection")
        return os.read(fd, 4097).decode()
    finally:
        os.close(fd)


def write_token(path, value, *, gid, mode):
    fd, temporary = tempfile.mkstemp(dir=path.parent, prefix=".haos-ui-")
    try:
        os.fchown(fd, 0, gid)
        os.fchmod(fd, mode)
        os.write(fd, (value + "\n").encode())
        os.fsync(fd)
        os.close(fd)
        fd = -1
        os.replace(temporary, path)
        directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        if fd >= 0:
            os.close(fd)
        Path(temporary).unlink(missing_ok=True)


def prepare(config, ui_gid):
    if os.geteuid() != 0 or type(ui_gid) is not int or ui_gid <= 0:
        raise PermissionError("dashboard authority requires the root boot broker")
    metadata = config.lstat()
    if not stat.S_ISDIR(metadata.st_mode) or metadata.st_uid != 0 or metadata.st_mode & 0o022:
        raise PermissionError("untrusted dashboard configuration directory")
    descriptor = existing(config / "backend.json")
    old = json.loads(descriptor) if descriptor is not None else None
    legacy = {"version": 1, "baseUrl": "http://127.0.0.1:9119", "tokenFile": "/etc/haos/backend-token"}
    backend = existing(config / "backend-token")
    observer = existing(config / "ui-token")
    expected = {"version": 2, "baseUrl": "http://127.0.0.1:9119", "tokenFile": "/etc/haos/ui-token"}
    if old is not None and old not in (legacy, expected):
        raise PermissionError("unsupported dashboard descriptor; owner inspection required")
    private = config / "backend-token"
    metadata = private.lstat() if backend is not None else None
    if old != expected or (metadata is not None and (stat.S_IMODE(metadata.st_mode) != 0o600 or metadata.st_gid != 0)):
        # The previous token was observer-readable. Changing its mode alone
        # cannot revoke copies: issue an independent new backend credential.
        backend = secrets.token_urlsafe(48)
    elif backend is None or not TOKEN.fullmatch(backend.strip()):
        raise PermissionError("missing or invalid private backend credential")
    else:
        backend = backend.strip()
    if observer is None:
        observer = secrets.token_urlsafe(48)
    else:
        observer = observer.strip()
        if not TOKEN.fullmatch(observer) or observer == backend:
            raise PermissionError("invalid observer capability")
    # Atomic replacement also removes any old named ACLs. Descriptor is last:
    # an interrupted migration repeats safely before either service starts.
    write_token(config / "backend-token", backend, gid=0, mode=0o600)
    write_token(config / "ui-token", observer, gid=ui_gid, mode=0o640)
    atomic_json(config / "backend.json", expected, mode=0o644)


def main():
    import subprocess
    for unit in ("haos-hermes.service", "haos-controller.service"):
        status = subprocess.run(["/usr/bin/systemctl", "show", unit, "--property=ActiveState", "--value"],
                                capture_output=True, text=True, timeout=5, check=True)
        if status.stdout.strip() not in {"inactive", "failed"}:
            raise PermissionError("dashboard migration requires stopped execution services")
    prepare(Path("/etc/haos"), grp.getgrnam("haos-ui").gr_gid)


if __name__ == "__main__":
    main()
