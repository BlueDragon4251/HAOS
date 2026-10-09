"""Owner-defined model routes. Requests cannot select URLs, credentials or remote tools."""

import re
from urllib.parse import urlsplit

PORT = 9120
BASE = f"http://127.0.0.1:{PORT}/v1"
ENDPOINTS = {
    "openai-codex": "https://chatgpt.com/backend-api/codex",
    "openai": "https://api.openai.com/v1",
    "openrouter": "https://openrouter.ai/api/v1",
}


class ProviderPolicy:
    def __init__(self, data):
        if (not isinstance(data, dict) or set(data) != {
                "version", "provider", "endpoint", "models", "default_model", "api_mode", "requests_per_day", "requests_per_minute"}
                or type(data["version"]) is not int or data["version"] != 1):
            raise ValueError("unsupported provider policy")
        self.data = dict(data)
        self.provider = data["provider"]
        if self.provider not in {*ENDPOINTS, "local"}:
            raise ValueError("unsupported provider")
        endpoint = data["endpoint"]
        if not isinstance(endpoint, str):
            raise ValueError("invalid provider endpoint")
        if self.provider in ENDPOINTS:
            if endpoint != ENDPOINTS[self.provider]:
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
                or any(not isinstance(m, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_./:-]{0,127}", m) for m in self.models)
                or len(set(self.models)) != len(self.models) or data["default_model"] not in self.models):
            raise ValueError("invalid allowed models")
        self.api_mode = data["api_mode"]
        if self.api_mode not in {"chat_completions", "codex_responses"}:
            raise ValueError("unsupported model transport")
        if self.provider == "openai-codex" and self.api_mode != "codex_responses":
            raise ValueError("Codex OAuth requires the native Responses transport")
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
        expected = "/v1/responses" if self.api_mode == "codex_responses" else "/v1/chat/completions"
        if path != expected or not isinstance(data, dict) or data.get("model") not in self.models:
            raise PermissionError("model or API route is outside owner policy")
        if type(data.get("stream", False)) is not bool:
            raise ValueError("stream must be a boolean")
        # Remote MCP/computer/file/vector-store tools would grant the provider an
        # independent executor. Hermes supplies only local function definitions.
        tools = data.get("tools", [])
        if not isinstance(tools, list) or len(tools) > 256 or any(not isinstance(t, dict) or t.get("type") != "function" for t in tools):
            raise PermissionError("only local Hermes function tools are authorized")
        forbidden = {"background", "webhook", "previous_response_id", "conversation", "file_ids"}
        if forbidden & set(data):
            raise PermissionError("remote state and asynchronous provider execution are not authorized")
        payload = dict(data)
        payload["store"] = False
        if self.provider == "openai-codex":
            if payload.get("stream") is not True or not isinstance(payload.get("instructions"), str):
                raise ValueError("Codex requires streamed Responses and native instructions")
            # Matches the pinned Hermes consumer-Codex wire path, including the
            # unsupported retention field removed at its final request boundary.
            for key in ("max_output_tokens", "max_tokens", "max_completion_tokens", "temperature", "top_p", "prompt_cache_retention"):
                payload.pop(key, None)
        return payload
