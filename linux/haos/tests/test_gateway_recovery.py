import asyncio
import copy
import hashlib
import json
import os

import pytest

from haos.gateway import GatewayEngine, GatewayPolicy
from haos.gateway_recovery import private_store, reconcile, unresolved
from haos.gateway_setup import owner_delivery
from haos import gateway_setup, owner
from haos.store import Conflict, MissionStore


@pytest.fixture
def outbox(tmp_path):
    tmp_path.chmod(0o700)
    path = tmp_path / "missions.db"
    store = MissionStore(path)
    path.chmod(0o600)
    config = {"version": 1, "connectors": [{"id": "first", "platform": "telegram"}],
              "bindings": [{"id": "device", "connector": "first", "sender": "42", "chat": "42",
                            "scope": "", "thread": "", "identity": "owner-principal", "capabilities": ["create", "read"]}]}
    policy = GatewayPolicy(config)
    engine = GatewayEngine(store)
    asyncio.run(engine.receive(policy, "first", {"platform": "telegram", "sender": "42", "chat": "42", "scope": "",
        "thread": "", "message_id": "1", "is_bot": False, "text": "Inspect a local fixture"}, None))
    delivery = engine.next_delivery(policy)
    engine.acknowledge(policy, delivery["id"], {"attempt": 1, "status": "uncertain"})
    yield store, engine, config, delivery
    store.close()


def decision(delivery, **changes):
    return {"delivery_id": delivery["id"], "attempt": 1, "decision": "retry", "owner_uid": 1000,
            "note_sha256": hashlib.sha256(b"Inspected the remote transport").hexdigest(), "receipt": None,
            "confirmed_not_delivered": True, **changes}


def test_inspected_retry_is_durable_and_old_decisions_cannot_repeat_it(outbox, tmp_path):
    store, engine, config, delivery = outbox
    policy = GatewayPolicy(config)
    before = store.get(store.list()[0]["id"])
    assert reconcile(store, policy, decision(delivery))["state"] == "pending"
    with pytest.raises(Conflict):
        reconcile(store, policy, decision(delivery))
    next_delivery = engine.next_delivery(policy)
    assert next_delivery["id"] == delivery["id"] and next_delivery["attempt"] == 2
    engine.acknowledge(policy, delivery["id"], {"attempt": 2, "status": "uncertain"})
    with pytest.raises(Conflict, match="stale"):
        reconcile(store, policy, decision(delivery))
    reopened = MissionStore(tmp_path / "missions.db")
    try:
        assert reopened.get(before["id"]) == before  # delivery repair cannot replay the mission
        events = [e for e in reopened.events(before["id"]) if e["kind"] == "owner.gateway-reconciled"]
        assert len(events) == 1 and events[0]["payload"]["actor"] == "owner:1000"
        assert not any("Inspected the remote transport" in json.dumps(e) for e in events)
    finally:
        reopened.close()


def test_verified_remote_receipt_never_resends(outbox):
    store, engine, config, delivery = outbox
    result = reconcile(store, GatewayPolicy(config), decision(delivery, decision="delivered", receipt="987654321", confirmed_not_delivered=False))
    assert result["state"] == "delivered"
    assert engine.next_delivery(GatewayPolicy(config)) is None
    assert store.db.execute("SELECT receipt FROM gateway_outbox").fetchone()[0] == "987654321"
    with pytest.raises(Conflict):
        reconcile(store, GatewayPolicy(config), decision(delivery, decision="discard", confirmed_not_delivered=False))


def test_discard_can_settle_revoked_uncertainty_without_delivery(outbox):
    store, engine, config, delivery = outbox
    config["bindings"] = []
    result = reconcile(store, GatewayPolicy(config), decision(delivery, decision="discard", confirmed_not_delivered=False))
    assert result["state"] == "revoked"
    assert engine.next_delivery(GatewayPolicy(config)) is None
    with pytest.raises(Conflict):
        reconcile(store, GatewayPolicy(config), decision(delivery, decision="discard", confirmed_not_delivered=False))


