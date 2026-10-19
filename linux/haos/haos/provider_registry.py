"""Data-only view of the actual pinned Hermes provider registry.

This module is safe in the root setup UI: it never imports provider code, opens
credentials, scans a user's plugin directory or performs a network lookup.
"""
from __future__ import annotations

from functools import lru_cache
import json
from pathlib import Path


@lru_cache(maxsize=1)
def registry():
    data = json.loads(Path(__file__).with_name("hermes_registry.json").read_text())
    if data["version"] != 1:
        raise ValueError("unsupported Hermes registry export")
    return {row["slug"]: row for row in data["providers"]}


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
    row = descriptor(provider)
    return row["endpoint"] if row else ""


def default_mode(provider):
    if provider in {"local", "bedrock"}:
        return "chat_completions"
    row = descriptor(provider)
    if row is None:
        raise ValueError("unknown provider")
    return row["api_mode"]


def oauth_providers():
    return frozenset(slug for slug, row in registry().items() if row["auth_type"].startswith("oauth_"))
