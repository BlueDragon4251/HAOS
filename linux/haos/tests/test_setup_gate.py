import pytest

from haos import setup_gate


def state(owner=False, recovery=False, complete=False, pending=False):
    return {"owner": owner, "recovery": recovery, "complete": complete, "pending": pending}


@pytest.mark.parametrize("values,active,expected", [
    (state(), False, "setup"),
    (state(pending=True), True, "setup"),
    (state(owner=True, recovery=True, complete=True), True, "setup"),
    (state(owner=True, recovery=True, complete=True), False, "desktop"),
    (state(owner=True, recovery=False), False, "setup"),
    (state(owner=True, recovery=True, complete=False, pending=True), False, "setup"),
])
def test_transition_preserves_existing_installations(values, active, expected):
    assert setup_gate.decision(values, active) == expected


def test_never_accept_incomplete_or_untrusted_onboarding_receipts():
    with pytest.raises(ValueError):
        setup_gate.decision({"complete": True}, False)
    with pytest.raises(ValueError):
        setup_gate.decision({**state(owner=True, recovery=True, complete=True), "token": "secret"}, False)
    with pytest.raises(ValueError):
        setup_gate.decision(state(owner=True, recovery=True, complete=True), 1)


def test_gate_requires_root_and_reads_in_progress_before_allowing_desktop(monkeypatch):
    monkeypatch.setattr(setup_gate.os, "geteuid", lambda: 1000)
    with pytest.raises(PermissionError):
        setup_gate.boot_destination()
    monkeypatch.setattr(setup_gate.os, "geteuid", lambda: 0)
    monkeypatch.setattr(setup_gate.initial_setup, "account_status",
                        lambda: state(owner=True, recovery=True, complete=True))
    monkeypatch.setattr(setup_gate.initial_setup, "setup_in_progress", lambda: True)
    assert setup_gate.boot_destination() == "setup"
    monkeypatch.setattr(setup_gate.initial_setup, "setup_in_progress", lambda: False)
    assert setup_gate.boot_destination() == "desktop"
