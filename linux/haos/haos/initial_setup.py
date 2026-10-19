"""Root-only initial HAOS setup authority for a dedicated *local* graphical seat.

The normal Hermes renderer and agent must never call this module. The graphical
launcher is not enabled at boot until actual installed-OS GUI acceptance passes.
"""
from __future__ import annotations

import os
from pathlib import Path
import pwd
import subprocess

from .enrollment import enroll, validate_name
from .owner_recovery import RecoveryCodes, enrolled_owner, owners
from .region import CONSOLE_MAP, LOCALES
from .provider_policy import ProviderPolicy, ENDPOINTS
from .setup_errors import SetupStageError
from .provider_registry import default_endpoint, default_mode, http_providers, oauth_providers, account_providers
from .provider_cloud import CLOUD

# Never store a plaintext password, recovery code, provider key or GHCR token
# in setup state, IPC, temporary files, shell argv, or the audit log.
RUNNING = ("haos-gateway.service", "haos-controller.service", "haos-hermes.service")
PROVIDER_UNITS = ("haos-provider.socket", "haos-provider.service")


def quiesce_for_setup(*, gateway_only=False):
    """Root-only predictable service interruption before changing live secrets.

    Unlike the legacy owner CLI (which requires a manual stop), the graphical
    flow stops its own services and verifies quiescence, never invokes a shell.
    """
    require_root()
    units = ("haos-gateway.service",) if gateway_only else (*RUNNING, *PROVIDER_UNITS)
    subprocess.run(["/usr/bin/systemctl", "stop", *units], check=True,
                   timeout=75, capture_output=True)
    from .gateway_setup import stopped_gateway
    stopped_gateway()
    if not gateway_only:
        from .owner import stopped
        from .provider_setup import stopped_provider
        stopped()
        stopped_provider()

PENDING = Path("/var/lib/haos-owner/setup-recovery-pending.json")
COMPLETE = Path("/var/lib/haos-owner/graphical-setup.json")
IN_PROGRESS = Path("/var/lib/haos-owner/graphical-setup-in-progress.json")


