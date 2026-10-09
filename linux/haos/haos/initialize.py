"""Per-machine credentials. Never bake a shared backend token into an image."""

import grp
import os
import secrets
import sys
from pathlib import Path

from .policy import atomic_json
from .observer import secure_observer


def main():
    if os.geteuid() != 0:
        raise PermissionError("host initialization requires root")
    user = sys.argv[1]
    if user in {"root", "haos-agent", "haos-control", "haos-gateway"}:
        raise ValueError("observer/owner and service accounts must be separate")
    secure_observer(user)
    gid = grp.getgrnam("haos-ui").gr_gid
    config = Path("/etc/haos")
    config.mkdir(mode=0o755, exist_ok=True)
    token = config / "backend-token"
    if not token.exists():
        fd = os.open(token, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o640)
        try:
            os.fchown(fd, 0, gid)
            os.write(fd, (secrets.token_urlsafe(48) + "\n").encode())
            os.fsync(fd)
        finally:
            os.close(fd)
    atomic_json(config / "backend.json", {"version": 1, "baseUrl": "http://127.0.0.1:9119", "tokenFile": str(token)}, mode=0o644)
    atomic_json(config / "controller.json", {"backend_url": "http://127.0.0.1:9119", "control_users": [user]}, mode=0o644)
    if not (config / "volumes.json").exists():
        atomic_json(config / "volumes.json", {"version": 1, "volumes": []})
    (config / "enabled").touch(mode=0o644)


if __name__ == "__main__":
    main()
