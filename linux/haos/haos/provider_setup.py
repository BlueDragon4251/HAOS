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
from .provider_registry import default_mode, oauth_providers, account_providers
from .provider_routes import ProviderRoutes

CONFIG = Path("/etc/haos")
UNITS = ("haos-provider.service", "haos-provider.socket", "haos-provider-acp.socket", "haos-provider-acp.service")


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
    if policy.provider == "copilot-acp":
        if credential is not None:
            raise PermissionError("ACP requires login under its separate service identity")
        return
    from .provider_cloud import CLOUD, credential_data
    if policy.provider in CLOUD:
        credential_data(policy.provider, credential)
        return
    if credential is not None and (not isinstance(credential, str) or not 16 <= len(credential) <= 16384
                                   or any(ord(c) < 33 or ord(c) > 126 for c in credential)):
        raise ValueError("invalid provider credential")
    if policy.provider not in {"local", "lmstudio", "custom", *account_providers()} and not credential:
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
        if "default_ensemble" in data:
            data["default_ensemble"] = None
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
        if "default_ensemble" in data:
            data["default_ensemble"] = None
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
        for name, preset in list(data.get("ensembles", {}).items()):
            if any(slot["route"] == route_id for slot in [*preset["references"], preset["aggregator"]]):
                del data["ensembles"][name]
                if data.get("default_ensemble") == name:
                    data["default_ensemble"] = None
    publish(data, credentials, config=config)
    return {"default": data["default"], "routes": list(data["routes"]), "fallbacks": data["fallbacks"]}


def configure_ensemble(name, references, aggregator, *, active=True, config=CONFIG):
    if os.geteuid() != 0:
        raise PermissionError("MoA configuration requires authenticated owner authority")
    current = ProviderRoutes(trusted_json(config / "provider.json"))
    if current.data["version"] == 1:
        # The graphical selection calls this legacy route `default`. Preserve
        # that identity and its private credential during atomic migration.
        data = {"version": 2, "default": "default", "routes": {"default": current.primary.data}, "fallbacks": {}}
        credentials = {"default": trusted_json(config / "provider-credentials")}
    else:
        data = current.data
        credentials = trusted_json(config / "provider-credentials")["routes"]
    data.setdefault("ensembles", {})[name] = {"references": references, "aggregator": aggregator}
    data.setdefault("default_ensemble", None)
    if active:
        data["default_ensemble"] = name
    publish(data, credentials, config=config)
    return {"preset": name, "default_ensemble": data["default_ensemble"], "model_turn_tested": False}


