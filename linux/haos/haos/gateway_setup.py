"""Owner-only pairing and transport credential setup; never callable by a model."""

import getpass
import grp
import hashlib
import json
import os
import pwd
import stat
import subprocess
from pathlib import Path

from .gateway import GatewayPolicy
from .policy import atomic_json
from .sandbox import trusted_json

CONFIG = Path("/etc/haos")


def owner_delivery(args, policy):
    """Drop root before opening controller-owned SQLite; keep credentials out of the child."""
    from .owner import audit, stopped
    if os.geteuid() != 0:
        raise PermissionError("outbox reconciliation requires authenticated owner authority")
    stopped_gateway()
    stopped()
    GatewayPolicy(policy)
    params = {"after": args.after} if args.gateway_action == "deliveries" else None
    if params is None:
        if not isinstance(args.note, str) or not 1 <= len(args.note.strip()) <= 2000:
            raise ValueError("bounded non-secret owner inspection evidence is required")
        params = {"delivery_id": args.delivery_id, "attempt": args.attempt, "decision": args.decision,
                  "owner_uid": int(os.environ.get("SUDO_UID", "0")),
                  "note_sha256": hashlib.sha256(args.note.strip().encode()).hexdigest(), "receipt": args.receipt,
                  "confirmed_not_delivered": args.confirm_not_delivered}
    directory = Path("/usr/lib/haos").lstat()
    if not stat.S_ISDIR(directory.st_mode) or directory.st_uid != 0 or directory.st_mode & 0o022:
        raise PermissionError("untrusted installed recovery code")
    account = pwd.getpwnam("haos-control")
    if account.pw_uid == 0 or account.pw_gid == 0:
        raise PermissionError("controller recovery may not retain root")
    result = subprocess.run(["/usr/bin/python3", "-E", "-s", "-m", "haos.gateway_recovery"],
                            input=json.dumps({"action": args.gateway_action, "policy": policy, "params": params}),
                            text=True, capture_output=True, check=False, timeout=15,
                            user=account.pw_uid, group=account.pw_gid, extra_groups=[], umask=0o077,
                            cwd="/usr/lib/haos", env={"PATH": "/usr/bin:/bin", "LANG": "C.UTF-8", "PYTHONDONTWRITEBYTECODE": "1"})
    if result.returncode or len(result.stdout) > 256 * 1024:
        raise RuntimeError("offline outbox recovery failed; inspect the private ledger and selected attempt")
    value = json.loads(result.stdout)
    if args.gateway_action == "reconcile-delivery":
        audit("gateway.delivery-reconciled", {**value, "note_sha256": params["note_sha256"]})
    return value


def stopped_gateway():
    result = subprocess.run(["/usr/bin/systemctl", "show", "--property=LoadState,ActiveState,MainPID,ControlPID",
                             "haos-gateway.service"], check=True, capture_output=True, text=True, timeout=15)
    state = dict(line.split("=", 1) for line in result.stdout.splitlines() if "=" in line)
    if (state.get("LoadState") not in {"loaded", "masked"} or state.get("ActiveState") != "inactive"
            or state.get("MainPID") != "0" or state.get("ControlPID") != "0"):
        raise PermissionError("stop haos-gateway.service before changing pairing or transport credentials")


def load(config=CONFIG):
    metadata = config.lstat()
    if not stat.S_ISDIR(metadata.st_mode) or metadata.st_uid != 0 or metadata.st_mode & 0o022:
        raise PermissionError("untrusted gateway configuration directory")
    policy = trusted_json(config / "gateways.json") if (config / "gateways.json").exists() else {
        "version": 1, "connectors": [], "bindings": []}
    GatewayPolicy(policy)
    secret_path = config / "gateway-credentials"
    if secret_path.exists() and stat.S_IMODE(secret_path.lstat().st_mode) & 0o077:
        raise PermissionError("transport credential store must be root-private")
    credentials = trusted_json(secret_path) if secret_path.exists() else {"connectors": {}}
    if set(credentials) != {"connectors"} or not isinstance(credentials["connectors"], dict):
        raise ValueError("invalid protected transport credentials")
    return policy, credentials


def persist(policy, credentials, *, config=CONFIG, gid=None):
    if os.geteuid() != 0:
        raise PermissionError("gateway setup requires authenticated owner authority")
    load(config)
    GatewayPolicy(policy)
    if set(credentials["connectors"]) != {c["id"] for c in policy["connectors"]}:
        raise ValueError("transport credentials and connector policy disagree")
    gid = grp.getgrnam("haos-gateway").gr_gid if gid is None else gid
    # Service is stopped. A crash between writes cannot introduce an authorized new sender.
    atomic_json(config / "gateway-credentials", credentials)
    atomic_json(config / "gateways.json", policy, mode=0o640, gid=gid)


def owner_gateway(args):
    from .owner import audit
    if os.geteuid() != 0:
        raise PermissionError("gateway setup requires authenticated owner authority")
    if args.gateway_action in {"start", "stop"}:
        subprocess.run(["/usr/bin/systemctl", args.gateway_action, "haos-gateway.service"], check=True, timeout=30)
        audit("gateway." + args.gateway_action, {})
        return {"action": args.gateway_action}
    policy, credentials = load()
    if args.gateway_action == "status":
        return {"policy": policy, "credential_configured": sorted(credentials["connectors"])}
    if args.gateway_action in {"deliveries", "reconcile-delivery"}:
        return owner_delivery(args, policy)
    stopped_gateway()
    if args.gateway_action == "setup":
        if args.platform not in {"telegram", "discord"}:
            raise ValueError("currently provisioned transports: telegram, discord")
        if any(c["id"] != args.connector and c["platform"] == args.platform for c in policy["connectors"]):
            raise ValueError("one isolated adapter per platform is currently supported")
        # Validate the proposed connector before asking for a credential.
        policy["connectors"] = [c for c in policy["connectors"] if c["id"] != args.connector] + [{"id": args.connector, "platform": args.platform}]
        GatewayPolicy(policy)
        token = getpass.getpass("Bot token (stored only in the owner-protected credential store): ")
        if not 16 <= len(token) <= 4096 or any(c.isspace() or ord(c) < 32 for c in token):
            raise ValueError("invalid transport credential")
        credentials["connectors"][args.connector] = {"token": token}
    elif args.gateway_action == "pair":
        binding = {"id": args.binding, "connector": args.connector, "sender": args.sender, "chat": args.chat,
                   "scope": args.scope, "thread": args.thread, "identity": args.identity,
                   "capabilities": args.capabilities}
        policy["bindings"] = [b for b in policy["bindings"] if b["id"] != args.binding] + [binding]
    elif args.gateway_action == "revoke":
        if not any(b["id"] == args.binding for b in policy["bindings"]):
            raise KeyError("unknown gateway binding")
        policy["bindings"] = [b for b in policy["bindings"] if b["id"] != args.binding]
    elif args.gateway_action == "remove":
        policy["connectors"] = [c for c in policy["connectors"] if c["id"] != args.connector]
        policy["bindings"] = [b for b in policy["bindings"] if b["connector"] != args.connector]
        credentials["connectors"].pop(args.connector, None)
    persist(policy, credentials)
    audit("gateway." + args.gateway_action, {"connector": getattr(args, "connector", None), "binding": getattr(args, "binding", None)})
    return {"configured": True, "action": args.gateway_action, "restart_required": True}
