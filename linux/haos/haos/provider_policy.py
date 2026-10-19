"""Owner-defined model routes. Requests cannot select URLs, credentials or remote tools."""

import re
import ipaddress
from urllib.parse import urlsplit
from .provider_registry import default_endpoint, default_mode, descriptor, http_providers, oauth_providers
from .provider_cloud import CLOUD, valid_endpoint

PORT = 9120
BASE = f"http://127.0.0.1:{PORT}/v1"
ENDPOINTS = {
    "openai-codex": "https://chatgpt.com/backend-api/codex",
    "openai": "https://api.openai.com/v1",
    "openrouter": "https://openrouter.ai/api/v1",
}
ENDPOINTS.update({name: default_endpoint(name) for name in http_providers()})
ENDPOINTS.update({name: default_endpoint(name) for name in oauth_providers()})
ENDPOINTS["gemini"] = default_endpoint("gemini")
ENDPOINTS.update({name: default_endpoint(name) for name in CLOUD})
ENDPOINTS["custom"] = ""
ENDPOINTS["copilot"] = default_endpoint("copilot")
ENDPOINTS["copilot-acp"] = "acp://copilot"


def custom_endpoint(endpoint):
    parsed = urlsplit(endpoint)
    if (parsed.scheme != "https" or not parsed.hostname or parsed.port not in {None, 443}
            or parsed.username or parsed.password or parsed.query or parsed.fragment
            or len(endpoint) > 1024 or not re.fullmatch(r"(?:/[A-Za-z0-9_.~-]+)*/?", parsed.path)
            or any(part in {".", ".."} for part in parsed.path.split("/"))):
        raise PermissionError("custom API requires an explicit HTTPS base URL")
    try:
        if not ipaddress.ip_address(parsed.hostname).is_global:
            raise PermissionError("custom API cannot expose private-address administration services")
    except ValueError:
        if not re.fullmatch(r"[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+", parsed.hostname) or parsed.hostname.endswith((".localhost", ".local", ".home.arpa")):
            raise PermissionError("custom API requires an explicit public DNS name")


