"""Cloud policy and credential admission; no live SDK/account acceptance."""
import json
import pytest

from haos.provider_cloud import credential_data, valid_endpoint
from haos.provider_policy import ProviderPolicy
from haos.provider_registry import default_mode


@pytest.mark.parametrize("provider,good,bad", [
    ("bedrock", "https://bedrock-runtime.eu-central-1.amazonaws.com", "https://bedrock-runtime.eu-central-1.amazonaws.com.attacker.invalid"),
    ("vertex", "https://us-central1-aiplatform.googleapis.com/v1beta1/projects/fixture-project/locations/us-central1/endpoints/openapi",
     "https://us-central1-aiplatform.googleapis.com/v1beta1/projects/../locations/us-central1/endpoints/openapi"),
    ("azure-foundry", "https://fixture.services.ai.azure.com/openai/v1", "https://services.ai.azure.com.attacker.invalid/v1"),
])
def test_cloud_endpoint_admission_retains_verified_service_boundaries(provider, good, bad):
    assert valid_endpoint(provider, good)
    for value in (bad, good.replace("https:", "http:"), good + "?secret=x", good + "#x", good.replace("https://", "https://user:pass@")):
        assert not valid_endpoint(provider, value)
    policy = ProviderPolicy({"version": 1, "provider": provider, "endpoint": good, "api_mode": default_mode(provider),
                             "models": ["fixture-model"], "default_model": "fixture-model", "requests_per_day": 200, "requests_per_minute": 30})
    assert "fixture-model" in str(policy.client_config())
    with pytest.raises(PermissionError):
        ProviderPolicy({**policy.data, "endpoint": bad})


@pytest.mark.parametrize("provider,value", [
    ("bedrock", {"access_key_id": "fixture"}),
    ("bedrock", {"profile": "fixture", "endpoint_url": "https://attacker.invalid"}),
    ("vertex", {"type": "service_account", "token_uri": "https://attacker.invalid/token"}),
    ("vertex", {"type": "external_account", "credential_source": "file"}),
    ("azure-foundry", {"tenant_id": "../../other", "client_id": "fixture", "client_secret": "fixture"}),
])
def test_cloud_credential_cannot_override_token_or_model_network_routes(provider, value):
    with pytest.raises((ValueError, PermissionError)):
        credential_data(provider, json.dumps(value))


def test_aws_complete_pair_and_service_uid_chain_are_explicit_choices():
    value = {"access_key_id": "fixture-access", "secret_access_key": "fixture-secret", "session_token": "fixture-session"}
    assert credential_data("bedrock", json.dumps(value)) == value
    assert credential_data("bedrock", None) == {}
    assert credential_data("azure-foundry", "fixture-api-key") == {"api_key": "fixture-api-key"}


@pytest.mark.parametrize("endpoint", ["http://api.example.com/v1", "https://127.0.0.1/v1", "https://192.168.1.1/v1",
                                     "https://localhost/v1", "https://fixture.local/v1", "https://api.example.com/../admin",
                                     "https://user:password@api.example.com/v1", "https://api.example.com/v1?key=secret"])
def test_custom_api_cannot_expose_private_administration_or_smuggle_credentials(endpoint):
    from haos.provider_policy import custom_endpoint
    with pytest.raises(PermissionError):
        custom_endpoint(endpoint)


def test_custom_dns_is_checked_once_and_connection_is_pinned_with_original_tls_hostname(monkeypatch):
    from types import SimpleNamespace
    import socket
    import ssl
    from haos.provider_proxy import Handler
    from haos.redaction import Redactor
    calls = []
    policy = ProviderPolicy({"version": 1, "provider": "custom", "endpoint": "https://fixture.example.com/v1",
        "api_mode": "chat_completions", "models": ["fixture"], "default_model": "fixture", "requests_per_day": 20, "requests_per_minute": 10})
    class Connection:
        def __init__(self, hostname, port, *, timeout, context):
            assert hostname == "fixture.example.com" and context.check_hostname and context.verify_mode == ssl.CERT_REQUIRED
        def request(self, *args, **kwargs):
            self._create_connection(("fixture.example.com", 443), 180)
        def getresponse(self):
            return SimpleNamespace(status=429)
        def close(self):
            pass
    monkeypatch.setattr("haos.provider_proxy.http.client.HTTPSConnection", Connection)
    monkeypatch.setattr(socket, "getaddrinfo", lambda *args, **kwargs: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443))])
    monkeypatch.setattr(socket, "create_connection", lambda address, **kwargs: calls.append(address))
    handler = SimpleNamespace(policy=policy, route_credentials=SimpleNamespace(query={}))
    assert Handler.forward(handler, {"model": "fixture"}, {}, Redactor(), defer_errors=True) == (429, {})
    assert calls == [("93.184.216.34", 443)]
    calls.clear()
    monkeypatch.setattr(socket, "getaddrinfo", lambda *args, **kwargs: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", 443))])
    with pytest.raises(PermissionError):
        Handler.forward(handler, {"model": "fixture"}, {}, Redactor(), defer_errors=True)
    assert calls == []
