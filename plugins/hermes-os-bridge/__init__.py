"""Hermes OS system bridge.

Registers the ``hermes_os`` toolset: a narrow set of explicit, permission-tiered tools that let
Hermes act on the computer it is running on. Execution goes through a per-platform
``HostAdapter`` (macOS and Linux implemented; Windows is a typed stub), permissions through
``bridge.permissions`` (tiers, protected paths, the upstream approval gate), and every call is
recorded by ``bridge.audit``.

Out-of-tree by design: the plugin uses only public plugin APIs (``register``,
``ctx.register_tool``, ``ctx.register_skill``, ``tools.approval.request_tool_approval``) so Hermes
OS never patches the Hermes core.
"""

from __future__ import annotations

from pathlib import Path

from .bridge import tools as _tools
from .bridge.host import host_available

_SKILL_DIR = Path(__file__).parent / "skills" / "hermes-os"


def _check_available() -> bool:
    """Reachability gate: the host adapter must exist for this platform and the bridge must not
    be disabled in config. Cached process-wide by the registry."""
    return host_available() and _tools.bridge_enabled()


def register(ctx) -> None:
    for spec in _tools.TOOL_SPECS:
        ctx.register_tool(
            name=spec.name,
            toolset="hermes_os",
            schema=spec.schema,
            handler=spec.handler,
            check_fn=_check_available,
            emoji=spec.emoji,
            description=spec.schema["description"],
        )
    skill_md = _SKILL_DIR / "SKILL.md"
    if skill_md.exists() and hasattr(ctx, "register_skill"):
        ctx.register_skill(
            "hermes-os",
            skill_md,
            description="How Hermes acts as the operating environment on this computer.",
        )
