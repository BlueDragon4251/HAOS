"""Data-only view of the actual pinned Hermes provider registry.

This module is safe in the root setup UI: it never imports provider code, opens
credentials, scans a user's plugin directory or performs a network lookup.
"""
from __future__ import annotations

from functools import lru_cache
import json
import re
from pathlib import Path


@lru_cache(maxsize=1)
def registry_export():
    data = json.loads(Path(__file__).with_name("hermes_registry.json").read_text())
    if data["version"] != 1:
        raise ValueError("unsupported Hermes registry export")
    return data


@lru_cache(maxsize=1)
def registry():
    return {row["slug"]: row for row in registry_export()["providers"]}


def descriptor(provider):
    # Preserve the existing HAOS OpenAI policy spelling; upstream's `openai`
    # alias means OpenRouter and must NOT be used for this migration.
    return registry().get("openai-api" if provider == "openai" else provider)


def http_providers():
    """Reviewed HTTP families; other registry entries remain unavailable.

    OAuth, SDK, virtual and subprocess entries require their own admission path.
    A new compatible provider becomes eligible only after regenerating and
    reviewing the immutable registry export in the OS image.
    """
    return frozenset(slug for slug, row in registry().items()
                     if row["auth_type"] == "api_key" and row["endpoint"].startswith("https://")
                     and row["api_mode"] in {"chat_completions", "codex_responses", "anthropic_messages"}
                     and slug not in {"copilot", "gemini"})


def default_endpoint(provider):
    if provider == "copilot-acp":
        return "acp://copilot"
    row = descriptor(provider)
    endpoint = row["endpoint"] if row else ""
    if provider == "lmstudio":
        # The upstream default uses localhost; this broker requires a literal
        # loopback address so local-model routing never depends on DNS.
        endpoint = endpoint.replace("http://localhost:", "http://127.0.0.1:")
    return endpoint


def default_mode(provider, model=""):
    rules = registry_export().get("model_routing", {})
    if provider in rules.get("opencode", {}):
        normalized = model.removeprefix(provider + "/").lower()
        for prefixes, mode in rules["opencode"][provider]:
            if normalized.startswith(tuple(prefixes)):
                return mode
        return "chat_completions"
    if provider == "azure-foundry" and model.lower().rsplit("/", 1)[-1].startswith(tuple(rules.get("azure_responses_prefixes", []))):
        return "codex_responses"
    if provider == "copilot":
        match = re.match(r"^(?:openai/)?gpt-(\d+)", model)
        return "codex_responses" if match and int(match[1]) >= 5 and not model.removeprefix("openai/").startswith("gpt-5-mini") else "chat_completions"
    if provider in {"local", "bedrock", "copilot-acp"}:
        return "chat_completions"
    row = descriptor(provider)
    if row is None:
        raise ValueError("unknown provider")
    return row["api_mode"]


def oauth_providers():
    return frozenset(slug for slug, row in registry().items() if row["auth_type"].startswith("oauth_"))


def account_providers():
    return oauth_providers() | {"anthropic", "openrouter", "copilot", "copilot-acp"}
