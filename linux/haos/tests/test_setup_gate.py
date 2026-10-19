import pytest

from haos import setup_gate


def state(owner=False, recovery=False, complete=False, pending=False):
    return {"owner": owner, "recovery": recovery, "complete": complete, "pending": pending}


@pytest.mark.parametrize("values,active,expected", [
    (state(), False, "setup"),
    (state(pending=True), True, "setup"),
    (state(owner=True, recovery=True, complete=True), True, "setup"),
    (state(owner=True, recovery=True, complete=True), False, "desktop"),
    # A forged completion bit or unacknowledged recovery is never sufficient.
    (state(complete=True), False, "setup"),
    (state(owner=True, complete=True), False, "setup"),
    (state(recovery=True, complete=True), False, "setup"),
    (state(owner=True, recovery=True, complete=True, pending=True), False, "setup"),
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
    monkeypatch.setattr(setup_gate.initial_setup, "setup_finished", lambda: False)
    assert setup_gate.boot_destination() == "setup"
    monkeypatch.setattr(setup_gate.initial_setup, "setup_finished", lambda: True)
    assert setup_gate.boot_destination() == "desktop"



def test_completed_owner_recovery_without_wizard_receipt_stays_in_setup(monkeypatch):
    monkeypatch.setattr(setup_gate.os, "geteuid", lambda: 0)
    monkeypatch.setattr(setup_gate.initial_setup, "account_status",
                        lambda: state(owner=True, recovery=True, complete=True))
    monkeypatch.setattr(setup_gate.initial_setup, "setup_in_progress", lambda: False)
    monkeypatch.setattr(setup_gate.initial_setup, "setup_finished", lambda: False)
    assert setup_gate.boot_destination() == "setup"


def test_validated_receipt_denied_when_owner_or_codes_are_missing(monkeypatch):
    monkeypatch.setattr(setup_gate.os, "geteuid", lambda: 0)
    monkeypatch.setattr(setup_gate.initial_setup, "setup_in_progress", lambda: False)
    monkeypatch.setattr(setup_gate.initial_setup, "setup_finished", lambda: True)
    for broken in (state(), state(owner=True), state(complete=True),
                   state(owner=True, recovery=True, complete=True, pending=True)):
        monkeypatch.setattr(setup_gate.initial_setup, "account_status", lambda b=broken: b)
        assert setup_gate.boot_destination() == "setup"


@pytest.mark.parametrize("destination,command,expected_code", [
    ("setup", "prompt", 0),          # Native firstboot MUST start.
    ("setup", "desktop", 1),         # Locked observer MUST stay blocked.
    ("desktop", "prompt", 1),        # No repeat privileged setup after finish.
    ("desktop", "desktop", 0),       # Normal shell starts only after receipt.
])
def test_real_systemd_execcondition_command_mapping(monkeypatch, destination, command, expected_code):
    # Exercise the actual CLI rather than only the boot decision helper.
    monkeypatch.setattr(setup_gate, "boot_destination", lambda: destination)
    monkeypatch.setattr(setup_gate.sys, "argv", ["haos-setup-gate", command])
    with pytest.raises(SystemExit) as exc:
        setup_gate.main()
    assert exc.value.code == expected_code


@pytest.mark.parametrize("destination", ["setup", "desktop"])
def test_state_cli_reports_actual_destination(monkeypatch, capsys, destination):
    monkeypatch.setattr(setup_gate, "boot_destination", lambda: destination)
    monkeypatch.setattr(setup_gate.sys, "argv", ["haos-setup-gate", "state"])
    assert setup_gate.main() is None
    assert capsys.readouterr().out == destination + "\n"


@pytest.mark.parametrize("command", ["prompt", "desktop", "state"])
def test_invalid_owner_state_never_unblocks_any_systemd_unit(monkeypatch, command):
    def invalid_state():
        raise PermissionError("missing trusted owner/recovery marker")
    monkeypatch.setattr(setup_gate, "boot_destination", invalid_state)
    monkeypatch.setattr(setup_gate.sys, "argv", ["haos-setup-gate", command])
    with pytest.raises(SystemExit) as exc:
        setup_gate.main()
    assert exc.value.code == 255
