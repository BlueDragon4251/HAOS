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
    from agent.transports.anthropic import AnthropicTransport
    routes = ProviderRoutes(data)
    config = routes.client_config()
    selected = {"haos-model": routes.primary}
    if data["version"] == 2:
        selected.update({"haos-" + key: policy for key, policy in routes.routes.items()})
    profiles = {}
    bindings = {}
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
        endpoint = policy.endpoint
        if source == "bedrock" and policy.api_mode == "codex_responses":
            from .provider_cloud import mantle_endpoint
            endpoint = mantle_endpoint(endpoint)
        elif source == "bedrock" and policy.api_mode == "anthropic_messages":
            # Native Claude InvokeModel accepts the same signed thinking as
            # Anthropic; the generic third-party-host branch would discard it.
            endpoint = None
        attributes = {}
        def delegate(hook, original=original, endpoint=endpoint):
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
        flags = {field: getattr(original, field) for field in fields}
        if source == "bedrock" and policy.api_mode == "chat_completions":
            from .provider_bedrock_replay import TYPE
            flags["native_reasoning_details_type"] = TYPE
        profile = profile_class(name="custom:" + name, aliases=(name,), api_mode=policy.api_mode,
            base_url=route["base_url"], env_vars=("HAOS_MODEL_TOKEN",), auth_type="api_key",
            default_aux_model=policy.data["default_model"], fallback_models=tuple(policy.models),
            **flags)
        # No source auth handler, refresh callback, client builder, CLI process,
        # extra credential header or catalog override crosses this boundary.
        register_provider(profile)
        profiles[route["base_url"].rstrip("/")] = (profile, endpoint, source)
        bindings[route["base_url"].rstrip("/")] = (source, policy.api_mode, policy.endpoint)

    class WireContext:
        def haos_wire_context(self, base_url):
            return bindings.get(str(base_url).rstrip("/"))

    class BrokerChat(WireContext, ChatCompletionsTransport):
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

    class BrokerResponses(WireContext, ResponsesApiTransport):
        def build_kwargs(self, model, messages, tools=None, **params):
            from .provider_moa_streams import _binding, _restore
            messages = _restore(messages, _binding(self, params.get("base_url"), model))
            selected = profiles.get(str(params.get("base_url") or "").rstrip("/"))
            if selected:
                params["provider_profile"] = selected[0]
                params["provider"] = selected[2]
                # This is wire-builder context only. The HTTP client remains
                # bound to the broker URL and capability selected by Hermes.
                params["base_url"] = selected[1]
            return super().build_kwargs(model, messages, tools, **params)

    class BrokerMessages(WireContext, AnthropicTransport):
        def convert_messages(self, messages, **kwargs):
            selected = profiles.get(str(kwargs.get("base_url") or "").rstrip("/"))
            if selected:
                kwargs["base_url"] = selected[1]
            return super().convert_messages(messages, **kwargs)
        def build_kwargs(self, model, messages, tools=None, **params):
            from .provider_moa_streams import _binding, _restore
            messages = _restore(messages, _binding(self, params.get("base_url"), model))
            selected = profiles.get(str(params.get("base_url") or "").rstrip("/"))
            if selected:
                params["base_url"] = selected[1]
                # Only the private broker can classify the real credential.
                params["is_oauth"] = False
            return super().build_kwargs(model, messages, tools, **params)

    fallback_bases = {config["providers"]["haos-" + key]["base_url"].rstrip("/") for key in routes.fallbacks}
    if routes.default in routes.fallbacks:
        fallback_bases.add(config["providers"]["haos-model"]["base_url"].rstrip("/"))
    from functools import wraps
    from .provider_fallback import capture, attach
    def contextual_build(method):
        @wraps(method)
        def build(self, model, messages, tools=None, **params):
            base = str(params.get("base_url") or "").rstrip("/")
            needs_context = base in fallback_bases or any(params.get(key) for key in ("fast_mode", "context_length", "drop_context_1m_beta"))
            context = capture(self.api_mode, model, messages, tools, params) if needs_context else None
            return attach(method(self, model, messages, tools, **params), context)
        return build
    for cls in (BrokerChat, BrokerResponses, BrokerMessages):
        cls.build_kwargs = contextual_build(cls.build_kwargs)

    # Complete normal discovery first so it cannot overwrite these adapters.
    get_transport("chat_completions")
    get_transport("codex_responses")
    get_transport("anthropic_messages")
    register_transport("chat_completions", BrokerChat)
    register_transport("codex_responses", BrokerResponses)
    register_transport("anthropic_messages", BrokerMessages)
    return profiles


def install():
    path = Path("/run/haos-credentials/provider-policy.json")
    if not path.exists():
        return 0
    data = path.read_bytes()
    if len(data) > 1024 * 1024:
        raise ValueError("broker wire policy exceeds its bound")
    return len(register_profiles(json.loads(data)))
