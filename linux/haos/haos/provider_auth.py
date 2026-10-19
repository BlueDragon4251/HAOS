"""Fixed OAuth actions under the provider UID, using the unmodified pinned Hermes."""

import os
import sys
import json


def qwen_import(value):
    """Validate the exact upstream Qwen-CLI credential shape before private import."""
    if not isinstance(value, str) or len(value.encode()) > 32768:
        raise ValueError("invalid Qwen credential import")
    data = json.loads(value)
    if (not isinstance(data, dict) or set(data) - {"access_token", "refresh_token", "token_type", "resource_url", "expiry_date"}
            or not {"access_token", "refresh_token", "expiry_date"} <= set(data)):
        raise ValueError("Qwen CLI credential fields are required")
    for name in ("access_token", "refresh_token"):
        if (not isinstance(data[name], str) or not 16 <= len(data[name]) <= 16384
                or any(ord(c) < 33 or ord(c) > 126 for c in data[name])):
            raise ValueError("invalid Qwen token")
    if (type(data["expiry_date"]) is not int or not 0 <= data["expiry_date"] < 2**53
            or data.get("resource_url", "portal.qwen.ai") not in {"portal.qwen.ai", "https://portal.qwen.ai"}
            or data.get("token_type", "Bearer") != "Bearer"):
        raise PermissionError("Qwen credential endpoint or expiry is outside the supported contract")
    return data


def main():
    action = sys.argv[1] if len(sys.argv) in {2, 3} else ""
    provider = sys.argv[2] if len(sys.argv) == 3 else "openai-codex"
    identity = "haos-provider-acp" if provider == "copilot-acp" else "haos-provider"
    import pwd
    if (os.geteuid() == 0 or os.geteuid() != pwd.getpwnam(identity).pw_uid
            or os.environ.get("HERMES_HOME") != "/var/lib/" + identity + "/.hermes"):
        raise PermissionError("provider OAuth needs its separate, private identity")
    from .provider_registry import account_providers
    if provider not in account_providers():
        raise ValueError("unsupported provider account")
    if provider == "copilot-acp":
        from .provider_acp import COMMAND, HOME, isolated_client
        if os.environ.get("HOME") != HOME:
            raise PermissionError("separate ACP authentication HOME required")
        if action == "login":
            os.execv(COMMAND, [COMMAND, "login", "--device-code"])
        if action == "logout":
            import shutil
            from pathlib import Path
            path = Path(HOME) / ".copilot"
            if path.is_symlink():
                path.unlink()
            elif path.exists():
                shutil.rmtree(path)
            print("Local Copilot CLI account state removed. Revoke the OAuth grant at GitHub if required.")
            return
        if action == "status":
            import tempfile
            with tempfile.TemporaryDirectory() as cwd:
                client = isolated_client(cwd=cwd)
                try:
                    if not client.list_models(timeout_seconds=30):
                        raise PermissionError("ACP account has no enabled models")
                finally:
                    client.close()
            print("Copilot ACP session authenticated. No model turn tested.")
            return
        raise ValueError("unsupported ACP account action")
    if provider == "copilot":
        from .provider_copilot import bind_transport
        bind_transport()
    if action == "status":
        from hermes_cli.auth import get_auth_status
        if not get_auth_status(provider).get("logged_in"):
            raise PermissionError("provider credentials are not configured")
        print("Provider credential store is configured. No model turn has been tested.")
        return
    executable = "/usr/lib/haos/hermes/.venv/bin/hermes"
    if action == "login":
        if provider == "qwen-oauth":
            from .provider_qwen import device_login
            from hermes_cli.auth_qwen import _save_qwen_cli_tokens
            _save_qwen_cli_tokens(device_login())
        if provider == "copilot":
            from hermes_cli.copilot_auth import copilot_device_code_login
            from hermes_cli.config import save_env_value
            token = copilot_device_code_login(timeout_seconds=600)
            if not token:
                raise PermissionError("Copilot device authorization did not complete")
            save_env_value("COPILOT_GITHUB_TOKEN", token)
            print("Copilot account saved in the private provider identity. No inference tested.")
            return
        args = ["auth", "add", provider, "--type", "oauth", "--no-browser", "--timeout", "600"]
    elif action == "logout":
        if provider == "qwen-oauth":
            from pathlib import Path
            (Path.home() / ".qwen/oauth_creds.json").unlink(missing_ok=True)
        if provider == "copilot":
            from hermes_cli.copilot_auth import resolve_copilot_token, evict_cached_exchanged_token
            from hermes_cli.config import save_env_value
            token = resolve_copilot_token()[0]
            if token:
                evict_cached_exchanged_token(token)
            save_env_value("COPILOT_GITHUB_TOKEN", "")
        args = ["auth", "logout", provider]
    else:
        raise ValueError("unsupported provider credential action")
    os.execv(executable, [executable, *args])


if __name__ == "__main__":
    from .provider_qwen import QwenLoginError
    try:
        main()
    except QwenLoginError as error:
        print("Qwen authorization did not complete (" + str(error) + "). Check the account/network and retry; existing credentials are retained.", file=sys.stderr)
        raise SystemExit(1)
    except Exception:
        print("Provider credential action refused; complete the protected owner setup.", file=sys.stderr)
        raise SystemExit(1)
