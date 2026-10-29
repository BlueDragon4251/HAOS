"""Recovery and policy authority; callable by an authenticated owner via sudo/console."""

from __future__ import annotations

import argparse
import json
import os
import stat
import subprocess
import time
from pathlib import Path

from .policy import atomic_json, cleanup, inventory, prepare, resolve_volume, validate_policy
from .sandbox import trusted_json
from .store import MissionStore


def stopped():
    for unit in ("haos-controller.service", "haos-hermes.service"):
        result = subprocess.run(["/usr/bin/systemctl", "show", "--property=LoadState,ActiveState,MainPID,ControlPID", unit],
                                check=True, capture_output=True, text=True)
        state = dict(line.split("=", 1) for line in result.stdout.splitlines() if "=" in line)
        # is-active's exit 3 also covers activating/deactivating units: neither is stopped.
        if (state.get("LoadState") not in {"loaded", "masked"} or state.get("ActiveState") != "inactive"
                or state.get("MainPID") != "0" or state.get("ControlPID") != "0"):
            raise PermissionError(f"stop {unit} before modifying authority or reconciling a mission")


def audit(kind: str, details: dict):
    path = Path("/var/lib/haos-owner")
    path.mkdir(mode=0o700, exist_ok=True)
    fd = os.open(path / "audit.jsonl", os.O_WRONLY | os.O_APPEND | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    try:
        os.write(fd, (json.dumps({"at": time.time(), "kind": kind, "owner_uid": os.environ.get("SUDO_UID", "0"), **details}) + "\n").encode())
        os.fsync(fd)
    finally:
        os.close(fd)


def runtime_action(verb):
    """Fixed owner action shared by console and trusted local management UI."""
    if os.geteuid()!=0:raise PermissionError('runtime management requires authenticated owner authority')
    if verb not in {'stop','start'}:raise ValueError('invalid owner runtime action')
    units=['haos-controller.service','haos-hermes.service','haos-policy.service']
    if verb=='stop':subprocess.run(['/usr/bin/systemctl','stop','haos-gateway.service'],check=True,timeout=60)
    if verb=='start' and Path('/etc/haos/provider.json').exists():
        subprocess.run(['/usr/bin/systemctl','start','haos-provider.socket'],check=True,timeout=60)
    subprocess.run(['/usr/bin/systemctl',verb,*units],check=True,timeout=60)
    if verb=='stop':
        subprocess.run(['/usr/bin/systemctl','stop','haos-provider.socket','haos-provider.service'],check=True,timeout=60)
    else:subprocess.run(['/usr/bin/systemctl','start','haos-gateway.service'],check=True,timeout=60)
    audit('runtime.'+verb,{})


def _kernel_virtual_terminal(device: str) -> bool:
    """Only actual Linux kernel VTs, never pseudo-terminals, symlinks or serial TTYs."""
    if not isinstance(device, str) or not device.startswith("/dev/tty"):
        return False
    number = device[8:]
    if not number.isdecimal() or not 1 <= int(number) <= 63:
        return False
    try:
        info = os.stat(device, follow_symlinks=False)
    except (OSError, ValueError):
        return False
    return (stat.S_ISCHR(info.st_mode) and os.major(info.st_rdev) == 4
            and os.minor(info.st_rdev) == int(number))


def require_physical_setup_console() -> None:
    """Validate the invoking owner VT even when sudo use_pty changes our stdin.

    Fedora sudo commonly runs the privileged command on a fresh /dev/pts/N.
    SUDO_TTY is populated by sudo from the *invoking* terminal, not stdin
    of the child. Its user/UID must still match an enrolled owner, and its
    device must be a kernel VT. Refuse SSH and all unverified origins.
    """
    from .owner_recovery import enrolled_owner, require_console
    require_console()
    if any(os.environ.get(key) for key in ("SSH_CONNECTION", "SSH_CLIENT", "SSH_TTY")):
        raise PermissionError("initial setup requires a local physical console")
    try:
        stdin_device = os.ttyname(0)
    except OSError:
        stdin_device = ""
    if _kernel_virtual_terminal(stdin_device):
        return

    sudo_device = os.environ.get("SUDO_TTY", "")
    sudo_user = os.environ.get("SUDO_USER", "")
    sudo_uid = os.environ.get("SUDO_UID", "")
    if (not _kernel_virtual_terminal(sudo_device) or not sudo_user
            or not sudo_uid.isdecimal()):
        raise PermissionError("initial setup requires a local Linux virtual terminal")
    # Never trust an unbound SUDO_TTY in isolation: this CLI is executable only
    # through the enrolled owner's authenticated fixed-action sudo rule.
    try:
        owner = enrolled_owner(sudo_user)
    except (KeyError, ValueError, PermissionError) as exc:
        raise PermissionError("initial setup requires an authenticated local owner") from exc
    if owner.pw_uid != int(sudo_uid):
        raise PermissionError("initial setup requires an authenticated local owner")


def manage_media(action,ids=None,note='',*,confirmed=False):
    """Fixed local-root operation shared by CLI and physical owner GUI."""
    if os.geteuid()!=0:raise PermissionError('authenticate as the owner with sudo or a recovery console')
    if action not in {'list','purge'}:raise ValueError('unknown owner media action')
    stopped()
    from types import SimpleNamespace
    from .gateway_setup import owner_delivery
    return owner_delivery(SimpleNamespace(gateway_action='media-list' if action=='list' else 'purge-media',
        ids=ids,note=note,confirmed=confirmed),{'version':1,'connectors':[],'bindings':[]})


def main():
    parser = argparse.ArgumentParser(description="HAOS owner recovery; agent and UI policy cannot grant root authority")
    sub = parser.add_subparsers(dest="action", required=True)
    sub.add_parser("prepare")
    sub.add_parser("cleanup")
    sub.add_parser("status")
    sub.add_parser("stop")
    sub.add_parser("start")
    speech=sub.add_parser('speech',help='manage fixed isolated local speech, independent of gateway sender approval')
    speech_actions=speech.add_subparsers(dest='speech_action',required=True)
    for action in ['status','enable','disable']:speech_actions.add_parser(action)
    onboard = sub.add_parser("setup",
        help="local owner fallback for completing setup if the graphical VT8 fails")
    onboard_actions = onboard.add_subparsers(dest="setup_action", required=True)
    onboard_actions.add_parser("status")
    onboard_name = onboard_actions.add_parser("name",
        help="configure the bounded observer display name, not a Unix username")
    onboard_name.add_argument("display_name")
    onboard_actions.add_parser("finish",
        help="complete setup only after owner, recovery and normal profile are ready")
    remote=sub.add_parser('remote',help='owner-paired TLS observation; disabled until explicitly started')
    remote_sub=remote.add_subparsers(dest='remote_action',required=True)
    for action in ('start','stop','status'):remote_sub.add_parser(action)
    configure_remote=remote_sub.add_parser('configure')
    configure_remote.add_argument('--server-cert',required=True)
    configure_remote.add_argument('--server-key',required=True)
    configure_remote.add_argument('--client-ca',required=True)
    configure_remote.add_argument('--bind',default='127.0.0.1')
    configure_remote.add_argument('--port',type=int,default=8443)
    configure_remote.add_argument('--requests-per-minute',type=int,default=60)
    configure_remote.add_argument('--bytes-per-minute',type=int,default=16*1024*1024)
    pair_remote=remote_sub.add_parser('pair')
    pair_remote.add_argument('id');pair_remote.add_argument('certificate')
    pair_remote.add_argument('--mission',action='append',required=True)
    pair_remote.add_argument('--hours',type=int,default=1)
    pair_remote.add_argument('--share-content',action='store_true')
    pair_remote.add_argument('--share-screenshots',action='store_true')
    renew_remote=remote_sub.add_parser('renew',
        help='owner-only reauthorization of an existing fingerprint; grant at most 24h')
    renew_remote.add_argument('id')
    renew_remote.add_argument('--hours',type=int,default=12)
    remote_sub.add_parser('revoke').add_argument('id')
    bootstrap_remote=remote_sub.add_parser('bootstrap',
        help='one-time local CA/server/device certificate generation on authenticated owner console')
    bootstrap_remote.add_argument('--hostname',required=True,
        help='exact server DNS name or literal IP included in TLS SAN')
    bootstrap_remote.add_argument('--bind',default='127.0.0.1',
        help='IP address on which to listen; stays local until explicitly configured')
    bootstrap_remote.add_argument('--port',type=int,default=8443)
    bootstrap_remote.add_argument('--device-id',required=True)
    bootstrap_remote.add_argument('--mission',action='append',required=True)
    bootstrap_remote.add_argument('--hours',type=int,default=1)
    bootstrap_remote.add_argument('--share-content',action='store_true')
    bootstrap_remote.add_argument('--share-screenshots',action='store_true')

    applications = sub.add_parser("application", help="owner-approved exact host executable identities; no direct execution")
    applications_sub = applications.add_subparsers(dest="application_action", required=True)
    applications_sub.add_parser("status")
    register = applications_sub.add_parser("register")
    register.add_argument("id")
    register.add_argument("executable")
    register.add_argument("--class", dest="application_class", choices=["browser", "editor", "terminal", "utility"], required=True)
    register.add_argument("--arg", action="append", default=[])
    register.add_argument("--memory-mib", type=int, default=512)
    register.add_argument("--runtime-seconds", type=int, default=300)
    applications_sub.add_parser("revoke").add_argument("id")
    gateway = sub.add_parser("gateway", help="owner-authenticated transport credentials and exact sender pairing")
    gateway_sub = gateway.add_subparsers(dest="gateway_action", required=True)
    for action in ("status", "start", "stop", "recover-configuration"):
        gateway_sub.add_parser(action)
    setup = gateway_sub.add_parser("setup")
    setup.add_argument("connector")
    setup.add_argument("platform", choices=["telegram", "discord", "slack", "mattermost", "matrix", "ntfy", "homeassistant", "irc", "line", "sms", "email"])
    email_account=gateway_sub.add_parser('email-account',help='authenticate configured IMAP/SMTP without sending or granting access')
    email_account.add_argument('connector')
    matrix_devices=gateway_sub.add_parser('matrix-devices',help='inspect signed public device keys without granting access')
    matrix_devices.add_argument('connector');matrix_devices.add_argument('sender')
    pair = gateway_sub.add_parser("pair")
    pair.add_argument("binding")
    pair.add_argument("connector")
    pair.add_argument("sender")
    pair.add_argument("chat")
    pair.add_argument("--identity", required=True)
    pair.add_argument("--scope", default="")
    pair.add_argument("--thread", default="")
    pair.add_argument('--matrix-device',nargs=3,action='append',default=[],metavar=('DEVICE_ID','ED25519','CURVE25519'))
    pair.add_argument('--trust-topic-publishers',action='store_true',help='explicit ntfy approval of all publishers to the exact private topic')
    pair.add_argument('--homeassistant-shared-notifications',action='store_true',help='approve mission replies visible to every Home Assistant instance user')
    pair.add_argument('--homeassistant-trust-system',action='store_true',help='explicitly trust system/automation events for the exact Home Assistant entity; sender must be system')
    pair.add_argument('--allow-plaintext',action='store_true',help='explicit Matrix plaintext approval')
    pair.add_argument('--allow-media',action='store_true',help='explicit LINE/SMS incoming PNG/JPEG/document approval; requires create, not voice or outbound media')
    pair.add_argument('--allow-video',action='store_true',help='separate LINE/SMS incoming video approval; requires create; no video analysis guarantee')
    pair.add_argument('--allow-outbound-media',action='store_true',help='separate LINE/SMS generated output file export approval; requires read')
    pair.add_argument('--allow-voice',action='store_true',help='explicit LINE/SMS incoming audio-to-text approval; requires create and configured isolated local speech')
    pair.add_argument('--no-require-mention',action='store_true',help='explicit Matrix mention exemption')
    pair.add_argument("--capabilities", nargs="+", choices=["create", "read", "cancel", "answer", "pause", "resume"], default=["create", "read", "cancel", "answer"])
    revoke = gateway_sub.add_parser("revoke")
    revoke.add_argument("binding")
    remove = gateway_sub.add_parser("remove")
    remove.add_argument("connector")
    gateway_sub.add_parser('media-cache',help='inspect retained private gateway media with gateway stopped')
    cache_purge=gateway_sub.add_parser('purge-media-cache',help='purge one inspected retained cache after sender grant withdrawal')
    cache_purge.add_argument('--id',required=True)
    cache_purge.add_argument('--note',required=True)
    cache_purge.add_argument('--confirm-inspected',action='store_true')
    deliveries = gateway_sub.add_parser("deliveries", help="list unresolved outbox metadata with all runtime services stopped")
    deliveries.add_argument("--after", type=int, default=0)
    retry_ntfy=gateway_sub.add_parser('retry-ntfy-auth',help='allow renewed authentication after server/account correction; never sends')
    retry_ntfy.add_argument('connector')
    retry_ntfy.add_argument('--note',default='Owner requested a new ntfy authentication check',help='non-secret action context; only its digest is retained')
    retry_irc=gateway_sub.add_parser('retry-irc-auth',help='permit fresh native IRC account authentication after owner correction; never sends')
    retry_irc.add_argument('connector')
    retry_irc.add_argument('--note',default='Owner requested a new IRC authentication check',help='non-secret action context; only its digest is retained')
    retry_line=gateway_sub.add_parser('retry-line-auth',help='allow renewed LINE bot authentication after owner correction; never sends')
    retry_line.add_argument('connector')
    retry_line.add_argument('--note',default='Owner requested a new LINE authentication check',help='non-secret action context; only its digest is retained')
    retry_sms=gateway_sub.add_parser('retry-sms-auth',help='allow renewed Twilio account authentication after owner correction; never sends')
    retry_sms.add_argument('connector')
    retry_sms.add_argument('--note',default='Owner requested a new SMS authentication check',help='non-secret action context; only its digest is retained')
    retry_email=gateway_sub.add_parser('retry-email-auth',help='permit fresh IMAP/SMTP authentication after owner correction; never sends')
    retry_email.add_argument('connector')
    retry_email.add_argument('--note',default='Owner requested a new email authentication check')
    mailbox_recovery=gateway_sub.add_parser('recover-email-mailbox',help='accept an inspected changed UID state as a new scan; preserve old receipts')
    mailbox_recovery.add_argument('identity')
    mailbox_recovery.add_argument('--snapshot-sha256',required=True)
    mailbox_recovery.add_argument('--note',required=True)
    mailbox_recovery.add_argument('--confirm-inspected',action='store_true')
    sources=gateway_sub.add_parser('email-sources',help='inspect private retained email profiles/sources while the gateway is stopped')
    sources.add_argument('--profile')
    source_purge=gateway_sub.add_parser('purge-email-source',help='purge one inspected eligible raw source; preserve receipt and audit')
    source_purge.add_argument('--profile',required=True)
    source_purge.add_argument('--id',required=True)
    source_purge.add_argument('--snapshot-sha256',required=True)
    source_purge.add_argument('--note',required=True)
    source_purge.add_argument('--confirm-inspected',action='store_true')
    email_retry=gateway_sub.add_parser('approve-email-retry',help='offline permission after independent non-delivery inspection; controller reconciliation still required')
    email_retry.add_argument('connector')
    email_retry.add_argument('delivery_id')
    email_retry.add_argument('--attempt',type=int,required=True)
    email_retry.add_argument('--snapshot-sha256',required=True)
    email_retry.add_argument('--note',required=True)
    email_retry.add_argument('--confirm-inspected',action='store_true')
    email_retry.add_argument('--confirm-not-delivered',action='store_true')
    retry_ha=gateway_sub.add_parser('retry-homeassistant-auth',help='allow renewed native Home Assistant authentication after owner correction; never sends')
    retry_ha.add_argument('connector')
    retry_ha.add_argument('--note',default='Owner requested a new Home Assistant authentication check',help='non-secret action context; only its digest is retained')
    ingress = gateway_sub.add_parser('ingress', help='list unresolved private native input with gateway service stopped')
    ingress.add_argument('--after', type=int, default=0)
    recover_ingress = gateway_sub.add_parser('reconcile-ingress', help='owner retries failed decoding or preserves discarded input')
    recover_ingress.add_argument('ingress_id')
    recover_ingress.add_argument('--attempt', type=int, required=True)
    recover_ingress.add_argument('--state', choices=['pending','processing','failed','expired','revoked'], required=True)
    recover_ingress.add_argument('--decision', choices=['retry','discard'], required=True)
    recover_ingress.add_argument('--note', required=True, help='non-secret inspection evidence; only its digest is retained')
    delivery = gateway_sub.add_parser("reconcile-delivery", help="record inspected delivery; never blindly resend an uncertain reply")
    delivery.add_argument("delivery_id")
    delivery.add_argument("--attempt", type=int, required=True)
    delivery.add_argument("--decision", choices=["delivered", "retry", "discard"], required=True)
    delivery.add_argument("--note", required=True, help="non-secret inspection evidence; only its digest is persisted")
    delivery.add_argument("--receipt", help="inspected platform-specific message ID or server-acceptance receipt, required for delivered")
    delivery.add_argument("--confirm-not-delivered", action="store_true")
    enroll = sub.add_parser("enroll", help="create a separate password-authenticated owner from a trusted root console")
    enroll.add_argument("username")
    recovery = sub.add_parser("recovery-codes", help="issue ten single-use codes at an authenticated owner console")
    recovery.add_argument("username")
    region = sub.add_parser("region", help="owner-approved system locale and physical keyboard layout")
    region_sub = region.add_subparsers(dest="region_action", required=True)
    region_sub.add_parser("status")
    region_apply = region_sub.add_parser("apply")
    region_apply.add_argument("--language", required=True,
                              choices=["de_AT.UTF-8", "de_DE.UTF-8", "en_US.UTF-8", "en_GB.UTF-8", "fr_FR.UTF-8"])
    region_apply.add_argument("--keyboard", required=True,
                              choices=["at", "de", "us", "gb", "fr", "ch"])
    provider = sub.add_parser("provider", help="owner-only credential-isolated model configuration")
    provider_sub = provider.add_subparsers(dest="provider_action", required=True)
    for action in ("status", "stop", "disable", "login-codex", "logout-codex"):
        provider_sub.add_parser(action)
    from .provider_registry import account_providers
    for action in ("login", "logout", "auth-status"):
        auth_action = provider_sub.add_parser(action)
        auth_action.add_argument("provider", choices=sorted(account_providers()))
        auth_action.add_argument("--region", choices=["global", "cn"], default="global",
                                 help="MiniMax account region; other providers require global")
    for action in ("set-default", "fallbacks", "remove"):
        route_action = provider_sub.add_parser(action)
        route_action.add_argument("route")
        if action == "fallbacks":
            route_action.add_argument("--fallback", action="append", default=[])
    ensemble = provider_sub.add_parser("ensemble")
    ensemble.add_argument("name")
    configure = provider_sub.add_parser("configure")
    from .provider_policy import ENDPOINTS
    configure.add_argument("provider", choices=sorted({*ENDPOINTS, "local", "lmstudio"}))
    configure.add_argument("--model", required=True)
    configure.add_argument("--allow-model", action="append", default=[])
    configure.add_argument("--api-mode", choices=["codex_responses", "chat_completions", "anthropic_messages"])
    configure.add_argument("--endpoint", help="local loopback /v1 endpoint; remote endpoints are fixed")
    configure.add_argument("--requests-per-day", type=int, default=200)
    configure.add_argument("--requests-per-minute", type=int, default=30)
    updater = sub.add_parser("update", help="owner-approved bootc image channel and private GHCR credentials")
    updater_sub = updater.add_subparsers(dest="update_action", required=True)
    for action in ("status", "login", "check", "stage", "logout"):
        updater_sub.add_parser(action)
    change_channel = updater_sub.add_parser("channel")
    change_channel.add_argument("channel", choices=["stable", "dev"])
    change_channel.add_argument("--auto-stage", action="store_true",
                                help="download and stage new images automatically; reboot remains manual")
    backup = sub.add_parser("backup")
    backup_sub = backup.add_subparsers(dest="backup_action", required=True)
    for action in ("init", "create", "check", "snapshots"):
        backup_sub.add_parser(action)
    restore = backup_sub.add_parser("restore")
    restore.add_argument("snapshot_id")
    retention = backup_sub.add_parser("retention", help="preview scoped retention; deletion requires --apply")
    retention.add_argument("--keep-last", type=int, default=7)
    retention.add_argument("--keep-daily", type=int, default=7)
    retention.add_argument("--keep-weekly", type=int, default=4)
    retention.add_argument("--keep-monthly", type=int, default=12)
    retention.add_argument("--apply", action="store_true")
    schedule = backup_sub.add_parser("schedule", help="configure encrypted system or consistent live mission-ledger backups")
    schedule.add_argument("interval", choices=["off", "daily", "weekly"])
    schedule.add_argument('--scope', choices=['system', 'mission-ledger'], help='system requires stopped execution; mission-ledger uses an online SQLite checkpoint')
    schedule.add_argument("--prune", action="store_true", help="explicitly authorize applying scoped retention")
    schedule.add_argument("--keep-last", type=int, default=7)
    schedule.add_argument("--keep-daily", type=int, default=7)
    schedule.add_argument("--keep-weekly", type=int, default=4)
    schedule.add_argument("--keep-monthly", type=int, default=12)
    backup_sub.add_parser("schedule-status")
    clear = backup_sub.add_parser("schedule-clear", help="clear an interrupted attempt after owner inspection, without deleting snapshots")
    clear.add_argument("--note", required=True)
    clear.add_argument("--confirm-inspected", action="store_true")
    grant = sub.add_parser("volume")
    grant.add_argument("id", help="UUID:<filesystem UUID> or PARTUUID:<partition UUID>")
    grant.add_argument("mode", choices=["blocked", "read-only", "full-data-access", "system-managed"])
    media = sub.add_parser('media',help='inspect or explicitly purge retained gateway payloads with execution stopped')
    media_sub=media.add_subparsers(dest='media_action',required=True)
    media_sub.add_parser('list')
    media_purge=media_sub.add_parser('purge')
    media_purge.add_argument('--id',action='append',required=True,help='exact upload ID; at most four, no wildcard')
    media_purge.add_argument('--note',required=True)
    media_purge.add_argument('--confirm-inspected',action='store_true')
    reconciler = sub.add_parser("reconcile")
    reconciler.add_argument("mission_id")
    reconciler.add_argument("--note", required=True, help="evidence from inspection of Hermes/processes/files")
    args = parser.parse_args()
    if os.geteuid() != 0:
        raise PermissionError("authenticate as the owner with sudo or a recovery console")
    if args.action=='speech':
        from . import speech_setup
        print(json.dumps({'status':speech_setup.status,'enable':speech_setup.enable,'disable':speech_setup.disable}[args.speech_action](),indent=2))
    elif args.action == "setup":
        # Owner-only fixed actions on the physical VT; handle sudo use_pty.
        require_physical_setup_console()
        from . import initial_setup
        if args.setup_action == "status":
            print(json.dumps({"owner_recovery": initial_setup.account_status(),
                              "normal_profile_ready": initial_setup.normal_user_ready(),
                              "wizard_receipt": initial_setup.setup_finished()}, indent=2))
        elif args.setup_action == "name":
            print(json.dumps(initial_setup.configure_normal_user(args.display_name), indent=2))
        elif args.setup_action == "finish":
            print(json.dumps(initial_setup.finalize(), indent=2))
        else:
            raise PermissionError("unknown local setup operation")
    elif args.action=='remote':
        from .remote_setup import owner_remote
        print(json.dumps(owner_remote(args),indent=2))
    elif args.action == "application":
        from .applications import owner_application
        print(json.dumps(owner_application(args), indent=2))
    elif args.action == "update":
        from .update import owner_update
        print(json.dumps(owner_update(args), indent=2))
    elif args.action == "region":
        from .region import owner_region
        print(json.dumps(owner_region(args), indent=2))
    elif args.action == "provider":
        from .provider_setup import owner_provider
        print(json.dumps(owner_provider(args), indent=2))
    elif args.action == "recovery-codes":
        from .owner_recovery import print_codes
        print_codes(args.username)
    elif args.action == "gateway":
        from .gateway_setup import owner_gateway
        print(json.dumps(owner_gateway(args), indent=2))
    elif args.action == "enroll":
        from .enrollment import enroll_interactive
        from .owner_recovery import print_codes
        stopped()
        print(json.dumps(enroll_interactive(args.username), indent=2))
        print_codes(args.username)
    elif args.action == "backup":
        if args.backup_action in {"schedule", "schedule-status", "schedule-clear"}:
            from .backup_schedule import installed_scheduler
            scheduler = installed_scheduler()
            if args.backup_action == "schedule":
                value = {"version": 1, "interval": args.interval, "scope": args.scope or scheduler.configuration_value().get('scope', 'system'), "prune": args.prune, "retention": {
                    "keep_last": args.keep_last, "keep_daily": args.keep_daily,
                    "keep_weekly": args.keep_weekly, "keep_monthly": args.keep_monthly}}
                result = scheduler.configure(value)
                subprocess.run(["/usr/bin/systemctl", "disable" if args.interval == "off" else "enable", "--now",
                                "haos-backup-schedule.timer"], check=True)
            elif args.backup_action == "schedule-clear":
                result = scheduler.clear(args.note, args.confirm_inspected)
            else:
                result = scheduler.status()
            print(json.dumps(result, indent=2))
            return
        from .backup import Retention, owner_backup
        retention = (Retention(args.keep_last, args.keep_daily, args.keep_weekly, args.keep_monthly)
                     if args.backup_action == "retention" else None)
        print(json.dumps(owner_backup(args.backup_action, getattr(args, "snapshot_id", None),
                                     retention=retention, apply=getattr(args, "apply", False)), indent=2))
    elif args.action == "prepare":
        stopped()
        prepare()
    elif args.action == "cleanup":
        stopped()
        cleanup()
    elif args.action == "status":
        runtime = Path("/run/haos-policy/sandbox.json")
        print(json.dumps({"policy": trusted_json(Path("/etc/haos/volumes.json")), "devices": inventory(),
                          "runtime_volumes": trusted_json(runtime) if runtime.exists() or runtime.is_symlink() else None}, indent=2))
    elif args.action in {"stop", "start"}:
        runtime_action(args.action)
    elif args.action == "volume":
        stopped()
        policy = trusted_json(Path("/etc/haos/volumes.json"))
        new = {"id": args.id, "mode": args.mode}
        policy["volumes"] = [v for v in policy["volumes"] if v["id"] != args.id] + [new]
        validate_policy(policy)
        if args.mode in {"read-only", "full-data-access"}:
            resolve_volume(args.id, inventory())
        cleanup()
        atomic_json(Path("/etc/haos/volumes.json"), policy)
        audit("volume.policy", new)
    elif args.action == 'media':
        print(json.dumps(manage_media(args.media_action,getattr(args,'id',None),getattr(args,'note',''),
            confirmed=getattr(args,'confirm_inspected',False)),indent=2))
    elif args.action == "reconcile":
        stopped()
        store = MissionStore(Path("/var/lib/haos-control/missions.db"))
        try:
            store.reconcile(args.mission_id, f"owner:{os.environ.get('SUDO_UID', '0')}", args.note)
        finally:
            store.close()
        audit("mission.reconciled", {"id": args.mission_id, "note": args.note})


if __name__ == "__main__":
    main()
