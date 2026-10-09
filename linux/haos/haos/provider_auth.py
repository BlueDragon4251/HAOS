"""Fixed OAuth actions under the provider UID, using the unmodified pinned Hermes."""

import os
import sys


def main():
    if os.geteuid() == 0 or os.environ.get("HERMES_HOME") != "/var/lib/haos-provider/.hermes":
        raise PermissionError("provider OAuth needs its separate, private identity")
    action = sys.argv[1] if len(sys.argv) == 2 else ""
    if action == "status":
        from hermes_cli.auth_codex import resolve_codex_runtime_credentials
        result = resolve_codex_runtime_credentials(read_only=True)
        if not result.get("api_key"):
            raise PermissionError("Codex credentials are not configured")
        print("Codex credential store is configured. No model turn has been tested.")
        return
    executable = "/usr/lib/haos/hermes/.venv/bin/hermes"
    if action == "login":
        args = ["auth", "add", "openai-codex", "--type", "oauth", "--no-browser", "--timeout", "600"]
    elif action == "logout":
        args = ["auth", "logout", "openai-codex"]
    else:
        raise ValueError("unsupported provider credential action")
    os.execv(executable, [executable, *args])


if __name__ == "__main__":
    try:
        main()
    except Exception:
        print("Provider credential action refused; complete the protected owner setup.", file=sys.stderr)
        raise SystemExit(1)
