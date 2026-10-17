"""Owner-authenticated HAOS bootc channel selection and unattended staged updates.

Credentials never cross the observer/agent APIs. Public status contains no token,
registry errors, filenames, arbitrary image references or account names.
"""
from __future__ import annotations

import getpass
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import sys
import tempfile
from datetime import datetime, timezone

PRIVATE = Path("/etc/haos/update.json")
AUTH = Path("/etc/ostree/auth.json")
PUBLIC = Path("/run/haos-update/status.json")
IMAGE = "ghcr.io/bluedragon4251/haos"
CHANNELS = {"dev": IMAGE + ":dev-current", "stable": IMAGE + ":stable"}
ENV = {"PATH": "/usr/sbin:/usr/bin:/sbin:/bin", "LANG": "C", "LC_ALL": "C"}


def root():
    if os.geteuid() != 0:
        raise PermissionError("HAOS image updates require authenticated owner authority")


def load_config(path=PRIVATE):
    if path.is_symlink():
        raise PermissionError("update configuration may not be a symlink")
    if not path.exists():
        return {"channel": "unconfigured", "auto_stage": False}
    st = path.stat()
    if not stat.S_ISREG(st.st_mode) or st.st_uid != 0 or st.st_mode & 0o077:
        raise PermissionError("update configuration must be private")
    cfg = json.loads(path.read_text())
    if (not isinstance(cfg, dict) or set(cfg) != {"channel", "auto_stage"}
            or cfg["channel"] not in CHANNELS or type(cfg["auto_stage"]) is not bool):
        raise ValueError("invalid update channel configuration")
    return cfg


def persist_config(cfg, path=PRIVATE):
    if cfg["channel"] not in CHANNELS or type(cfg["auto_stage"]) is not bool:
        raise ValueError("unsupported update channel")
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    if path.is_symlink():
        raise PermissionError("update configuration may not be a symlink")
    fd, tmp = tempfile.mkstemp(prefix=".update-", dir=path.parent)
    try:
        with os.fdopen(fd, "w") as f:
            os.fchmod(f.fileno(), 0o600)
            json.dump(cfg, f)
            f.write("\n")
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    finally:
        Path(tmp).unlink(missing_ok=True)


def publish(state, *, channel, auto_stage, error=None, reboot_required=False, path=PUBLIC):
    """Strictly whitelisted non-secret status displayed by the Electron shell."""
    if channel not in {*CHANNELS, "unconfigured"}:
        raise ValueError("unsupported channel")
    if state not in {"unconfigured", "configured", "checking", "up-to-date", "update-available",
                     "staged", "offline-or-error", "checked"}:
        raise ValueError("unsupported update state")
    data = {"version": 1, "channel": channel, "auto_stage": bool(auto_stage),
            "state": state, "reboot_required": bool(reboot_required),
            "checked_at": datetime.now(timezone.utc).isoformat(),
            "message": (error if error in {"registry unavailable", "bootc check failed",
                                         "bootc stage failed"} else None)}
    path.parent.mkdir(parents=True, mode=0o755, exist_ok=True)
    if path.parent.is_symlink():
        raise PermissionError("update status directory may not be a symlink")
    directory = path.parent.stat()
    if directory.st_uid != 0 or not stat.S_ISDIR(directory.st_mode) or directory.st_mode & 0o022:
        raise PermissionError("update status directory is not root-controlled")
    # The root service uses UMask=0077; explicitly permit the observer to read
    # the non-secret receipt, never the separate credential/config directory.
    os.chmod(path.parent, 0o755)
    fd, tmp = tempfile.mkstemp(prefix=".status-", dir=path.parent)
    try:
        with os.fdopen(fd, "w") as f:
            os.fchmod(f.fileno(), 0o644)
            json.dump(data, f)
            f.write("\n")
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    finally:
        Path(tmp).unlink(missing_ok=True)
    return data


def command(*args, input_text=None, timeout=300):
    result = subprocess.run(args, input=input_text, capture_output=True, text=True,
                            env=ENV, timeout=timeout)
    if result.returncode:
        # Never surface remote registry output that might echo secrets.
        raise RuntimeError("HAOS update command failed (" + str(result.returncode) + ")")
    return result.stdout


def has_auth(path=AUTH):
    if path.is_symlink() or not path.exists():
        return False
    info = path.stat()
    return (stat.S_ISREG(info.st_mode) and info.st_uid == 0
            and not info.st_mode & 0o077 and info.st_size <= 32768)


