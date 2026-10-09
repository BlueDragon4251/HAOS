"""Root-only storage broker. No arbitrary path, command, shell or mount options API."""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
import subprocess
import tempfile
from pathlib import Path

from .sandbox import MODES, trusted_json

IDENTITY = re.compile(r"^(UUID|PARTUUID):([A-Za-z0-9][A-Za-z0-9-]{0,127})$")
SYSTEM_MOUNTS = {"/", "/usr", "/boot", "/boot/efi", "/var", "/home", "/etc", "/opt", "/srv"}
FILESYSTEMS = {"ext4", "xfs", "btrfs", "vfat", "ntfs3"}


def validate_policy(policy: dict) -> list[dict]:
    if set(policy) != {"version", "volumes"} or type(policy["version"]) is not int or policy["version"] != 1:
        raise ValueError("unsupported storage policy schema")
    volumes = policy["volumes"]
    if not isinstance(volumes, list) or len(volumes) > 64:
        raise ValueError("volumes must be a list of at most 64 entries")
    seen, result = set(), []
    for item in volumes:
        if not isinstance(item, dict) or set(item) != {"id", "mode"}:
            raise ValueError("volume entries accept only id and mode")
        identifier, mode = item["id"], item["mode"]
        if not isinstance(identifier, str) or not IDENTITY.fullmatch(identifier) or identifier in seen:
            raise ValueError("invalid or duplicate stable volume identity")
        if mode not in MODES:
            raise ValueError("unknown storage access mode")
        seen.add(identifier)
        result.append({"id": identifier, "mode": mode, "key": hashlib.sha256(identifier.encode()).hexdigest()})
    return result


