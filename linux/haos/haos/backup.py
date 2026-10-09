"""Owner-only encrypted local snapshots; restores never replace live state."""
import json
import os
from pathlib import Path
import re
import secrets
import stat
import subprocess
import tempfile
from dataclasses import dataclass

SNAPSHOT = re.compile(r"[a-f0-9]{64}")
SOURCES = [Path(p) for p in ("/var/lib/haos-workspace", "/var/lib/haos-agent",
                           "/var/lib/haos-control", "/etc/haos")]


@dataclass(frozen=True)
class Retention:
    keep_last: int = 7
    keep_daily: int = 7
    keep_weekly: int = 4
    keep_monthly: int = 12

    def arguments(self):
        limits = {"keep_last": (1, 512), "keep_daily": (0, 366),
                  "keep_weekly": (0, 104), "keep_monthly": (0, 120)}
        result = []
        for key, (low, high) in limits.items():
            value = getattr(self, key)
            if type(value) is not int or not low <= value <= high:
                raise ValueError("retention requires bounded whole counts and at least one latest snapshot per group")
            result.extend(["--" + key.replace("_", "-"), str(value)])
        return result


def private_directory(path: Path):
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    info = path.lstat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o077:
        raise PermissionError("backup directory must be root-owned/private and not a symlink")


def private_password(path: Path):
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o077 or info.st_nlink != 1:
        raise PermissionError("backup password must be a private root-owned regular file")


