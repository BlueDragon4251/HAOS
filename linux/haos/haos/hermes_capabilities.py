"""Pinned Hermes UI discovery; availability is NOT authorization to execute.

Keep in sync with upstream/UPSTREAM.lock (NousResearch/hermes-agent).
Runtime access must remain controlled by HAOS ProviderPolicy and GatewayPolicy.
No network calls, plugin installation, OAuth or credential loading occurs here.
"""
from __future__ import annotations

PINNED_HERMES_SHA = "f97608f178d1ffeca59860195ab7da295f7c8e5f"

# Hermes canonical provider slugs from hermes_cli/models_catalog_static.py.
HERMES_PROVIDERS = (
    ("nous", "Nous Portal"), ("fireworks", "Fireworks AI"),
    ("openrouter", "OpenRouter"), ("moa", "Mixture of Agents"),
    ("novita", "NovitaAI"), ("lmstudio", "LM Studio"),
    ("anthropic", "Anthropic"), ("openai-codex", "ChatGPT/Codex-Abo"),
    ("openai-api", "OpenAI API"), ("alibaba", "Qwen Cloud"),
    ("xai-oauth", "xAI Grok OAuth"), ("xiaomi", "Xiaomi MiMo"),
    ("tencent-tokenhub", "Tencent TokenHub"), ("tencent-tokenplan", "Tencent TokenPlan"),
    ("nvidia", "NVIDIA NIM"), ("copilot", "GitHub Copilot"),
    ("copilot-acp", "Copilot ACP"), ("huggingface", "Hugging Face"),
    ("gemini", "Google AI Studio"), ("vertex", "Google Vertex AI"),
    ("deepseek", "DeepSeek"), ("xai", "xAI"),
    ("zai", "Z.AI / GLM"), ("kimi-coding", "Kimi Coding"),
    ("kimi-coding-cn", "Kimi China"), ("stepfun", "StepFun"),
    ("minimax", "MiniMax"), ("minimax-oauth", "MiniMax OAuth"),
    ("minimax-cn", "MiniMax China"), ("ollama-cloud", "Ollama Cloud"),
    ("arcee", "Arcee AI"), ("gmi", "GMI Cloud"),
    ("kilocode", "Kilo Code"), ("opencode-zen", "OpenCode Zen"),
    ("opencode-go", "OpenCode Go"), ("bedrock", "AWS Bedrock"),
    ("azure-foundry", "Azure Foundry"), ("ai-gateway", "Vercel AI Gateway"),
    ("qwen-oauth", "Qwen OAuth"),
)

# Hermes pinned plugins/platforms/<name>/adapter.py, independent of HAOS approval.
HERMES_PLATFORMS = (
    "a2a", "buzz", "dingtalk", "discord", "email", "feishu",
    "google_chat", "homeassistant", "irc", "line", "matrix",
    "mattermost", "ntfy", "photon", "raft", "simplex", "slack",
    "sms", "teams", "telegram", "wecom", "whatsapp",
)

# Implemented owner provisioning, transport, and security admission paths.
# The pinned Hermes picker uses 'openai-api'; HAOS's policy uses 'openai'.
HAOS_GUI_PROVIDERS = frozenset({"openai-api", "openrouter"})
HAOS_GUI_GATEWAYS = frozenset({"telegram", "discord"})
# Local compatible model API is an HAOS route but not a Hermes vendor slug.
HAOS_EXTRA_GUI_PROVIDERS = (("local", "Lokaler OpenAI-kompatibler Server"),)
# Codex is supported via authenticated owner CLI, NOT graphical OAuth.
HAOS_CONSOLE_ONLY_PROVIDERS = frozenset({"openai-codex"})


def provider_rows():
    return tuple((slug, label, "GUI" if slug in HAOS_GUI_PROVIDERS else
                 "Konsole" if slug in HAOS_CONSOLE_ONLY_PROVIDERS else "Nicht integriert")
                 for slug, label in HERMES_PROVIDERS)


def gateway_rows():
    return tuple((name, "GUI" if name in HAOS_GUI_GATEWAYS else "Nicht integriert")
                 for name in HERMES_PLATFORMS)
