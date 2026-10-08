"""Root-only storage broker. No arbitrary path, command, shell or mount options API."""

from __future__ import annotations

import hashlib
import json
import os
import re
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


def prepare():
    if os.geteuid() != 0:
        raise PermissionError("storage preparation requires the owner/root service")
    import grp
    import pwd
    policy = trusted_json(Path("/etc/haos/volumes.json"))
    grants = validate_policy(policy)
    devices = inventory()
    base = Path("/run/haos-volumes")
    base.mkdir(mode=0o750, exist_ok=True)
    os.chown(base, 0, pwd.getpwnam("haos-agent").pw_gid)
    mounted = []
    try:
        for grant in grants:
            if grant["mode"] in {"blocked", "system-managed"}:
                continue
            target = resolve_volume(grant["id"], devices)
            destination = base / grant["key"]
            destination.mkdir(mode=0o750, exist_ok=True)
            if destination.is_symlink() or os.path.ismount(destination):
                raise PermissionError("unexpected existing broker mount; stop and reconcile before preparation")
            options = "nodev,nosuid,noexec," + ("ro" if grant["mode"] == "read-only" else "rw")
            subprocess.run(["/usr/bin/mount", "--types", target["fstype"], "--options", options,
                            "--source", target["path"], "--target", str(destination)], check=True)
            mounted.append(destination)
        runtime = Path("/run/haos-policy")
        runtime.mkdir(mode=0o750, exist_ok=True)
        os.chown(runtime, 0, pwd.getpwnam("haos-agent").pw_gid)
        atomic_json(runtime / "sandbox.json", {"version": 1, "grants": grants}, mode=0o640,
                    gid=pwd.getpwnam("haos-agent").pw_gid)
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