def setup_in_progress():
    """Durable wizard fence. Survives recovery-code acknowledgement and reboot."""
    if IN_PROGRESS.is_symlink():
        raise PermissionError("untrusted initial setup marker")
    if not IN_PROGRESS.exists():
        return False
    import stat
    info = IN_PROGRESS.stat()
    if not stat.S_ISREG(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o077:
        raise PermissionError("initial setup marker must be root-private")
    return True



def setup_finished():
    """Require a verified, durable root-owned wizard completion receipt.

    Owner enrollment on tty2 is deliberately not equivalent to completing
    the normal user profile, localization, and graphical wizard.
    """
    require_root()
    if COMPLETE.is_symlink():
        raise PermissionError("untrusted graphical setup completion marker")
    if not COMPLETE.exists():
        return False
    from .sandbox import trusted_json
    import stat
    info = COMPLETE.lstat()
    if (not stat.S_ISREG(info.st_mode) or info.st_uid != 0
            or info.st_mode & 0o077 or info.st_nlink != 1):
        raise PermissionError("graphical setup receipt must be root-private")
    value = trusted_json(COMPLETE)
    if (set(value) != {"version", "completed"} or type(value["version"]) is not int
            or value["version"] != 1 or value["completed"] is not True):
        raise PermissionError("invalid graphical setup completion receipt")
    return True


def recovery_pending():
    if PENDING.is_symlink():
        raise PermissionError("untrusted recovery pending marker")
    if not PENDING.exists():
        return False
    info = PENDING.stat()
    import stat
    if not stat.S_ISREG(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o077:
        raise PermissionError("owner recovery marker must be private")
    return True


def mark_pending():
    from .policy import atomic_json
    if recovery_pending() or setup_in_progress():
        raise PermissionError("a prior graphical setup must be resolved first")
    # Fence the normal desktop BEFORE enrolling another privileged principal.
    atomic_json(IN_PROGRESS, {"version": 1, "setup_in_progress": True}, mode=0o600)
    atomic_json(PENDING, {"version": 1, "unconfirmed_recovery": True}, mode=0o600)



def require_root():
    if os.geteuid() != 0:
        raise PermissionError("initial setup is reserved for the trusted local root seat")


def account_status():
    require_root()
    entries = owners()
    if len(entries) > 1:
        # Multiple owners require explicit migration; never guess whose rights to change.
        raise PermissionError("multiple enrolled owners need a separate migration review")
    if not entries:
        return {"owner": False, "recovery": False, "complete": False, "pending": recovery_pending()}
    owner = enrolled_owner(entries[0]["username"])
    recovery = RecoveryCodes()._load()
    has_codes = bool(recovery["owners"].get(str(owner.pw_uid), {}).get("hashes"))
    return {"owner": True, "recovery": has_codes, "complete": has_codes and not recovery_pending(), "pending": recovery_pending()}


def create_initial_owner(username: str, password: str, repeated: str) -> tuple[str, list[str]]:
    """Creates an independent password owner and returns one-time recovery codes.

    Recovery codes are returned only to this local root process; a crash before
    the operator saves them means the trusted local setup must *rotate* them.
    """
    require_root()
    if password != repeated:
        raise ValueError("Administrator passwords do not match")
    if owners():
        raise PermissionError("existing owners must never be overwritten during migration")
    # Stop all autonomous execution before granting another principal.
    subprocess.run(["/usr/bin/systemctl", "stop", *RUNNING],
                   check=True, timeout=45, capture_output=True)
    from .owner import stopped, audit
    stopped()
    mark_pending()  # Durable before password creation/recovery issuance. A crash can be resumed.
    created = enroll(username, password, initial_only=True)
    identity = enrolled_owner(created["username"])
    codes = RecoveryCodes().issue(identity.pw_uid)
    audit("setup.initial-owner", {"uid": identity.pw_uid, "recovery_count": len(codes)})
    return identity.pw_name, codes


def rotate_unconfirmed_codes(username: str) -> list[str]:
    """Used only on the physical trusted root display after an interrupted setup."""
    require_root()
    if not recovery_pending():
        raise PermissionError("recovery rotation requires pending local setup")
    entry = enrolled_owner(username)
    codes = RecoveryCodes().issue(entry.pw_uid)
    from .owner import audit
    audit("setup.recovery-rotated", {"uid": entry.pw_uid})
    return codes


def configure_region(language: str, keyboard: str):
    require_root()
    if language not in LOCALES or keyboard not in CONSOLE_MAP:
        raise ValueError("unsupported language or keyboard")
    from .region import owner_region
    from types import SimpleNamespace
    try:
        result = owner_region(SimpleNamespace(region_action="apply", language=language, keyboard=keyboard))
    except Exception as error:
        raise SetupStageError("REGION_SYSTEM", error) from None
    # The private VT8 X keyboard must change immediately too; other callers
    # cannot ask the owner broker to modify the normal observer's X display.
    if os.getenv("HAOS_TRUSTED_SETUP") == "1" and os.getenv("DISPLAY") == ":8":
        subprocess.run(["/usr/bin/setxkbmap", "-layout", keyboard], check=True,
                       timeout=8, capture_output=True,
                       env={"DISPLAY": ":8", "XAUTHORITY": "/run/haos-setup-display/Xauthority",
                            "PATH": "/usr/bin:/bin"})
    from .normal_profile import configure_region as observer_region
    try:
        observer_region(language, keyboard)
    except Exception as error:
        raise SetupStageError("REGION_OBSERVER", error) from None
    return result


def configure_normal_user(display_name: str):
    require_root()
    from .normal_profile import configure_name
    from .owner import audit
    try:
        result = configure_name(display_name)
    except Exception as error:
        raise SetupStageError("PROFILE", error) from None
    audit("setup.normal-user-named", {"configured": True})
    return result


def normal_user_ready() -> bool:
    require_root()
    from .normal_profile import name_exists
    return name_exists()


def configure_ghcr(username: str, token: str):
    require_root()
    from .update import login_credentials
    from .owner import audit
    result = login_credentials(username, token)
    audit("setup.ghcr-login", {"ghcr": True})
    return result


def configure_update(channel: str, automatic: bool):
    require_root()
    if channel not in {"stable", "dev"} or type(automatic) is not bool:
        raise ValueError("unsupported update configuration")
    from .update import switch_channel
    from .owner import audit
    result = switch_channel(channel, automatic)
    audit("setup.update-channel", {"channel": channel, "auto_stage": automatic})
    return result


def configure_provider(provider: str, model: str, api_key: str = "", endpoint: str = "", api_mode: str = ""):
    """Provision a vetted HTTP or account route from the trusted local seat."""
    require_root()
    if provider not in {*http_providers(), *oauth_providers(), *CLOUD, "openai", "local", "lmstudio", "gemini", "custom", "copilot", "copilot-acp"}:
        raise ValueError("use a provider with an implemented graphical credential flow")
    from .provider_setup import add_route, stopped_provider
    from .gateway_setup import stopped_gateway
    from .network import install
    from .owner import stopped, audit
    data = {"version": 1, "provider": provider,
            "endpoint": endpoint or default_endpoint(provider),
            "models": [model], "default_model": model,
            "api_mode": api_mode or default_mode(provider, model),
            "requests_per_day": 200, "requests_per_minute": 30}
    policy = ProviderPolicy(data)
    if provider not in {"local", "lmstudio", "custom", *account_providers(), *CLOUD} and not api_key:
        raise ValueError("cloud API key required")
    if provider not in CLOUD and api_key and (not 16 <= len(api_key) <= 16384 or
                                   any(ord(c) < 33 or ord(c) > 126 for c in api_key)):
        raise ValueError("invalid provider credential")
    quiesce_for_setup()
    if provider in oauth_providers() or provider == "copilot-acp" or (provider in {"anthropic", "openrouter", "copilot"} and not api_key):
        from .provider_setup import auth_helper
        auth_helper("status", provider, graphical_status=True)
    # Only now does the vetted owner credential publisher replace trusted files.
    add_route(policy.data, api_key or None)
    install(pwd.getpwnam("haos-agent").pw_uid)
    subprocess.run(["/usr/bin/systemctl", "start", "haos-provider.socket"],
                   check=True, timeout=30, capture_output=True)
    audit("setup.provider", {"provider": provider, "models": [model]})
    return {"configured": True, "provider": provider, "model_turn_tested": False}


def provider_models(provider, api_key="", endpoint="", api_mode=""):
    require_root()
    from .provider_setup import catalog_helper
    data = {"version": 1, "provider": provider, "endpoint": endpoint or default_endpoint(provider),
            "models": ["haos-discovery"], "default_model": "haos-discovery",
            "api_mode": api_mode or default_mode(provider, "haos-discovery"),
            "requests_per_day": 200, "requests_per_minute": 30}
    return catalog_helper(data, api_key or None)


def provider_state():
    require_root()
    from .provider_routes import ProviderRoutes
    from .sandbox import trusted_json
    path = Path("/etc/haos/provider.json")
    if not path.exists() and not path.is_symlink():
        return {"routes": [], "default": None, "fallbacks": {}}
    current = ProviderRoutes(trusted_json(path))
    return {"routes": [{"id": name, "provider": policy.provider, "model": policy.data["default_model"],
                        "api_mode": policy.api_mode} for name, policy in current.routes.items()],
            "default": current.default, "fallbacks": current.fallbacks}


def manage_provider_route(route, action, fallbacks=()):
    require_root()
    if action not in {"default", "remove", "fallbacks"}:
        raise ValueError("unsupported provider route action")
    from .provider_setup import route_settings
    from .owner import audit
    quiesce_for_setup()
    result = route_settings(route, make_default=action == "default", remove=action == "remove",
                            fallbacks=fallbacks if action == "fallbacks" else None)
    subprocess.run(["/usr/bin/systemctl", "start", "haos-provider.socket"],
                   check=True, timeout=30, capture_output=True)
    audit("setup.provider-routes", {"route": route, "action": action})
    return result


def provider_account(provider, action="login"):
    """Native trusted-seat account flow; OAuth runs in the separate provider UID."""
    require_root()
    from .initial_setup_gui import session_allowed
    if not session_allowed() or provider not in account_providers() or action not in {"login", "logout"}:
        raise PermissionError("provider account login requires the trusted local setup seat")
    quiesce_for_setup()
    if action == "logout":
        from .provider_setup import revoke_account_routes
        from .network import install
        revoke_account_routes(provider)
        install(pwd.getpwnam("haos-agent").pw_uid)
    subprocess.run(["/usr/bin/xterm", "-T", "HAOS Provider-Anmeldung", "-geometry", "110x32+20+20",
                    "-e", "/usr/bin/python3", "-I", "/usr/lib/haos/provider-login.py", action, provider],
                   check=True, timeout=780, capture_output=True,
                   env={"DISPLAY": ":8", "XAUTHORITY": "/run/haos-setup-display/Xauthority",
                        "HAOS_TRUSTED_SETUP": "1", "PATH": "/usr/bin:/bin"})
    return {"credential_action_completed": True, "model_turn_tested": False}


def configure_moa(name, value):
    require_root()
    import json
    if not isinstance(value, str) or len(value) > 16384:
        raise ValueError("invalid MoA configuration")
    preset = json.loads(value)
    if not isinstance(preset, dict) or set(preset) != {"references", "aggregator"}:
        raise ValueError("MoA expects references and aggregator")
    quiesce_for_setup()
    from .provider_setup import configure_ensemble
    from .owner import audit
    result = configure_ensemble(name, preset["references"], preset["aggregator"])
    audit("setup.moa", {"name": name})
    return result


def configure_gateway(connector: str, platform: str, token: str):
    """Graphical root-seat setup for HAOS's TWO authorized message adapters.

    Upstream Hermes lists more platform plugins, but HAOS's ingress authorization
    currently supports only these two. Never auto-authorize upstream modules.
    """
    require_root()
    if platform not in {"telegram", "discord"}:
        raise ValueError("HAOS has not approved this platform for gateway execution")
    if (not isinstance(token, str) or not 16 <= len(token) <= 4096
            or any(c.isspace() or ord(c) < 32 for c in token)):
        raise ValueError("invalid protected gateway credential")
    from .gateway_setup import load, persist, stopped_gateway
    from .gateway import GatewayPolicy
    from .owner import audit
    policy, credentials = load()
    quiesce_for_setup(gateway_only=True)
    if any(c["id"] != connector and c["platform"] == platform for c in policy["connectors"]):
        raise ValueError("one isolated adapter per platform is currently supported")
    policy["connectors"] = [c for c in policy["connectors"] if c["id"] != connector] + [
        {"id": connector, "platform": platform}]
    GatewayPolicy(policy)
    credentials["connectors"][connector] = {"token": token}
    persist(policy, credentials)
    audit("setup.gateway", {"connector": connector, "platform": platform})
    return {"configured": True, "platform": platform, "restart_required": True}


def pair_gateway_sender(binding_id: str, connector: str, sender: str, chat: str,
                        identity: str, capabilities: tuple[str, ...] = ("create", "read")):
    """Grant one exact sender+chat on an already provisioned platform."""
    require_root()
    if not capabilities or not set(capabilities) <= {"create", "read", "cancel", "answer", "pause", "resume"}:
        raise ValueError("unsupported gateway permissions")
    from .gateway_setup import load, persist, stopped_gateway
    from .gateway import GatewayPolicy
    from .owner import audit
    policy, credentials = load()
    quiesce_for_setup(gateway_only=True)
    item = {"id": binding_id, "connector": connector, "sender": sender, "chat": chat,
            "scope": "", "thread": "", "identity": identity,
            "capabilities": list(capabilities)}
    policy["bindings"] = [b for b in policy["bindings"] if b["id"] != binding_id] + [item]
    GatewayPolicy(policy)
    persist(policy, credentials)
    audit("setup.gateway-pair", {"binding": binding_id, "connector": connector})
    return {"paired": True, "binding": binding_id}


def acknowledge_recovery(username: str):
    """Only the trusted root window after *displaying* all recovery codes."""
    require_root()
    if not recovery_pending():
        raise PermissionError("no pending recovery code display to confirm")
    entry = enrolled_owner(username)
    record = RecoveryCodes()._load()["owners"].get(str(entry.pw_uid), {})
    if len(record.get("hashes", [])) != 10:
        raise PermissionError("ten active codes required at first setup")
    PENDING.unlink()
    from .owner import audit
    audit("setup.recovery-confirmed", {"uid": entry.pw_uid})
    return {"acknowledged": True}


def retry_failed_new_enrollment():
    """Allow a physical operator to retry an interrupted pre-account enrollment.

    Never delete or repurpose any existing user or their home folder.
    """
    require_root()
    if owners():
        raise PermissionError("an enrolled owner requires authenticated recovery")
    if recovery_pending():
        PENDING.unlink()
    if setup_in_progress():
        IN_PROGRESS.unlink()
    return {"may_retry_enrollment": True}


def issue_missing_recovery(username: str):
    """Migrate a pre-existing owner missing recovery without replacing their account."""
    require_root()
    status = account_status()
    if not status["owner"] or status["recovery"] or status["pending"]:
        raise PermissionError("recovery migration is unavailable")
    entry = enrolled_owner(username)
    from .policy import atomic_json
    if not setup_in_progress():
        atomic_json(IN_PROGRESS, {"version": 1, "setup_in_progress": True}, mode=0o600)
    atomic_json(PENDING, {"version": 1, "unconfirmed_recovery": True}, mode=0o600)
    return RecoveryCodes().issue(entry.pw_uid)


def finalize():
    """Never complete if account/recovery safety gates have not passed."""
    require_root()
    state = account_status()
    if not state["complete"]:
        raise PermissionError("initial owner recovery must be acknowledged before first-use")
    from .owner_ready import main as readiness_check
    from .owner import audit
    from .policy import atomic_json
    readiness_check()
    # tty2 may have enrolled the owner without creating IN_PROGRESS. Never
    # finalize such a path without a normal observer display name and profile.
    # mark_ready preserves pre-existing user data and validates its ownership.
    from .normal_profile import mark_ready
    mark_ready()
    if COMPLETE.is_symlink():
        raise PermissionError("untrusted setup completion marker")
    subprocess.run(["/usr/bin/systemctl", "restart", "haos-owner-ready.service"],
                   check=True, timeout=35, capture_output=True)
    # Publish a validated receipt only after all mandatory owner/profile
    # readiness operations succeeded; the gate rejects any partial state.
    atomic_json(COMPLETE, {"version": 1, "completed": True}, mode=0o600)
    audit("setup.graphical-complete", {"owner_confirmed": True})
    if setup_in_progress():
        IN_PROGRESS.unlink()
    return {"completed": True, "reboot_required": True}
