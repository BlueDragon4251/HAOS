"""Actual encrypted scheduler/restart/restore tests on disposable directories."""
import json
import os
from pathlib import Path
import uuid

import pytest

import sys
sys.path.insert(0, str(Path(__file__).parents[1]))
from haos.backup import Repository
from haos.backup_schedule import Scheduler
from haos.policy import atomic_json


@pytest.fixture
def fixture(tmp_path):
    assert os.geteuid() == 0, "run only these disposable encrypted directories as root"
    repository = Repository(tmp_path / "repository-owner", tmp_path / "password")
    repository.initialize()
    source = tmp_path / "source"
    source.mkdir()
    (source / "data").write_text("actual encrypted scheduled fixture")
    audit = []
    scheduler = Scheduler(tmp_path / "scheduler", tmp_path / "config/settings.json", repository,
                          lambda: [source], lambda: None, lambda kind, details: audit.append({"kind": kind, **details}))
    scheduler.configure({"version": 1, "interval": "daily", "prune": False,
                         "retention": {"keep_last": 1, "keep_daily": 0, "keep_weekly": 0, "keep_monthly": 0}})
    return scheduler, source, audit


def test_actual_encrypted_schedule_survives_restart_and_preserves_retention_preview(fixture):
    scheduler, source, audit = fixture
    assert scheduler.status(1000)["due"]
    first = scheduler.tick(1000)
    assert first["phase"] == "succeeded" and not first["retention_applied"]
    assert scheduler.tick(1001)["phase"] == "not-due"
    assert not scheduler.status(900)["due"] and scheduler.status(900)["clock_behind_last_success"]
    reopened = Scheduler(scheduler.root, scheduler.configuration, scheduler.repository, scheduler.sources, scheduler.check_stopped, scheduler.audit)
    assert reopened.status(1001)["snapshot_id"] == first["snapshot_id"]
    (source / "data").write_text("actual next scheduled revision")
    second = reopened.tick(87400)
    assert second["phase"] == "succeeded"
    assert set(reopened.repository.snapshots()["snapshot_ids"]) == {first["snapshot_id"], second["snapshot_id"]}
    staged = Path(reopened.repository.restore(second["snapshot_id"])["staging_directory"])
    assert (staged / source.relative_to("/") / "data").read_text() == "actual next scheduled revision"
    assert "actual next scheduled revision" not in json.dumps(audit)
    configured = reopened.configuration_value()
    configured["prune"] = True
    reopened.configure(configured)
    (source / "data").write_text("owner-authorized retained revision")
    third = reopened.tick(173800)
    assert third["retention_applied"] and reopened.repository.snapshots()["snapshot_ids"] == [third["snapshot_id"]]
    print(json.dumps({"actual_encrypted_schedule_and_restore": True, "restart_retains_due_and_receipt": True,
                      "retention_preview_preserves_snapshots": True, "installed_systemd_scheduler": False}))


def test_busy_runtime_missing_key_and_disabled_policy_never_create_backup(fixture):
    scheduler, _, _ = fixture
    def busy():
        raise PermissionError("execution still active")
    scheduler.check_stopped = busy
    assert scheduler.tick(1000) == {"phase": "deferred", "reason": "execution-not-stopped"}
    assert scheduler.repository.snapshots()["snapshot_ids"] == []
    scheduler.check_stopped = lambda: None
    scheduler.repository.password.unlink()
    assert scheduler.tick(1000)["phase"] == "unavailable"
    value = scheduler.configuration_value()
    value["interval"] = "off"
    scheduler.configure(value)
    assert scheduler.tick(1000)["phase"] == "not-due"


def test_crash_intent_blocks_without_repeating_a_real_existing_snapshot(fixture):
    scheduler, _, audit = fixture
    receipt = scheduler.repository.create(scheduler.sources())
    atomic_json(scheduler.root / "state.json", {"version": 1, "last_success": None, "phase": "running",
                "attempt": str(uuid.uuid4()), "snapshot_id": receipt["snapshot_id"]})
    assert scheduler.tick(1000)["phase"] == "blocked"
    assert scheduler.tick(1001)["phase"] == "blocked"
    assert scheduler.repository.snapshots()["snapshot_ids"] == [receipt["snapshot_id"]]
    with pytest.raises(PermissionError):
        scheduler.clear("inspected actual snapshot", False)
    assert scheduler.clear("inspected actual snapshot", True)["snapshots_deleted"] is False
    assert scheduler.repository.snapshots()["snapshot_ids"] == [receipt["snapshot_id"]]
    assert "inspected actual snapshot" not in json.dumps(audit)


def test_modifying_failure_blocks_and_cannot_be_hidden_by_reconfiguration(fixture, monkeypatch):
    scheduler, _, audit = fixture
    actual = scheduler.repository.create
    def failed(sources):
        actual(sources)  # actual encrypted external effect before lost receipt
        raise RuntimeError("private fixture exception must not be logged")
    monkeypatch.setattr(scheduler.repository, "create", failed)
    assert scheduler.tick(1000)["phase"] == "blocked"
    assert len(scheduler.repository.snapshots()["snapshot_ids"]) == 1
    scheduler.configure(scheduler.configuration_value())
    assert scheduler.tick(1001)["phase"] == "blocked"
    assert len(scheduler.repository.snapshots()["snapshot_ids"]) == 1
    assert "private fixture exception" not in json.dumps(audit)


def test_untrusted_schedule_and_lock_files_denied(fixture):
    scheduler, _, _ = fixture
    scheduler.configuration.chmod(0o666)
    with pytest.raises(PermissionError):
        scheduler.tick(1000)
    scheduler.configuration.chmod(0o600)
    lock = scheduler.root / "lock"
    lock.unlink()
    lock.symlink_to(scheduler.configuration)
    with pytest.raises(OSError):
        scheduler.tick(1000)
    assert scheduler.repository.snapshots()["snapshot_ids"] == []


def test_concurrent_scheduler_cannot_modify_repository(fixture):
    scheduler, _, _ = fixture
    with scheduler.lock():
        with pytest.raises(BlockingIOError):
            scheduler.tick(1000)
    assert scheduler.repository.snapshots()["snapshot_ids"] == []


def test_lost_success_persistence_keeps_valid_blocked_intent(fixture, monkeypatch):
    scheduler, _, _ = fixture
    from haos import backup_schedule
    actual = backup_schedule.atomic_json
    lost = False
    def lose_final_receipt(path, value):
        nonlocal lost
        if value.get("phase") == "idle" and value.get("last_success") is not None and not lost:
            lost = True
            raise OSError("injected final receipt loss")
        actual(path, value)
    monkeypatch.setattr(backup_schedule, "atomic_json", lose_final_receipt)
    assert scheduler.tick(1000)["phase"] == "blocked"
    state = scheduler.state()
    assert state["phase"] == "blocked" and state["attempt"] and state["last_success"] is None
    assert scheduler.repository.snapshots()["snapshot_ids"] == [state["snapshot_id"]]
    assert scheduler.tick(1001)["phase"] == "blocked"
