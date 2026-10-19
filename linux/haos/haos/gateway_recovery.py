"""Offline outbox recovery, delegated by the owner to the ledger's unprivileged UID.

No controller/transport RPC exposes these operations. No model, credential,
provider call or network delivery runs here.
"""

import hashlib
import json
import os
from pathlib import Path
import pwd
import re
import resource
import stat
import sys
import time
import uuid

from .gateway import GatewayEngine, GatewayPolicy
from .store import Conflict, MissionStore

DATABASE = Path("/var/lib/haos-control/missions.db")
RECOVERABLE = {"sending", "uncertain", "failed"}


def private_store(path: Path) -> MissionStore:
    """Never create a missing ledger or follow replaced/hardlinked SQLite files."""
    uid = os.geteuid()
    directory = path.parent.lstat()
    if not stat.S_ISDIR(directory.st_mode) or directory.st_uid != uid or directory.st_mode & 0o077:
        raise PermissionError("outbox ledger directory must belong privately to its service")
    for candidate in (path, path.with_name(path.name + "-wal"), path.with_name(path.name + "-shm")):
        try:
            metadata = candidate.lstat()
        except FileNotFoundError:
            if candidate == path:
                raise
            continue
        if (not stat.S_ISREG(metadata.st_mode) or metadata.st_uid != uid
                or metadata.st_nlink != 1 or metadata.st_mode & 0o077):
            raise PermissionError("untrusted private outbox ledger")
    return MissionStore(path)


def unresolved(store: MissionStore, after: int = 0) -> dict:
    if type(after) is not int or after < 0:
        raise ValueError("after must be a nonnegative cursor")
    rows = store.db.execute("""SELECT o.rowid AS cursor,o.id,o.state,o.attempt,o.content,r.mission_id
        FROM gateway_outbox o JOIN gateway_routes r ON r.id=o.route_id
        WHERE o.state IN ('sending','uncertain','failed') AND o.rowid>? ORDER BY o.rowid LIMIT 100""", (after,)).fetchall()
    deliveries = []
    for row in rows:
        if (not isinstance(row["id"], str) or not re.fullmatch(r"[0-9a-f]{64}", row["id"])
                or str(uuid.UUID(row["mission_id"])) != row["mission_id"]
                or type(row["attempt"]) is not int or not 1 <= row["attempt"] <= 5):
            raise ValueError("invalid outbox metadata")
        if len(row["content"]) > 1800:
            raise ValueError("outbox content exceeds its platform chunk bound")
        deliveries.append({"cursor": row["cursor"], "delivery_id": row["id"], "mission_id": row["mission_id"],
                           "state": row["state"], "attempt": row["attempt"],
                           "content_sha256": hashlib.sha256(row["content"].encode()).hexdigest()})
    return {"deliveries": deliveries, "next_cursor": rows[-1]["cursor"] if rows else after}


def reconcile(store: MissionStore, policy: GatewayPolicy, request: dict) -> dict:
    if set(request) != {"delivery_id", "attempt", "decision", "owner_uid", "note_sha256", "receipt", "confirmed_not_delivered"}:
        raise ValueError("invalid owner outbox decision")
    delivery, attempt, decision = request["delivery_id"], request["attempt"], request["decision"]
    if not isinstance(delivery, str) or not re.fullmatch(r"[0-9a-f]{64}", delivery):
        raise ValueError("invalid delivery ID")
    if type(attempt) is not int or not 1 <= attempt <= 5 or decision not in {"delivered", "retry", "discard"}:
        raise ValueError("invalid attempt or recovery decision")
    if (type(request["owner_uid"]) is not int or not 0 <= request["owner_uid"] < 2**32 - 1
            or not isinstance(request["note_sha256"], str) or not re.fullmatch(r"[0-9a-f]{64}", request["note_sha256"])
            or type(request["confirmed_not_delivered"]) is not bool):
        raise ValueError("invalid owner inspection evidence")
    receipt = request["receipt"]
    # The supported Telegram/Discord adapters return numeric remote message IDs.
    if decision == "delivered":
        if not isinstance(receipt, str) or not re.fullmatch(r"[1-9][0-9]{0,31}", receipt):
            raise ValueError("delivered requires the inspected remote message ID")
        if request["confirmed_not_delivered"]:
            raise ValueError("contradictory owner evidence")
    elif receipt is not None:
        raise ValueError("only delivered may carry a remote receipt")
    if decision == "retry" and request["confirmed_not_delivered"] is not True:
        raise PermissionError("retry requires explicit confirmation of non-delivery")
    if decision != "retry" and request["confirmed_not_delivered"]:
        raise ValueError("non-delivery confirmation applies only to retry")
    with store.transaction():
        row = store.db.execute("""SELECT o.*,r.mission_id,r.binding_id,r.binding_digest
            FROM gateway_outbox o JOIN gateway_routes r ON r.id=o.route_id WHERE o.id=?""", (delivery,)).fetchone()
        if row is None:
            raise KeyError("unknown delivery")
        if row["attempt"] != attempt:
            raise Conflict("stale owner decision for a different delivery attempt")
        if row["state"] not in RECOVERABLE:
            raise Conflict("delivery does not require offline reconciliation")
        if decision != "discard":
            binding = policy.current_binding(dict(row))
            if "read" not in binding["capabilities"]:
                raise PermissionError("gateway result delivery is no longer authorized")
        if decision == "retry" and attempt >= 5:
            raise Conflict("delivery retry budget exhausted")
        state = {"delivered": "delivered", "retry": "pending", "discard": "revoked"}[decision]
        store.db.execute("UPDATE gateway_outbox SET state=?,receipt=?,lease_until=NULL,next_attempt=?,error=? WHERE id=?",
                         (state, receipt, time.time(), None if decision == "delivered" else "owner-" + decision, delivery))
        store._event(row["mission_id"], "owner.gateway-reconciled", {
            "actor": f"owner:{request['owner_uid']}", "delivery": delivery, "attempt": attempt,
            "decision": decision, "state": state, "receipt": receipt, "note_sha256": request["note_sha256"],
            "confirmed_not_delivered": request["confirmed_not_delivered"]})
    return {"delivery_id": delivery, "attempt": attempt, "decision": decision, "state": state}


def main():
    account = pwd.getpwnam("haos-control")
    if os.geteuid() == 0 or os.geteuid() != account.pw_uid:
        raise PermissionError("outbox recovery must run without root as the ledger service")
    resource.setrlimit(resource.RLIMIT_AS, (256 * 1024 * 1024, 256 * 1024 * 1024))
    resource.setrlimit(resource.RLIMIT_CPU, (5, 5))
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    raw = sys.stdin.buffer.read(1024 * 1024 + 1)
    if len(raw) > 1024 * 1024:
        raise ValueError("owner recovery input exceeds its bound")
    data = json.loads(raw)
    if not isinstance(data, dict) or set(data) != {"action", "policy", "params"} or not isinstance(data["params"], dict):
        raise ValueError("invalid owner recovery request")
    policy = GatewayPolicy(data["policy"])
    store = private_store(DATABASE)
    try:
        GatewayEngine(store)
        if data["action"] == "deliveries" and set(data["params"]) == {"after"}:
            result = unresolved(store, data["params"]["after"])
        elif data["action"] == "reconcile-delivery":
            result = reconcile(store, policy, data["params"])
        else:
            raise ValueError("unknown offline outbox action")
        print(json.dumps(result))
    finally:
        store.close()


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        # SQLite/paths/JSON errors may contain private text. Emit their type only.
        print(type(error).__name__, file=sys.stderr)
        raise SystemExit(1)
