from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import secrets
from types import SimpleNamespace
import threading
import pytest

from haos import provider_discovery as discovery
from haos.provider_policy import ProviderPolicy
from haos.provider_proxy import Credentials
from haos.provider_registry import default_mode
from haos.redaction import Redactor


@contextmanager
def fixture(payloads, *, status=200, truncated=False):
    calls = []
    class Server(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass
        def do_GET(self):
            calls.append((self.path, dict(self.headers)))
            data = json.dumps(payloads[min(len(calls) - 1, len(payloads) - 1)]).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data) + (16 if truncated else 0)))
            self.send_header("Connection", "close")
            if status == 302:
                self.send_header("Location", "http://127.0.0.1:9119/api/env")
            self.end_headers()
            self.wfile.write(data)
            self.close_connection = True
    server = ThreadingHTTPServer(("127.0.0.1", 0), Server)
    thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True)
    thread.start()
    try:
        yield "http://127.0.0.1:" + str(server.server_port), calls
    finally:
        server.shutdown()
        server.server_close()
        thread.join(5)


def local(endpoint):
    return ProviderPolicy({"version": 1, "provider": "local", "endpoint": endpoint + "/v1",
        "models": ["fixture"], "default_model": "fixture", "api_mode": "chat_completions",
        "requests_per_day": 200, "requests_per_minute": 30})


def test_real_catalog_http_key_is_private_and_reflected_or_unsafe_model_ids_are_not_returned():
    key = secrets.token_urlsafe(40)
    with fixture([{"data": [{"id": value} for value in ("fixture-model", "fixture-model", key, "../admin", "untrusted\nheader")]}]) as (endpoint, calls):
        policy = local(endpoint)
        result = discovery.discover(policy, key)
    assert result["models"] == [{"id": "fixture-model", "api_mode": "chat_completions"}]
    assert result["source"] == "provider-api" and result["inference_tested"] is False
    assert calls[0][0] == "/v1/models" and calls[0][1]["Authorization"] == "Bearer " + key
    assert key not in json.dumps(result)


def test_catalog_redirects_are_not_followed_and_offline_provenance_is_not_account_acceptance():
    with fixture([{}], status=302) as (endpoint, calls):
        result = discovery.discover(local(endpoint), None)
    assert len(calls) == 1 and result["source"] == "unavailable"
    assert result["diagnostic"] == "catalog-unavailable" and result["inference_tested"] is False
    offline = discovery.fallback("openai-codex", "account-required")
    assert offline["models"] and offline["source"] == "upstream-offline" and not offline["inference_tested"]
    assert discovery.fallback("copilot-acp", "account-required")["models"] == []


def test_short_http_catalog_is_not_published_even_if_json_itself_is_valid():
    with fixture([{"data": [{"id": "incomplete-fixture"}]}], truncated=True) as (endpoint, calls):
        result = discovery.discover(local(endpoint), None)
    assert len(calls) == 1
    assert result["source"] == "unavailable" and result["models"] == []
    assert result["diagnostic"] == "catalog-unavailable" and not result["inference_tested"]


def test_native_gemini_catalog_pagination_uses_google_key_header_and_text_generation_models_only():
    key = secrets.token_urlsafe(40)
    with fixture([{"models": [{"name": "models/gemini-fixture", "supportedGenerationMethods": ["generateContent"]},
                              {"name": "models/embedding", "supportedGenerationMethods": ["embedContent"]}], "nextPageToken": "cursor"},
                  {"models": [{"name": "models/gemini-next", "supportedGenerationMethods": ["generateContent"]}]}]) as (endpoint, calls):
        # Only the test supplies this loopback replacement; production accepts
        # Gemini's fixed HTTPS endpoint through ProviderPolicy.
        policy = SimpleNamespace(provider="gemini", endpoint=endpoint + "/v1beta", api_mode="chat_completions")
        credentials = SimpleNamespace(headers=lambda: ({"Authorization": "Bearer " + key}, Redactor([key])),
                                       effective_endpoint=policy.endpoint, query={})
        result = discovery.http_catalog(policy, credentials)
    assert [row["id"] for row in result["models"]] == ["gemini-fixture", "gemini-next"]
    assert len(calls) == 2 and "pageToken=cursor" in calls[1][0]
    assert calls[0][1]["x-goog-api-key"] == key and "Authorization" not in calls[0][1]


