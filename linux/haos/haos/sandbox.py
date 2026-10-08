"""Fail-closed filesystem view for the system-owned Hermes service."""

from __future__ import annotations

import json
import os
import stat
from pathlib import Path

MODES = {"blocked", "read-only", "full-data-access", "system-managed"}


def trusted_json(path: Path) -> dict:
    # Both file and containing directory are root-owned and cannot be replaced by an agent.
    for parent in (path.parent, path):
        metadata = parent.lstat()
        if metadata.st_uid != 0 or metadata.st_mode & 0o022 or stat.S_ISLNK(metadata.st_mode):
            raise PermissionError(f"untrusted service configuration: {parent}")
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        metadata = os.fstat(fd)
        if metadata.st_uid != 0 or metadata.st_mode & 0o022 or not stat.S_ISREG(metadata.st_mode):
            raise PermissionError("untrusted service configuration")
        with os.fdopen(fd, "r") as stream:
            fd = -1
            config = json.load(stream)
    finally:
        if fd >= 0:
            os.close(fd)
    if not isinstance(config, dict):
        raise ValueError("service configuration must be an object")
    return config


def command(grants: list[dict], token: str, *, certificates: list[str]) -> list[str]:
    if not token.strip():
        raise ValueError("missing backend credential")
    args = ["/usr/bin/bwrap", "--unshare-all", "--unshare-user", "--share-net", "--die-with-parent", "--new-session",
            "--disable-userns", "--assert-userns-disabled", "--cap-drop", "ALL", "--clearenv",
            "--ro-bind", "/usr", "/usr", "--symlink", "usr/bin", "/bin", "--symlink", "usr/sbin", "/sbin",
            "--symlink", "usr/lib", "/lib", "--symlink", "usr/lib64", "/lib64",
            "--proc", "/proc", "--dev", "/dev", "--tmpfs", "/tmp", "--dir", "/run", "--dir", "/etc",
            "--dir", "/var", "--dir", "/home", "--bind", "/var/lib/haos-agent", "/home/agent",
            "--bind", "/var/lib/haos-workspace", "/workspace", "--dir", "/volumes"]
    # Do not bind the host's /etc, /run, /var, home folders, /sys or raw devices.
    for path in certificates:
        if path not in {"/etc/ssl", "/etc/pki", "/etc/hosts", "/etc/resolv.conf", "/etc/nsswitch.conf", "/etc/localtime"}:
            raise ValueError("unexpected runtime configuration path")
        args.extend(["--ro-bind", path, path])
    seen = set()
    for grant in grants:
        key, mode = grant.get("key"), grant.get("mode")
        if mode not in MODES:
            raise ValueError("unknown volume access mode")
        if mode in {"blocked", "system-managed"}:
            continue
        if not isinstance(key, str) or len(key) != 64 or any(c not in "0123456789abcdef" for c in key) or key in seen:
            raise ValueError("invalid volume mount key")
        seen.add(key)
        args.extend(["--ro-bind" if mode == "read-only" else "--bind", f"/run/haos-volumes/{key}", f"/volumes/{key}"])
    for name, value in {
        "HOME": "/home/agent", "HERMES_HOME": "/home/agent/.hermes", "PATH": "/usr/lib/haos/hermes/.venv/bin:/usr/bin",
        "LANG": "C.UTF-8", "PYTHONDONTWRITEBYTECODE": "1", "PYTHONUNBUFFERED": "1",
        "HERMES_DASHBOARD_SESSION_TOKEN": token,
    }.items():
        args.extend(["--setenv", name, value])
    return args + ["--chdir", "/workspace", "--", "/usr/lib/haos/hermes/.venv/bin/hermes", "serve",
                   "--host", "127.0.0.1", "--port", "9119", "--no-open"]


def main():
    config = trusted_json(Path("/run/haos-policy/sandbox.json"))
    credential = Path(os.environ["CREDENTIALS_DIRECTORY"]) / "backend-token"
    certs = [str(p) for p in map(Path, ["/etc/ssl", "/etc/pki", "/etc/hosts", "/etc/resolv.conf", "/etc/nsswitch.conf", "/etc/localtime"]) if p.exists()]
    args = command(config["grants"], credential.read_text().strip(), certificates=certs)
    os.execv(args[0], args)


if __name__ == "__main__":
    main()
