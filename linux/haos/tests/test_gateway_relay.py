import time

import pytest

from haos.gateway import Conflict, GatewayPolicy
from haos.gateway_relay import RelayInbox
from haos.redaction import Redactor


def configuration():
    return {"version": 1, "connectors": [{"id": "first", "platform": "telegram"}], "bindings": [
        {"id": "paired", "connector": "first", "sender": "42", "chat": "42", "scope": "", "thread": "",
         "identity": "principal-1", "capabilities": ["create", "read"]}]}


def envelope():
    return {"platform": "telegram", "sender": "42", "chat": "42", "scope": "", "thread": "",
            "message_id": "11", "is_bot": False, "text": "Run tests"}


def test_controller_outage_and_lost_admission_receipt_can_retry_after_reboot(tmp_path):
    path = tmp_path / "relay.db"
    policy = GatewayPolicy(configuration())
    inbox = RelayInbox(path, Redactor())
    key = inbox.admit(policy, "first", envelope())
    inbox.retry(key)
    assert inbox.next(policy) is None
    inbox.close()
    inbox = RelayInbox(path, Redactor())
    assert inbox.admit(policy, "first", envelope()) == key
    item = inbox.next(policy, time.time() + 3)
    assert item["id"] == key and item["envelope"] == envelope()
    inbox.admitted(key, "actual-controller-mission-id")
    assert inbox.next(policy, time.time() + 100) is None
    assert inbox.db.execute("SELECT COUNT(*) FROM inbox").fetchone()[0] == 1
    inbox.close()


def test_replay_revocation_expiry_and_secrets_are_enforced_before_forwarding(tmp_path):
    config = configuration()
    policy = GatewayPolicy(config)
    path = tmp_path / "relay.db"
    inbox = RelayInbox(path, Redactor(["fixture-credential-value"]))
    item = {**envelope(), "text": "Test fixture-credential-value"}
    inbox.admit(policy, "first", item)
    with pytest.raises(Conflict):
        inbox.admit(policy, "first", {**item, "text": "Changed replay"})
    assert "fixture-credential-value" not in inbox.next(policy)["envelope"]["text"]
    config["bindings"] = []
    assert inbox.next(GatewayPolicy(config)) is None
    assert inbox.db.execute("SELECT state FROM inbox").fetchone()[0] == "revoked"
    policy = GatewayPolicy(configuration())
    inbox.admit(policy, "first", {**envelope(), "message_id": "12"})
    assert inbox.next(policy, time.time() + 86401) is None
    assert inbox.db.execute("SELECT state FROM inbox WHERE state='expired'").fetchone()
    inbox.close()
    assert b"fixture-credential-value" not in path.read_bytes()