def atomic_json(path: Path, value: dict, *, mode: int = 0o600, gid: int = 0):
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(dir=path.parent, prefix=".haos-")
    try:
        os.fchmod(fd, mode)
        os.fchown(fd, 0, gid)
        with os.fdopen(fd, "w") as stream:
            json.dump(value, stream, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        parent_fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(parent_fd)
        finally:
            os.close(parent_fd)
    finally:
        Path(temporary).unlink(missing_ok=True)


def agent_directory(path: Path, gid: int):
    """Publish root-owned, group-traversable runtime directories despite UMask=0077."""
    if os.geteuid() != 0 or type(gid) is not int or gid <= 0:
        raise PermissionError("a root broker and separate agent group are required")
    if os.path.ismount(path):
        raise PermissionError("unexpected mount at a broker runtime directory")
    path.mkdir(mode=0o700, exist_ok=True)
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        info = os.fstat(fd)
        if info.st_uid != 0 or not stat.S_ISDIR(info.st_mode) or info.st_mode & 0o022:
            raise PermissionError("untrusted broker runtime directory")
        # mkdir's requested mode is reduced by the service umask. Apply the
        # minimum read/traverse rights explicitly to this verified inode.
        os.fchown(fd, 0, gid)
        os.fchmod(fd, 0o750)
        info = os.fstat(fd)
        if (info.st_uid, info.st_gid, stat.S_IMODE(info.st_mode)) != (0, gid, 0o750):
            raise PermissionError("broker runtime directory authority could not be verified")
    finally:
        os.close(fd)


def inventory() -> list[dict]:
    data = json.loads(subprocess.check_output([
        "/usr/bin/lsblk", "--json", "--paths", "--output", "PATH,TYPE,FSTYPE,UUID,PARTUUID,MOUNTPOINTS,MAJ:MIN"], text=True))
    flat = []

    def visit(node, ancestors: tuple[str, ...]):
        path = node["path"]
        flat.append({**node, "ancestors": ancestors})
        for child in node.get("children", []):
            visit(child, ancestors + (path,))

    for node in data["blockdevices"]:
        visit(node, ())
    return flat


def resolve_volume(identifier: str, devices: list[dict]) -> dict:
    match = IDENTITY.fullmatch(identifier)
    if not match:
        raise ValueError("invalid stable identity")
    field, value = match[1].lower(), match[2]
    # Repeated entries from device-mapper topology still represent the same device.
    candidates = {d["path"]: d for d in devices if d.get(field) == value}
    if len(candidates) != 1:
        raise PermissionError("volume identity is missing or ambiguous")
    target = next(iter(candidates.values()))
    protected = set()
    for device in devices:
        if SYSTEM_MOUNTS.intersection(device.get("mountpoints") or []):
            protected.update((device["path"], *device["ancestors"]))
    if protected.intersection((target["path"], *target["ancestors"])):
        raise PermissionError("system/owner disk cannot be granted to an agent")
    if target.get("fstype") not in FILESYSTEMS or target.get("type") not in {"part", "disk", "crypt", "lvm"}:
        raise PermissionError("unsupported data filesystem; unlock encrypted data through owner recovery first")
    return target


def verify_mount(grant: dict, target: dict, destination: Path):
    """Do not publish a device name that was reused between discovery and mount."""
    mounted = json.loads(subprocess.check_output([
        "/usr/bin/findmnt", "--json", "--first-only", "--mountpoint", str(destination),
        "--output", "TARGET,FSTYPE,UUID,PARTUUID,MAJ:MIN,OPTIONS"], text=True)).get("filesystems", [])
    if len(mounted) != 1:
        raise PermissionError("broker mount is missing or ambiguous")
    actual = mounted[0]
    match = IDENTITY.fullmatch(grant["id"])
    options = set((actual.get("options") or "").split(","))
    expected_access = "ro" if grant["mode"] == "read-only" else "rw"
    if (not match or actual.get(match[1].lower()) != match[2]
            or actual.get("target") != str(destination) or actual.get("fstype") != target["fstype"]
            or not target.get("maj:min") or actual.get("maj:min") != target["maj:min"]
            or not {"nodev", "nosuid", "noexec", expected_access}.issubset(options)
            or ("rw" if expected_access == "ro" else "ro") in options):
        raise PermissionError("mounted device identity or access flags differ from owner policy")
    # Re-read topology as well: a changed UUID or a newly ambiguous/system disk
    # must fail before the independently protected runtime grant is committed.
    current = resolve_volume(grant["id"], inventory())
    if current["path"] != target["path"] or current.get("maj:min") != target["maj:min"]:
        raise PermissionError("data device topology changed during preparation")


def prepare():
    if os.geteuid() != 0:
        raise PermissionError("storage preparation requires the owner/root service")
    # A failed new preparation must not leave an older compiled grant usable.
    Path("/run/haos-policy/sandbox.json").unlink(missing_ok=True)
    import pwd
    agent_gid = pwd.getpwnam("haos-agent").pw_gid
    policy = trusted_json(Path("/etc/haos/volumes.json"))
    grants = validate_policy(policy)
    devices = inventory()
    base = Path("/run/haos-volumes")
    agent_directory(base, agent_gid)
    mounted = []
    try:
        for grant in grants:
            if grant["mode"] in {"blocked", "system-managed"}:
                continue
            target = resolve_volume(grant["id"], devices)
            destination = base / grant["key"]
            if destination.is_symlink() or os.path.ismount(destination):
                raise PermissionError("unexpected existing broker mount; stop and reconcile before preparation")
            agent_directory(destination, agent_gid)
            options = "nodev,nosuid,noexec," + ("ro" if grant["mode"] == "read-only" else "rw")
            subprocess.run(["/usr/bin/mount", "--types", target["fstype"], "--options", options,
                            "--source", target["path"], "--target", str(destination)], check=True)
            mounted.append(destination)
            verify_mount(grant, target, destination)
        runtime = Path("/run/haos-policy")
        agent_directory(runtime, agent_gid)
        atomic_json(runtime / "sandbox.json", {"version": 1, "grants": grants}, mode=0o640,
                    gid=agent_gid)
    except BaseException:
        for destination in reversed(mounted):
            subprocess.run(["/usr/bin/umount", str(destination)], check=True)
        raise


def cleanup():
    if os.geteuid() != 0:
        raise PermissionError("storage cleanup requires root")
    base = Path("/run/haos-volumes")
    if base.exists():
        for destination in base.iterdir():
            if re.fullmatch(r"[a-f0-9]{64}", destination.name) and os.path.ismount(destination):
                subprocess.run(["/usr/bin/umount", str(destination)], check=True)
    Path("/run/haos-policy/sandbox.json").unlink(missing_ok=True)


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Root storage service entrypoint; ordered by systemd")
    parser.add_argument("action", choices=["prepare", "cleanup"])
    action = parser.parse_args().action
    (prepare if action == "prepare" else cleanup)()
