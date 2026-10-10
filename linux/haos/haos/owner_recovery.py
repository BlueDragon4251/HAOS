"""Single-use owner recovery codes and an independent, fixed-action local console."""

from __future__ import annotations

import fcntl
import getpass
import hashlib
import hmac
import os
from pathlib import Path
import re
import secrets
import stat
import sys
import time

from . import enrollment
from .policy import atomic_json
from .sandbox import trusted_json

RECOVERY = Path("/var/lib/haos-owner/recovery.json")
LOCK = Path("/run/haos-owner-recovery.lock")
_CODE = re.compile(r"[A-Za-z0-9_-]{43}\Z")


def code_hash(salt, code):
    return hashlib.sha256((salt + ":" + code).encode()).hexdigest()


class RecoveryCodes:
    def __init__(self, path=RECOVERY, lock=LOCK):
        if os.geteuid() != 0:
            raise PermissionError("owner recovery requires the privileged local broker")
        self.path, self.lock = Path(path), Path(lock)
        enrollment.protected_directory(self.path.parent)
        enrollment.protected_directory(self.lock.parent)

    def _locked(self):
        fd = os.open(self.lock, os.O_WRONLY | os.O_CREAT | os.O_NOFOLLOW, 0o600)
        info = os.fstat(fd)
        if info.st_uid != 0 or info.st_mode & 0o077 or not stat.S_ISREG(info.st_mode):
            os.close(fd)
            raise PermissionError("untrusted owner recovery lock")
        fcntl.flock(fd, fcntl.LOCK_EX)
        return fd

    def _load(self):
        if self.path.is_symlink():
            raise PermissionError("recovery store must not be a symlink")
        if not self.path.exists():
            return {"version": 1, "owners": {}}
        info = self.path.lstat()
        if not stat.S_ISREG(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o077:
            raise PermissionError("recovery store must be root-private")
        data = trusted_json(self.path)
        if set(data) != {"version", "owners"} or type(data["version"]) is not int or data["version"] != 1 or not isinstance(data["owners"], dict):
            raise PermissionError("unsupported recovery store")
        for uid, entry in data["owners"].items():
            if (not uid.isdecimal() or int(uid) < 1000 or not isinstance(entry, dict)
                    or set(entry) != {"salt", "hashes", "failures", "retry_at"}
                    or not isinstance(entry["salt"], str) or not re.fullmatch(r"[0-9a-f]{64}", entry["salt"])
                    or not isinstance(entry["hashes"], list) or len(entry["hashes"]) > 10
                    or any(not isinstance(v, str) or not re.fullmatch(r"[0-9a-f]{64}", v) for v in entry["hashes"])
                    or type(entry["failures"]) is not int or entry["failures"] < 0
                    or type(entry["retry_at"]) not in {int, float} or not 0 <= entry["retry_at"] < float("inf")):
                raise PermissionError("invalid recovery credential record")
        return data

    def issue(self, uid: int):
        if type(uid) is not int or uid < 1000:
            raise PermissionError("recovery codes require a separate owner identity")
        fd = self._locked()
        try:
            data = self._load()
            codes = [secrets.token_urlsafe(32) for _ in range(10)]
            salt = secrets.token_hex(32)
            data["owners"][str(uid)] = {"salt": salt, "hashes": [code_hash(salt, code) for code in codes],
                                       "failures": 0, "retry_at": 0}
            atomic_json(self.path, data)
            return codes
        finally:
            os.close(fd)

    def consume(self, uid: int, code: str, *, now=None):
        now = time.time() if now is None else now
        fd = self._locked()
        try:
            data = self._load()
            entry = data["owners"].get(str(uid))
            if entry is None or entry["retry_at"] > now:
                raise PermissionError("recovery authentication refused or temporarily delayed")
            candidate = code_hash(entry["salt"], code) if isinstance(code, str) and _CODE.fullmatch(code) else ""
            matching = [value for value in entry["hashes"] if hmac.compare_digest(candidate, value)]
            if not matching:
                entry["failures"] += 1
                entry["retry_at"] = now + min(300, 2 ** min(entry["failures"], 9))
                atomic_json(self.path, data)
                raise PermissionError("recovery authentication refused or temporarily delayed")
            entry["hashes"].remove(matching[0])
            entry["failures"], entry["retry_at"] = 0, 0
            # Consumption is durable before any password/system mutation.
            atomic_json(self.path, data)
        finally:
            os.close(fd)


def owners():
    if not enrollment.REGISTRY.exists():
        return []
    data = trusted_json(enrollment.REGISTRY)
    if data.get("schema_version") != 1 or not isinstance(data.get("owners"), list):
        raise PermissionError("invalid enrolled-owner registry")
    return data["owners"]


def enrolled_owner(username):
    rows = [row for row in owners() if row.get("username") == username]
    if len(rows) != 1:
        raise PermissionError("owner identity is not enrolled")
    entry = enrollment.verify_account(username, rows[0]["uid"])
    return entry


def require_console():
    if os.geteuid() != 0 or not all(stream.isatty() for stream in (sys.stdin, sys.stdout, sys.stderr)):
        raise PermissionError("use the trusted local owner console")


def print_codes(username):
    require_console()
    from .owner import audit
    entry = enrolled_owner(username)
    codes = RecoveryCodes().issue(entry.pw_uid)
    audit("owner.recovery-codes-issued", {"uid": entry.pw_uid, "count": len(codes)})
    print("Store these single-use recovery codes separately from this computer and its backups.")
    print("All previously issued codes for this owner have been revoked.")
    for code in codes:
        print(code)


def main():
    require_console()
    from .owner import audit, stopped
    print("HAOS owner onboarding and recovery. No agent or desktop is required.")
    if not owners():
        print("No owner is enrolled. Set up the owner from this local console.")
        username = input("New owner account: ").strip()
        # Another console may have enrolled the owner while this prompt was open.
        if owners():
            raise PermissionError("initial onboarding has already completed; authenticate with recovery instead")
        enrollment.run("/usr/bin/systemctl", "stop", "haos-gateway.service", "haos-controller.service", "haos-hermes.service")
        stopped()
        enrollment.enroll_interactive(username, initial_only=True)
        print_codes(username)
        enrollment.run("/usr/bin/systemctl", "start", "haos-hermes.service", "haos-controller.service", "haos-gateway.service")
        print("Owner enrolled. Authenticate with the owner password for subsequent administration.")
        return
    username = input("Enrolled owner account: ").strip()
    entry = enrolled_owner(username)
    code = getpass.getpass("Single-use recovery code: ")
    RecoveryCodes().consume(entry.pw_uid, code)
    audit("owner.recovery-authenticated", {"uid": entry.pw_uid})
    choice = input("Action: reset-password or stop-agent: ").strip()
    if choice == "reset-password":
        password = getpass.getpass("New owner password (at least 20 characters): ")
        if password != getpass.getpass("Repeat owner password: "):
            raise ValueError("owner passwords do not match; the recovery code was consumed")
        enrollment.password_quality(username, password)
        enrollment.verify_account(username, entry.pw_uid)
        enrollment.run("/usr/sbin/chpasswd", secret=f"{username}:{password}\n")
        status = enrollment.run("/usr/bin/passwd", "--status", username).split()
        if status[:2] != [username, "P"]:
            raise PermissionError("owner password reset could not be verified")
        audit("owner.password-recovered", {"uid": entry.pw_uid})
        print("Owner password changed. This recovery code is no longer valid.")
    elif choice == "stop-agent":
        enrollment.run("/usr/bin/systemctl", "stop", "haos-gateway.service", "haos-controller.service", "haos-hermes.service")
        audit("owner.recovery-runtime-stopped", {"uid": entry.pw_uid})
        print("Execution services stopped. Recovery remains available.")
    else:
        raise ValueError("unsupported recovery action; the recovery code was consumed")


if __name__ == "__main__":
    try:
        main()
    except (PermissionError, ValueError, RuntimeError, OSError):
        # Console failure never journals entered secrets or opens a shell.
        print("Owner recovery refused or could not complete. Check identity, code and system state.", file=sys.stderr)
        raise SystemExit(1)
