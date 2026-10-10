"""Policy boundaries, without lowering authority checks in root fixtures."""
import pytest

from haos.backup_schedule import policy, timestamp, Scheduler


def valid():
    return {"version": 1, "interval": "daily", "prune": False,
            "retention": {"keep_last": 7, "keep_daily": 7, "keep_weekly": 4, "keep_monthly": 12}}


@pytest.mark.parametrize("alter", [
    lambda value: value.update(destination="https://attacker.invalid"),
    lambda value: value.update(command="touch private-file"),
    lambda value: value.update(interval="* * * * *"),
    lambda value: value.update(prune="false"),
    lambda value: value.update(version=True),
    lambda value: value["retention"].update(keep_last=0),
    lambda value: value["retention"].update(keep_last=True),
    lambda value: value["retention"].update(keep_monthly=1000000),
])
def test_untrusted_policy_cannot_choose_paths_commands_or_delete_every_snapshot(alter):
    value = valid()
    alter(value)
    with pytest.raises((ValueError, PermissionError)):
        policy(value)


@pytest.mark.parametrize("value", [float("nan"), float("inf"), -1, True, "now"])
def test_untrusted_clocks_cannot_claim_scheduling_success(value):
    with pytest.raises(ValueError):
        timestamp(value)


def test_non_owner_cannot_construct_scheduler(monkeypatch, tmp_path):
    monkeypatch.setattr("haos.backup_schedule.os.geteuid", lambda: 1001)
    with pytest.raises(PermissionError):
        Scheduler(tmp_path / "protected", tmp_path / "config", None, None, None, None)
    assert not (tmp_path / "protected").exists()
