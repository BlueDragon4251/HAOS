"""Root-seat regional selection and private helper arguments; no live accounts."""
import pytest

from haos import initial_setup, initial_setup_gui, provider_setup
from haos.provider_auth import minimax_login, anthropic_login


@pytest.mark.parametrize("endpoint,region", [("", "global"),
    ("https://api.minimax.io/anthropic", "global"), ("https://api.minimaxi.com/anthropic", "cn")])
def test_minimax_status_uses_the_exact_selected_region_before_execution(monkeypatch, endpoint, region):
    calls = []
    monkeypatch.setattr(initial_setup, "require_root", lambda: None)
    monkeypatch.setattr(initial_setup_gui, "session_allowed", lambda: True)
    monkeypatch.setattr(provider_setup, "auth_helper", lambda *args, **kwargs: calls.append((args, kwargs)))
    monkeypatch.setattr(initial_setup, "quiesce_for_setup", lambda: pytest.fail("status must not stop missions"))
    initial_setup.provider_account("minimax-oauth", "status", endpoint)
    assert calls == [(("status", "minimax-oauth"), {"graphical_status": True, "region": region})]
    with pytest.raises(PermissionError):
        initial_setup.provider_account("minimax-oauth", "status", "https://attacker.invalid/anthropic")
    assert len(calls) == 1


def test_minimax_graphical_login_passes_only_a_fixed_region_to_private_terminal(monkeypatch):
    calls, stopped = [], []
    monkeypatch.setattr(initial_setup, "require_root", lambda: None)
    monkeypatch.setattr(initial_setup_gui, "session_allowed", lambda: True)
    monkeypatch.setattr(initial_setup, "quiesce_for_setup", lambda: stopped.append(True))
    monkeypatch.setattr(initial_setup.subprocess, "run", lambda *args, **kwargs: calls.append((args, kwargs)))
    endpoint = "https://api.minimaxi.com/anthropic"
    initial_setup.provider_account("minimax-oauth", "login", endpoint)
    assert stopped == [True] and calls[0][0][0][-3:] == ["login", "minimax-oauth", "cn"]
    assert endpoint not in calls[0][0][0]
    monkeypatch.setattr(initial_setup_gui, "session_allowed", lambda: False)
    with pytest.raises(PermissionError):
        initial_setup.provider_account("minimax-oauth", "login", endpoint)
    assert len(calls) == 1


def test_unknown_regions_and_cross_provider_region_flags_fail_before_optional_imports():
    with pytest.raises(ValueError):
        minimax_login("unreviewed")
    with pytest.raises(ValueError):
        provider_setup.auth_helper("login", "qwen-oauth", region="cn")
    with pytest.raises(ValueError):
        provider_setup.auth_helper("login", "minimax-oauth", region="unreviewed")


def test_anthropic_code_entry_requires_a_private_terminal_before_optional_imports(monkeypatch):
    import sys
    from types import SimpleNamespace
    monkeypatch.setattr(sys, "stdin", SimpleNamespace(isatty=lambda: False))
    with pytest.raises(PermissionError, match="protected owner terminal"):
        anthropic_login()