def login():
    root()
    if not all(stream.isatty() for stream in (sys.stdin, sys.stdout, sys.stderr)):
        raise PermissionError("enter GHCR credentials only in an authenticated owner terminal")
    username = input("GitHub username (GHCR read:packages): ").strip()
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9-]{0,38}", username):
        raise ValueError("invalid GitHub username")
    token = getpass.getpass("Read-only GHCR token (hidden): ")
    if not 16 <= len(token) <= 512 or any(ord(c) < 33 or ord(c) > 126 for c in token):
        raise ValueError("invalid GHCR token")
    AUTH.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
    if AUTH.is_symlink():
        raise PermissionError("registry authfile may not be a symlink")
    fd, tmp = tempfile.mkstemp(prefix=".haos-ghcr-", dir=AUTH.parent)
    try:
        with os.fdopen(fd, "w") as f:
            os.fchmod(f.fileno(), 0o600)
            f.write("{}\n")
        # Temporary credentials are published only after GHCR verifies them.
        command("/usr/bin/podman", "login", "--authfile", tmp, "--username", username,
                "--password-stdin", "ghcr.io", input_text=token + "\n", timeout=90)
        os.chmod(tmp, 0o600)
        os.replace(tmp, AUTH)
    finally:
        Path(tmp).unlink(missing_ok=True)
    return {"ghcr_auth_configured": True, "token_disclosed": False}


def switch_channel(channel, auto_stage):
    root()
    if channel not in CHANNELS:
        raise ValueError("select stable or dev")
    if type(auto_stage) is not bool:
        raise ValueError("invalid auto-stage option")
    if channel == "dev" and not has_auth():
        raise PermissionError("authenticate to private GHCR first: haos-owner update login")
    # Ref is from the fixed, reviewed allowlist, never supplied by renderer/model.
    # bootc validates/pulls the target before staging; the prior deployment remains for rollback.
    command("/usr/bin/bootc", "switch", CHANNELS[channel], timeout=1800)
    cfg = {"channel": channel, "auto_stage": auto_stage}
    persist_config(cfg)
    return publish("staged", **cfg, reboot_required=True)


def watch(*, stage=False):
    root()
    cfg = load_config()
    if cfg["channel"] == "unconfigured":
        return publish("unconfigured", **cfg)
    if cfg["channel"] == "dev" and not has_auth():
        return publish("offline-or-error", **cfg, error="registry unavailable")
    try:
        stdout = command("/usr/bin/bootc", "upgrade", "--check", timeout=300)
        # Do not translate an unknown CLI message into a claim of new updates.
        available = bool(re.search(r"(?m)^(?:.{0,40})?(?<!no )(?<!no new )(?:update|upgrade) available\b", stdout, re.I)) and not bool(re.search(r"\bno (?:new )?(?:update|upgrade) available\b", stdout, re.I))
        if available and stage and cfg["auto_stage"]:
            command("/usr/bin/bootc", "upgrade", timeout=1800)
            return publish("staged", **cfg, reboot_required=True)
        return publish("update-available" if available else "checked", **cfg)
    except (RuntimeError, OSError, subprocess.TimeoutExpired):
        return publish("offline-or-error", **cfg, error="bootc check failed")


def stage_now():
    root()
    cfg = load_config()
    if cfg["channel"] == "unconfigured" or (cfg["channel"] == "dev" and not has_auth()):
        raise PermissionError("configure the update channel and private GHCR login first")
    command("/usr/bin/bootc", "upgrade", timeout=1800)
    return publish("staged", **cfg, reboot_required=True)


def logout():
    root()
    if AUTH.is_symlink():
        raise PermissionError("authfile may not be a symlink")
    if AUTH.exists():
        info = AUTH.stat()
        if not stat.S_ISREG(info.st_mode) or info.st_uid != 0:
            raise PermissionError("untrusted registry authfile")
        AUTH.unlink()
    cfg = load_config()
    return publish("configured" if cfg["channel"] in CHANNELS else "unconfigured", **cfg)


def owner_update(args):
    root()
    from .owner import audit
    if args.update_action == "status":
        cfg = load_config()
        return {**cfg, "ghcr_auth_configured": has_auth(), "secret_exposed": False}
    if args.update_action == "login":
        result = login()
        audit("update.login", {"ghcr": True})
        return result
    if args.update_action == "channel":
        result = switch_channel(args.channel, args.auto_stage)
        audit("update.channel", {"channel": args.channel, "auto_stage": args.auto_stage})
        return result
    if args.update_action == "check":
        return watch()
    if args.update_action == "stage":
        result = stage_now()
        audit("update.staged", {})
        return result
    if args.update_action == "logout":
        result = logout()
        audit("update.logout", {})
        return result
    raise ValueError("unsupported update operation")


if __name__ == "__main__":
    if sys.argv[1:] != ["watch"]:
        raise SystemExit("usage: python -m haos.update watch")
    print(json.dumps(watch(stage=True)))
