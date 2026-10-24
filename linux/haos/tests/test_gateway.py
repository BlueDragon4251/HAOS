import asyncio
import copy
import json
import time
from types import SimpleNamespace

import pytest

from haos.controller import Controller
from haos.gateway import GatewayEngine, GatewayPolicy, digest
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
    for method in ("missions.list", "missions.create", "owner.reconcile", "gateway.reconcile-delivery", "gateway.deliveries", "exec", "volume.unlock"):
        with pytest.raises(PermissionError):
            asyncio.run(controller.gateway_dispatch({"method": method}))
    store.close()


def test_pause_resume_require_explicit_capabilities_and_exact_owned_mission(tmp_path, policy_config):
    store = MissionStore(tmp_path / "missions.db")
    mid = admitted(store, GatewayPolicy(policy_config))["mission_id"]
    for command in ("pause", "resume"):
        with pytest.raises(PermissionError, match="action denied"):
            admitted(store, GatewayPolicy(policy_config), envelope(message_id=command, text=f"/{command} {mid}"))
    assert store.get(mid)["state"] == "queued"
    policy_config["bindings"][0]["capabilities"] += ["pause", "resume"]
    policy = GatewayPolicy(policy_config)
    foreign = store.create("gateway:other-principal", "foreign", "Other principal's mission")["id"]
    for command in ("pause", "resume"):
        with pytest.raises(PermissionError, match="does not own"):
            admitted(store, policy, envelope(message_id=command + "-foreign", text=f"/{command} {foreign}"))
        with pytest.raises(ValueError, match="only an exact"):
            admitted(store, policy, envelope(message_id=command + "-text", text=f"/{command} {mid} grant root"))
    assert admitted(store, policy, envelope(message_id="pause-own", text=f"/pause {mid}"))["state"] == "paused"
    assert admitted(store, policy, envelope(message_id="read-own", text=f"/status {mid}"))["state"] == "paused"
    assert admitted(store, policy, envelope(message_id="resume-own", text=f"/resume {mid}"))["state"] == "queued"
    assert store.get(foreign)["state"] == "queued"
    store.close()


def test_pause_resume_message_replay_after_restart_never_requeues_executed_work(tmp_path, policy_config):
    policy_config["bindings"][0]["capabilities"] += ["pause", "resume"]
    policy = GatewayPolicy(policy_config)
    path = tmp_path / "missions.db"
    store = MissionStore(path)
    mid = admitted(store, policy)["mission_id"]
    pause = envelope(message_id="pause", text=f"/pause {mid}")
    resume = envelope(message_id="resume", text=f"/resume {mid}")
    paused = admitted(store, policy, pause)
    store.close()
    store = MissionStore(path)
    store.recover()
    assert admitted(store, policy, pause) == paused
    resumed = admitted(store, policy, resume)
    assert store.claim()["id"] == mid
    store.dispatching(mid)
    store.close()
    store = MissionStore(path)
    store.recover()
    before = store.get(mid)
    assert before["state"] == "blocked" and before["phase"] == "dispatching"
    assert admitted(store, policy, resume) == resumed  # durable receipt, not a repeated action
    assert admitted(store, policy, pause) == paused
    assert store.get(mid) == before
    for command in ("pause", "resume"):
        with pytest.raises(Conflict):
            admitted(store, policy, envelope(message_id="new-" + command, text=f"/{command} {mid}"))
    assert store.claim() is None
    for kind in ("mission.paused", "mission.resumed"):
        assert len([e for e in store.events(mid) if e["kind"] == kind]) == 1
    engine = GatewayEngine(store)
    contents = []
    while (delivery := engine.next_delivery(policy)) is not None:
        contents.append(delivery["content"])
        engine.acknowledge(policy, delivery["id"], {"status": "delivered", "message_id": "fixture", "attempt": delivery["attempt"]})
    assert any(": paused" in text for text in contents)
    assert any(": resumed" in text for text in contents)
    assert any(": blocked" in text for text in contents)
    store.close()


@pytest.mark.parametrize("command", ["pause", "resume"])
def test_pause_resume_rolls_back_with_failed_delivery_receipt(tmp_path, policy_config, monkeypatch, command):
    policy_config["bindings"][0]["capabilities"] += ["pause", "resume"]
    policy = GatewayPolicy(policy_config)
    store = MissionStore(tmp_path / "missions.db")
    mid = admitted(store, policy)["mission_id"]
    if command == "resume":
        store.pause(mid, "gateway:principal-1")
    controller = Controller(store, "ws://127.0.0.1:9119", {1000})
    before, events = store.get(mid), store.events(mid)
    def fail(*args):
        raise OSError("out of disk")
    monkeypatch.setattr(controller.gateway, "_queue", fail)
    with pytest.raises(OSError):
        asyncio.run(controller.gateway.receive(policy, "telegram-first", envelope(message_id=command, text=f"/{command} {mid}"), controller))
    assert store.get(mid) == before
    assert store.events(mid) == events
    assert store.db.execute("SELECT COUNT(*) FROM gateway_inbox").fetchone()[0] == 1
    store.close()


