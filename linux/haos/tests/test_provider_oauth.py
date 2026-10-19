"""Resolver dispatch/route isolation. These are not real-account OAuth tests."""
import sys
from types import SimpleNamespace

import pytest

from haos.provider_policy import ProviderPolicy
from haos.provider_proxy import Credentials
from haos.provider_registry import default_mode, default_endpoint


@pytest.mark.parametrize("provider", ["nous", "xai-oauth", "qwen-oauth", "openrouter"])
def test_private_upstream_resolver_is_used_without_exposing_provider_token(provider, monkeypatch):
    seen, secret = [], "private-fixture-token-00000000000000"
    policy = ProviderPolicy({"version": 1, "provider": provider, "endpoint": default_endpoint(provider),
                             "api_mode": default_mode(provider), "models": ["fixture"], "default_model": "fixture",
                             "requests_per_day": 20, "requests_per_minute": 10})
    def resolve(**kwargs):
        seen.append(kwargs)
        return {"base_url": policy.endpoint, "api_mode": policy.api_mode, "api_key": secret}
    monkeypatch.setitem(sys.modules, "hermes_cli.runtime_provider", SimpleNamespace(resolve_runtime_provider=resolve))
    headers, redactor = Credentials(policy, {"api_key": None}).headers()
    assert headers["Authorization"] == "Bearer " + secret
    assert seen == [{"requested": provider, "target_model": "fixture"}]
    assert secret not in redactor.text(secret)
    assert secret not in str(policy.client_config())
    monkeypatch.setitem(sys.modules, "hermes_cli.runtime_provider", SimpleNamespace(resolve_runtime_provider=lambda **kwargs: {
        "base_url": "https://attacker.invalid/v1", "api_mode": policy.api_mode, "api_key": secret}))
    with pytest.raises(PermissionError):
        Credentials(policy, {"api_key": None}).headers()
