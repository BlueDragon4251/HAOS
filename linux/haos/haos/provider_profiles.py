"""Project pinned provider wire hooks onto capability-only broker routes.

The public registry/transport extension seams preserve vendor message and
reasoning behavior. Client construction, real auth and subprocess hooks are
never delegated to the agent. Existing client configuration remains unchanged.
"""
from __future__ import annotations

import json
from pathlib import Path

from .provider_registry import descriptor
from .provider_routes import ProviderRoutes


def register_profiles(data):
    from providers import get_provider_profile, register_provider
    from providers.base import ProviderProfile
    from agent.transports import get_transport, register_transport
    from agent.transports.chat_completions import ChatCompletionsTransport
    from agent.transports.codex import ResponsesApiTransport
    routes = ProviderRoutes(data)
    config = routes.client_config()
    selected = {"haos-model": routes.primary}
    if data["version"] == 2:
        selected.update({"haos-" + key: policy for key, policy in routes.routes.items()})
    profiles = {}
    fields = ("supports_vision", "supports_vision_tool_messages", "supports_prompt_cache_key",
              "native_reasoning_details_type", "fixed_temperature", "default_max_tokens",
              "unsupported_response_formats", "model_capabilities")
    hooks = ("prepare_messages", "build_extra_body", "build_api_kwargs_extras", "get_max_tokens",
             "supported_reasoning_efforts", "default_reasoning_config")
    for name, policy in selected.items():
        source = "openai-api" if policy.provider == "openai" else policy.provider
        if descriptor(source) is None and source != "local":
            raise ValueError("broker wire profile is outside the reviewed registry")
        original = get_provider_profile(source) or get_provider_profile("custom")
        route = config["providers"][name]
        attributes = {}
        def delegate(hook, original=original, endpoint=policy.endpoint):
            def call(self, *args, **kwargs):
                if "base_url" in kwargs:
                    kwargs["base_url"] = endpoint
                if hook == "build_api_kwargs_extras" and original.name == "qwen-oauth" and not kwargs.get("qwen_session_metadata"):
                    # Hermes ordinarily derives this from the remote host,
                    # which is hidden behind the local broker URL here.
                    import uuid
                    kwargs["qwen_session_metadata"] = {"sessionId": kwargs.get("session_id") or "hermes",
                                                       "promptId": str(uuid.uuid4())}
                return getattr(original, hook)(*args, **kwargs)
            return call
        for hook in hooks:
            # Keep upstream's type-level detection of custom reasoning hooks.
            if getattr(type(original), hook) is not getattr(ProviderProfile, hook):
                attributes[hook] = delegate(hook)
        profile_class = type("HAOSBrokerWireProfile", (ProviderProfile,), attributes)
        profile = profile_class(name="custom:" + name, aliases=(name,), api_mode=policy.api_mode,
            base_url=route["base_url"], env_vars=("HAOS_MODEL_TOKEN",), auth_type="api_key",
            default_aux_model=policy.data["default_model"], fallback_models=tuple(policy.models),
            **{field: getattr(original, field) for field in fields})
        # No source auth handler, refresh callback, client builder, CLI process,
        # extra credential header or catalog override crosses this boundary.
        register_provider(profile)
        profiles[route["base_url"].rstrip("/")] = (profile, policy.endpoint, source)

    class BrokerChat(ChatCompletionsTransport):
        def convert_messages(self, messages, **kwargs):
            selected = profiles.get(str(kwargs.get("base_url") or "").rstrip("/"))
            if selected:
                profile, endpoint, _ = selected
                kwargs = {**kwargs, "provider_profile": profile, "base_url": endpoint}
            return super().convert_messages(messages, **kwargs)
        def build_kwargs(self, model, messages, tools=None, **params):
            selected = profiles.get(str(params.get("base_url") or "").rstrip("/"))
            if selected:
                params["provider_profile"] = selected[0]
            return super().build_kwargs(model, messages, tools, **params)

    class BrokerResponses(ResponsesApiTransport):
        def build_kwargs(self, model, messages, tools=None, **params):
            selected = profiles.get(str(params.get("base_url") or "").rstrip("/"))
            if selected:
                params["provider_profile"] = selected[0]
                params["provider"] = selected[2]
                # This is wire-builder context only. The HTTP client remains
                # bound to the broker URL and capability selected by Hermes.
                params["base_url"] = selected[1]
            return super().build_kwargs(model, messages, tools, **params)

    # Complete normal discovery first so it cannot overwrite these adapters.
    get_transport("chat_completions")
    get_transport("codex_responses")
    register_transport("chat_completions", BrokerChat)
    register_transport("codex_responses", BrokerResponses)
    return profiles


def install():
    path = Path("/run/haos-credentials/provider-policy.json")
    if not path.exists():
        return 0
    data = path.read_bytes()
    if len(data) > 1024 * 1024:
        raise ValueError("broker wire policy exceeds its bound")
    return len(register_profiles(json.loads(data)))
