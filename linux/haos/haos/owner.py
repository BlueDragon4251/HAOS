"""Recovery and policy authority; callable by an authenticated owner via sudo/console."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import time
from pathlib import Path

from .policy import atomic_json, cleanup, inventory, prepare, resolve_volume, validate_policy
from .sandbox import trusted_json
from .store import MissionStore


def stopped():
    for unit in ("haos-controller.service", "haos-hermes.service"):
        result = subprocess.run(["/usr/bin/systemctl", "is-active", "--quiet", unit], check=False)
        if result.returncode not in {3, 4}:
            raise PermissionError(f"stop {unit} before modifying authority or reconciling a mission")


def audit(kind: str, details: dict):
    path = Path("/var/lib/haos-owner")
    path.mkdir(mode=0o700, exist_ok=True)
    fd = os.open(path / "audit.jsonl", os.O_WRONLY | os.O_APPEND | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    try:
        os.write(fd, (json.dumps({"at": time.time(), "kind": kind, "owner_uid": os.environ.get("SUDO_UID", "0"), **details}) + "\n").encode())
        os.fsync(fd)
    finally:
        os.close(fd)


def main():
    parser = argparse.ArgumentParser(description="HAOS owner recovery; agent and UI policy cannot grant root authority")
    sub = parser.add_subparsers(dest="action", required=True)
    sub.add_parser("prepare")
    sub.add_parser("cleanup")
    sub.add_parser("status")
    sub.add_parser("stop")
    sub.add_parser("start")
    grant = sub.add_parser("volume")
    grant.add_argument("id", help="UUID:<filesystem UUID> or PARTUUID:<partition UUID>")
    grant.add_argument("mode", choices=["blocked", "read-only", "full-data-access", "system-managed"])
    reconciler = sub.add_parser("reconcile")
    reconciler.add_argument("mission_id")
    reconciler.add_argument("--note", required=True, help="evidence from inspection of Hermes/processes/files")
    args = parser.parse_args()
    if os.geteuid() != 0:
        raise PermissionError("authenticate as the owner with sudo or a recovery console")
    if args.action == "prepare":
        prepare()
    elif args.action == "cleanup":
        cleanup()
    elif args.action == "status":
        print(json.dumps({"policy": trusted_json(Path("/etc/haos/volumes.json")), "devices": inventory()}, indent=2))
    elif args.action in {"stop", "start"}:
        verb = args.action
        units = ["haos-controller.service", "haos-hermes.service", "haos-policy.service"]
        subprocess.run(["/usr/bin/systemctl", verb, *units], check=True)
        audit(f"runtime.{verb}", {})
    elif args.action == "volume":
        stopped()
        policy = trusted_json(Path("/etc/haos/volumes.json"))
        new = {"id": args.id, "mode": args.mode}
        policy["volumes"] = [v for v in policy["volumes"] if v["id"] != args.id] + [new]
        validate_policy(policy)
        if args.mode in {"read-only", "full-data-access"}:
            resolve_volume(args.id, inventory())
        cleanup()
        atomic_json(Path("/etc/haos/volumes.json"), policy)
        audit("volume.policy", new)
    elif args.action == "reconcile":
        stopped()
        store = MissionStore(Path("/var/lib/haos-control/missions.db"))
        try:
            store.reconcile(args.mission_id, f"owner:{os.environ.get('SUDO_UID', '0')}", args.note)
        finally:
            store.close()
        audit("mission.reconciled", {"id": args.mission_id, "note": args.note})


if __name__ == "__main__":
    main()
