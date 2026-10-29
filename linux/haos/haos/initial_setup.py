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
from .provider_registry import default_endpoint, default_mode, http_providers, oauth_providers, account_providers, account_region
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
            "api_mode": api_mode or default_mode(provider, model, endpoint),
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
        region = {"region": account_region(provider, policy.endpoint)} if provider == "minimax-oauth" else {}
        auth_helper("status", provider, graphical_status=True, **region)
    # Only now does the vetted owner credential publisher replace trusted files.
    add_route(policy.data, api_key or None)
    install(pwd.getpwnam("haos-agent").pw_uid)
    subprocess.run(["/usr/bin/systemctl", "start", "haos-provider.socket"],
                   check=True, timeout=30, capture_output=True)
    audit("setup.provider", {"provider": provider, "models": [model]})
    return {"configured": True, "provider": provider, "model_turn_tested": False}


def provider_models(provider, api_key="", endpoint="", api_mode="", model=""):
    require_root()
    from .provider_setup import catalog_helper
    selected_model = model or "haos-discovery"
    data = {"version": 1, "provider": provider, "endpoint": endpoint or default_endpoint(provider),
            "models": [selected_model], "default_model": selected_model,
            "api_mode": api_mode or default_mode(provider, selected_model, endpoint),
            "requests_per_day": 200, "requests_per_minute": 30}
    return catalog_helper(data, api_key or None)


