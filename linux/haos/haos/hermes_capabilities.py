"""Pinned Hermes UI discovery; availability is NOT authorization to execute.

Keep in sync with upstream/UPSTREAM.lock (NousResearch/hermes-agent).
Runtime access must remain controlled by HAOS ProviderPolicy and GatewayPolicy.
No network calls, plugin installation, OAuth or credential loading occurs here.
"""
from __future__ import annotations
import json
from pathlib import Path
from .provider_registry import registry, http_providers

_EXPORT = json.loads(Path(__file__).with_name("hermes_registry.json").read_text())
PINNED_HERMES_SHA = _EXPORT["hermes_sha"]
HERMES_PROVIDERS = tuple((row["slug"], row["label"]) for row in _EXPORT["providers"])
HERMES_PLATFORMS = tuple(_EXPORT["platforms"])

# Implemented owner provisioning, transport, and security admission paths.
# The pinned Hermes picker uses 'openai-api'; HAOS's policy uses 'openai'.
HAOS_GUI_PROVIDERS = http_providers() | {"lmstudio", "nous", "openai-codex", "xai-oauth", "minimax-oauth", "gemini", "bedrock", "vertex", "azure-foundry", "moa", "custom", "copilot", "copilot-acp", "qwen-oauth"}
HAOS_GUI_GATEWAYS = frozenset({"telegram", "discord", "slack", "mattermost", "matrix"})
# Local compatible model API is an HAOS route but not a Hermes vendor slug.
HAOS_EXTRA_GUI_PROVIDERS = (("local", "Lokaler OpenAI-kompatibler Server"),)
# Codex is supported via authenticated owner CLI, NOT graphical OAuth.
HAOS_CONSOLE_ONLY_PROVIDERS = frozenset()


def provider_rows():
    return tuple((slug, label, "GUI" if slug in HAOS_GUI_PROVIDERS else
                 "Konsole" if slug in HAOS_CONSOLE_ONLY_PROVIDERS else "Nicht integriert")
                 for slug, label in ((r["slug"], r["label"]) for r in registry().values()))


def gateway_rows():
    return tuple((name, "GUI" if name in HAOS_GUI_GATEWAYS else "Nicht integriert")
                 for name in HERMES_PLATFORMS)
