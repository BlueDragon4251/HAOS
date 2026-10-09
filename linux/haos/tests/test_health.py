import asyncio
from pathlib import Path
from types import SimpleNamespace
import time

import pytest

from haos import health
from haos.controller import Controller
from haos.health import HealthSampler, RESERVE_BYTES, RESERVE_MEMORY
from haos.store import MissionStore


def test_real_kernel_measurements_and_scratch_filesystem(monkeypatch, tmp_path):
    monkeypatch.setattr(health, "DISKS", {"fixture": tmp_path})
    sampler = HealthSampler()
    first = sampler.sample()
    assert first["cpu_busy_percent"] is None
    assert first["memory"]["total"] > 0
    assert 0 <= first["memory"]["available"] <= first["memory"]["total"]
    assert first["disks"]["fixture"]["total"] > 0
    time.sleep(0.02)
    second = sampler.sample()
    assert second["cpu_busy_percent"] is not None and 0 <= second["cpu_busy_percent"] <= 100
    assert second["at"] >= first["at"]
    assert all(-100 <= row["celsius"] <= 250 for row in second["temperatures"])


@pytest.mark.parametrize("free,expected", [(RESERVE_BYTES - 1, False), (RESERVE_BYTES + 1, True)])
def test_actual_reserve_decision_does_not_fabricate_available_space(monkeypatch, tmp_path, free, expected):
    monkeypatch.setattr(health, "DISKS", {"fixture": tmp_path})
    monkeypatch.setattr(health.shutil, "disk_usage", lambda path: SimpleNamespace(total=10 * RESERVE_BYTES, free=free))
    snapshot = HealthSampler().sample()
    assert snapshot["disks"]["fixture"]["free"] == free
    assert snapshot["can_dispatch"] is expected
    if not expected:
        assert snapshot["status"] == "critical" and snapshot["alerts"] == ["disk-reserve:fixture"]


def test_unknown_storage_blocks_new_dispatch_without_leaking_exception_text(monkeypatch):
    monkeypatch.setattr(health, "DISKS", {"fixture": Path("/unknown")})
    def unavailable(path):
        raise PermissionError("sensitive filesystem metadata must not be published")
    monkeypatch.setattr(health.shutil, "disk_usage", unavailable)
    snapshot = HealthSampler().sample()
    assert not snapshot["can_dispatch"] and "disk:fixture" in snapshot["errors"]
    assert "sensitive" not in str(snapshot)


def test_service_probe_is_read_only_fixed_and_hides_unavailable_counters(monkeypatch, tmp_path):
    monkeypatch.setattr(health, "DISKS", {"fixture": tmp_path})
    def show(args, **kwargs):
        assert args[:3] == ["/usr/bin/systemctl", "show", "--no-pager"]
        assert args[4:] == list(health.UNITS)
        assert kwargs["timeout"] == 3
        return SimpleNamespace(returncode=0, stdout="Id=haos-hermes.service\nActiveState=failed\nSubState=failed\nMemoryCurrent=18446744073709551615\nCPUUsageNSec=1000\nTasksCurrent=2\n\nId=owner-secret.service\nActiveState=active\n")
    monkeypatch.setattr(health.subprocess, "run", show)
    snapshot = HealthSampler().sample()
    assert snapshot["services"] == [{"unit": "haos-hermes.service", "active": "failed", "state": "failed", "cpu_nanoseconds": 1000, "tasks": 2}]
    assert "service:haos-hermes.service" in snapshot["alerts"]
    assert "owner-secret" not in str(snapshot)


@pytest.mark.parametrize("snapshot", [None, {"at": time.time(), "can_dispatch": False},
                                        {"at": time.time() - 60, "can_dispatch": True}])
def test_unsafe_or_stale_health_leaves_jobs_queued_without_claim_or_replay(tmp_path, snapshot):
    async def exercise():
        store = MissionStore(tmp_path / "missions.db")
        mission = store.create("uid:1000", "pressure", "A real pending goal")
        controller = Controller(store, "ws://127.0.0.1:9119/api/ws", {1000})
        controller.system_health = snapshot
        async def forbidden(row):
            raise AssertionError("unsafe resources started execution")
        controller.execute = forbidden
        task = asyncio.create_task(controller.worker())
        await asyncio.sleep(0.01)
        controller.stop.set()
        await task
        row = store.get(mission["id"])
        assert row["state"] == "queued" and row["attempt"] == 0
        store.close()
    asyncio.run(exercise())


def test_recovered_resources_admit_the_saved_job_once(tmp_path):
    async def exercise():
        store = MissionStore(tmp_path / "missions.db")
        mission = store.create("uid:1000", "recover-resources", "Pending goal")
        controller = Controller(store, "ws://127.0.0.1:9119/api/ws", {1000})
        controller.system_health = {"at": time.time(), "can_dispatch": True}
        calls = []
        async def cancelled_fixture(row):
            calls.append(row["id"])
            store.settle(row["id"], "cancelled")
            controller.stop.set()
        controller.execute = cancelled_fixture
        await controller.worker()
        assert calls == [mission["id"]] and store.get(mission["id"])["attempt"] == 1
        store.close()
    asyncio.run(exercise())
