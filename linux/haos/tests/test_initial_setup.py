from types import SimpleNamespace
import pytest
from haos import initial_setup


def test_root_required(monkeypatch):
    monkeypatch.setattr(initial_setup.os, "geteuid", lambda: 1000)
    for call in (
        lambda: initial_setup.account_status(),
        lambda: initial_setup.create_initial_owner("secure", "X" * 25, "X" * 25),
        lambda: initial_setup.configure_region("de_AT.UTF-8", "at"),
        lambda: initial_setup.configure_update("dev", True),
        lambda: initial_setup.configure_ghcr("owner", "private"),
        lambda: initial_setup.configure_provider("openai", "gpt-model", "secret"),
    ):
        with pytest.raises(PermissionError):
            call()


def test_no_existing_owner_may_be_reenrolled(monkeypatch):
    monkeypatch.setattr(initial_setup.os, "geteuid", lambda: 0)
    monkeypatch.setattr(initial_setup, "owners", lambda: [{"username": "present", "uid": 1002}])
    with pytest.raises(PermissionError):
        initial_setup.create_initial_owner("other", "secret", "secret")


def test_initial_owner_requires_repeated_password_before_stopping_services(monkeypatch):
    monkeypatch.setattr(initial_setup.os, "geteuid", lambda: 0)
    with pytest.raises(ValueError):
        initial_setup.create_initial_owner("separate", "first", "second")


def test_reject_unknown_region_and_provider_without_mutating_os(monkeypatch):
    monkeypatch.setattr(initial_setup.os, "geteuid", lambda: 0)
    with pytest.raises(ValueError):
        initial_setup.configure_region("unsupported", "us")
    with pytest.raises(ValueError):
        initial_setup.configure_region("de_AT.UTF-8", "xx")
    with pytest.raises(ValueError):
        initial_setup.configure_provider("codex", "model")
    with pytest.raises(ValueError):
        initial_setup.configure_provider("openai", "gpt-4")
    with pytest.raises(ValueError):
        initial_setup.configure_provider("local", "m", "secret", "http://127.0.0.1:4000/v1")


def test_update_allowlist_is_applied_before_any_command(monkeypatch):
    monkeypatch.setattr(initial_setup.os, "geteuid", lambda: 0)
    with pytest.raises(ValueError):
        initial_setup.configure_update("ghcr.io/bad/unsafe", True)
    with pytest.raises(ValueError):
        initial_setup.configure_update("dev", "yes")


def test_physical_owner_status_is_not_a_permission(monkeypatch):
    monkeypatch.setattr(initial_setup.os, "geteuid", lambda: 0)
    monkeypatch.setattr(initial_setup, "owners", lambda: [])
    monkeypatch.setattr(initial_setup, "recovery_pending", lambda: False)
    assert initial_setup.account_status() == {"owner": False, "recovery": False, "complete": False, "pending": False}


def test_gateway_owner_and_platform_validation(monkeypatch):
    monkeypatch.setattr(initial_setup.os, "geteuid", lambda: 1000)
    with pytest.raises(PermissionError):
        initial_setup.configure_gateway("id", "telegram", "x" * 24)
    with pytest.raises(PermissionError):
        initial_setup.pair_gateway_sender("id", "bot", "sender", "chat", "personal")
    monkeypatch.setattr(initial_setup.os, "geteuid", lambda: 0)
    with pytest.raises(ValueError):
        initial_setup.configure_gateway("id", "whatsapp", "x" * 24)
    with pytest.raises(ValueError):
        initial_setup.configure_gateway("id", "telegram", "short")
    with pytest.raises(ValueError):
        initial_setup.pair_gateway_sender("id", "bot", "sender", "chat", "personal", ("root",))


def test_recovery_pending_prevents_success_without_loading_raw_codes(monkeypatch):
    monkeypatch.setattr(initial_setup.os, "geteuid", lambda: 0)
    monkeypatch.setattr(initial_setup, "owners", lambda: [{"username": "owner", "uid": 1001}])
    monkeypatch.setattr(initial_setup, "enrolled_owner", lambda name: SimpleNamespace(pw_uid=1001))
    monkeypatch.setattr(initial_setup, "recovery_pending", lambda: True)
    from haos import owner_recovery
    monkeypatch.setattr(owner_recovery.RecoveryCodes, "__init__", lambda self: None)
    monkeypatch.setattr(owner_recovery.RecoveryCodes, "_load", lambda self: {"owners": {"1001": {"hashes": ["dummy"] * 10}}})
    assert initial_setup.account_status()["complete"] is False
    with pytest.raises(PermissionError):
        initial_setup.finalize()