@pytest.mark.parametrize("changes,exception", [
    ({"confirmed_not_delivered": False}, PermissionError),
    ({"attempt": 2}, Conflict), ({"attempt": True}, ValueError),
    ({"decision": "delivered", "receipt": None, "confirmed_not_delivered": False}, ValueError),
    ({"decision": "delivered", "receipt": "authorization=hidden", "confirmed_not_delivered": False}, ValueError),
    ({"decision": "delivered", "receipt": "42"}, ValueError),
    ({"receipt": "42"}, ValueError), ({"note_sha256": "plaintext evidence"}, ValueError),
    ({"decision": "exec"}, ValueError), ({"owner_uid": -1}, ValueError),
])
def test_invalid_stale_or_unconfirmed_decisions_do_not_modify_receipts(outbox, changes, exception):
    store, engine, config, delivery = outbox
    before = dict(store.db.execute("SELECT * FROM gateway_outbox").fetchone())
    with pytest.raises(exception):
        reconcile(store, GatewayPolicy(config), decision(delivery, **changes))
    assert dict(store.db.execute("SELECT * FROM gateway_outbox").fetchone()) == before
    assert not any(e["kind"] == "owner.gateway-reconciled" for e in store.events(store.list()[0]["id"]))


@pytest.mark.parametrize("change", ["recipient", "read", "revoked"])
def test_changed_or_revoked_binding_cannot_be_retried(outbox, change):
    store, engine, config, delivery = outbox
    config = copy.deepcopy(config)
    if change == "recipient":
        config["bindings"][0]["chat"] = "different-recipient"
    elif change == "read":
        config["bindings"][0]["capabilities"] = ["create"]
    else:
        config["bindings"] = []
    with pytest.raises(PermissionError):
        reconcile(store, GatewayPolicy(config), decision(delivery))
    assert store.db.execute("SELECT state FROM gateway_outbox").fetchone()[0] == "uncertain"


def test_owner_repair_preserves_exhausted_delivery_budget(outbox):
    store, engine, config, delivery = outbox
    store.db.execute("UPDATE gateway_outbox SET attempt=5,state='failed'")
    with pytest.raises(Conflict, match="budget exhausted"):
        reconcile(store, GatewayPolicy(config), decision(delivery, attempt=5))
    assert store.db.execute("SELECT attempt,state FROM gateway_outbox").fetchone()[:] == (5, "failed")


def test_unresolved_metadata_is_paginated_without_content_or_recipient(outbox):
    store, engine, config, delivery = outbox
    report = unresolved(store)
    assert len(report["deliveries"]) == 1
    row = report["deliveries"][0]
    assert set(row) == {"cursor", "delivery_id", "mission_id", "state", "attempt", "content_sha256"}
    assert row["content_sha256"] == hashlib.sha256(delivery["content"].encode()).hexdigest()
    assert unresolved(store, report["next_cursor"])["deliveries"] == []
    with pytest.raises(ValueError):
        unresolved(store, True)


@pytest.mark.parametrize("attack", ["missing", "symlink-db", "hardlink-db", "readable-db", "writable-directory", "symlink-wal"])
def test_untrusted_recovery_ledger_paths_are_denied(outbox, tmp_path, attack):
    store, engine, config, delivery = outbox
    path = tmp_path / "missions.db"
    if attack == "missing":
        path = tmp_path / "absent.db"
    elif attack == "symlink-db":
        path = tmp_path / "linked.db"
        path.symlink_to(tmp_path / "missions.db")
    elif attack == "hardlink-db":
        os.link(path, tmp_path / "second.db")
    elif attack == "readable-db":
        path.chmod(0o644)
    elif attack == "writable-directory":
        tmp_path.chmod(0o777)
    else:
        wal = tmp_path / "missions.db-wal"
        wal.rename(tmp_path / "original-wal")
        wal.symlink_to(tmp_path / "original-wal")
    with pytest.raises((PermissionError, FileNotFoundError)):
        private_store(path)


def test_unprivileged_owner_wrapper_cannot_run_recovery():
    if os.geteuid() != 0:
        with pytest.raises(PermissionError, match="owner authority"):
            owner_delivery(None, {})


@pytest.mark.parametrize("guard", ["gateway", "runtime"])
def test_owner_wrapper_checks_stopped_services_before_reading_or_delegating(monkeypatch, guard):
    calls = []
    monkeypatch.setattr(os, "geteuid", lambda: 0)
    def gateway_stopped():
        calls.append("gateway")
        if guard == "gateway":
            raise PermissionError("gateway is active")
    def runtime_stopped():
        calls.append("runtime")
        raise PermissionError("runtime is active")
    monkeypatch.setattr(gateway_setup, "stopped_gateway", gateway_stopped)
    monkeypatch.setattr(owner, "stopped", runtime_stopped)
    with pytest.raises(PermissionError, match="active"):
        owner_delivery(None, {})
    assert calls == (["gateway"] if guard == "gateway" else ["gateway", "runtime"])
