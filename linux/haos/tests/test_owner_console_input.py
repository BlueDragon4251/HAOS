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
