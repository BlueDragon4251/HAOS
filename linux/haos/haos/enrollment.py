"""Root-console enrollment; no UI, agent or gateway endpoint can select an owner."""

from __future__ import annotations

import fcntl
import getpass
import grp
import os
from pathlib import Path
import pwd
import re
import stat
import subprocess
import sys
import tempfile

from .observer import ENV, PRIVILEGED_GROUPS
from .policy import atomic_json
from .sandbox import trusted_json

SUDOERS = Path("/etc/sudoers.d")
REGISTRY = Path("/var/lib/haos-owner/owners.json")
LOCK = Path("/run/haos-owner-enroll.lock")


def run(*args, secret=None):
    # Never expose subprocess output or password-bearing input in an exception.
    try:
        result = subprocess.run(list(args), input=secret, env=ENV, capture_output=True,
                                text=True, timeout=30)
    except (OSError, subprocess.TimeoutExpired):
        raise RuntimeError(f"owner enrollment command unavailable: {args[0]}") from None
    if result.returncode:
        raise RuntimeError(f"owner enrollment command failed: {args[0]}")
    return result.stdout


def protected_directory(path):
    for item in (path, *path.parents):
        info = item.lstat()
        if not stat.S_ISDIR(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o022:
            raise PermissionError("owner authority directory must be root-owned and protected")


def validate_name(user, observer):
    if not isinstance(user, str) or not re.fullmatch(r"[a-z][a-z0-9_-]{0,30}", user):
        raise ValueError("owner username must be a simple lowercase account name")
    if user in {"root", "hermes", "haos-agent", "haos-control", "haos-gateway", "haos-provider", observer}:
        raise PermissionError("owner must be separate from observer and service accounts")
    try:
        pwd.getpwnam(user)
    except KeyError:
        return
    raise PermissionError("enrollment requires a new account; existing accounts are never repurposed")


def password_quality(user, password):
    if (not isinstance(password, str) or not 20 <= len(password) <= 256
            or len(password.encode("utf-8")) > 512
            or any(ord(c) < 32 or ord(c) == 127 for c in password)
            or user.casefold() in password.casefold()):
        raise ValueError("use a strong 20–256 character password without the account name or control characters")
    score = run("/usr/bin/pwscore", user, secret=password + "\n").strip()
    if not score.isdecimal() or not 0 <= int(score) <= 100:
        raise PermissionError("password quality could not be verified")


def verify_account(user, expected_uid=None):
    entry = pwd.getpwnam(user)
    if entry.pw_uid < 1000 or (expected_uid is not None and entry.pw_uid != expected_uid):
        raise PermissionError("owner account identity changed or is a system account")
    if any(other.pw_uid == entry.pw_uid and other.pw_name != user for other in pwd.getpwall()):
        raise PermissionError("owner UID must not be shared")
    for group in grp.getgrall():
        if group.gr_name in PRIVILEGED_GROUPS | {"haos-ui", "haos-agent", "haos-control", "haos-gateway", "haos-provider"}:
            if entry.pw_gid == group.gr_gid or user in group.gr_mem:
                raise PermissionError("owner must not inherit administrator, observer or service groups")
    return entry


def sudo_rule(uid):
    if type(uid) is not int or uid < 1000:
        raise PermissionError("invalid owner UID")
    return ("# Managed HAOS owner; authenticate separately for every fixed CLI invocation.\n"
            f"Defaults:#{uid} timestamp_timeout=0, env_reset, !setenv, authenticate, !rootpw, !targetpw, !runaspw\n"
            f"#{uid} ALL=(ALL:ALL) !ALL\n"
            f"#{uid} ALL=(root:root) PASSWD: NOSETENV: /usr/bin/haos-owner\n")


def install_rule(uid, directory=SUDOERS):
    protected_directory(directory)
    target = directory / f"zzzz-haos-owner-{uid}"
    if target.exists() or target.is_symlink():
        raise PermissionError("owner rule already exists")
    fd, name = tempfile.mkstemp(prefix=".haos-owner-", dir=directory)
    published = False
    try:
        with os.fdopen(fd, "w") as stream:
            stream.write(sudo_rule(uid))
            stream.flush()
            os.fchmod(stream.fileno(), 0o440)
            os.fchown(stream.fileno(), 0, 0)
            os.fsync(stream.fileno())
        run("/usr/sbin/visudo", "-c", "-f", name)
        os.replace(name, target)
        published = True
        run("/usr/sbin/visudo", "-c")
        return target
    except BaseException:
        if published:
            target.unlink(missing_ok=True)
        raise
    finally:
        Path(name).unlink(missing_ok=True)


def enroll(user, password, *, initial_only=False):
    if os.geteuid() != 0:
        raise PermissionError("owner enrollment requires an authenticated root console")
    config = trusted_json(Path("/etc/haos/controller.json"))
    observers = config.get("control_users")
    if not isinstance(observers, list) or len(observers) != 1 or not isinstance(observers[0], str):
        raise PermissionError("exactly one configured observer is required")
    validate_name(user, observers[0])
    password_quality(user, password)
    protected_directory(LOCK.parent)
    fd = os.open(LOCK, os.O_WRONLY | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    created, success, rule = False, False, None
    registry_before, registry_written = None, False
    try:
        info = os.fstat(fd)
        if info.st_uid != 0 or info.st_mode & 0o077 or not stat.S_ISREG(info.st_mode):
            raise PermissionError("untrusted owner enrollment lock")
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        validate_name(user, observers[0])
        REGISTRY.parent.mkdir(mode=0o700, exist_ok=True)
        protected_directory(REGISTRY.parent)
        registry = trusted_json(REGISTRY) if REGISTRY.exists() else {"schema_version": 1, "owners": []}
        if registry.get("schema_version") != 1 or not isinstance(registry.get("owners"), list):
            raise PermissionError("invalid owner enrollment registry")
        if initial_only and registry["owners"]:
            raise PermissionError("initial owner onboarding has already completed")
        registry_before = registry
        created = True  # Also clean up an account left by a failed/timed-out useradd.
        run("/usr/sbin/useradd", "--create-home", "--user-group", "--shell", "/bin/bash", "--", user)
        entry = verify_account(user)
        status = run("/usr/bin/passwd", "--status", user).split()
        if len(status) < 2 or status[:2] != [user, "L"]:
            raise PermissionError("new owner must start with a locked password")
        rule = install_rule(entry.pw_uid)
        run("/usr/sbin/chpasswd", secret=f"{user}:{password}\n")
        verify_account(user, entry.pw_uid)
        status = run("/usr/bin/passwd", "--status", user).split()
        if len(status) < 2 or status[:2] != [user, "P"]:
            raise PermissionError("owner password installation could not be verified")
        record = {"username": user, "uid": entry.pw_uid, "authority": "password-authenticated-fixed-cli"}
        atomic_json(REGISTRY, {**registry, "owners": [*registry["owners"], record]})
        registry_written = True
        from .owner import audit
        audit("owner.enrolled", record)
        success = True
        return record
    finally:
        try:
            if not success and created:
                if rule is not None:
                    rule.unlink(missing_ok=True)
                # Preserve the new home for inspection; never delete user data.
                try:
                    pwd.getpwnam(user)
                except KeyError:
                    pass
                else:
                    run("/usr/sbin/usermod", "--lock", user)
                if registry_written:
                    atomic_json(REGISTRY, registry_before)
        finally:
            os.close(fd)


def enroll_interactive(user, *, initial_only=False):
    if not sys.stdin.isatty() or not sys.stderr.isatty():
        raise PermissionError("owner passwords must be entered at a trusted interactive console")
    password = getpass.getpass("New owner password (at least 20 characters): ")
    if password != getpass.getpass("Repeat owner password: "):
        raise ValueError("owner passwords do not match")
    return enroll(user, password, initial_only=initial_only)
