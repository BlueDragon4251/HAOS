#!/usr/bin/env python3
"""Pinned Hermes resolver/Responses contract, with no external model call or credential."""

import json
import os
from pathlib import Path
import secrets
import sys
import tempfile


def main():
    sys.path.insert(0, sys.argv[1])
    from haos.provider_policy import BASE, ENDPOINTS, ProviderPolicy
    with tempfile.TemporaryDirectory(prefix="haos-provider-contract-") as directory:
        os.environ["HOME"] = directory
        os.environ["HERMES_HOME"] = str(Path(directory) / ".hermes")
        capability = secrets.token_urlsafe(48)
        os.environ["HAOS_MODEL_TOKEN"] = capability
        from hermes_cli.config import DEFAULT_CONFIG, load_config
        from hermes_cli.runtime_provider import resolve_runtime_provider
        from agent.transports.codex import ResponsesApiTransport
        from agent.codex_headers import codex_cloudflare_headers
        from hermes_cli.auth_codex import resolve_codex_runtime_credentials
        policy = ProviderPolicy({"version": 1, "provider": "openai-codex", "endpoint": ENDPOINTS["openai-codex"],
                                 "models": ["gpt-5.4"], "default_model": "gpt-5.4", "api_mode": "codex_responses",
                                 "requests_per_day": 20, "requests_per_minute": 10})
        client = policy.client_config()
        assert client["_config_version"] == DEFAULT_CONFIG["_config_version"], "review client schema before updating pinned Hermes"
        home = Path(os.environ["HERMES_HOME"])
        home.mkdir(mode=0o700, exist_ok=True)
        config = home / "config.yaml"
        config.write_text(json.dumps(client))
        config.chmod(0o400)
        loaded = load_config()
        assert loaded["model"]["base_url"] == BASE
        runtime = resolve_runtime_provider(requested="custom:haos-model", target_model="gpt-5.4")
        assert runtime["provider"] == "custom" and runtime["api_mode"] == "codex_responses"
        assert runtime["api_key"] == capability and runtime["base_url"].rstrip("/") == BASE
        transport = ResponsesApiTransport()
        kwargs = transport.build_kwargs("gpt-5.4", [{"role": "user", "content": "Contract only; do not execute"}],
                                        tools=[{"type": "function", "function": {"name": "fixture", "parameters": {"type": "object"}}}],
                                        provider="custom", base_url=BASE, max_tokens=8192)
        kwargs["stream"] = True
        wire = policy.request("/v1/responses", kwargs)
        assert wire["instructions"] and wire["input"] and wire["tools"][0]["type"] == "function"
        assert wire["store"] is False and "max_output_tokens" not in wire
        assert callable(resolve_codex_runtime_credentials) and codex_cloudflare_headers("")["originator"] == "hermes-agent"
        result = {"native_runtime_resolver": True, "native_responses_tool_contract": True,
                  "oauth_resolver_present": True, "provider_connected": False, "model_turn_tested": False}
    Path(sys.argv[2]).write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result))


if __name__ == "__main__":
    main()
