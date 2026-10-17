"""System-global regional configuration, solely through password-authenticated owner CLI.

Never accept a caller-selected executable, file path, console keymap or locale.
The locked HAOS observer may change its own session preferences but not the
owner/recovery console or system locale.
"""
from __future__ import annotations

import os
import subprocess

LOCALES = ("de_AT.UTF-8", "de_DE.UTF-8", "en_US.UTF-8", "en_GB.UTF-8", "fr_FR.UTF-8")
CONSOLE_MAP = {
    "at": "de-latin1",
    "de": "de-latin1",
    "us": "us",
    "gb": "uk",
    "fr": "fr",
    "ch": "sg",
}


def localectl(*args):
    subprocess.run(["/usr/bin/localectl", *args], check=True, timeout=25,
                   env={"PATH": "/usr/bin:/bin", "LANG": "C"})


def owner_region(args):
    if os.geteuid() != 0:
        raise PermissionError("only the password-authenticated owner can change system locale")
    if args.region_action == "status":
        # Fixed subprocess invocation; never expose untrusted systemd command text to a model.
        result = subprocess.run(["/usr/bin/localectl", "status"], check=True,
                                capture_output=True, text=True, timeout=15)
        return {"localectl": result.stdout[:3072]}
    if args.region_action != "apply" or args.language not in LOCALES or args.keyboard not in CONSOLE_MAP:
        raise ValueError("unsupported system locale or keyboard layout")
    # Apply terminal layout first: systemd-localed may infer the X11 layout
    # from a console keymap, so the explicit Austrian/German choice goes last.
    localectl("set-keymap", CONSOLE_MAP[args.keyboard])
    localectl("set-x11-keymap", args.keyboard)
    localectl("set-locale", "LANG=" + args.language)
    from .owner import audit
    audit("region.applied", {"language": args.language, "keyboard": args.keyboard})
    return {"applied": True, "language": args.language, "keyboard": args.keyboard,
            "new_sessions_required": True}