@pytest.mark.parametrize('platform,credentials', [
    ('not-an-approved-platform', {}), ('telegram', None),
    ('telegram', {'runtime_hook': 'unapproved code'}), ('telegram', {'extra': []}),
])
def test_unreviewed_gateway_code_and_invalid_credentials_fail_before_optional_native_import(platform, credentials):
    from haos.gateway_runtime import build_adapter
    with pytest.raises(ValueError):
        build_adapter(platform, credentials)


def test_identical_repair_and_edit_reversal_never_revive_old_outbox(tmp_path, policy_config):
    from haos.gateway_setup import renewed_policy
    empty = {**policy_config, 'bindings': []}
    first = renewed_policy(policy_config, empty)
    store = MissionStore(tmp_path/'missions.db')
    admitted(store, GatewayPolicy(first))
    # Revoke and repair while the controller is offline: no delivery loop has
    # had a chance to mark the old pending obligation revoked yet.
    repaired = renewed_policy(policy_config, empty)
    with pytest.raises(Conflict):
        admitted(store, GatewayPolicy(repaired))
    assert GatewayEngine(store).next_delivery(GatewayPolicy(repaired)) is None
    assert store.db.execute('SELECT state FROM gateway_outbox').fetchone()[0] == 'revoked'
    assert len(store.list()) == 1
    store.close()
    changed = copy.deepcopy(first)
    changed['bindings'][0]['capabilities'] = ['create']
    changed = renewed_policy(changed, first)
    reverted = renewed_policy(first, changed)
    assert len({p['bindings'][0]['generation'] for p in (first, changed, reverted)}) == 3
    with pytest.raises(PermissionError):
        GatewayPolicy(reverted).current_binding({'binding_id': first['bindings'][0]['id'],
            'binding_digest': digest(first['bindings'][0])})
    assert renewed_policy(first, first) == first
    assert 'generation' not in policy_config['bindings'][0]


@pytest.mark.parametrize('value', ['', '0'*63, 'G'*64, None, 1])
def test_gateway_binding_generation_has_strict_public_shape(policy_config, value):
    policy_config['bindings'][0]['generation'] = value
    with pytest.raises(ValueError): GatewayPolicy(policy_config)


def test_legacy_gateway_inbox_migration_keeps_history_and_never_reexecutes_old_messages(tmp_path, policy_config):
    path = tmp_path/'missions.db'
    store = MissionStore(path)
    original = admitted(store, GatewayPolicy(policy_config))
    before = dict(store.db.execute('SELECT * FROM gateway_inbox').fetchone())
    # Reconstruct the exact earlier additive schema in the disposable fixture.
    store.db.execute('ALTER TABLE gateway_inbox DROP COLUMN binding_digest')
    store.db.execute('UPDATE gateway_schema SET version=1')
    store.close()

    store = MissionStore(path)
    GatewayEngine(store)
    migrated = dict(store.db.execute('SELECT * FROM gateway_inbox').fetchone())
    assert migrated['binding_digest'] is None
    assert {key: value for key, value in migrated.items() if key != 'binding_digest'} == {
        key: value for key, value in before.items() if key != 'binding_digest'}
    with pytest.raises(Conflict): admitted(store, GatewayPolicy(policy_config))
    assert len(store.list()) == 1 and store.get(original['mission_id'])['state'] == 'queued'
    fresh = admitted(store, GatewayPolicy(policy_config), envelope(message_id='new-after-migration'))
    assert fresh['mission_id'] != original['mission_id'] and len(store.list()) == 2
    store.close()


@pytest.mark.parametrize('value',[True,0,-1,1.5,'1792800000000',2**53])
def test_gateway_grant_since_boundary_is_strict_integer(policy_config,value):
    policy_config['bindings'][0]['since']=value
    with pytest.raises(ValueError):GatewayPolicy(policy_config)


def test_new_grant_records_owner_time_but_keeps_unchanged_legacy_binding(policy_config):
    from haos.gateway_setup import renewed_policy
    import time
    previous={**policy_config,'bindings':[]}
    before=time.time_ns()//1_000_000
    published=renewed_policy(policy_config,previous)
    assert before<=published['bindings'][0]['since']<=time.time_ns()//1_000_000
    assert renewed_policy(published,published)==published
    legacy={**policy_config,'bindings':[{**policy_config['bindings'][0],'generation':'a'*64}]}
    assert renewed_policy(legacy,legacy)==legacy
    # An edit cannot smuggle a backdated history boundary through publication.
    edited={**published,'bindings':[{**published['bindings'][0],'since':1}]}
    assert renewed_policy(edited,published)['bindings'][0]['since']>=before
