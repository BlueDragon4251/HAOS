"""Boot arbitration: the normal nonprivileged desktop must not race root setup.

New installations with missing owner/recovery are directed to a *physical*
administrator wizard. Existing owners with validated recovery are migrated
without automatically exposing a root X11 session after an image update.
The graphical setup stays explicitly opt-in until installed-OS boot acceptance.
"""
from __future__ import annotations

import os
import sys

from . import initial_setup


def decision(state: dict, in_progress: bool) -> str:
    if not isinstance(state, dict) or not isinstance(in_progress, bool):
        raise ValueError("invalid boot state")
    if (set(state) != {"owner", "recovery", "complete", "pending"}
            or any(type(v) is not bool for v in state.values())):
        raise ValueError("unsafe onboarding state")
    # All independent enrollment indicators must agree. A corrupted or
    # partially committed state must never open the normal desktop.
    if in_progress or state["pending"] or not (state["owner"] and state["recovery"] and state["complete"]):
        return "setup"
    return "desktop"


def boot_destination() -> str:
    # Refuse missing/untrusted owner metadata rather than booting a non-secure
    # 'emergency' Electron root session.
    if os.geteuid() != 0:
        raise PermissionError("boot decision requires root-owned host state")
    return decision(initial_setup.account_status(), initial_setup.setup_in_progress())


def main() -> None:
    if len(sys.argv) != 2 or sys.argv[1] not in {"prompt", "desktop", "state"}:
        raise SystemExit("usage: haos-setup-gate [prompt|desktop|state]")
    try:
        destination = boot_destination()
    except (OSError, ValueError, PermissionError, KeyError):
        # Missing or corrupted owner files must not grant normal startup.
        # Exit 255, causing systemd ExecCondition to fail visibly.
        raise SystemExit(255) from None
    if sys.argv[1] == "state":
        print(destination)
        return
    raise SystemExit(0 if sys.argv[1] == destination else 1)


if __name__ == "__main__":
    main()
