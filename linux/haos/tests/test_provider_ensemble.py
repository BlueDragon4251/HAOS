from copy import deepcopy
import pytest
from haos.provider_routes import ProviderRoutes


def configuration():
    policy = {"version": 1, "provider": "local", "endpoint": "http://127.0.0.1:11434/v1", "api_mode": "chat_completions",
              "models": ["fixture"], "default_model": "fixture", "requests_per_day": 200, "requests_per_minute": 30}
    return {"version": 2, "default": "local", "routes": {"local": policy}, "fallbacks": {},
            "ensembles": {"personal": {"references": [{"route": "local", "model": "fixture"}],
                                         "aggregator": {"route": "local", "model": "fixture"}}}, "default_ensemble": "personal"}


def test_moa_routes_use_only_scoped_broker_credentials_and_replace_unsafe_upstream_default():
    config = ProviderRoutes(configuration()).client_config()
    assert config["model"] == {"provider": "moa", "default": "personal", "api_mode": "chat_completions"}
    assert config["moa"]["privacy_filter"] == "full" and config["moa"]["save_traces"] is False
    assert config["moa"]["presets"]["default"] == config["moa"]["presets"]["personal"]
    preset = config["moa"]["presets"]["personal"]
    for slot in [*preset["reference_models"], preset["aggregator"]]:
        assert slot["provider"] == "custom:haos-local"
        assert "api_key" not in slot and "base_url" not in slot
    assert config["providers"]["haos-local"]["key_env"] == "HAOS_MODEL_TOKEN"


@pytest.mark.parametrize("change", [
    {"route": "unapproved", "model": "fixture"}, {"route": "local", "model": "unapproved"},
    {"route": "local", "model": "fixture", "base_url": "https://attacker.invalid"},
    {"route": "local", "model": "fixture", "api_key": "fixture-key"},
])
def test_moa_cannot_grant_a_provider_model_url_or_credential(change):
    data = configuration()
    data["ensembles"]["personal"]["aggregator"] = change
    with pytest.raises(PermissionError):
        ProviderRoutes(data)


def test_moa_fanout_and_unknown_preset_are_bounded():
    data = configuration()
    data["ensembles"]["personal"]["references"] *= 3
    with pytest.raises(ValueError):
        ProviderRoutes(data)
    data = configuration()
    data["default_ensemble"] = "missing"
    with pytest.raises(ValueError):
        ProviderRoutes(data)
