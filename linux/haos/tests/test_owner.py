from types import SimpleNamespace

import pytest

from haos.owner import stopped


@pytest.mark.parametrize("state,pid,load", [
    ("active", "123", "loaded"), ("activating", "123", "loaded"),
    ("deactivating", "123", "loaded"), ("failed", "0", "loaded"),
    ("inactive", "123", "loaded"), ("inactive", "0", "not-found"),
])
def test_owner_does_not_treat_nonactive_transition_as_stopped(monkeypatch, state, pid, load):
    monkeypatch.setattr("haos.owner.subprocess.run", lambda *a, **k: SimpleNamespace(
        stdout=f"LoadState={load}\nActiveState={state}\nMainPID={pid}\nControlPID=0\n"))
    with pytest.raises(PermissionError, match="stop"):
        stopped()


def test_owner_requires_no_control_process_and_checks_both_units(monkeypatch):
    seen = []
    def show(args, **kwargs):
        seen.append(args[-1])
        return SimpleNamespace(stdout="LoadState=loaded\nActiveState=inactive\nMainPID=0\nControlPID=0\n")
    monkeypatch.setattr("haos.owner.subprocess.run", show)
    stopped()
    assert seen == ["haos-controller.service", "haos-hermes.service"]
    monkeypatch.setattr("haos.owner.subprocess.run", lambda *a, **k: SimpleNamespace(
        stdout="LoadState=loaded\nActiveState=inactive\nMainPID=0\nControlPID=123\n"))
    with pytest.raises(PermissionError):
        stopped()
