"""Fixed OAuth actions under the provider UID, using the unmodified pinned Hermes."""

import os
import sys


def main():
    if os.geteuid() == 0 or os.environ.get("HERMES_HOME") != "/var/lib/haos-provider/.hermes":
        raise PermissionError("provider OAuth needs its separate, private identity")
    action = sys.argv[1] if len(sys.argv) in {2, 3} else ""
    provider = sys.argv[2] if len(sys.argv) == 3 else "openai-codex"
    from .provider_registry import oauth_providers
    if provider not in oauth_providers() | {"anthropic", "openrouter"}:
        raise ValueError("unsupported provider account")
    if action == "status":
        from hermes_cli.auth import get_auth_status
        if not get_auth_status(provider).get("logged_in"):
            raise PermissionError("provider credentials are not configured")
        print("Provider credential store is configured. No model turn has been tested.")
        return
    executable = "/usr/lib/haos/hermes/.venv/bin/hermes"
    if action == "login":
        args = ["auth", "add", provider, "--type", "oauth", "--no-browser", "--timeout", "600"]
    elif action == "logout":
        args = ["auth", "logout", provider]
    else:
        raise ValueError("unsupported provider credential action")
    os.execv(executable, [executable, *args])


if __name__ == "__main__":
    try:
        main()
    except Exception:
        print("Provider credential action refused; complete the protected owner setup.", file=sys.stderr)
        raise SystemExit(1)
