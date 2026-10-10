"""Per-machine credentials. Never bake a shared backend token into an image."""

import grp
import os
import secrets
import sys
from pathlib import Path

from .policy import atomic_json
from .observer import secure_observer
from .ui_credentials import prepare as prepare_ui_credentials


def main():
    if os.geteuid() != 0:
        raise PermissionError("host initialization requires root")
    user = sys.argv[1]
    if user in {"root", "haos-agent", "haos-control", "haos-gateway", "haos-provider"}:
        raise ValueError("observer/owner and service accounts must be separate")
    secure_observer(user)
    gid = grp.getgrnam("haos-ui").gr_gid
    config = Path("/etc/haos")
    config.mkdir(mode=0o755, exist_ok=True)
    prepare_ui_credentials(config, gid)
    atomic_json(config / "controller.json", {"backend_url": "http://127.0.0.1:9119", "control_users": [user]}, mode=0o644)
    if not (config / "provider-token").exists():
        atomic_json(config / "provider-token", {"token": secrets.token_urlsafe(48)})
    if not (config / "provider-credentials").exists():
        atomic_json(config / "provider-credentials", {"api_key": None})
    if not (config / "volumes.json").exists():
        atomic_json(config / "volumes.json", {"version": 1, "volumes": []})
    (config / "enabled").touch(mode=0o644)


if __name__ == "__main__":
    main()
