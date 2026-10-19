#!/usr/bin/env python3
"""Pinned Codex catalog/routing and signed AWS control-plane HTTP fixtures."""
from contextlib import contextmanager
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
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
    checks = 0
    for provider in ("opencode-go", "opencode-zen", "azure-foundry"):
        for model in [*registry()[provider]["fallback_models"], "gpt-6-sol", "qwen-fixture", "claude-fixture", "kimi-fixture", "openai/gpt-5-mini"]:
            expected = (azure_foundry_model_api_mode(model) or "chat_completions" if provider == "azure-foundry" else
                        opencode_model_api_mode(provider, model))
            assert default_mode(provider, model) == expected
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
            return SimpleNamespace(client=lambda service, **options: actual.client(service, endpoint_url=endpoint, **options))
        boto3.Session = make_session
        try:
            policy = ProviderPolicy({"version": 1, "provider": "bedrock", "endpoint": "https://bedrock-runtime.us-east-1.amazonaws.com",
                "api_mode": "chat_completions", "models": ["fixture"], "default_model": "fixture",
                "requests_per_day": 200, "requests_per_minute": 30})
            result = discover(policy, json.dumps({"access_key_id": key, "secret_access_key": secret, "session_token": session}))
            assert result["source"] == "sdk-catalog"
            assert [row["id"] for row in result["models"]] == ["anthropic.fixture", "global.anthropic.fixture"]
            assert all(call[1]["Authorization"].startswith("AWS4-HMAC-SHA256 Credential=" + key + "/") for call in received[2:])
            assert all(call[1]["X-Amz-Security-Token"] == session for call in received[2:])
            assert secret not in json.dumps(result) and session not in json.dumps(result)
        finally:
            boto3.Session = original
    receipt = {"actual_codex_catalog_helper_http": True, "actual_boto3_control_plane_signing": True,
        "generated_routing_cases_match_upstream": checks, "static_catalog_is_not_entitlement": True,
        "live_provider_tested": False, "python": sys.version.split()[0], "source_sha256": {
            path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in
            (Path(__file__), root / "haos/provider_discovery.py", root / "haos/hermes_registry.json")}}
    Path(sys.argv[2]).write_text(json.dumps(receipt, indent=2) + "\n")
    print(json.dumps(receipt))


if __name__ == "__main__":
    main()