class ProviderPolicy:
    def __init__(self, data):
        if (not isinstance(data, dict) or set(data) != {
                "version", "provider", "endpoint", "models", "default_model", "api_mode", "requests_per_day", "requests_per_minute"}
                or type(data["version"]) is not int or data["version"] != 1):
            raise ValueError("unsupported provider policy")
        self.data = dict(data)
        self.provider = data["provider"]
        if self.provider not in {*ENDPOINTS, "local", "lmstudio"}:
            raise ValueError("unsupported provider")
        endpoint = data["endpoint"]
        if not isinstance(endpoint, str):
            raise ValueError("invalid provider endpoint")
        if self.provider == "custom":
            custom_endpoint(endpoint)
        elif self.provider == "copilot-acp":
            if endpoint != "acp://copilot":
                raise PermissionError("ACP executable and transport are fixed by the image")
        elif self.provider == "copilot":
            parsed = urlsplit(endpoint)
            if (parsed.scheme != "https" or parsed.port not in {None, 443} or parsed.path not in {"", "/"}
                    or parsed.username or parsed.password or parsed.query or parsed.fragment
                    or not re.fullmatch(r"api(?:\.[a-z0-9-]+)?\.githubcopilot\.com", parsed.hostname or "")):
                raise PermissionError("Copilot endpoint must remain inside its verified API service domain")
        elif self.provider in CLOUD:
            if not valid_endpoint(self.provider, endpoint):
                raise PermissionError("cloud SDK endpoint is outside its verified service domain")
        elif self.provider in ENDPOINTS:
            row = descriptor(self.provider)
            if endpoint not in (row["endpoints"] if row else [ENDPOINTS[self.provider]]):
                raise PermissionError("remote provider endpoints are fixed and require verified TLS")
        else:
            parsed = urlsplit(endpoint)
            if (parsed.scheme != "http" or parsed.hostname != "127.0.0.1" or not parsed.port
                    or not 1024 <= parsed.port <= 65535 or parsed.port in {9119, PORT}
                    or parsed.path != "/v1" or parsed.username or parsed.password or parsed.query or parsed.fragment):
                raise PermissionError("local models require an explicit loopback /v1 endpoint")
        self.endpoint = endpoint
        self.models = data["models"]
        if (not isinstance(self.models, list) or not 1 <= len(self.models) <= 16
                or any(not isinstance(m, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_./:-]{0,511}", m)
                       or any(part in {".", ".."} for part in m.split("/")) for m in self.models)
                or len(set(self.models)) != len(self.models) or data["default_model"] not in self.models):
            raise ValueError("invalid allowed models")
        self.api_mode = data["api_mode"]
        if self.api_mode not in {"chat_completions", "codex_responses", "anthropic_messages"}:
            raise ValueError("unsupported model transport")
        if self.provider == "openai-codex" and self.api_mode != "codex_responses":
            raise ValueError("Codex OAuth requires the native Responses transport")
        if self.provider in {"bedrock", "vertex", "gemini", "copilot-acp"} and self.api_mode != "chat_completions":
            raise ValueError("this broker SDK adapter requires local Chat Completions ingress")
        if self.provider == "copilot" and any(default_mode("copilot", model) != self.api_mode for model in self.models):
            raise ValueError("Copilot model allowlist must use the selected native protocol")
        for key, upper in (("requests_per_day", 10000), ("requests_per_minute", 120)):
            if type(data[key]) is not int or not 1 <= data[key] <= upper:
                raise ValueError("invalid provider request limit")

    def client_config(self):
        route = {"base_url": BASE, "api_mode": self.api_mode, "key_env": "HAOS_MODEL_TOKEN",
                 "default_model": self.data["default_model"]}
        # Pinned Hermes deliberately ignores Responses for a bare custom URL.
        # Its documented named custom provider supports an explicit transport.
        return {"_config_version": 46, "providers": {"haos-model": route},
                "model": {"provider": "custom:haos-model", "default": self.data["default_model"], "base_url": BASE,
                          "api_mode": self.api_mode, "key_env": "HAOS_MODEL_TOKEN", "openai_runtime": "auto"}}

    def request(self, path, data):
        expected = {"codex_responses": "/v1/responses", "chat_completions": "/v1/chat/completions",
                    "anthropic_messages": "/v1/messages"}[self.api_mode]
        if path != expected or not isinstance(data, dict) or data.get("model") not in self.models:
            raise PermissionError("model or API route is outside owner policy")
        if type(data.get("stream", False)) is not bool:
            raise ValueError("stream must be a boolean")
        # Remote MCP/computer/file/vector-store tools would grant the provider an
        # independent executor. Hermes supplies only local function definitions.
        tools = data.get("tools", [])
        def local_function(tool):
            if not isinstance(tool, dict):
                return False
            if self.api_mode == "anthropic_messages":
                return (tool.get("type", "custom") == "custom" and isinstance(tool.get("name"), str)
                        and isinstance(tool.get("input_schema"), dict))
            return tool.get("type") == "function"
        if not isinstance(tools, list) or len(tools) > 256 or not all(map(local_function, tools)):
            raise PermissionError("only local Hermes function tools are authorized")
        forbidden = {"background", "webhook", "previous_response_id", "conversation", "file_ids",
                     "mcp_servers", "container", "betas", "extra_headers", "extra_query", "extra_body"}
        if forbidden & set(data):
            raise PermissionError("remote state and asynchronous provider execution are not authorized")
        payload = dict(data)
        if self.api_mode != "anthropic_messages":
            payload["store"] = False
        else:
            payload.pop("store", None)
        if self.provider == "openai-codex":
            if payload.get("stream") is not True or not isinstance(payload.get("instructions"), str):
                raise ValueError("Codex requires streamed Responses and native instructions")
            # Matches the pinned Hermes consumer-Codex wire path, including the
            # unsupported retention field removed at its final request boundary.
            for key in ("max_output_tokens", "max_tokens", "max_completion_tokens", "temperature", "top_p", "prompt_cache_retention"):
                payload.pop(key, None)
        return payload
