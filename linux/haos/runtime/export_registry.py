#!/usr/bin/env python3
"""Export the installed Hermes registries without loading user plugins as root.

Run with the pinned Hermes interpreter in a disposable, empty HERMES_HOME.
The output is data, never an authorization to execute a new plugin.
"""
from __future__ import annotations

from dataclasses import asdict
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile


def inventory(root: Path):
    from hermes_cli.provider_catalog import provider_catalog
    from hermes_cli.auth import PROVIDER_REGISTRY
    from hermes_cli.providers import determine_api_mode, get_provider
    from providers import get_provider_profile
    from hermes_cli.models_catalog_static import _PROVIDER_MODELS, _AZURE_FOUNDRY_RESPONSES_PREFIXES
    from hermes_cli.models import _OPENCODE_API_MODE_PREFIXES

    rows = []
    for descriptor in provider_catalog():
        auth = PROVIDER_REGISTRY.get(descriptor.slug)
        profile = get_provider_profile(descriptor.slug)
        definition = get_provider(descriptor.slug, allow_network=False)
        endpoint = ((auth.inference_base_url if auth else "")
                    or (profile.base_url if profile else "")
                    or (definition.base_url if definition else ""))
        # determine_api_mode consults get_provider with network enabled. The
        # export is offline, so use the already resolved immutable definition.
        from hermes_cli.providers import host_mandated_api_mode, TRANSPORT_TO_API_MODE
        mode = (host_mandated_api_mode(endpoint) or
                (TRANSPORT_TO_API_MODE.get(definition.transport, definition.transport) if definition else
                 (profile.api_mode if profile else "chat_completions")))
        rows.append({**asdict(descriptor), "endpoint": endpoint,
                     "api_mode": mode,
                     "headers": dict(profile.default_headers) if profile else {},
                     "fallback_models": list(dict.fromkeys([*_PROVIDER_MODELS.get(descriptor.slug, []),
                         *(profile.fallback_models if profile else [])]))})
    # Endpoint variants declared by upstream authentication adapters, rather
    # than a second hand-maintained vendor URL table in HAOS.
    from hermes_cli.auth_zai_kimi import KIMI_CODE_BASE_URL, ZAI_ENDPOINTS
    from hermes_cli.auth_constants import DEFAULT_NOUS_WELCOME_URL, MINIMAX_OAUTH_CN_INFERENCE
    variants = {"kimi-coding": [KIMI_CODE_BASE_URL], "kimi-coding-cn": [KIMI_CODE_BASE_URL],
                "zai": [entry[1] for entry in ZAI_ENDPOINTS], "nous": [DEFAULT_NOUS_WELCOME_URL],
                "minimax-oauth": [MINIMAX_OAUTH_CN_INFERENCE]}
    for row in rows:
        row["endpoints"] = list(dict.fromkeys([row["endpoint"], *variants.get(row["slug"], [])]))
    # Inventory bundled adapters without importing their listeners or installing dependencies.
    platforms = sorted(p.parent.name for p in (root / "plugins/platforms").glob("*/adapter.py"))
    return {"version": 1, "hermes_sha": (root / ".herald-os-upstream-sha").read_text().strip(),
            "providers": rows, "platforms": platforms,
            "model_routing": {"opencode": _OPENCODE_API_MODE_PREFIXES,
                              "azure_responses_prefixes": _AZURE_FOUNDRY_RESPONSES_PREFIXES}}


def main():
    root, output = map(Path, sys.argv[1:])
    sys.path.insert(0, str(root.resolve()))
    with tempfile.TemporaryDirectory(prefix="haos-catalogue-") as directory:
        os.environ["HERMES_HOME"] = directory
        # Models.dev network lookup must never change a build's exported contract.
        result = inventory(root)
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({"providers": len(result["providers"]), "platforms": len(result["platforms"]),
                      "sha256": hashlib.sha256(output.read_bytes()).hexdigest()}))


if __name__ == "__main__":
    main()
