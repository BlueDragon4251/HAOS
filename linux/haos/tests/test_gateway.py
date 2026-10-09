import asyncio
import copy
import json
import time
from types import SimpleNamespace

import pytest

from haos.controller import Controller
from haos.gateway import GatewayEngine, GatewayPolicy
from haos.gateway_runtime import adapter_envelope
from haos.store import Conflict, MissionStore


@pytest.fixture
def policy_config():
    return {"version": 1, "connectors": [{"id": "telegram-first", "platform": "telegram"}],
            "bindings": [{"id": "paired-device", "connector": "telegram-first", "sender": "42", "chat": "42",
                          "scope": "", "thread": "", "identity": "principal-1", "capabilities": ["create", "read", "cancel", "answer"]}]}


def envelope(**changes):
    return {"platform": "telegram", "sender": "42", "chat": "42", "scope": "", "thread": "",
            "message_id": "11", "is_bot": False, "text": "Test a real workspace", **changes}


def admitted(store, policy, item=None):
    controller = Controller(store, "ws://127.0.0.1:9119/api/ws", {1000})
    return asyncio.run(controller.gateway.receive(policy, "telegram-first", item or envelope(), controller))


def test_admission_replay_crash_and_terminal_delivery_are_durable(tmp_path, policy_config):
    path = tmp_path / "missions.db"
    policy = GatewayPolicy(policy_config)
    store = MissionStore(path)
    first = admitted(store, policy)
    assert admitted(store, policy) == first
    assert len(store.list()) == 1
    store.close()
    store = MissionStore(path)
    assert admitted(store, policy) == first
    assert len(store.list()) == 1
    engine = GatewayEngine(store)
    delivery = engine.next_delivery(policy)
    assert first["mission_id"] in delivery["content"]
    engine.acknowledge(policy, delivery["id"], {"status": "delivered", "message_id": "receipt-1", "attempt": delivery["attempt"]})
    store.claim()
    store.settle(first["mission_id"], "failed", error="Provider credentials unavailable")
    contents = []
    while (delivery := engine.next_delivery(policy)) is not None:
        contents.append(delivery["content"])
        engine.acknowledge(policy, delivery["id"], {"status": "delivered", "message_id": "receipt-2", "attempt": delivery["attempt"]})
    assert any("failed" in item and "credentials unavailable" in item for item in contents)
    assert engine.next_delivery(policy) is None
    store.close()


@pytest.mark.parametrize("changes", [dict(sender="foreign"), dict(chat="other-room"), dict(scope="other-server"),
                                     dict(thread="foreign-thread"), dict(is_bot=True), dict(platform="discord"),
                                     dict(actor="owner:0"), dict(message_id=""), dict(sender=None)])
def test_unpaired_or_forged_sources_cannot_create_any_mission(tmp_path, policy_config, changes):
    store = MissionStore(tmp_path / "missions.db")
    with pytest.raises((PermissionError, ValueError)):
        admitted(store, GatewayPolicy(policy_config), envelope(**changes))
    assert store.list() == []
    assert store.db.execute("SELECT COUNT(*) FROM gateway_inbox").fetchone()[0] == 0
    store.close()


def test_changed_replay_and_binding_identity_are_refused(tmp_path, policy_config):
    store = MissionStore(tmp_path / "missions.db")
    admitted(store, GatewayPolicy(policy_config))
    with pytest.raises(Conflict):
        admitted(store, GatewayPolicy(policy_config), envelope(text="Run a different operation"))
    policy_config["bindings"][0]["identity"] = "principal-2"
    with pytest.raises(Conflict):
        admitted(store, GatewayPolicy(policy_config))
    assert len(store.list()) == 1
    store.close()


def test_revocation_or_route_edit_never_sends_old_private_results(tmp_path, policy_config):
    store = MissionStore(tmp_path / "missions.db")
    admitted(store, GatewayPolicy(policy_config))
    changed = copy.deepcopy(policy_config)
    changed["bindings"][0]["chat"] = "new-private-recipient"
    assert GatewayEngine(store).next_delivery(GatewayPolicy(changed)) is None
    assert store.db.execute("SELECT state FROM gateway_outbox").fetchone()[0] == "revoked"
    store.close()


def test_delivery_retry_is_bounded_and_crashed_sends_are_not_replayed(tmp_path, policy_config):
    path = tmp_path / "missions.db"
    policy = GatewayPolicy(policy_config)
    store = MissionStore(path)
    admitted(store, policy)
    engine = GatewayEngine(store)
    delivery = engine.next_delivery(policy)
    assert engine.acknowledge(policy, delivery["id"], {"status": "retry", "retry_after": 20, "attempt": 1})["state"] == "pending"
    assert engine.next_delivery(policy) is None
    retried = engine.next_delivery(policy, time.time() + 21)
    assert retried["attempt"] == 2
    with pytest.raises(Conflict, match="stale"):
        engine.acknowledge(policy, delivery["id"], {"status": "delivered", "message_id": "old-receipt", "attempt": 1})
    store.close()
    store = MissionStore(path)
    engine = GatewayEngine(store)
    assert engine.next_delivery(policy, time.time() + 150) is None
    assert store.db.execute("SELECT state FROM gateway_outbox").fetchone()[0] == "uncertain"
    store.close()