def disable_configuration(*, config=CONFIG):
    if os.geteuid() != 0:
        raise PermissionError("provider withdrawal requires authenticated owner authority")
    protected_directory(config)
    for name in ("provider.json", "provider-client.json"):
        path = config / name
        if path.exists() or path.is_symlink():
            trusted_json(path)
            path.unlink()
    parent = os.open(config, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        os.fsync(parent)
    finally:
        os.close(parent)
    atomic_json(config / "provider-credentials", {"api_key": None})
    atomic_json(config / "provider-token", {"token": secrets.token_urlsafe(48)})


def revoke_account_routes(provider, *, config=CONFIG):
    if os.geteuid() != 0:
        raise PermissionError("provider withdrawal requires authenticated owner authority")
    descriptor = config / "provider.json"
    if not descriptor.exists() and not descriptor.is_symlink():
        return {"withdrawn_routes": 0}
    current = ProviderRoutes(trusted_json(descriptor))
    removed = {key for key, policy in current.routes.items() if policy.provider == provider}
    if not removed:
        return {"withdrawn_routes": 0}
    if len(removed) == len(current.routes):
        disable_configuration(config=config)
    else:
        data = current.data
        credentials = trusted_json(config / "provider-credentials")["routes"]
        for key in removed:
            del data["routes"][key]
            del credentials[key]
            data["fallbacks"].pop(key, None)
        for source, targets in data["fallbacks"].items():
            data["fallbacks"][source] = [target for target in targets if target not in removed]
        if data["default"] in removed:
            data["default"] = next(iter(data["routes"]))
        for name, preset in list(data.get("ensembles", {}).items()):
            if any(slot["route"] in removed for slot in [*preset["references"], preset["aggregator"]]):
                del data["ensembles"][name]
                if data.get("default_ensemble") == name:
                    data["default_ensemble"] = None
        publish(data, credentials, config=config)
    return {"withdrawn_routes": len(removed)}


def private_command(provider, module, arguments=(), *, pipe=True):
    """Fixed helper entrypoints, private service identities and no secret argv."""
    if os.geteuid() != 0 or module not in {"haos.provider_auth", "haos.provider_discovery"}:
        raise PermissionError("root-owned fixed provider helper required")
    identity = "haos-provider-acp" if provider == "copilot-acp" else "haos-provider"
    entry = pwd.getpwnam(identity)
    if entry.pw_uid == 0:
        raise PermissionError("invalid provider service identity")
    inaccessible = ["/var/lib/haos-agent", "/var/lib/haos-control", "/var/lib/haos-owner", "/var/lib/haos-workspace",
        "/var/lib/haos-gateway", "/var/lib/" + ("haos-provider" if provider == "copilot-acp" else "haos-provider-acp"),
        "/etc/haos/backend-token", "/etc/haos/provider-token", "/etc/haos/provider-credentials",
        "/run/haos-control", "/run/haos-volumes", "/run/haos-policy", "/run/haos-applications-control",
        "/run/haos-gui-agent", "/run/credentials", "/run/dbus", "/run/user"]
    command = ["/usr/bin/systemd-run", "--pipe" if pipe else "--pty", "--wait", "--collect", "--quiet", "--service-type=exec",
               "--unit=haos-provider-owner-" + secrets.token_hex(12),
               "--property=User=" + identity, "--property=Group=" + identity,
               "--property=StateDirectory=" + identity, "--property=StateDirectoryMode=0700",
               "--property=UMask=0077", "--property=RuntimeMaxSec=" + ("90" if module == "haos.provider_discovery" else "720"), "--property=KillMode=control-group",
               "--property=NoNewPrivileges=yes", "--property=CapabilityBoundingSet=",
               "--property=PrivateTmp=yes", "--property=PrivateDevices=yes", "--property=ProtectSystem=strict",
               "--property=ProtectHome=yes", "--property=ProtectKernelTunables=yes", "--property=ProtectKernelModules=yes",
               "--property=ProtectControlGroups=yes", "--property=ProtectProc=invisible",
               "--property=RestrictSUIDSGID=yes", "--property=RestrictNamespaces=yes",
               "--property=RestrictAddressFamilies=AF_UNIX AF_INET AF_INET6", "--property=TasksMax=64", "--property=MemoryMax=1G",
               "--property=InaccessiblePaths=" + " ".join("-" + path for path in inaccessible),
               "--setenv=HOME=/var/lib/" + identity, "--setenv=HERMES_HOME=/var/lib/" + identity + "/.hermes",
               "--setenv=PYTHONPATH=/usr/lib/haos:/usr/lib/haos/hermes", "--setenv=PYTHONDONTWRITEBYTECODE=1",
               "--setenv=PATH=/usr/lib/haos/hermes/.venv/bin:/usr/bin",
               "--setenv=COPILOT_AUTO_UPDATE=false", "--setenv=DO_NOT_TRACK=1",
               "/usr/lib/haos/hermes/.venv/bin/python", "-m", module, *arguments]
    if provider == "copilot-acp":
        subprocess.run(["/usr/bin/systemctl", "start", "haos-provider-acp-network.service"],
                       check=True, capture_output=True, timeout=30)
    return command


def auth_helper(action, provider="openai-codex", *, graphical_status=False, region="global"):
    # --pty keeps device codes and OAuth output off the journal.
    if action not in {"login", "status", "logout"} or provider not in account_providers():
        raise ValueError("unsupported provider credential action")
    if region not in {"global", "cn"} or region != "global" and provider != "minimax-oauth":
        raise ValueError("unsupported provider account region")
    from .owner_recovery import require_console
    if graphical_status:
        from .initial_setup_gui import session_allowed
        if action != "status" or not session_allowed():
            raise PermissionError("graphical auth status requires the trusted local setup seat")
    else:
        require_console()
    arguments = (action, provider, region) if provider == "minimax-oauth" else (action, provider)
    command = private_command(provider, "haos.provider_auth", arguments, pipe=graphical_status)
    result = subprocess.run(command, env=ENV, timeout=740, capture_output=graphical_status)
    if result.returncode:
        if provider == "minimax-oauth":
            raise RuntimeError("MiniMax account or region did not match. Check the global/China endpoint and sign in through the trusted owner terminal.")
        raise RuntimeError("provider credential action failed; inspect the trusted owner console")


def catalog_helper(policy, credential):
    """Root-seat key input goes only through stdin to the protected identity."""
    import json
    from .provider_discovery import validate_catalog, fallback
    if os.geteuid() != 0:
        raise PermissionError("model discovery requires owner authority")
    policy = ProviderPolicy(policy)
    # Public/offline catalogs do not require saving an incomplete API credential.
    if credential is not None:
        validate_credential(policy, credential)
    request = json.dumps({"policy": policy.data, "credential": credential}).encode()
    if len(request) > 32768:
        raise ValueError("private catalog input exceeds its bound")
    command = private_command(policy.provider, "haos.provider_discovery")
    result = subprocess.run(command, input=request, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                            env=ENV, timeout=110)
    if result.returncode:
        return fallback(policy.provider, "catalog-unavailable")
    if len(result.stdout) > 4 * 1024 * 1024:
        raise ValueError("private catalog reply exceeds its bound")
    return validate_catalog(json.loads(result.stdout), policy.provider)


def owner_provider(args):
    from .owner import audit, stopped
    from .gateway_setup import stopped_gateway
    from .network import install
    if os.geteuid() != 0:
        raise PermissionError("provider changes require authenticated owner authority")
    if args.provider_action in {"login", "logout", "auth-status"}:
        region = getattr(args, "region", "global")
        if args.provider not in account_providers() or region not in {"global", "cn"} or region != "global" and args.provider != "minimax-oauth":
            raise ValueError("unsupported provider account or region")
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
    if args.provider_action == "auth-status":
        auth_helper("status", args.provider, region=getattr(args, "region", "global"))
        audit("provider.auth-status", {"provider": args.provider})
        return {"credential_action_completed": True, "model_turn_tested": False}
    stopped()
    stopped_gateway()
    stopped_provider()
    if args.provider_action == "ensemble":
        import json
        from .owner_recovery import require_console
        require_console()
        value = json.loads(input("MoA preset JSON (references + aggregator; route and model only): "))
        if not isinstance(value, dict) or set(value) != {"references", "aggregator"}:
            raise ValueError("invalid MoA preset")
        result = configure_ensemble(args.name, value["references"], value["aggregator"])
        audit("provider.ensemble", {"name": args.name})
        return result
    if args.provider_action in {"set-default", "fallbacks", "remove"}:
        result = route_settings(args.route, make_default=args.provider_action == "set-default",
                                fallbacks=args.fallback if args.provider_action == "fallbacks" else None,
                                remove=args.provider_action == "remove")
        audit("provider.routes-changed", {"route": args.route, "action": args.provider_action})
        return result
    if args.provider_action in {"login-codex", "logout-codex", "login", "logout"}:
        provider = "openai-codex" if args.provider_action.endswith("-codex") else args.provider
        action = {"login-codex": "login", "logout-codex": "logout"}.get(args.provider_action, args.provider_action)
        if action == "logout":
            revoke_account_routes(provider)
            install(pwd.getpwnam("haos-agent").pw_uid)
        auth_helper(action, provider, region=getattr(args, "region", "global"))
        audit("provider." + args.provider_action, {"provider": provider})
        return {"credential_action_completed": True, "model_turn_tested": False}
    if args.provider_action == "disable":
        disable_configuration()
        install(pwd.getpwnam("haos-agent").pw_uid)
        audit("provider.disabled", {})
        return {"disabled": True, "oauth_state": "private retained state; logout-codex removes local OAuth credentials"}
    if args.provider_action != "configure":
        raise ValueError("unsupported owner provider action")
    data = {"version": 1, "provider": args.provider, "endpoint": args.endpoint or ENDPOINTS.get(args.provider, ""),
            "models": list(dict.fromkeys([args.model, *args.allow_model])), "default_model": args.model,
            "api_mode": args.api_mode or default_mode(args.provider, args.model, args.endpoint or ""),
            "requests_per_day": args.requests_per_day, "requests_per_minute": args.requests_per_minute}
    policy = ProviderPolicy(data)
    credential = None
    from .provider_cloud import CLOUD
    if policy.provider not in {"local", "lmstudio", "copilot-acp", *oauth_providers(), *CLOUD}:
        from .owner_recovery import require_console
        require_console()
        credential = getpass.getpass("Provider API key (owner store only, never agent state): ") or None
    elif policy.provider in CLOUD:
        from .owner_recovery import require_console
        require_console()
        credential = getpass.getpass("Cloud credential JSON (Azure also accepts an API key; blank = service UID SDK chain): ") or None
    if policy.provider in oauth_providers() or policy.provider == "copilot-acp":
        from .provider_registry import account_region
        auth_helper("status", policy.provider, region=account_region(policy.provider, policy.endpoint))
    add_route(policy.data, credential)
    install(pwd.getpwnam("haos-agent").pw_uid)
    subprocess.run(["/usr/bin/systemctl", "start", "haos-provider.socket"], check=True, timeout=30)
    audit("provider.configured", {"provider": policy.provider, "models": policy.models})
    return {"configured": True, "start_runtime": "haos-owner start", "model_turn_tested": False}
