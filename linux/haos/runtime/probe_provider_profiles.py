#!/usr/bin/env python3
"""Compare actual upstream wire hooks through broker routes without network."""
import hashlib
import json
from pathlib import Path
import socket
import sys


def main():
    root = Path(sys.argv[1]).resolve()
    sys.path.insert(0, str(root))
    from haos.provider_profiles import register_profiles
    from haos.provider_policy import ProviderPolicy
    from haos.provider_registry import http_providers, descriptor, default_mode, default_endpoint
    from providers import get_provider_profile
    from agent.transports import get_transport
    from agent.transports.chat_completions import ChatCompletionsTransport
    from agent.transports.codex import ResponsesApiTransport
    checks = []
    old_dns, old_connect = socket.getaddrinfo, socket.socket.connect
    def no_network(*_args, **_kwargs):
        raise PermissionError("provider wire projection must not use network")
    socket.getaddrinfo, socket.socket.connect = no_network, no_network
    try:
        for provider in sorted(http_providers() | {"gemini", "copilot", "copilot-acp", "bedrock", "openai-codex",
                "nous", "xai-oauth", "qwen-oauth", "minimax-oauth", "azure-foundry", "vertex", "lmstudio", "custom", "local"}):
            row = descriptor(provider)
            model = next(iter(row["fallback_models"]), "fixture-model") if row else "fixture-model"
            if provider == "copilot-acp":
                model = "fixture-model"
            mode = default_mode(provider, model)
            endpoint = {"local": "http://127.0.0.1:11434/v1", "custom": "https://fixture.example.com/v1",
                "azure-foundry": "https://fixture.services.ai.azure.com/openai/v1",
                "vertex": "https://us-central1-aiplatform.googleapis.com/v1beta1/projects/fixture-project/locations/us-central1/endpoints/openapi"}.get(provider, default_endpoint(provider))
            policy = ProviderPolicy({"version": 1, "provider": provider, "endpoint": endpoint,
                "models": [model], "default_model": model, "api_mode": mode,
                "requests_per_day": 200, "requests_per_minute": 30})
            original = get_provider_profile(provider) or get_provider_profile("custom")
            profiles = register_profiles(policy.data)
            profile, _, _ = next(iter(profiles.values()))
            assert profile.auth_type == "api_key" and profile.env_vars == ("HAOS_MODEL_TOKEN",)
            assert profile.auth_handler is None and profile.refresh_credential is None
            assert profile.process_command == "" and profile.process_args == ()
            assert profile.default_headers == {} and profile.create_client(api_key="fixture-capability") is None
            if mode == "anthropic_messages":
                checks.append(provider + ":safe-profile-admission")
                continue
            messages = [{"role": "system", "content": "fixture-only system"}, {"role": "user", "content": "fixture-only prompt"}]
            tools = [{"type": "function", "function": {"name": "fixture", "parameters": {"type": "object"}}}]
            params = {"reasoning_config": {"enabled": True, "effort": "high"}, "supports_reasoning": True,
                "max_tokens": 4096, "temperature": 0.2, "session_id": "fixture-session", "cache_scope_id": "fixture-cache"}
            if provider == "qwen-oauth":
                params["qwen_session_metadata"] = {"sessionId": "fixture-session", "promptId": "fixture-prompt"}
            native = ChatCompletionsTransport() if mode == "chat_completions" else ResponsesApiTransport()
            expected = native.build_kwargs(model, messages, tools, base_url=policy.endpoint,
                provider=provider, provider_profile=original, **params)
            actual = get_transport(mode).build_kwargs(model, messages, tools,
                base_url=policy.client_config()["model"]["base_url"], provider="custom", **params)
            if actual != expected:
                changed = sorted(key for key in set(actual) | set(expected) if actual.get(key) != expected.get(key))
                raise AssertionError(provider + " broker lost wire fields: " + ",".join(changed))
            checks.append(provider + ":native-wire-kwargs")
            if provider == "qwen-oauth":
                auto = get_transport(mode).build_kwargs(model, messages, tools,
                    base_url=policy.client_config()["model"]["base_url"], session_id="fixture-session")
                assert auto["metadata"]["sessionId"] == "fixture-session" and auto["metadata"]["promptId"]
        # The broker URL must retain a replaying provider's reasoning details.
        provider = "openrouter"
        policy = ProviderPolicy({"version": 1, "provider": provider, "endpoint": default_endpoint(provider),
            "models": ["fixture"], "default_model": "fixture", "api_mode": "chat_completions",
            "requests_per_day": 200, "requests_per_minute": 30})
        register_profiles(policy.data)
        messages = [{"role": "assistant", "content": "fixture", "reasoning_details": [{"type": "reasoning.text", "text": "fixture-only"}]}]
        actual = get_transport("chat_completions").build_kwargs("fixture", messages, base_url=policy.client_config()["model"]["base_url"])
        assert actual["messages"][0]["reasoning_details"] == messages[0]["reasoning_details"]
    finally:
        socket.getaddrinfo, socket.socket.connect = old_dns, old_connect
    receipt = {"actual_pinned_provider_wire_cases": checks, "network_disabled_during_projection": True,
        "agent_profiles_have_only_broker_capability": True, "upstream_client_and_auth_hooks_not_delegated": True,
        "openrouter_reasoning_replay_through_broker": True, "live_provider_tested": False, "python": sys.version.split()[0],
        "source_sha256": {path.name: hashlib.sha256(path.read_bytes()).hexdigest()
            for path in (Path(__file__), root / "haos/provider_profiles.py", root / "haos/sandbox.py", root / "haos/serve.py")}}
    Path(sys.argv[2]).write_text(json.dumps(receipt, indent=2) + "\n")
    print(json.dumps({**receipt, "actual_pinned_provider_wire_cases": len(checks)}))


if __name__ == "__main__":
    main()