def test_explicit_transport_failures_exhaust_retry_budget(tmp_path, policy_config):
    store = MissionStore(tmp_path / "missions.db")
    policy = GatewayPolicy(policy_config)
    admitted(store, policy)
    engine = GatewayEngine(store)
    for attempt in range(1, 6):
        delivery = engine.next_delivery(policy)
        result = engine.acknowledge(policy, delivery["id"], {"status": "retry", "retry_after": 0, "attempt": attempt})
    assert result["state"] == "failed"
    assert engine.next_delivery(policy) is None
    store.close()


def test_gateway_can_only_control_its_missions_and_granted_actions(tmp_path, policy_config):
    store = MissionStore(tmp_path / "missions.db")
    own = admitted(store, GatewayPolicy(policy_config))["mission_id"]
    foreign = store.create("uid:1000", "local", "Local private mission")["id"]
    with pytest.raises(PermissionError):
        admitted(store, GatewayPolicy(policy_config), envelope(message_id="12", text=f"/cancel {foreign}"))
    cancelled = admitted(store, GatewayPolicy(policy_config), envelope(message_id="13", text=f"/cancel {own}"))
    assert cancelled["state"] == "cancelled"
    policy_config["bindings"][0]["capabilities"] = ["read"]
    with pytest.raises(PermissionError):
        admitted(store, GatewayPolicy(policy_config), envelope(message_id="14", text="Create new work"))
    assert store.get(foreign)["state"] == "queued"
    store.close()


def test_question_answer_receipt_is_committed_before_external_response(tmp_path, policy_config):
    store = MissionStore(tmp_path / "missions.db")
    policy = GatewayPolicy(policy_config)
    mid = admitted(store, policy)["mission_id"]
    class InterruptedController:
        current = mid
        async def dispatch(self, actor, request):
            assert not store.db.in_transaction
            assert store.db.execute("SELECT COUNT(*) FROM gateway_inbox").fetchone()[0] == 2
            raise ConnectionError("lost response")
    engine = GatewayEngine(store)
    request = envelope(message_id="12", text=f"/answer {mid} request-1 once")
    first = asyncio.run(engine.receive(policy, "telegram-first", request, InterruptedController()))
    assert asyncio.run(engine.receive(policy, "telegram-first", request, None)) == first
    assert len([e for e in store.events(mid) if e["kind"] == "gateway.answer-unconfirmed"]) == 1
    store.close()


def test_admission_and_inbox_roll_back_together_on_disk_failure(tmp_path, policy_config, monkeypatch):
    store = MissionStore(tmp_path / "missions.db")
    controller = Controller(store, "ws://127.0.0.1:9119", set())
    def fail(*args):
        raise OSError("out of disk")
    monkeypatch.setattr(controller.gateway, "_queue", fail)
    with pytest.raises(OSError):
        asyncio.run(controller.gateway.receive(GatewayPolicy(policy_config), "telegram-first", envelope(), controller))
    assert store.list() == []
    assert store.db.execute("SELECT COUNT(*) FROM gateway_inbox").fetchone()[0] == 0
    assert not store.db.in_transaction
    store.close()


def test_native_adapter_boundary_rejects_media_synthetic_events_and_missing_sender():
    source = SimpleNamespace(platform=SimpleNamespace(value="telegram"), user_id="42", chat_id="42",
                             scope_id=None, thread_id=None, is_bot=False)
    event = SimpleNamespace(source=source, internal=False, media_urls=[], message_type=SimpleNamespace(value="text"),
                            message_id="11", text="Run task")
    assert adapter_envelope(event, "telegram") == envelope(text="Run task")
    event.media_urls = ["/etc/shadow"]
    with pytest.raises(ValueError):
        adapter_envelope(event, "telegram")
    event.media_urls = []
    event.internal = True
    with pytest.raises(PermissionError):
        adapter_envelope(event, "telegram")


def test_gateway_api_has_no_general_controller_or_owner_capability(tmp_path, policy_config):
    store = MissionStore(tmp_path / "missions.db")
    controller = Controller(store, "ws://127.0.0.1:9119", set())
    controller.gateway_policy = lambda: GatewayPolicy(policy_config)
    for method in ("missions.list", "missions.create", "owner.reconcile", "exec", "volume.unlock"):
        with pytest.raises(PermissionError):
            asyncio.run(controller.gateway_dispatch({"method": method}))
    store.close()
