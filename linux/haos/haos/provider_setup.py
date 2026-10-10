"""Authenticated owner provisioning of the isolated model broker."""

import getpass
import os
from pathlib import Path
import pwd
import secrets
import subprocess

from .enrollment import ENV, protected_directory
from .policy import atomic_json
from .provider_policy import ENDPOINTS, ProviderPolicy
from .sandbox import trusted_json

CONFIG = Path("/etc/haos")
UNITS = ("haos-provider.service", "haos-provider.socket")


def stopped_provider():
    for unit in UNITS:
        result = subprocess.run(["/usr/bin/systemctl", "show", "--property=LoadState,ActiveState,MainPID,ControlPID", unit],
                                check=True, capture_output=True, text=True, timeout=15)
        state = dict(line.split("=", 1) for line in result.stdout.splitlines() if "=" in line)
        if state.get("LoadState") not in {"loaded", "masked"} or state.get("ActiveState") != "inactive" or any(
                state.get(key, "0") != "0" for key in ("MainPID", "ControlPID")):
            raise PermissionError("stop the model broker and activation socket before changing credentials")


def publish(policy, credential, *, config=CONFIG):
    if os.geteuid() != 0:
        raise PermissionError("provider provisioning requires authenticated owner authority")
    protected_directory(config)
    policy = ProviderPolicy(policy)
    if credential is not None and (not isinstance(credential, str) or not 16 <= len(credential) <= 16384
                                   or any(ord(c) < 33 or ord(c) > 126 for c in credential)):
        raise ValueError("invalid provider credential")
    if policy.provider in {"openai", "openrouter"} and not credential:
        raise ValueError("API provider requires a securely entered credential")
    # Execution and socket activation must already be stopped. Publish the
    # authority descriptor last; an interrupted configuration fails closed.
    descriptor = config / "provider.json"
    if descriptor.exists() or descriptor.is_symlink():
        trusted_json(descriptor)
        descriptor.unlink()
        parent_fd = os.open(config, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            os.fsync(parent_fd)
        finally:
            os.close(parent_fd)
    atomic_json(config / "provider-credentials", {"api_key": credential})
    atomic_json(config / "provider-token", {"token": secrets.token_urlsafe(48)})
    atomic_json(config / "provider-client.json", policy.client_config(), mode=0o644)
    atomic_json(config / "provider.json", policy.data, mode=0o644)


def auth_helper(action):
    # Transient service supplies a private state directory and the same security
    # boundary as the long-lived broker. No root CLI command/user/path is passed
    # from the model. --pty keeps device codes and OAuth output off the journal.
    if action not in {"login", "status", "logout"}:
        raise ValueError("unsupported provider credential action")
    from .owner_recovery import require_console
    require_console()
    entry = pwd.getpwnam("haos-provider")
    if entry.pw_uid == 0:
        raise PermissionError("invalid provider service identity")
    command = ["/usr/bin/systemd-run", "--pty", "--wait", "--collect", "--quiet", "--service-type=exec",
               "--unit=haos-provider-owner-" + secrets.token_hex(12),
               "--property=User=haos-provider", "--property=Group=haos-provider",
               "--property=StateDirectory=haos-provider", "--property=StateDirectoryMode=0700",
               "--property=UMask=0077", "--property=RuntimeMaxSec=720", "--property=KillMode=control-group",
               "--property=NoNewPrivileges=yes", "--property=CapabilityBoundingSet=",
               "--property=PrivateTmp=yes", "--property=PrivateDevices=yes", "--property=ProtectSystem=strict",
               "--property=ProtectHome=yes", "--property=ProtectKernelTunables=yes", "--property=ProtectKernelModules=yes",
               "--property=ProtectControlGroups=yes", "--property=ProtectProc=invisible",
               "--property=RestrictSUIDSGID=yes", "--property=RestrictNamespaces=yes",
               "--property=RestrictAddressFamilies=AF_UNIX AF_INET AF_INET6", "--property=TasksMax=64", "--property=MemoryMax=1G",
               "--property=InaccessiblePaths=-/var/lib/haos-agent -/var/lib/haos-control -/var/lib/haos-owner -/var/lib/haos-workspace -/etc/haos/backend-token -/run/haos-control -/run/haos-volumes -/run/haos-policy",
               "--setenv=HOME=/var/lib/haos-provider", "--setenv=HERMES_HOME=/var/lib/haos-provider/.hermes",
               "--setenv=PYTHONPATH=/usr/lib/haos:/usr/lib/haos/hermes", "--setenv=PYTHONDONTWRITEBYTECODE=1",
               "--setenv=PATH=/usr/lib/haos/hermes/.venv/bin:/usr/bin",
               "/usr/lib/haos/hermes/.venv/bin/python", "-m", "haos.provider_auth", action]
    result = subprocess.run(command, env=ENV, timeout=740)
    if result.returncode:
        raise RuntimeError("provider credential action failed; inspect the trusted owner console")


def owner_provider(args):
    from .owner import audit, stopped
    from .gateway_setup import stopped_gateway
    from .network import install
    if os.geteuid() != 0:
        raise PermissionError("provider changes require authenticated owner authority")
    protected_directory(CONFIG)
    if args.provider_action == "status":
        exists = (CONFIG / "provider.json").exists()
        return {"configured": exists, "policy": ProviderPolicy(trusted_json(CONFIG / "provider.json")).data if exists else None,
                "credential_values_exposed": False, "external_model_acceptance": "requires a real mission and provider receipt"}
    if args.provider_action == "stop":
        # Stop missions before withdrawing their model connection. Socket-first
        # withdrawal prevents reactivation while the service drains/stops.
        stopped()
        stopped_gateway()
        subprocess.run(["/usr/bin/systemctl", "stop", "haos-provider.socket", "haos-provider.service"], check=True, timeout=40)
        stopped_provider()
        return {"stopped": True}
    stopped()
    stopped_gateway()
    stopped_provider()
    if args.provider_action in {"login-codex", "logout-codex"}:
        auth_helper("login" if args.provider_action == "login-codex" else "logout")
        audit("provider." + args.provider_action, {"provider": "openai-codex"})
        return {"credential_action_completed": True, "model_turn_tested": False}
    if args.provider_action == "disable":
        for name in ("provider.json", "provider-client.json"):
            path = CONFIG / name
            if path.exists() or path.is_symlink():
                trusted_json(path)
                path.unlink()
        atomic_json(CONFIG / "provider-credentials", {"api_key": None})
        install(pwd.getpwnam("haos-agent").pw_uid)
        audit("provider.disabled", {})
        return {"disabled": True, "oauth_state": "private retained state; logout-codex removes local OAuth credentials"}
    if args.provider_action != "configure":
        raise ValueError("unsupported owner provider action")
    data = {"version": 1, "provider": args.provider, "endpoint": args.endpoint or ENDPOINTS.get(args.provider, ""),
            "models": list(dict.fromkeys([args.model, *args.allow_model])), "default_model": args.model,
            "api_mode": args.api_mode or ("chat_completions" if args.provider in {"openrouter", "local"} else "codex_responses"),
            "requests_per_day": args.requests_per_day, "requests_per_minute": args.requests_per_minute}
    policy = ProviderPolicy(data)
    credential = None
    if policy.provider in {"openai", "openrouter"}:
        from .owner_recovery import require_console
        require_console()
        credential = getpass.getpass("Provider API key (owner store only, never agent state): ")
    if policy.provider == "openai-codex":
        auth_helper("status")  # Real pinned OAuth resolver, read-only; no fake ready state.
    publish(policy.data, credential)
    install(pwd.getpwnam("haos-agent").pw_uid)
    subprocess.run(["/usr/bin/systemctl", "start", "haos-provider.socket"], check=True, timeout=30)
    audit("provider.configured", {"provider": policy.provider, "models": policy.models})
    return {"configured": True, "start_runtime": "haos-owner start", "model_turn_tested": False}
