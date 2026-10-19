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
from .provider_registry import default_mode, oauth_providers
from .provider_routes import ProviderRoutes

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
    if policy.get("version") == 2:
        routes = ProviderRoutes(policy)
        if (not isinstance(credential, dict) or set(credential) != set(routes.routes)
                or any(set(value) != {"api_key"} for value in credential.values())):
            raise ValueError("provider credentials must match configured routes")
        for key, route in routes.routes.items():
            validate_credential(route, credential[key]["api_key"])
        envelope, client, data = {"routes": credential}, routes.client_config(), routes.data
    else:
        policy = ProviderPolicy(policy)
        validate_credential(policy, credential)
        envelope, client, data = {"api_key": credential}, policy.client_config(), policy.data
    import json
    if len(json.dumps(envelope).encode()) > 32768:
        raise ValueError("provider credential envelope exceeds service credential bound")
    _publish(data, envelope, client, config)


def validate_credential(policy, credential):
    if credential is not None and (not isinstance(credential, str) or not 16 <= len(credential) <= 16384
                                   or any(ord(c) < 33 or ord(c) > 126 for c in credential)):
        raise ValueError("invalid provider credential")
    if policy.provider not in {"local", "lmstudio", "anthropic", "openrouter", *oauth_providers()} and not credential:
        raise ValueError("API provider requires a securely entered credential")


def _publish(data, envelope, client, config):
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
    atomic_json(config / "provider-credentials", envelope)
    atomic_json(config / "provider-token", {"token": secrets.token_urlsafe(48)})
    atomic_json(config / "provider-client.json", client, mode=0o644)
    atomic_json(config / "provider.json", data, mode=0o644)


def add_route(policy, credential, *, make_default=True, config=CONFIG):
    """Stopped, authenticated owner replaces one route, preserving the others."""
    if os.geteuid() != 0:
        raise PermissionError("provider changes require authenticated owner authority")
    policy = ProviderPolicy(policy)
    route_id = "openai-api" if policy.provider == "openai" else policy.provider
    descriptor = config / "provider.json"
    if descriptor.exists() or descriptor.is_symlink():
        existing = ProviderRoutes(trusted_json(descriptor))
        secrets = trusted_json(config / "provider-credentials")
        if existing.data["version"] == 1:
            name = "openai-api" if existing.primary.provider == "openai" else existing.primary.provider
            data = {"version": 2, "default": name, "routes": {name: existing.primary.data}, "fallbacks": {}}
            credentials = {name: secrets}
        else:
            data, credentials = existing.data, secrets["routes"]
    else:
        data, credentials = {"version": 2, "default": route_id, "routes": {}, "fallbacks": {}}, {}
    data["routes"][route_id] = policy.data
    credentials[route_id] = {"api_key": credential}
    if make_default:
        data["default"] = route_id
    publish(data, credentials, config=config)
    return {"route": route_id, "default": data["default"], "routes": list(data["routes"])}


def route_settings(route_id, *, fallbacks=None, make_default=False, remove=False, config=CONFIG):
    if os.geteuid() != 0:
        raise PermissionError("provider changes require authenticated owner authority")
    current = ProviderRoutes(trusted_json(config / "provider.json"))
    if current.data["version"] != 2 or route_id not in current.routes:
        raise ValueError("select a configured provider route")
    data = current.data
    credentials = trusted_json(config / "provider-credentials")["routes"]
    if make_default:
        data["default"] = route_id
    if fallbacks is not None:
        data["fallbacks"][route_id] = list(fallbacks)
    if remove:
        if len(data["routes"]) == 1:
            raise ValueError("disable the broker to remove its final route")
        if data["default"] == route_id:
            raise ValueError("select another default before removing this route")
        del data["routes"][route_id]
        del credentials[route_id]
        data["fallbacks"].pop(route_id, None)
        for targets in data["fallbacks"].values():
            if route_id in targets:
                targets.remove(route_id)
    publish(data, credentials, config=config)
    return {"default": data["default"], "routes": list(data["routes"]), "fallbacks": data["fallbacks"]}


def auth_helper(action, provider="openai-codex", *, graphical_status=False):
    # Transient service supplies a private state directory and the same security
    # boundary as the long-lived broker. No root CLI command/user/path is passed
    # from the model. --pty keeps device codes and OAuth output off the journal.
    if action not in {"login", "status", "logout"}:
        raise ValueError("unsupported provider credential action")
    if provider not in oauth_providers() | {"anthropic", "openrouter"}:
        raise ValueError("unsupported provider account login")
    from .owner_recovery import require_console
    if graphical_status:
        from .initial_setup_gui import session_allowed
        if action != "status" or not session_allowed():
            raise PermissionError("graphical auth status requires the trusted local setup seat")
    else:
        require_console()
    entry = pwd.getpwnam("haos-provider")
    if entry.pw_uid == 0:
        raise PermissionError("invalid provider service identity")
    command = ["/usr/bin/systemd-run", "--pipe" if graphical_status else "--pty", "--wait", "--collect", "--quiet", "--service-type=exec",
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
               "/usr/lib/haos/hermes/.venv/bin/python", "-m", "haos.provider_auth", action, provider]
    result = subprocess.run(command, env=ENV, timeout=740, capture_output=graphical_status)
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
        return {"configured": exists, "policy": ProviderRoutes(trusted_json(CONFIG / "provider.json")).data if exists else None,
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
    if args.provider_action in {"set-default", "fallbacks", "remove"}:
        result = route_settings(args.route, make_default=args.provider_action == "set-default",
                                fallbacks=args.fallback if args.provider_action == "fallbacks" else None,
                                remove=args.provider_action == "remove")
        audit("provider.routes-changed", {"route": args.route, "action": args.provider_action})
        return result
    if args.provider_action in {"login-codex", "logout-codex", "login", "logout", "auth-status"}:
        provider = "openai-codex" if args.provider_action.endswith("-codex") else args.provider
        action = {"login-codex": "login", "logout-codex": "logout", "auth-status": "status"}.get(args.provider_action, args.provider_action)
        auth_helper(action, provider)
        audit("provider." + args.provider_action, {"provider": provider})
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
            "api_mode": args.api_mode or default_mode(args.provider),
            "requests_per_day": args.requests_per_day, "requests_per_minute": args.requests_per_minute}
    policy = ProviderPolicy(data)
    credential = None
    if policy.provider not in {"local", "lmstudio", *oauth_providers()}:
        from .owner_recovery import require_console
        require_console()
        credential = getpass.getpass("Provider API key (owner store only, never agent state): ")
    if policy.provider in oauth_providers():
        auth_helper("status", policy.provider)
    add_route(policy.data, credential)
    install(pwd.getpwnam("haos-agent").pw_uid)
    subprocess.run(["/usr/bin/systemctl", "start", "haos-provider.socket"], check=True, timeout=30)
    audit("provider.configured", {"provider": policy.provider, "models": policy.models})
    return {"configured": True, "start_runtime": "haos-owner start", "model_turn_tested": False}
