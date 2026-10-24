#!/usr/bin/env python3
"""Pinned Codex catalog/routing and signed AWS control-plane HTTP fixtures."""
from contextlib import contextmanager
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
import tempfile
from pathlib import Path
import secrets
import sys
import threading
from types import SimpleNamespace


@contextmanager
def serving(server):
    thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True)
    thread.start()
    try:
        yield server.server_port
    finally:
        server.shutdown()
        server.server_close()
        thread.join(5)


def main():
    root = Path(sys.argv[1]).resolve()
    sys.path.insert(0, str(root))
    from haos.provider_discovery import http_catalog, discover
    from haos.provider_policy import ProviderPolicy
    from haos.provider_registry import default_mode, registry
    from haos.redaction import Redactor
    from hermes_cli.models import opencode_model_api_mode, azure_foundry_model_api_mode
    from hermes_cli.runtime_provider import _detect_api_mode_for_url
    from agent.bedrock_adapter import is_openai_bedrock_model, is_anthropic_bedrock_model, BEDROCK_OPENAI_RESPONSES_MODEL_IDS
    checks = 0
    for provider in ("opencode-go", "opencode-zen", "azure-foundry"):
        for model in [*registry()[provider]["fallback_models"], "gpt-6-sol", "qwen-fixture", "claude-fixture", "kimi-fixture", "openai/gpt-5-mini"]:
            expected = (azure_foundry_model_api_mode(model) or "chat_completions" if provider == "azure-foundry" else
                        opencode_model_api_mode(provider, model))
            assert default_mode(provider, model) == expected
            checks += 1
    for suffix in ("/anthropic", "/anthropic/v1", "/anthropic/v1/", "/ANTHROPIC", "/openai/v1", "/anthropic-other"):
        endpoint = "https://fixture.services.ai.azure.com" + suffix
        for model in ("claude-opus-4.6", "gpt-5.4"):
            expected = ("anthropic_messages" if _detect_api_mode_for_url(endpoint) == "anthropic_messages"
                else azure_foundry_model_api_mode(model) or "chat_completions")
            assert default_mode("azure-foundry", model, endpoint) == expected
            checks += 1
    for model in [*registry()["bedrock"]["fallback_models"], *BEDROCK_OPENAI_RESPONSES_MODEL_IDS,
            "openai.gpt-oss-120b-1:0", "global.anthropic.claude-opus-4-6-v1", "fixture"]:
        expected = "codex_responses" if is_openai_bedrock_model(model) else "anthropic_messages" if is_anthropic_bedrock_model(model) else "chat_completions"
        assert default_mode("bedrock", model) == expected
        checks += 1
    received = []
    key, secret, session = "fixture-aws-access", secrets.token_urlsafe(40), secrets.token_urlsafe(40)
    class Fixture(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass
        def do_GET(self):
            received.append((self.path, dict(self.headers)))
            if self.path.startswith("/backend-api/codex/models"):
                if "99.0.0" in self.path:
                    result = {"models": []}
                else:
                    result = {"models": [{"slug": "codex-fixture", "visibility": "list", "priority": 1},
                        {"slug": "hidden-fixture", "visibility": "hidden"}, {"slug": secret}]}
            elif self.path == "/foundation-models":
                result = {"modelSummaries": [{"modelId": "anthropic.fixture", "modelName": "Fixture model", "providerName": "Anthropic",
                    "outputModalities": ["TEXT"], "inputModalities": ["TEXT"], "modelLifecycle": {"status": "ACTIVE"},
                    "responseStreamingSupported": True}, {"modelId": "embedding-fixture", "outputModalities": ["EMBEDDING"]}]}
            elif self.path.startswith("/inference-profiles"):
                result = {"inferenceProfileSummaries": [{"inferenceProfileId": "global.anthropic.fixture", "inferenceProfileName": "Fixture profile", "status": "ACTIVE"}]}
            else:
                raise AssertionError("unexpected native catalog path")
            if self.path == "/foundation-models":
                result["modelSummaries"].extend({**result["modelSummaries"][0], "modelId": value} for value in (key, secret, session))
            body = json.dumps(result).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
    with serving(ThreadingHTTPServer(("127.0.0.1", 0), Fixture)) as port:
        endpoint = "http://127.0.0.1:" + str(port)
        policy = SimpleNamespace(provider="openai-codex", endpoint=endpoint, api_mode="codex_responses")
        credentials = SimpleNamespace(headers=lambda: ({"Authorization": "Bearer " + secret, "ChatGPT-Account-ID": "fixture-account"}, Redactor([secret])),
            effective_endpoint=endpoint, query={})
        result = http_catalog(policy, credentials)
        assert result["models"] == [{"id": "codex-fixture", "api_mode": "codex_responses"}]
        assert len(received) == 2 and all(call[1]["ChatGPT-Account-ID"] == "fixture-account" for call in received)
        # Keep the actual Session, signer and control-plane response decoder;
        # replace only the fixture destination inside this explicit probe.
        import boto3
        original = boto3.Session
        def make_session(**kwargs):
            actual = original(**kwargs)
            return SimpleNamespace(get_credentials=actual.get_credentials, client=lambda service, **options: actual.client(service, endpoint_url=endpoint, **options))
        boto3.Session = make_session
        try:
            policy = ProviderPolicy({"version": 1, "provider": "bedrock", "endpoint": "https://bedrock-runtime.us-east-1.amazonaws.com",
                "api_mode": "chat_completions", "models": ["fixture"], "default_model": "fixture",
                "requests_per_day": 200, "requests_per_minute": 30})
            with tempfile.TemporaryDirectory() as directory:
                credential_file = Path(directory)/"credentials"; config = Path(directory)/"config"
                credential_file.write_text(f"[default]\naws_access_key_id={key}\naws_secret_access_key={secret}\naws_session_token={session}\n"
                    f"[fixture]\naws_access_key_id={key}\naws_secret_access_key={secret}\naws_session_token={session}\n")
                credential_file.chmod(0o600); config.write_text("")
                overrides = {"AWS_SHARED_CREDENTIALS_FILE": str(credential_file), "AWS_CONFIG_FILE": str(config), "AWS_EC2_METADATA_DISABLED": "true"}
                keys = {*overrides, "AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "AWS_SESSION_TOKEN", "AWS_PROFILE", "AWS_DEFAULT_PROFILE"}
                previous = {name: os.environ.get(name) for name in keys}
                try:
                    for name in keys: os.environ.pop(name, None)
                    os.environ.update(overrides)
                    for credential in (json.dumps({"access_key_id": key, "secret_access_key": secret, "session_token": session}),
                            json.dumps({"profile": "fixture"}), None):
                        result = discover(policy, credential)
                        assert result["source"] == "sdk-catalog"
                        assert [row["id"] for row in result["models"]] == ["anthropic.fixture", "global.anthropic.fixture"]
                        assert all(value not in json.dumps(result) for value in (key, secret, session))
                finally:
                    for name, value in previous.items():
                        if value is None: os.environ.pop(name, None)
                        else: os.environ[name] = value
            assert all(call[1]["Authorization"].startswith("AWS4-HMAC-SHA256 Credential=" + key + "/") for call in received[2:])
            assert all(call[1]["X-Amz-Security-Token"] == session for call in received[2:])
        finally:
            boto3.Session = original
    receipt = {"actual_codex_catalog_helper_http": True, "actual_boto3_control_plane_signing": True, "aws_explicit_profile_default_chain_catalog_cases": 3,
        "generated_routing_cases_match_upstream": checks, "static_catalog_is_not_entitlement": True,
        "live_provider_tested": False, "python": sys.version.split()[0], "source_sha256": {
            path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in
            (Path(__file__), root / "haos/provider_discovery.py", root / "haos/provider_cloud.py", root / "haos/provider_proxy.py", root / "haos/provider_registry.py", root / "haos/hermes_registry.json")}}
    Path(sys.argv[2]).write_text(json.dumps(receipt, indent=2) + "\n")
    print(json.dumps(receipt))


if __name__ == "__main__":
    main()