def test_native_messages_catalog_retains_native_auth_and_bounded_cursor_pagination():
    with fixture([{"data": [{"id": "claude-fixture"}], "has_more": True, "last_id": "one"},
                  {"data": [{"id": "claude-next"}], "has_more": False}]) as (endpoint, calls):
        policy = SimpleNamespace(provider="anthropic", endpoint=endpoint, api_mode="anthropic_messages")
        credentials = SimpleNamespace(headers=lambda: ({"x-api-key": "fixture-only-key"}, Redactor()),
                                       effective_endpoint=endpoint, query={})
        result = discovery.http_catalog(policy, credentials)
    assert len(result["models"]) == 2 and calls[0][0] == "/v1/models?limit=1000"
    assert "after_id=one" in calls[1][0] and calls[0][1]["x-api-key"] == "fixture-only-key"


@pytest.mark.parametrize("change", [{"source": "live-model-tested"}, {"inference_tested": True},
    {"credential": "must-never-return"}, {"models": [{"id": "../../admin", "api_mode": "chat_completions"}]},
    {"models": [{"id": "fixture", "api_mode": "arbitrary-process"}]}])
def test_catalog_receipt_cannot_export_secrets_or_claim_inference_or_grant_an_unreviewed_transport(change):
    result = discovery.receipt("local", ["fixture"], "provider-api")
    with pytest.raises(ValueError):
        discovery.validate_catalog({**result, **change}, "local")


def test_lmstudio_upstream_default_obeys_literal_loopback_policy():
    from haos.provider_registry import default_endpoint
    data = local("http://127.0.0.1:11434").data
    policy = ProviderPolicy({**data, "provider": "lmstudio", "endpoint": default_endpoint("lmstudio")})
    assert policy.endpoint.startswith("http://127.0.0.1:")


def test_catalog_helper_sends_key_only_on_private_stdin_and_keeps_provider_identity_separate(monkeypatch):
    from haos import provider_setup
    key = secrets.token_urlsafe(40)
    monkeypatch.setattr(provider_setup.os, "geteuid", lambda: 0)
    monkeypatch.setattr(provider_setup.pwd, "getpwnam", lambda _: SimpleNamespace(pw_uid=1234))
    calls = []
    def run(command, **kwargs):
        calls.append((command, kwargs))
        assert key not in " ".join(command) and key not in json.dumps(kwargs["env"])
        assert json.loads(kwargs["input"])["credential"] == key
        return SimpleNamespace(returncode=0, stdout=json.dumps(discovery.receipt("local", ["fixture"], "provider-api")).encode())
    monkeypatch.setattr(provider_setup.subprocess, "run", run)
    assert provider_setup.catalog_helper(local("http://127.0.0.1:11434").data, key)["models"]
    command = calls[0][0]
    assert "--pipe" in command and "--property=User=haos-provider" in command
    assert any("/var/lib/haos-provider-acp" in arg for arg in command if arg.startswith("--property=InaccessiblePaths="))
    assert command[-1] == "haos.provider_discovery"
    monkeypatch.setattr(provider_setup.os, "geteuid", lambda: 1234)
    with pytest.raises(PermissionError):
        provider_setup.catalog_helper(local("http://127.0.0.1:11434").data, key)


@pytest.mark.parametrize("provider,model,mode", [("opencode-zen", "claude-sonnet-5", "anthropic_messages"),
    ("opencode-zen", "gpt-6-sol", "codex_responses"), ("opencode-go", "qwen-fixture", "anthropic_messages"),
    ("opencode-go", "kimi-fixture", "chat_completions"), ("azure-foundry", "openai/gpt-5-mini", "codex_responses")])
def test_generated_model_protocol_rules_are_applied_without_importing_plugins_in_root_setup(provider, model, mode):
    assert default_mode(provider, model) == mode


@pytest.mark.parametrize("suffix,expected", [("/anthropic", "anthropic_messages"),
    ("/anthropic/v1", "anthropic_messages"), ("/openai/v1", "chat_completions"),
    ("/anthropic-other", "chat_completions")])
