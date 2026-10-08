"""Sandbox-side launcher: keep the host credential out of public process arguments."""

import os
import re
from pathlib import Path


def main():
    token = Path("/run/haos-credentials/backend-token").read_text().strip()
    if not re.fullmatch(r"[A-Za-z0-9_-]{43,128}", token):
        raise ValueError("invalid backend credential")
    os.environ["HERMES_DASHBOARD_SESSION_TOKEN"] = token
    executable = "/usr/lib/haos/hermes/.venv/bin/hermes"
    os.execv(executable, [executable, "serve", "--host", "127.0.0.1", "--port", "9119", "--no-open"])


if __name__ == "__main__":
    main()
