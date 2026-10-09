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
        result = subprocess.run(["/usr/bin/systemctl", "show", "--property=LoadState,ActiveState,MainPID,ControlPID", unit],
                                check=True, capture_output=True, text=True)
        state = dict(line.split("=", 1) for line in result.stdout.splitlines() if "=" in line)
        # is-active's exit 3 also covers activating/deactivating units: neither is stopped.
        if (state.get("LoadState") not in {"loaded", "masked"} or state.get("ActiveState") != "inactive"
                or state.get("MainPID") != "0" or state.get("ControlPID") != "0"):
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
    gateway = sub.add_parser("gateway", help="owner-authenticated transport credentials and exact sender pairing")
    gateway_sub = gateway.add_subparsers(dest="gateway_action", required=True)
    for action in ("status", "start", "stop"):
        gateway_sub.add_parser(action)
    setup = gateway_sub.add_parser("setup")
    setup.add_argument("connector")
    setup.add_argument("platform", choices=["telegram", "discord"])
    pair = gateway_sub.add_parser("pair")
    pair.add_argument("binding")
    pair.add_argument("connector")
    pair.add_argument("sender")
    pair.add_argument("chat")
    pair.add_argument("--identity", required=True)
    pair.add_argument("--scope", default="")
    pair.add_argument("--thread", default="")
    pair.add_argument("--capabilities", nargs="+", choices=["create", "read", "cancel", "answer"], default=["create", "read", "cancel", "answer"])
    revoke = gateway_sub.add_parser("revoke")
    revoke.add_argument("binding")
    remove = gateway_sub.add_parser("remove")
    remove.add_argument("connector")
    enroll = sub.add_parser("enroll", help="create a separate password-authenticated owner from a trusted root console")
    enroll.add_argument("username")
    recovery = sub.add_parser("recovery-codes", help="issue ten single-use codes at an authenticated owner console")
    recovery.add_argument("username")
    backup = sub.add_parser("backup")
    backup_sub = backup.add_subparsers(dest="backup_action", required=True)
    for action in ("init", "create", "check"):
        backup_sub.add_parser(action)
    restore = backup_sub.add_parser("restore")
    restore.add_argument("snapshot_id")
    grant = sub.add_parser("volume")
    grant.add_argument("id", help="UUID:<filesystem UUID> or PARTUUID:<partition UUID>")
    grant.add_argument("mode", choices=["blocked", "read-only", "full-data-access", "system-managed"])
    reconciler = sub.add_parser("reconcile")
    reconciler.add_argument("mission_id")
    reconciler.add_argument("--note", required=True, help="evidence from inspection of Hermes/processes/files")
    args = parser.parse_args()
    if os.geteuid() != 0:
        raise PermissionError("authenticate as the owner with sudo or a recovery console")
    if args.action == "recovery-codes":
        from .owner_recovery import print_codes
        print_codes(args.username)
    elif args.action == "gateway":
        from .gateway_setup import owner_gateway
        print(json.dumps(owner_gateway(args), indent=2))
    elif args.action == "enroll":
        from .enrollment import enroll_interactive
        from .owner_recovery import print_codes
        stopped()
        print(json.dumps(enroll_interactive(args.username), indent=2))
        print_codes(args.username)
    elif args.action == "backup":
        from .backup import owner_backup
        print(json.dumps(owner_backup(args.backup_action, getattr(args, "snapshot_id", None)), indent=2))
    elif args.action == "prepare":
        stopped()
        prepare()
    elif args.action == "cleanup":
        stopped()
        cleanup()
    elif args.action == "status":
        print(json.dumps({"policy": trusted_json(Path("/etc/haos/volumes.json")), "devices": inventory()}, indent=2))
    elif args.action in {"stop", "start"}:
        verb = args.action
        units = ["haos-controller.service", "haos-hermes.service", "haos-policy.service"]
        if verb == "stop":
            subprocess.run(["/usr/bin/systemctl", "stop", "haos-gateway.service"], check=True)
        subprocess.run(["/usr/bin/systemctl", verb, *units], check=True)
        if verb == "start":
            subprocess.run(["/usr/bin/systemctl", "start", "haos-gateway.service"], check=True)
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