def test_graphical_cloud_discovery_auto_mode_respects_native_endpoint(monkeypatch, suffix, expected):
    from haos import initial_setup, provider_setup
    captured = []
    monkeypatch.setattr(initial_setup, "require_root", lambda: None)
    monkeypatch.setattr(provider_setup, "catalog_helper", lambda policy, key: captured.append((policy, key)))
    endpoint = "https://fixture.services.ai.azure.com" + suffix
    initial_setup.provider_models("azure-foundry", endpoint=endpoint)
    assert captured[0][0]["api_mode"] == expected and captured[0][1] is None
    assert ProviderPolicy(captured[0][0]).endpoint == endpoint
    with pytest.raises(PermissionError):
        ProviderPolicy({**captured[0][0], "endpoint": "https://attacker.invalid/anthropic"})


def test_http_catalog_does_not_certify_a_silently_truncated_page_series():
    pages = [{'data': [{'id': f'fixture-{number}'}], 'has_more': True, 'last_id': str(number)} for number in range(6)]
    with fixture(pages) as (endpoint, calls):
        result = discovery.discover(local(endpoint), None)
    assert len(calls) == 5 and result['diagnostic'] == 'catalog-unavailable'
    assert result['source'] == 'unavailable' and result['models'] == []


def test_http_catalog_requires_cursor_when_provider_reports_more_pages():
    with fixture([{'data': [{'id': 'fixture'}], 'has_more': True}]) as (endpoint, calls):
        result = discovery.discover(local(endpoint), None)
    assert len(calls) == 1 and result['diagnostic'] == 'catalog-unavailable'
    assert result['models'] == []


def test_vertex_publisher_catalog_uses_only_owner_publisher_and_fixed_host_paths():
    with fixture([{'publisherModels': [{'name': value} for value in (
            'publishers/google/models/gemini-fixture', 'publishers/google/models/gemini-fixture',
            'publishers/foreign/models/unapproved', 'publishers/google/models/../admin')], 'nextPageToken': 'page/2'},
            {'publisherModels': [{'name': 'publishers/google/models/gemini-next'}]}]) as (endpoint, calls):
        policy = SimpleNamespace(provider='vertex', data={'default_model': 'google/gemini-fixture'}, api_mode='chat_completions')
        credentials = SimpleNamespace(headers=lambda: ({'Authorization': 'Bearer fixture-only-token'}, Redactor()), effective_endpoint=endpoint)
        result = discovery.vertex_catalog(policy, credentials)
    assert result['models'] == [{'id': name, 'api_mode': 'chat_completions'} for name in ('google/gemini-fixture', 'google/gemini-next')]
    assert result['source'] == 'provider-api' and not result['inference_tested']
    assert calls[0][0].startswith('/v1beta1/publishers/google/models?') and 'pageToken=page%2F2' in calls[1][0]
    assert all(call[1]['Authorization'] == 'Bearer fixture-only-token' for call in calls)


def test_graphical_vertex_discovery_retains_owner_selected_publisher_without_publishing_a_route(monkeypatch):
    from haos import initial_setup, provider_setup
    captured = []
    monkeypatch.setattr(initial_setup, 'require_root', lambda: None)
    monkeypatch.setattr(provider_setup, 'catalog_helper', lambda policy, key: captured.append((policy, key)))
    initial_setup.provider_models('vertex', endpoint='https://us-central1-aiplatform.googleapis.com/v1beta1/projects/fixture-project/locations/us-central1/endpoints/openapi', model='meta/llama-fixture')
    policy = ProviderPolicy(captured[0][0])
    assert policy.data['default_model'] == 'meta/llama-fixture' and policy.models == ['meta/llama-fixture']
    assert captured[0][1] is None and policy.api_mode == 'chat_completions'


@pytest.mark.parametrize('flag', ['true', 1, None])
def test_catalog_rejects_ambiguous_non_boolean_pagination_flags(flag):
    with fixture([{'data': [{'id': 'fixture'}], 'has_more': flag, 'last_id': 'one'}]) as (endpoint, calls):
        result = discovery.discover(local(endpoint), None)
    assert len(calls) == 1 and result['diagnostic'] == 'catalog-unavailable'
    assert result['models'] == []