class Repository:
    def __init__(self, root: Path, password: Path):
        if os.geteuid() != 0:
            raise PermissionError("backup recovery requires authenticated owner/root authority")
        self.root, self.password = root, password
        self.repository = root / "repository"
        private_directory(root)

    def command(self, *args):
        private_password(self.password)
        private_directory(self.repository)
        # Do not inherit password commands, remote backends, proxies or shell hooks.
        result = subprocess.run(["/usr/bin/restic", "--repo", str(self.repository),
                                 "--password-file", str(self.password), "--no-cache", "--json", *args],
                                env={"PATH": "/usr/bin:/bin", "HOME": str(self.root), "LANG": "C.UTF-8"},
                                capture_output=True, text=True, timeout=7200, check=False)
        # Partial snapshot exit 3, wrong credentials and interrupted commands fail.
        if result.returncode:
            raise RuntimeError(f"restic failed (exit {result.returncode}); no successful backup/restore receipt")
        return result.stdout

    def initialize(self):
        if not self.password.exists():
            if (self.repository / "config").exists():
                raise PermissionError("existing backup key is missing; restore the original owner key")
            fd = os.open(self.password, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
            try:
                os.write(fd, (secrets.token_hex(32) + "\n").encode())
                os.fsync(fd)
            finally:
                os.close(fd)
        if not (self.repository / "config").exists():
            self.command("init", "--repository-version", "2")
        self.command("check")
        return {"repository": str(self.repository), "password_file": str(self.password)}

    def create(self, sources):
        paths = [Path(p) for p in sources]
        if not paths or any(not p.is_absolute() or p.is_symlink() or not p.is_dir() for p in paths):
            raise ValueError("backup sources must be existing absolute directories")
        for path in paths:
            if path == self.root or self.root.is_relative_to(path) or path.is_relative_to(self.root):
                raise ValueError("backup sources must not overlap the repository/recovery directory")
        output = self.command("backup", "--one-file-system", "--tag", "haos-owner", *map(str, paths))
        summaries = [row for line in output.splitlines() if isinstance(row := json.loads(line), dict)
                     and row.get("message_type") == "summary"]
        identifier = summaries[-1].get("snapshot_id", "") if summaries else ""
        if not isinstance(identifier, str) or not SNAPSHOT.fullmatch(identifier):
            raise ValueError("missing complete snapshot receipt")
        return {"snapshot_id": identifier, "sources": list(map(str, paths))}

    def restore(self, identifier: str):
        if not SNAPSHOT.fullmatch(identifier):
            raise ValueError("restore requires an exact 64-character snapshot ID")
        self.command("check", "--read-data")
        staging = self.root / "restores"
        private_directory(staging)
        destination = Path(tempfile.mkdtemp(prefix="snapshot-", dir=staging))
        try:
            self.command("restore", identifier, "--target", str(destination), "--verify")
        except BaseException:
            # Preserve incomplete restored data for owner inspection. Never call it success.
            (destination / "HAOS_RESTORE_INCOMPLETE").touch(mode=0o600)
            raise
        return {"snapshot_id": identifier, "staging_directory": str(destination), "live_state_replaced": False}

    def snapshots(self):
        # Never return file names, host/user identities or arbitrary Restic output.
        rows = json.loads(self.command("snapshots", "--tag", "haos-owner"))
        if not isinstance(rows, list):
            raise ValueError("invalid encrypted snapshot inventory")
        result = []
        for row in rows:
            identifier = row.get("id") if isinstance(row, dict) else None
            if not isinstance(identifier, str) or not SNAPSHOT.fullmatch(identifier):
                raise ValueError("snapshot inventory lacks exact identifiers")
            result.append(identifier)
        return {"snapshot_ids": result}

    def retain(self, policy: Retention, *, apply=False):
        if type(apply) is not bool:
            raise ValueError("retention application must be an explicit boolean")
        arguments = policy.arguments()
        # Verify encrypted data before a destructive operation. Grouping by host
        # and source paths preserves at least one snapshot for every backup scope.
        self.command("check", "--read-data")
        # Do not combine --prune with forget: even with --json, Restic emits
        # prune's human progress after forget's JSON array. Keep the structured
        # deletion receipt separate from garbage collection and verify both.
        output = self.command("forget", "--tag", "haos-owner", "--group-by", "host,paths",
                              *arguments, *([] if apply else ["--dry-run"]))
        groups = json.loads(output)
        if not isinstance(groups, list):
            raise ValueError("invalid retention receipt")
        keep, remove = set(), set()
        for group in groups:
            if not isinstance(group, dict):
                raise ValueError("invalid retention group")
            for field, identifiers in (("keep", keep), ("remove", remove)):
                rows = group.get(field) or []
                if not isinstance(rows, list):
                    raise ValueError("invalid retention snapshots")
                for row in rows:
                    identifier = row.get("id") if isinstance(row, dict) else None
                    if not isinstance(identifier, str) or not SNAPSHOT.fullmatch(identifier):
                        raise ValueError("retention requires exact snapshot identifiers")
                    identifiers.add(identifier)
        if keep.intersection(remove):
            raise ValueError("contradictory retention receipt")
        if apply:
            self.command("prune")
            self.command("check", "--read-data")
            remaining = set(self.snapshots()["snapshot_ids"])
            if remove.intersection(remaining) or not keep.issubset(remaining):
                raise RuntimeError("encrypted retention inventory differs from the deletion receipt")
        return {"dry_run": not apply, "kept_snapshot_ids": sorted(keep), "selected_for_removal": sorted(remove),
                "encrypted_data_checked": True, "scope": "haos-owner; grouped by host and source paths"}


def owner_backup(action: str, identifier=None, *, retention=None, apply=False):
    # Fixed local scope, no CLI option that accepts arbitrary paths or remote URLs.
    from .owner import audit, stopped
    stopped()
    root = Path("/var/lib/haos-owner")
    private_directory(root)
    repository = Repository(root / "backup", Path("/etc/haos/backup-password"))
    if action == "init":
        result = repository.initialize()
    elif action == "create":
        permissions = root / "volume-acls"
        # The permission journal is a sibling of the repository, not its parent;
        # include it when present without recursively backing up the backup.
        sources = SOURCES + ([permissions] if permissions.exists() or permissions.is_symlink() else [])
        result = repository.create(sources)
    elif action == "check":
        repository.command("check", "--read-data")
        result = {"repository_checked": True}
    elif action == "restore":
        result = repository.restore(identifier)
    elif action == "snapshots":
        result = repository.snapshots()
    elif action == "retention":
        try:
            result = repository.retain(retention or Retention(), apply=apply)
        except Exception:
            # A failed post-operation receipt/check must not hide a possible
            # deletion. Never log the raw Restic exception or repository data.
            audit("backup.retention-failed", {"may_have_modified_repository": apply})
            raise
    else:
        raise ValueError("unsupported backup operation")
    audit("backup." + action, result)
    return result