def import_cloud_credential(provider, filename):
    """Read an explicitly selected private owner JSON file on the setup seat."""
    require_root()
    from .initial_setup_gui import session_allowed
    from .provider_cloud import credential_data
    import stat
    import json
    if not session_allowed() or provider not in CLOUD:
        raise PermissionError("cloud credential import requires the trusted local setup seat")
    descriptor = os.open(filename, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        info = os.fstat(descriptor)
        allowed = {0} | {owner["uid"] for owner in owners()}
        if (not stat.S_ISREG(info.st_mode) or info.st_uid not in allowed or info.st_mode & 0o077
                or info.st_nlink != 1 or not 1 <= info.st_size <= 16384):
            raise PermissionError("select one private regular JSON file owned by the enrolled owner or root")
        value = os.read(descriptor, 16385)
        if len(value) != info.st_size or len(value) > 16384:
            raise ValueError("cloud credential file changed or exceeds its bound")
    finally:
        os.close(descriptor)
    # Imports are data only. The native SDK still runs solely under its private
    # provider identity, after independent endpoint/model policy validation.
    data = json.loads(value)
    if not isinstance(data, dict) or not data:
        raise ValueError("select a cloud credential JSON object")
    return json.dumps(credential_data(provider, json.dumps(data)))


def provider_state():
    require_root()
    from .provider_routes import ProviderRoutes
    from .sandbox import trusted_json
    path = Path("/etc/haos/provider.json")
    if not path.exists() and not path.is_symlink():
        return {"routes": [], "default": None, "fallbacks": {}}
    current = ProviderRoutes(trusted_json(path))
    return {"routes": [{"id": name, "provider": policy.provider, "model": policy.data["default_model"],
                        "models": list(policy.models), "api_mode": policy.api_mode} for name, policy in current.routes.items()],
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


def provider_account(provider, action="login", endpoint=""):
    """Native trusted-seat account flow; OAuth runs in the separate provider UID."""
    require_root()
    from .initial_setup_gui import session_allowed
    if not session_allowed() or provider not in account_providers() or action not in {"login", "logout", "status"}:
        raise PermissionError("provider account login requires the trusted local setup seat")
    region = {}
    if provider == "minimax-oauth":
        selected = endpoint or default_endpoint(provider)
        ProviderPolicy({"version": 1, "provider": provider, "endpoint": selected,
            "models": ["haos-account"], "default_model": "haos-account", "api_mode": default_mode(provider),
            "requests_per_day": 200, "requests_per_minute": 30})
        region = {"region": account_region(provider, selected)}
    if action == "status":
        from .provider_setup import auth_helper
        auth_helper("status", provider, graphical_status=True, **region)
        return {"credential_action_completed": True, "model_turn_tested": False}
    quiesce_for_setup()
    if action == "logout":
        from .provider_setup import revoke_account_routes
        from .network import install
        revoke_account_routes(provider)
        install(pwd.getpwnam("haos-agent").pw_uid)
    subprocess.run(["/usr/bin/xterm", "-T", "HAOS Provider-Anmeldung", "-geometry", "110x32+20+20",
                    "-e", "/usr/bin/python3", "-I", "/usr/lib/haos/provider-login.py", action, provider, *region.values()],
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


def configure_gateway(connector: str, platform: str, token: str, app_token: str = '', server_url: str = '', *,
                      homeserver: str = '', user_id: str = '', device_id: str = '', recovery_key: str = '', topic: str = ''):
    """Graphical root-seat setup for explicitly integrated native adapters."""
    require_root()
    if platform not in {"telegram", "discord", "slack", "mattermost", "matrix", "ntfy", "homeassistant"}:
        raise ValueError("HAOS has not approved this platform for gateway execution")
    if platform not in {'matrix','ntfy','homeassistant'} and (not isinstance(token, str) or not 16 <= len(token) <= 4096
            or any(c.isspace() or ord(c) < 32 for c in token)):
        raise ValueError("invalid protected gateway credential")
    if platform=='slack':
        from .gateway_slack import validate_credentials
        validate_credentials(token,app_token)
    elif app_token:
        raise ValueError('an app token applies only to Slack')
    if platform=='mattermost':
        from .gateway_mattermost import validate_credentials
        server_url=validate_credentials(token,server_url)
    elif platform not in {'ntfy','homeassistant'} and server_url:raise ValueError('a server URL applies only to Mattermost, ntfy or Home Assistant')
    homeassistant=None
    if platform=='homeassistant':
        from .gateway_homeassistant_profile import credentials as ha_credentials
        homeassistant=ha_credentials({'token':token,'server_url':server_url})
    ntfy=None
    if platform=='ntfy':
        from .gateway_ntfy_profile import credentials as ntfy_credentials
        ntfy=ntfy_credentials({'token':token,'server_url':server_url,'topic':topic})
    elif topic:raise ValueError('a topic applies only to ntfy')
    matrix=None
    if platform=='matrix':
        from .gateway_matrix_profile import credentials as matrix_credentials
        matrix=matrix_credentials({'token':token,'homeserver':homeserver,'user_id':user_id,'device_id':device_id,
            **({'recovery_key':recovery_key} if recovery_key else {})})
    elif any((homeserver,user_id,device_id,recovery_key)):
        raise ValueError('Matrix identity fields apply only to Matrix')
    from .gateway_setup import load, persist, stopped_gateway
    from .gateway import GatewayPolicy
    from .owner import audit
    policy, credentials = load()
    quiesce_for_setup(gateway_only=True)
    if any(c["id"] != connector and c["platform"] == platform for c in policy["connectors"]):
        raise ValueError("one isolated adapter per platform is currently supported")
    if any(c['id']==connector and c['platform']!=platform for c in policy['connectors']):
        policy['bindings']=[row for row in policy['bindings'] if row['connector']!=connector]
    policy["connectors"] = [c for c in policy["connectors"] if c["id"] != connector] + [
        {"id": connector, "platform": platform}]
    GatewayPolicy(policy)
    credentials["connectors"][connector] = matrix or ntfy or homeassistant or {"token": token}
    if platform=='slack':credentials['connectors'][connector]['app_token']=app_token
    if platform=='mattermost':credentials['connectors'][connector]['server_url']=server_url
    persist(policy, credentials)
    audit("setup.gateway", {"connector": connector, "platform": platform})
    return {"configured": True, "platform": platform, "restart_required": True, "sender_pairing_required": True}


def import_line_tls_file(filename,kind):
    require_root()
    from .initial_setup_gui import session_allowed
    if not session_allowed():raise PermissionError('LINE PEM import requires the trusted local setup seat')
    return read_line_tls_file(filename,kind)


def read_line_tls_file(filename,kind):
    """Read owner-selected PEM data; never return an arbitrary privileged file."""
    require_root()
    import stat
    if kind not in {'certificate','private_key'}:raise ValueError('select certificate or private_key PEM data')
    limit=16384 if kind=='certificate' else 8192
    descriptor=os.open(filename,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK)
    try:
        info=os.fstat(descriptor)
        allowed={0}|{owner['uid'] for owner in owners()}
        if (not stat.S_ISREG(info.st_mode) or info.st_uid not in allowed or info.st_mode&0o077
                or info.st_nlink!=1 or not 1<=info.st_size<=limit):
            raise PermissionError('select a private single-link PEM file owned by the enrolled owner or root')
        raw=os.read(descriptor,limit+1)
        if len(raw)!=info.st_size or len(raw)>limit:raise ValueError('LINE PEM file changed or exceeds its bound')
    finally:os.close(descriptor)
    try:
        value=raw.decode('ascii')
        from cryptography import x509
        from cryptography.hazmat.primitives import serialization
        if kind=='certificate':x509.load_pem_x509_certificates(raw)
        else:serialization.load_pem_private_key(raw,password=None)
    except Exception:raise ValueError('select a valid unencrypted PEM certificate chain or private key') from None
    return value


def configure_line_gateway(connector,channel_secret,channel_access_token,destination,port,tls):
    """Publish verified LINE HTTPS credentials; no listener or external message here."""
    require_root()
    from .gateway_line_profile import credentials as line_credentials
    value=line_credentials({'channel_secret':channel_secret,'channel_access_token':channel_access_token,
        'destination':destination,'port':port,'tls':tls})
    from .gateway_setup import load,persist
    from .gateway import GatewayPolicy
    from .owner import audit
    policy,private=load()
    if any(row['id']!=connector and row['platform']=='line' for row in policy['connectors']):
        raise ValueError('one isolated adapter per platform is currently supported')
    if any(row['id']==connector and row['platform']!='line' for row in policy['connectors']):
        policy['bindings']=[row for row in policy['bindings'] if row['connector']!=connector]
    policy['connectors']=[row for row in policy['connectors'] if row['id']!=connector]+[{'id':connector,'platform':'line'}]
    GatewayPolicy(policy)
    quiesce_for_setup(gateway_only=True)
    private['connectors'][connector]=value;persist(policy,private)
    audit('setup.gateway',{'connector':connector,'platform':'line'})
    return {'configured':True,'platform':'line','restart_required':True,'sender_pairing_required':True,
        'external_reachability_verified':False}


def configure_email_gateway(connector,account,*,trust_authentication_results=False):
    """Save a dedicated TLS mail account only after receiving-server approval."""
    require_root()
    if trust_authentication_results is not True:
        raise PermissionError('explicit approval of receiving-server Authentication-Results custody required')
    from .gateway_email import credentials,scope
    value=credentials(account)
    from .gateway_setup import load,persist
    from .gateway import GatewayPolicy
    from .owner import audit
    policy,private=load()
    if any(row['id']!=connector and row['platform']=='email' for row in policy['connectors']):
        raise ValueError('one isolated adapter per platform is currently supported')
    if any(row['id']==connector and row['platform']!='email' for row in policy['connectors']):
        policy['bindings']=[row for row in policy['bindings'] if row['connector']!=connector]
    policy['connectors']=[row for row in policy['connectors'] if row['id']!=connector]+[{'id':connector,'platform':'email'}]
    GatewayPolicy(policy)
    quiesce_for_setup(gateway_only=True)
    private['connectors'][connector]=value;persist(policy,private)
    audit('setup.gateway',{'connector':connector,'platform':'email','receiving_authentication_custody_approved':True})
    return {'configured':True,'platform':'email','scope':scope(value),'restart_required':True,
        'sender_pairing_required':True,'authenticated':False,'external_delivery_verified':False}


def configure_sms_gateway(connector,account_sid,auth_token,from_number,port,tls):
    """Publish verified SMS HTTPS credentials; no listener or external message here."""
    require_root()
    from .gateway_sms import credentials as sms_credentials
    value=sms_credentials({'account_sid':account_sid,'auth_token':auth_token,'from_number':from_number,'port':port,'tls':tls})
    from .gateway_setup import load,persist
    from .gateway import GatewayPolicy
    from .owner import audit
    policy,private=load()
    if any(row['id']!=connector and row['platform']=='sms' for row in policy['connectors']):
        raise ValueError('one isolated adapter per platform is currently supported')
    if any(row['id']==connector and row['platform']!='sms' for row in policy['connectors']):
        policy['bindings']=[row for row in policy['bindings'] if row['connector']!=connector]
    policy['connectors']=[row for row in policy['connectors'] if row['id']!=connector]+[{'id':connector,'platform':'sms'}]
    GatewayPolicy(policy)
    quiesce_for_setup(gateway_only=True)
    private['connectors'][connector]=value;persist(policy,private)
    audit('setup.gateway',{'connector':connector,'platform':'sms'})
    return {'configured':True,'platform':'sms','restart_required':True,'sender_pairing_required':True,
        'external_reachability_verified':False}


def configure_irc_gateway(connector,server,port,nickname,channel,*,server_password='',channel_password='',sasl_username='',sasl_password='',anonymous=False):
    """Owner-only real TLS IRC configuration; validate before stopping services."""
    require_root()
    if type(anonymous) is not bool or anonymous and (sasl_username or sasl_password) or not anonymous and not sasl_username:
        raise ValueError('SASL-Konto angeben oder Verbindung ohne SASL ausdrücklich freigeben')
    from .gateway_irc_transport import credentials as validate_irc
    value=validate_irc({'server':server,'port':port,'nickname':nickname,'channel':channel,
        **({'server_password':server_password} if server_password else {}),
        **({'channel_password':channel_password} if channel_password else {}),
        **({'sasl_username':sasl_username,'sasl_password':sasl_password} if sasl_username or sasl_password else {})})
    from .gateway_setup import load,persist
    from .gateway import GatewayPolicy
    from .owner import audit
    policy,credentials=load()
    if any(row['id']!=connector and row['platform']=='irc' for row in policy['connectors']):
        raise ValueError('one isolated adapter per platform is currently supported')
    if any(row['id']==connector and row['platform']!='irc' for row in policy['connectors']):
        policy['bindings']=[row for row in policy['bindings'] if row['connector']!=connector]
    policy['connectors']=[row for row in policy['connectors'] if row['id']!=connector]+[{'id':connector,'platform':'irc'}]
    GatewayPolicy(policy)
    quiesce_for_setup(gateway_only=True)
    credentials['connectors'][connector]=value;persist(policy,credentials)
    audit('setup.gateway',{'connector':connector,'platform':'irc'})
    return {'configured':True,'platform':'irc','restart_required':True,'sender_pairing_required':True}


def pair_gateway_sender(binding_id: str, connector: str, sender: str, chat: str,
                        identity: str, capabilities: tuple[str, ...] = ("create", "read"), *, scope: str = "", thread: str = "",
                        matrix_devices=None, allow_plaintext=False, require_mention=True, trust_topic_publishers=False, ntfy_server_url="",
                        homeassistant_shared_notifications=False,homeassistant_server_url="",homeassistant_trust_system=False,irc_server="",irc_port=None,irc_channel="",allow_media=False,allow_voice=False,allow_video=False,allow_outbound_media=False):
    """Grant one exact sender/chat/scope/thread with explicitly selected rights."""
    require_root()
    if not capabilities or not set(capabilities) <= {"create", "read", "cancel", "answer", "pause", "resume"}:
        raise ValueError("unsupported gateway permissions")
    from .gateway_setup import load, persist, stopped_gateway
    from .gateway import GatewayPolicy
    from .owner import audit
    policy, credentials = load()
    item = {"id": binding_id, "connector": connector, "sender": sender, "chat": chat,
            "scope": scope, "thread": thread, "identity": identity,
            "capabilities": list(capabilities)}
    selected=next((row for row in policy['connectors'] if row['id']==connector),None)
    if selected and selected['platform'] in {'line','sms'}:
        saved=credentials['connectors'][connector]
        destination=saved['destination'] if selected['platform']=='line' else saved['account_sid']+':'+saved['from_number']
        if scope and scope!=destination:raise ValueError('Gateway scope must match the saved receiving identity')
        if sender==destination:raise ValueError('Gateway sender must differ from its receiving identity')
        item['scope']=destination
        if type(allow_media) is not bool:raise ValueError('explicit boolean gateway media approval required')
        if type(allow_voice) is not bool:raise ValueError('explicit boolean gateway voice approval required')
        if type(allow_video) is not bool or type(allow_outbound_media) is not bool:raise ValueError('explicit boolean gateway video/output approval required')
        item['allow_media']=allow_media;item['allow_voice']=allow_voice
        item['allow_video']=allow_video;item['allow_outbound_media']=allow_outbound_media
        if allow_outbound_media and 'tls' not in credentials['connectors'][connector]:
            raise ValueError('configure public HTTPS/TLS before approving gateway output files')
        if allow_voice:
            if 'create' not in item['capabilities']:raise ValueError('Gateway voice approval requires mission-create rights')
            from .speech_setup import status as speech_status
            speech=speech_status()
            if not all(speech[key] for key in ['enabled','runtime_ready','model_ready']):
                raise PermissionError('configure the reviewed local speech model/service before approving gateway voice')
    elif allow_media or allow_voice or allow_video or allow_outbound_media:raise ValueError('media approval applies only to reviewed LINE/SMS paths')
    if selected and selected['platform']=='matrix':
        item.update(matrix_devices=matrix_devices if matrix_devices is not None else [],allow_plaintext=allow_plaintext,require_mention=require_mention)
    elif matrix_devices not in (None,[]) or allow_plaintext or require_mention is not True:
        raise ValueError('Matrix device and encryption options apply only to Matrix')
    if selected and selected['platform']=='ntfy':
        configured=credentials['connectors'][connector]
        if chat!=configured['topic']:
            raise ValueError('ntfy-Topic stimmt nicht mit dem gespeicherten Konnektor überein; Konfiguration zuerst speichern')
        if ntfy_server_url:
            from .gateway_ntfy_profile import credentials as ntfy_credentials
            requested=ntfy_credentials({'token':configured['token'],'server_url':ntfy_server_url,'topic':chat})
            if requested['server_url']!=configured['server_url']:
                raise ValueError('ntfy-Server stimmt nicht mit dem gespeicherten Konnektor überein; Konfiguration zuerst speichern')
        item['trust_topic_publishers']=trust_topic_publishers
    elif trust_topic_publishers or ntfy_server_url:
        raise ValueError('topic publisher trust applies only to ntfy')
    if selected and selected['platform']=='irc':
        configured=credentials['connectors'][connector]
        expected=f"{configured['server']}:{configured['port']}"
        if irc_port is not None and type(irc_port) is not int:raise ValueError('exact integer IRC port required')
        if (irc_server and irc_server!=configured['server'] or irc_port is not None and irc_port!=configured['port']
                or irc_channel and irc_channel!=configured['channel']):
            raise ValueError('IRC-Einstellungen zuerst speichern; Kopplung gehört zum gespeicherten Server und Kanal')
        if scope and scope!=expected or chat!=configured['channel']:
            raise ValueError('IRC-Server und Kanal müssen der gespeicherten Konfiguration entsprechen')
        item['scope']=expected
    elif irc_server or irc_port is not None or irc_channel:
        raise ValueError('IRC connection context applies only to IRC')
    if selected and selected['platform']=='homeassistant':
        if type(homeassistant_shared_notifications) is not bool:
            raise ValueError('explicit boolean approval of shared Home Assistant notifications required')
        if 'read' in capabilities and not homeassistant_shared_notifications:
            raise ValueError('Home Assistant-Antworten sind für alle Instanzbenutzer sichtbar; diese Freigabe ausdrücklich bestätigen')
        configured=credentials['connectors'][connector]
        if homeassistant_server_url:
            from .gateway_homeassistant_profile import credentials as ha_credentials
            if ha_credentials({'token':configured['token'],'server_url':homeassistant_server_url})['server_url']!=configured['server_url']:
                raise ValueError('Home Assistant-Server stimmt nicht mit gespeichertem Konnektor überein; Konfiguration zuerst speichern')
        item['homeassistant_shared_notifications']=homeassistant_shared_notifications
        item['homeassistant_trust_system']=homeassistant_trust_system
    elif homeassistant_shared_notifications or homeassistant_server_url or homeassistant_trust_system:
        raise ValueError('Home Assistant notification consent applies only to Home Assistant')
    policy["bindings"] = [b for b in policy["bindings"] if b["id"] != binding_id] + [item]
    GatewayPolicy(policy)
    quiesce_for_setup(gateway_only=True)
    persist(policy, credentials)
    audit("setup.gateway-pair", {"binding": binding_id, "connector": connector})
    return {"paired": True, "binding": binding_id}


def gateway_configuration():
    """Return pairing metadata to the trusted owner window, never credentials."""
    require_root()
    from .gateway_setup import load
    policy, _credentials = load()
    result={"connectors": policy["connectors"], "bindings": policy["bindings"]}
    topics={row['id']:{key:_credentials['connectors'][row['id']][key] for key in ('server_url','topic')}
        for row in policy['connectors'] if row['platform']=='ntfy'}
    if topics:result['ntfy']=topics
    servers={row['id']:{'server_url':_credentials['connectors'][row['id']]['server_url']}
        for row in policy['connectors'] if row['platform']=='homeassistant'}
    if servers:result['homeassistant']=servers
    irc={row['id']:{key:_credentials['connectors'][row['id']][key] for key in ('server','port','nickname','channel')}
        for row in policy['connectors'] if row['platform']=='irc'}
    if irc:result['irc']=irc
    line={row['id']:{key:_credentials['connectors'][row['id']][key] for key in ('destination','port')}
        |{'public_url':_credentials['connectors'][row['id']]['tls']['public_url'],
          'bind_host':_credentials['connectors'][row['id']]['tls']['bind_host']}
        for row in policy['connectors'] if row['platform']=='line'}
    if line:result['line']=line
    sms={row['id']:{key:_credentials['connectors'][row['id']][key] for key in ('account_sid','from_number','port')}
        |{'public_url':_credentials['connectors'][row['id']]['tls']['public_url'],
          'bind_host':_credentials['connectors'][row['id']]['tls']['bind_host']}
        for row in policy['connectors'] if row['platform']=='sms'}
    if sms:result['sms']=sms
    return result


def matrix_gateway_devices(connector,sender):
    require_root()
    from .gateway_matrix_policy import opaque
    if not opaque(sender,'@') or ':' not in sender:raise ValueError('exaktes Matrix-Absenderkonto erforderlich')
    quiesce_for_setup(gateway_only=True)
    from .gateway_setup import owner_matrix_devices
    return owner_matrix_devices(connector,sender)


def manage_gateway(action: str, identifier: str = ""):
    require_root()
    if action not in {"start", "stop", "revoke", "remove", "recover-configuration"}:
        raise ValueError("unsupported graphical gateway action")
    from types import SimpleNamespace
    from .gateway_setup import owner_gateway
    if action in {"start", "stop", "recover-configuration"}:
        if identifier:
            raise ValueError("service actions do not select a gateway identity")
        if action == "recover-configuration":
            quiesce_for_setup(gateway_only=True)
        return owner_gateway(SimpleNamespace(gateway_action=action))
    configured = gateway_configuration()
    rows = configured["bindings"] if action == "revoke" else configured["connectors"]
    if not isinstance(identifier, str) or not any(row["id"] == identifier for row in rows):
        raise ValueError("unknown gateway selection")
    quiesce_for_setup(gateway_only=True)
    return owner_gateway(SimpleNamespace(gateway_action=action, binding=identifier if action == "revoke" else None,
        connector=identifier if action == "remove" else None))


def retry_ntfy_gateway_auth(connector):
    require_root()
    configured=gateway_configuration()
    if not isinstance(connector,str) or not any(row['id']==connector and row['platform']=='ntfy' for row in configured['connectors']):
        raise ValueError('select an existing ntfy connector before retrying authentication')
    from types import SimpleNamespace
    from .gateway_setup import owner_gateway
    quiesce_for_setup(gateway_only=True)
    return owner_gateway(SimpleNamespace(gateway_action='retry-ntfy-auth',connector=connector,
        note='Owner requested a new ntfy authentication check'))


def retry_irc_gateway_auth(connector):
    require_root()
    configured=gateway_configuration()
    if not isinstance(connector,str) or not any(row['id']==connector and row['platform']=='irc' for row in configured['connectors']):
        raise ValueError('select one configured IRC connector')
    from .gateway_setup import owner_gateway
    from types import SimpleNamespace
    quiesce_for_setup(gateway_only=True)
    return owner_gateway(SimpleNamespace(gateway_action='retry-irc-auth',connector=connector,
        note='Owner requested a new IRC authentication check'))


def retry_line_gateway_auth(connector):
    require_root()
    configured=gateway_configuration()
    if not isinstance(connector,str) or not any(row['id']==connector and row['platform']=='line' for row in configured['connectors']):
        raise ValueError('select one configured LINE connector')
    from .gateway_setup import owner_gateway
    from types import SimpleNamespace
    quiesce_for_setup(gateway_only=True)
    return owner_gateway(SimpleNamespace(gateway_action='retry-line-auth',connector=connector,
        note='Owner requested a new LINE authentication check'))


def retry_sms_gateway_auth(connector):
    require_root()
    configured=gateway_configuration()
    if not isinstance(connector,str) or not any(row['id']==connector and row['platform']=='sms' for row in configured['connectors']):
        raise ValueError('select one configured SMS connector')
    from .gateway_setup import owner_gateway
    from types import SimpleNamespace
    quiesce_for_setup(gateway_only=True)
    return owner_gateway(SimpleNamespace(gateway_action='retry-sms-auth',connector=connector,
        note='Owner requested a new SMS authentication check'))


def inspect_email_gateway_account(connector):
    require_root()
    from .gateway_setup import owner_email_account
    quiesce_for_setup(gateway_only=True)
    return owner_email_account(connector)


def retry_email_gateway_auth(connector):
    require_root()
    configured=gateway_configuration()
    if not isinstance(connector,str) or not any(row['id']==connector and row['platform']=='email' for row in configured['connectors']):
        raise ValueError('select one configured email connector')
    from .gateway_setup import owner_gateway
    from types import SimpleNamespace
    quiesce_for_setup(gateway_only=True)
    return owner_gateway(SimpleNamespace(gateway_action='retry-email-auth',connector=connector,
        note='Owner requested a new email authentication check'))


def email_gateway_sources(profile=None):
    require_root()
    import re
    if profile is not None and (not isinstance(profile,str) or not re.fullmatch('email-[0-9a-f]{64}',profile)):
        raise ValueError('select an exact opaque email profile, not a path')
    from .gateway_setup import owner_gateway
    from types import SimpleNamespace
    quiesce_for_setup(gateway_only=True)
    return owner_gateway(SimpleNamespace(gateway_action='email-sources',profile=profile))


def recover_email_gateway(row,action,note,confirmed=False,*,profile=None,confirmed_not_delivered=False):
    """Carry an inspected snapshot to the offline helper; never infer consent."""
    require_root()
    import re
    if (not isinstance(row,dict) or action not in {'recover-email-mailbox','purge-email-source','approve-email-retry'}
            or confirmed is not True or not isinstance(note,str) or not 1<=len(note.strip())<=2000
            or not isinstance(row.get('snapshot_sha256'),str) or not re.fullmatch('[0-9a-f]{64}',row['snapshot_sha256'])):
        raise ValueError('select an inspected email snapshot and explicitly confirm a bounded non-secret decision')
    values={'gateway_action':action,'snapshot_sha256':row['snapshot_sha256'],'note':note,'confirm_inspected':True}
    if action=='recover-email-mailbox':
        if (not isinstance(row.get('identity'),str) or not re.fullmatch('[0-9a-f]{64}',row['identity'])
                or row.get('active') is not True or row.get('status') not in {'uid-validity-changed','uid-next-regressed'}):
            raise ValueError('select the active fenced mailbox scan')
        values['identity']=row['identity']
    elif action=='purge-email-source':
        if (not isinstance(profile,str) or not re.fullmatch('email-[0-9a-f]{64}',profile)
                or not isinstance(row.get('id'),str) or not re.fullmatch('[0-9a-f]{64}',row['id'])
                or row.get('purge_allowed') is not True):raise ValueError('select an inspected terminal email source')
        values.update(profile=profile,id=row['id'])
    else:
        if (confirmed_not_delivered is not True or row.get('state') not in {'writing','uncertain','rejected'}
                or type(row.get('attempt')) is not int or not 1<=row['attempt']<5
                or not isinstance(row.get('delivery_id'),str) or not re.fullmatch('[0-9a-f]{64}',row['delivery_id'])
                or not isinstance(row.get('connector'),str) or not re.fullmatch('[a-zA-Z0-9][a-zA-Z0-9_.:-]{0,127}',row['connector'])):
            raise ValueError('select an unconfirmed SMTP attempt and independently confirm non-delivery')
        values.update(connector=row['connector'],delivery_id=row['delivery_id'],attempt=row['attempt'],confirm_not_delivered=True)
    from .gateway_setup import owner_gateway
    from types import SimpleNamespace
    quiesce_for_setup(gateway_only=True)
    return owner_gateway(SimpleNamespace(**values))


def retry_homeassistant_gateway_auth(connector):
    require_root()
    configured=gateway_configuration()
    if not isinstance(connector,str) or not any(row['id']==connector and row['platform']=='homeassistant' for row in configured['connectors']):
        raise ValueError('select an existing Home Assistant connector before retrying authentication')
    from types import SimpleNamespace
    from .gateway_setup import owner_gateway
    quiesce_for_setup(gateway_only=True)
    return owner_gateway(SimpleNamespace(gateway_action='retry-homeassistant-auth',connector=connector,
        note='Owner requested a new Home Assistant authentication check'))


def gateway_ingress(after=0):
    require_root()
    if type(after) is not int or after < 0:
        raise ValueError('invalid ingress cursor')
    from types import SimpleNamespace
    from .gateway_setup import owner_gateway
    quiesce_for_setup(gateway_only=True)
    return owner_gateway(SimpleNamespace(gateway_action='ingress',after=after))


def reconcile_gateway_ingress(row, decision, note):
    require_root()
    import re
    if (not isinstance(row,dict) or not isinstance(row.get('ingress_id'),str)
            or not re.fullmatch('[0-9a-f]{64}',row['ingress_id'])
            or type(row.get('attempt')) is not int or not 0 <= row['attempt'] <= 8
            or row.get('state') not in {'pending','processing','failed','expired','revoked'}
            or decision not in {'retry','discard'} or not isinstance(note,str) or not 1 <= len(note.strip()) <= 2000):
        raise ValueError('select an unresolved ingress and provide bounded non-secret inspection evidence')
    if decision == 'retry' and row['state'] != 'failed':
        raise ValueError('only failed native decoding may be retried')
    from types import SimpleNamespace
    from .gateway_setup import owner_gateway
    quiesce_for_setup(gateway_only=True)
    return owner_gateway(SimpleNamespace(gateway_action='reconcile-ingress',ingress_id=row['ingress_id'],
        attempt=row['attempt'],state=row['state'],decision=decision,note=note))


def gateway_process_status():
    require_root()
    result = subprocess.run(["/usr/bin/systemctl", "show", "--property=LoadState,ActiveState,SubState,Result,ExecMainStatus",
        "haos-gateway.service"], check=True, capture_output=True, text=True, timeout=15)
    allowed = {"LoadState", "ActiveState", "SubState", "Result", "ExecMainStatus"}
    if len(result.stdout) > 4096:
        raise ValueError("invalid gateway service status")
    values = dict(line.split("=", 1) for line in result.stdout.splitlines() if "=" in line)
    if set(values) != allowed or any(not value or len(value) > 128 or any(ord(c) < 32 or ord(c) > 126 for c in value) for value in values.values()):
        raise ValueError("invalid gateway service status")
    return values


def gateway_deliveries(after=0):
    require_root()
    if type(after) is not int or after<0:raise ValueError('invalid delivery cursor')
    from types import SimpleNamespace
    from .gateway_setup import owner_gateway
    quiesce_for_setup()
    return owner_gateway(SimpleNamespace(gateway_action='deliveries',after=after))


def reconcile_gateway_delivery(row,decision,note,receipt=None,confirmed_not_delivered=False):
    require_root()
    import re
    if (not isinstance(row,dict) or not isinstance(row.get('delivery_id'),str)
            or not re.fullmatch('[0-9a-f]{64}',row['delivery_id'])
            or type(row.get('attempt')) is not int or not 1<=row['attempt']<=5
            or row.get('state') not in {'sending','uncertain','failed'}
            or decision not in {'delivered','retry','discard'} or not isinstance(note,str)
            or not 1<=len(note.strip())<=2000 or type(confirmed_not_delivered) is not bool):
        raise ValueError('select an unresolved delivery and provide bounded non-secret inspection evidence')
    if decision=='delivered':
        if not isinstance(receipt,str) or not 1<=len(receipt)<=64 or any(ord(c)<33 or ord(c)>126 for c in receipt):
            raise ValueError('record the inspected platform message identity')
    elif receipt is not None and receipt!='':raise ValueError('only confirmed delivery accepts a receipt')
    if decision=='retry' and not confirmed_not_delivered:
        raise PermissionError('retry requires explicit evidence that the previous attempt was not delivered')
    if decision!='retry' and confirmed_not_delivered:raise ValueError('non-delivery confirmation applies only to retry')
    from types import SimpleNamespace
    from .gateway_setup import owner_gateway
    quiesce_for_setup()
    return owner_gateway(SimpleNamespace(gateway_action='reconcile-delivery',delivery_id=row['delivery_id'],attempt=row['attempt'],
        decision=decision,note=note,receipt=receipt if decision=='delivered' else None,
        confirm_not_delivered=confirmed_not_delivered))


def resume_runtime():
    require_root()
    if not account_status()['complete'] or not normal_user_ready() or setup_in_progress():
        raise PermissionError('complete administrator, recovery and normal-user setup before starting mission services')
    from .owner import runtime_action
    runtime_action('start')
    return {'started':True}


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


def gateway_media_inventory():
    require_root()
    quiesce_for_setup()
    from .owner import manage_media
    return manage_media('list')


def purge_gateway_media(identity,note,confirmed=False):
    require_root()
    import re
    if (not isinstance(identity,str) or not re.fullmatch('[0-9a-f]{64}',identity)
            or not isinstance(note,str) or not 1<=len(note.strip())<=2000 or confirmed is not True):
        raise PermissionError('select one exact upload and explicitly confirm inspection with a bounded note')
    quiesce_for_setup()
    from .owner import manage_media
    return manage_media('purge',[identity],note,confirmed=True)


def gateway_media_cache_inventory():
    require_root()
    from types import SimpleNamespace
    from .gateway_setup import owner_gateway
    quiesce_for_setup(gateway_only=True)
    return owner_gateway(SimpleNamespace(gateway_action='media-cache'))


def purge_gateway_media_cache(identity,note,confirmed=False):
    require_root()
    import re
    if (not isinstance(identity,str) or not re.fullmatch('[0-9a-f]{64}',identity)
            or not isinstance(note,str) or not 1<=len(note.strip())<=2000 or confirmed is not True):
        raise PermissionError('select one exact retained cache item and explicitly confirm inspection')
    from types import SimpleNamespace
    from .gateway_setup import owner_gateway
    quiesce_for_setup(gateway_only=True)
    return owner_gateway(SimpleNamespace(gateway_action='purge-media-cache',id=identity,note=note,confirm_inspected=True))


def gateway_speech_status():
    require_root()
    from .speech_setup import status
    return status()


def configure_gateway_speech(enabled):
    require_root()
    if type(enabled) is not bool:raise ValueError('explicit local speech service choice required')
    from .speech_setup import enable,disable
    return enable() if enabled else disable()
