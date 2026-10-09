#!/usr/bin/env python3
"""Report failed services and shut down only an explicitly disposable CI guest."""

import json
import os
import subprocess
from pathlib import Path

ROOT = Path("/var/lib/haos-acceptance")
UNITS = ("herald-os-firstboot.service", "haos-policy.service", "haos-hermes.service",
         "haos-controller.service", "haos-observer-security.service", "greetd.service")


def require_disposable_guest():
    if os.geteuid() != 0:
        raise PermissionError("guest diagnostics require root")
    if Path("/sys/class/dmi/id/product_name").read_text().strip() != "haos-acceptance":
        raise PermissionError("diagnostics may run only in the acceptance VM")
    if not (ROOT / "disposable-ci-guest").is_file():
        raise PermissionError("missing disposable guest marker")


def collect():
    # Fixed commands only. Never dump process environments, credentials or config.
    commands = [("unit states", ["systemctl", "show", *UNITS,
        "--property=Id,LoadState,ActiveState,SubState,Result,ExecMainCode,ExecMainStatus,ConditionResult"]),
        ("service journal", ["journalctl", "--boot", "--no-pager", "--output=short-monotonic", "--lines=120",
                             *[argument for unit in UNITS for argument in ("--unit", unit)]])]
    # Also redact the per-machine backend credential if a dependency logs it.
    token = Path("/etc/haos/backend-token")
    secret = token.read_text().strip() if token.is_file() else ""
    reports = []
    for label, args in commands:
        try:
            result = subprocess.run(args, capture_output=True, text=True, timeout=20, check=False)
            output = result.stdout + result.stderr
            if secret:
                output = output.replace(secret, "[REDACTED]")
            reports.append({"name": label, "returncode": result.returncode, "output": output[-48000:]})
        except (OSError, subprocess.TimeoutExpired) as error:
            reports.append({"name": label, "error": type(error).__name__})
    return reports


def main():
    require_disposable_guest()
    result = os.environ.get("SERVICE_RESULT", "unknown")
    if result == "success":
        return
    print("HAOS_ACCEPTANCE_FAILED", flush=True)
    try:
        print("HAOS_DIAGNOSTICS_JSON=" + json.dumps({"service_result": result, "reports": collect()}), flush=True)
    finally:
        # The host rejects the failure marker after QEMU exits. This preserves the
        # actual guest error instead of hiding it behind a 30-minute host timeout.
        subprocess.run(["systemctl", "--no-block", "poweroff"], check=True, timeout=20)


if __name__ == "__main__":
    main()
