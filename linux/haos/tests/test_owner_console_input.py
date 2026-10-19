"""Real console onboarding must reject malformed owner names before password input."""

from haos import owner, owner_recovery, enrollment


def test_invalid_names_are_reprompted_before_password(monkeypatch, capsys):
    entered = iter(["BlueIT", "hermes", "blue-new"])
    names = []
    monkeypatch.setattr(owner_recovery, "require_console", lambda: None)
    monkeypatch.setattr(owner_recovery, "owners", lambda: [])
    monkeypatch.setattr(owner_recovery, "trusted_json", lambda _: {"control_users": ["hermes"]})
    monkeypatch.setattr("builtins.input", lambda _: next(entered))
    monkeypatch.setattr(enrollment, "validate_name", lambda name, observer:
                        (_ for _ in ()).throw(ValueError("invalid")) if name in ("BlueIT", observer) else None)
    monkeypatch.setattr(enrollment, "run", lambda *args: None)
    monkeypatch.setattr(enrollment, "enroll_interactive", lambda name, **kwargs: names.append(name))
    monkeypatch.setattr(owner, "stopped", lambda: None)
    monkeypatch.setattr(owner_recovery, "print_codes", lambda _: None)

    owner_recovery.main()

    assert names == ["blue-new"]
    assert capsys.readouterr().out.count("Choose a new lowercase account name") == 2



def test_recovery_codes_require_explicit_confirmation(monkeypatch, capsys):
    from types import SimpleNamespace
    codes = [f"test-only-code-{i}" for i in range(10)]
    prompts = []
    values = iter(["", "yes", "SAVED"])
    audits = []
    monkeypatch.setattr(owner_recovery, "require_console", lambda: None)
    monkeypatch.setattr(owner_recovery, "enrolled_owner", lambda _: SimpleNamespace(pw_uid=2000))
    monkeypatch.setattr(owner_recovery, "RecoveryCodes", lambda: SimpleNamespace(issue=lambda _: codes))
    monkeypatch.setattr(owner, "audit", lambda kind, fields: audits.append((kind, fields)))
    monkeypatch.setattr("builtins.input", lambda prompt: (prompts.append(prompt), next(values))[1])

    owner_recovery.print_codes("owner")

    output = capsys.readouterr().out
    assert all(code in output for code in codes)
    assert output.count("Codes remain visible") == 2
    assert len(prompts) == 3
    assert all("SAVED" in prompt for prompt in prompts)
    assert audits == [("owner.recovery-codes-issued", {"uid": 2000, "count": 10})]


def test_recovery_codes_cannot_be_acknowledged_on_eof(monkeypatch):
    import pytest
    from types import SimpleNamespace

    monkeypatch.setattr(owner_recovery, "require_console", lambda: None)
    monkeypatch.setattr(owner_recovery, "enrolled_owner", lambda _: SimpleNamespace(pw_uid=2000))
    monkeypatch.setattr(owner_recovery, "RecoveryCodes", lambda: SimpleNamespace(issue=lambda _: ["test-only-code"]))
    monkeypatch.setattr(owner, "audit", lambda *args: None)
    monkeypatch.setattr("builtins.input", lambda _: (_ for _ in ()).throw(EOFError()))

    with pytest.raises(PermissionError, match="not acknowledged"):
        owner_recovery.print_codes("owner")
