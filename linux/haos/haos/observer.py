"""Separate the automatically displayed observer from owner/root authority."""

import grp
import os
from pathlib import Path
import pwd
import re
import stat
import subprocess
import tempfile

PRIVILEGED_GROUPS = {"wheel", "sudo", "admin"}
SUDOERS = Path("/etc/sudoers.d/zzzz-haos-observer")
ENV = {"PATH": "/usr/sbin:/usr/bin:/sbin:/bin", "LANG": "C", "LC_ALL": "C"}


def command(*args):
    return subprocess.run(list(args), env=ENV, check=True, capture_output=True, text=True)


def account(user):
    if os.geteuid() != 0:
        raise PermissionError("observer security requires root")
    if not isinstance(user, str) or not re.fullmatch(r"[a-z_][a-z0-9_-]{0,31}", user):
        raise ValueError("invalid observer account name")
    entry = pwd.getpwnam(user)
    if entry.pw_uid < 1000 or user in {"haos-agent", "haos-control"}:
        raise PermissionError("observer must be a separate non-system account")
    if any(other.pw_uid == entry.pw_uid and other.pw_name != user for other in pwd.getpwall()):
        raise PermissionError("observer UID must not be shared with another account")
    return entry


def deny_sudo(uid, path=SUDOERS):
    # A UID specification covers renaming/aliases as well as the current name.
    # This final included rule also denies inherited per-user NOPASSWD grants.
    parent = path.parent
    parent.mkdir(mode=0o750, exist_ok=True)
    info = parent.lstat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o022:
        raise PermissionError("sudoers directory must be root-owned and protected")
    if path.is_symlink():
        raise PermissionError("observer sudo rule must not be a symlink")
    fd, temporary = tempfile.mkstemp(prefix=".haos-observer-", dir=parent)
    try:
        with os.fdopen(fd, "w") as output:
            output.write(f"# HAOS observer has no owner authority. Managed by haos.observer.\n#{uid} ALL=(ALL:ALL) !ALL\n")
            output.flush()
            os.fchmod(output.fileno(), 0o440)
            os.fsync(output.fileno())
        command("/usr/sbin/visudo", "-c", "-f", temporary)
        os.replace(temporary, path)
        command("/usr/sbin/visudo", "-c")
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def secure_observer(user, sudoers=SUDOERS):
    entry = account(user)
    for group in grp.getgrall():
        if group.gr_name not in PRIVILEGED_GROUPS:
            continue
        if entry.pw_gid == group.gr_gid:
            raise PermissionError("observer primary group must not grant administrator authority")
        if user in group.gr_mem:
            command("/usr/bin/gpasswd", "--delete", user, group.gr_name)
    status = command("/usr/bin/passwd", "--status", user).stdout.split()
    if len(status) < 2 or status[0] != user or status[1] not in {"NP", "L", "P"}:
        raise PermissionError("observer password status could not be verified")
    if status[1] == "NP":
        command("/usr/sbin/usermod", "--lock", user)
        status = command("/usr/bin/passwd", "--status", user).stdout.split()
        if len(status) < 2 or status[0] != user or status[1] != "L":
            raise PermissionError("empty observer password was not locked")
    deny_sudo(entry.pw_uid, sudoers)
    return {"observer_uid": entry.pw_uid, "administrator_groups_removed": True,
            "empty_password_denied": True, "sudo_denied": True}


def main():
    # No account-selection endpoint exists for the UI or isolated agent.
    from .owner import audit
    from .sandbox import trusted_json
    configuration = trusted_json(Path("/etc/haos/controller.json"))
    users = configuration.get("control_users")
    if not isinstance(users, list) or len(users) != 1:
        raise PermissionError("exactly one configured observer account is required")
    audit("observer.secured", secure_observer(users[0]))


if __name__ == "__main__":
    main()
