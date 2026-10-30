import secrets
import sys
from types import SimpleNamespace
import pytest
from haos.provider_policy import ProviderPolicy
from haos.provider_proxy import Credentials
from haos.provider_registry import default_mode


def policy(model="gpt-6-sol"):
    return ProviderPolicy({"version": 1, "provider": "copilot", "endpoint": "https://api.githubcopilot.com",
        "api_mode": default_mode("copilot", model), "models": [model], "default_model": model,
        "requests_per_day": 200, "requests_per_minute": 30})


def test_copilot_exchanges_and_redacts_both_tokens_and_limits_enterprise_routing(monkeypatch):
    monkeypatch.setattr("haos.provider_copilot.bind_transport", lambda: None)
    raw, short = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
    called = []
    def exchange(value):
        called.append(value)
        return short, 1234567890, "https://api.business.githubcopilot.com"
    monkeypatch.setitem(sys.modules, "hermes_cli.copilot_auth", SimpleNamespace(
        exchange_copilot_token=exchange, resolve_copilot_token=lambda: (raw, "private-store"),
        copilot_request_headers=lambda: {"Copilot-Integration-Id": "fixture"}))
    credential = Credentials(policy(), {"api_key": None})
    headers, redactor = credential.headers()
    assert called == [raw] and headers["Authorization"] == "Bearer " + short
    assert credential.effective_endpoint == "https://api.business.githubcopilot.com"
    assert raw not in redactor.text(raw) and short not in redactor.text(short)
    monkeypatch.setitem(sys.modules, "hermes_cli.copilot_auth", SimpleNamespace(
        exchange_copilot_token=lambda value: (short, 123, "https://attacker.invalid"),
        resolve_copilot_token=lambda: (raw, "private-store"), copilot_request_headers=lambda: {}))
    with pytest.raises(PermissionError):
        credential.headers()


@pytest.mark.parametrize("model,mode", [("gpt-6-sol", "codex_responses"), ("gpt-5.4", "codex_responses"),
    ("gpt-5-mini", "chat_completions"), ("claude-sonnet-5", "chat_completions")])
def test_copilot_default_mode_matches_the_model_wire_family(model, mode):
    assert default_mode("copilot", model) == mode
    p = policy(model)
    with pytest.raises(ValueError):
        ProviderPolicy({**p.data, "api_mode": "chat_completions" if mode == "codex_responses" else "codex_responses"})
