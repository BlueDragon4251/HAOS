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

# Never store a plaintext password, recovery code, provider key or GHCR token
# in setup state, IPC, temporary files, shell argv, or the audit log.
RUNNING = ("haos-gateway.service", "haos-controller.service", "haos-hermes.service")
PENDING = Path("/var/lib/haos-owner/setup-recovery-pending.json")
COMPLETE = Path("/var/lib/haos-owner/graphical-setup.json")


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
    if recovery_pending():
        raise PermissionError("a prior recovery setup must be resolved first")
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
    mark_pending()  # Durable before password creation/recovery issuance. A crash can be resumed.\n    created = enroll(username, password, initial_only=True)
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
    return owner_region(SimpleNamespace(region_action="apply", language=language, keyboard=keyboard))


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


def configure_provider(provider: str, model: str, api_key: str = "", endpoint: str = ""):
    """Cloud API or local model; OAuth flow is not yet supported in this GUI."""
    require_root()
    if provider not in {"openai", "openrouter", "local"}:
        raise ValueError("use a provider with an implemented graphical credential flow")
    from .provider_setup import publish, stopped_provider
    from .gateway_setup import stopped_gateway
    from .network import install
    from .owner import stopped, audit
    data = {"version": 1, "provider": provider,
            "endpoint": endpoint if provider == "local" else ENDPOINTS[provider],
            "models": [model], "default_model": model,
            "api_mode": "chat_completions" if provider in {"openrouter", "local"} else "codex_responses",
            "requests_per_day": 200, "requests_per_minute": 30}
    policy = ProviderPolicy(data)
    if provider == "local" and api_key:
        raise ValueError("a local endpoint does not use a cloud credential")
    if provider != "local" and not api_key:
        raise ValueError("cloud API key required")
    stopped()
    stopped_gateway()
    stopped_provider()
    # Only now does the vetted owner credential publisher replace trusted files.
    publish(policy.data, api_key if provider != "local" else None)
    install(pwd.getpwnam("haos-agent").pw_uid)
    subprocess.run(["/usr/bin/systemctl", "start", "haos-provider.socket"],
                   check=True, timeout=30, capture_output=True)
    audit("setup.provider", {"provider": provider, "models": [model]})
    return {"configured": True, "provider": provider, "model_turn_tested": False}


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
    stopped_gateway()
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
    stopped_gateway()
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
    # Root-only evidence marker, never a plaintext secret or model-created flag.
    if COMPLETE.is_symlink():
        raise PermissionError("untrusted setup completion marker")
    atomic_json(COMPLETE, {"version": 1, "completed": True}, mode=0o600)
    subprocess.run(["/usr/bin/systemctl", "restart", "haos-owner-ready.service"],
                   check=True, timeout=35, capture_output=True)
    audit("setup.graphical-complete", {"owner_confirmed": True})
    return {"completed": True, "reboot_required": True}
