import concurrent.futures
import sqlite3
import time

import pytest

from haos.store import Conflict, MissionStore


def test_creation_is_durable_and_idempotency_is_actor_scoped(tmp_path):
    path = tmp_path / "missions.db"
    store = MissionStore(path)
    first = store.create("uid:1000", "request-1", "Build the project")
    assert store.create("uid:1000", "request-1", "Build the project")["id"] == first["id"]
    with pytest.raises(Conflict):
        store.create("uid:1000", "request-1", "Delete the project")
    assert store.create("uid:1001", "request-1", "Build the project")["id"] != first["id"]
    store.close()
    reopened = MissionStore(path)
    assert reopened.get(first["id"])["goal"] == first["goal"]
    assert reopened.events(first["id"])[0]["kind"] == "mission.queued"
    reopened.close()


def test_two_controllers_cannot_claim_the_same_execution_home(tmp_path):
    path = tmp_path / "missions.db"
    store = MissionStore(path)
    for key in ("a", "b"):
        store.create("uid:1000", key, key)

    def claim():
        contender = MissionStore(path)
        try:
            return contender.claim()
        finally:
            contender.close()

    with concurrent.futures.ThreadPoolExecutor(2) as pool:
        claims = list(pool.map(lambda _: claim(), range(2)))
    assert sum(c is not None for c in claims) == 1
    assert sum(r["state"] == "running" for r in store.list()) == 1
    store.close()


def test_crash_before_dispatch_requeues_but_ambiguous_dispatch_retains_lock(tmp_path):
    path = tmp_path / "missions.db"
    store = MissionStore(path)
    first = store.create("uid:1000", "a", "Build")
    store.claim()
    store.close()
    store = MissionStore(path)
    store.recover()
    assert store.get(first["id"])["state"] == "queued"
    assert store.claim()["id"] == first["id"]
    store.session(first["id"], "live-1", "stored-1")
    store.dispatching(first["id"])
    store.close()
    store = MissionStore(path)
    store.recover()
    assert store.get(first["id"])["state"] == "blocked"
    store.create("uid:1000", "b", "Next build")
    assert store.claim() is None
    with pytest.raises(Conflict):
        store.request_cancel(first["id"], "uid:1000")
    store.reconcile(first["id"], "owner:1000", "Stopped Hermes and inspected the working tree")
    assert store.claim()["goal"] == "Next build"
    assert any(e["kind"] == "owner.reconciled" for e in store.events(first["id"]))
    store.close()


def test_connection_failures_retry_only_before_prompt_dispatch(tmp_path):
    store = MissionStore(tmp_path / "missions.db")
    first = store.create("uid:1000", "a", "Build", max_attempts=2)
    store.claim()
    store.unavailable(first["id"], "ConnectionRefusedError")
    assert store.get(first["id"])["state"] == "queued"
    assert store.claim() is None
    store.claim(time.time() + 10)
    store.unavailable(first["id"], "ConnectionRefusedError")
    assert store.get(first["id"])["state"] == "failed"
    second = store.create("uid:1000", "b", "Another build")
    store.claim()
    store.session(second["id"], "live-2", "stored-2")
    store.dispatching(second["id"])
    store.unavailable(second["id"], "TimeoutError")
    assert store.get(second["id"])["state"] == "blocked"
    assert store.claim(time.time() + 100) is None
    store.close()


def test_cancel_deadlines_terminal_receipts_and_replay(tmp_path):
    store = MissionStore(tmp_path / "missions.db")
    cancelled = store.create("uid:1000", "a", "Build")
    assert store.request_cancel(cancelled["id"], "uid:1000")["state"] == "cancelled"
    expired = store.create("uid:1000", "b", "Build later", timeout=60)
    assert store.claim(time.time() + 61) is None
    assert store.get(expired["id"])["state"] == "failed"
    running = store.create("uid:1000", "c", "Build now")
    store.claim()
    event = {"type": "tool.complete", "seq": 4, "payload": {"name": "terminal", "result": "exit status 0"}}
    store.record(running["id"], event, "epoch-1")
    store.record(running["id"], event, "epoch-1")
    store.record(running["id"], event, "epoch-2")
    assert len([e for e in store.events(running["id"]) if e["kind"] == "hermes.tool.complete"]) == 2
    store.settle(running["id"], "completed", result="Actual result")
    assert store.get(running["id"])["result"] == "Actual result"
    with pytest.raises(Conflict):
        store.settle(running["id"], "failed", error="late receipt")
    store.close()


@pytest.mark.parametrize("parameters", [dict(goal=""), dict(key=""), dict(timeout=0), dict(max_attempts=99), dict(timeout=True)])
def test_invalid_missions_do_not_create_partial_rows(tmp_path, parameters):
    store = MissionStore(tmp_path / "missions.db")
    args = {"actor": "uid:1000", "key": "a", "goal": "Build", **parameters}
    with pytest.raises(ValueError):
        store.create(**args)
    assert store.list() == []
    store.close()


def test_newer_database_schema_is_not_silently_downgraded(tmp_path):
    path = tmp_path / "missions.db"
    with sqlite3.connect(path) as db:
        db.execute("PRAGMA user_version=2")
    with pytest.raises(RuntimeError, match="unsupported"):
        MissionStore(path)
