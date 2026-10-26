"""Owner-only pairing and transport credential setup; never callable by a model."""

import getpass
import grp
import hashlib
import json
import os
import pwd
import stat
import subprocess
import secrets
import time
from copy import deepcopy
from pathlib import Path

from .gateway import GatewayPolicy
from .sandbox import trusted_json

CONFIG = Path("/etc/haos")


def owner_matrix_devices(connector,sender):
    if os.geteuid()!=0:raise PermissionError('Matrix device inspection requires authenticated owner authority')
    from .gateway_matrix_policy import opaque,public_key
    if not opaque(sender,'@') or ':' not in sender:raise ValueError('exact Matrix sender account required')
    stopped_gateway();policy,private=load()
    selected=next((row for row in policy['connectors'] if row['id']==connector),None)
    if selected is None or selected['platform']!='matrix':raise ValueError('select one configured Matrix connector')
    code=Path('/usr/lib/haos');interpreter=code/'hermes/.venv/bin/python'
    for path in (code,code/'haos',code/'hermes',code/'hermes/.venv',interpreter.parent):
        info=path.lstat()
        if not stat.S_ISDIR(info.st_mode) or info.st_uid!=0 or info.st_mode&0o022:
            raise PermissionError('untrusted installed Matrix helper runtime')
    binary=interpreter.resolve().lstat()
    if not stat.S_ISREG(binary.st_mode) or binary.st_uid!=0 or binary.st_mode&0o022:
        raise PermissionError('untrusted installed Matrix helper interpreter')
    account=pwd.getpwnam('haos-gateway')
    if account.pw_uid==0 or account.pw_gid==0:raise PermissionError('Matrix account helper must drop root')
    row=private['connectors'][connector]
    values={key:row[key] for key in ('token','homeserver','user_id','device_id')}
    result=subprocess.run([str(interpreter),'-E','-s','-m','haos.gateway_matrix_account'],
        input=json.dumps({'credentials':values,'sender':sender}),text=True,capture_output=True,check=False,timeout=70,
        user=account.pw_uid,group=account.pw_gid,extra_groups=[],umask=0o077,cwd=str(code),
        env={'PATH':'/usr/bin:/bin','LANG':'C.UTF-8','PYTHONDONTWRITEBYTECODE':'1','HERMES_SAFE_MODE':'1'})
    if result.returncode or len(result.stdout)>131072:raise RuntimeError('Matrix device inspection failed in the private gateway identity')
    response=json.loads(result.stdout)
    if set(response)=={'error'}:raise RuntimeError('Matrix-Geräteabfrage abgelehnt oder nicht erreichbar; Konto, Gerät, Token und TLS prüfen.')
    if (set(response)!={'devices','signature_checked','owner_approval_required'} or response['signature_checked'] is not True
            or response['owner_approval_required'] is not True or not isinstance(response['devices'],list) or len(response['devices'])>256):
        raise ValueError('invalid private Matrix device inspection response')
    seen=set()
    for device in response['devices']:
        if (not isinstance(device,dict) or set(device)!={'device_id','ed25519','curve25519'}
                or not opaque(device['device_id']) or device['device_id']=='*' or device['device_id'] in seen
                or not public_key(device['ed25519']) or not public_key(device['curve25519'])):
            raise ValueError('invalid inspected Matrix public device keys')
        seen.add(device['device_id'])
    from .owner import audit
    audit('gateway.matrix-devices-inspected',{'connector':connector,'devices':len(seen)})
    return response


def owner_ingress(args, policy):
    """Owner authenticates; only the gateway UID opens its private native journal."""
    from .owner import audit
    if os.geteuid() != 0:
        raise PermissionError('native ingress recovery requires authenticated owner authority')
    stopped_gateway()
    GatewayPolicy(policy)
    params = {'after':args.after} if args.gateway_action == 'ingress' else None
    if args.gateway_action in {'retry-ntfy-auth','retry-homeassistant-auth'}:
        platform='ntfy' if args.gateway_action=='retry-ntfy-auth' else 'homeassistant'
        if not any(row['id']==args.connector and row['platform']==platform for row in policy['connectors']):
            raise ValueError('select one configured connector for this authentication recheck')
        if not isinstance(args.note,str) or not 1<=len(args.note.strip())<=2000:
            raise ValueError('bounded non-secret owner action context required')
        params={'connector':args.connector,'owner_uid':int(os.environ.get('SUDO_UID','0')),
            'note_sha256':hashlib.sha256(args.note.strip().encode()).hexdigest()}
    if params is None:
        if not isinstance(args.note,str) or not 1 <= len(args.note.strip()) <= 2000:
            raise ValueError('bounded non-secret owner inspection evidence required')
        params = {'ingress_id':args.ingress_id,'attempt':args.attempt,'state':args.state,
            'decision':args.decision,'owner_uid':int(os.environ.get('SUDO_UID','0')),
            'note_sha256':hashlib.sha256(args.note.strip().encode()).hexdigest()}
    directory = Path('/usr/lib/haos').lstat()
    if not stat.S_ISDIR(directory.st_mode) or directory.st_uid != 0 or directory.st_mode & 0o022:
        raise PermissionError('untrusted installed recovery code')
    account = pwd.getpwnam('haos-gateway')
    if account.pw_uid == 0 or account.pw_gid == 0:
        raise PermissionError('gateway recovery may not retain root')
    result = subprocess.run(['/usr/bin/python3','-E','-s','-m','haos.gateway_raw_recovery'],
        input=json.dumps({'action':args.gateway_action,'policy':policy,'params':params}),
        text=True,capture_output=True,check=False,timeout=15,user=account.pw_uid,group=account.pw_gid,
        extra_groups=[],umask=0o077,cwd='/usr/lib/haos',
        env={'PATH':'/usr/bin:/bin','LANG':'C.UTF-8','PYTHONDONTWRITEBYTECODE':'1'})
    if result.returncode or len(result.stdout) > 256*1024:
        raise RuntimeError('offline native ingress recovery failed; check selected state, attempt, grant and 24-hour expiry')
    value = json.loads(result.stdout)
    from .gateway import digest
    names = {digest(row):row['id'] for row in policy['bindings']}
    for row in value.get('history',[]):
        row['binding_id'] = names.get(row['binding_digest'],'widerrufene Freigabe')
    if args.gateway_action in {'retry-ntfy-auth','retry-homeassistant-auth'}:
        audit('gateway.'+platform+'-auth-retry',{**value,'note_sha256':params['note_sha256']})
    if args.gateway_action == 'reconcile-ingress':
        audit('gateway.ingress-reconciled',{**value,'note_sha256':params['note_sha256']})
    return value


def owner_delivery(args, policy):
    """Drop root before opening controller-owned SQLite; keep credentials out of the child."""
    from .owner import audit, stopped
    if os.geteuid() != 0:
        raise PermissionError("outbox reconciliation requires authenticated owner authority")
    stopped_gateway()
    stopped()
    GatewayPolicy(policy)
    params = {"after": args.after} if args.gateway_action == "deliveries" else None
    if params is None:
        if not isinstance(args.note, str) or not 1 <= len(args.note.strip()) <= 2000:
            raise ValueError("bounded non-secret owner inspection evidence is required")
        params = {"delivery_id": args.delivery_id, "attempt": args.attempt, "decision": args.decision,
                  "owner_uid": int(os.environ.get("SUDO_UID", "0")),
                  "note_sha256": hashlib.sha256(args.note.strip().encode()).hexdigest(), "receipt": args.receipt,
                  "confirmed_not_delivered": args.confirm_not_delivered}
    directory = Path("/usr/lib/haos").lstat()
    if not stat.S_ISDIR(directory.st_mode) or directory.st_uid != 0 or directory.st_mode & 0o022:
        raise PermissionError("untrusted installed recovery code")
    account = pwd.getpwnam("haos-control")
    if account.pw_uid == 0 or account.pw_gid == 0:
        raise PermissionError("controller recovery may not retain root")
    result = subprocess.run(["/usr/bin/python3", "-E", "-s", "-m", "haos.gateway_recovery"],
                            input=json.dumps({"action": args.gateway_action, "policy": policy, "params": params}),
                            text=True, capture_output=True, check=False, timeout=15,
                            user=account.pw_uid, group=account.pw_gid, extra_groups=[], umask=0o077,
                            cwd="/usr/lib/haos", env={"PATH": "/usr/bin:/bin", "LANG": "C.UTF-8", "PYTHONDONTWRITEBYTECODE": "1"})
    if result.returncode or len(result.stdout) > 256 * 1024:
        raise RuntimeError("offline outbox recovery failed; inspect the private ledger and selected attempt")
    value = json.loads(result.stdout)
    if args.gateway_action == "reconcile-delivery":
        audit("gateway.delivery-reconciled", {**value, "note_sha256": params["note_sha256"]})
    return value


def stopped_gateway():
    result = subprocess.run(["/usr/bin/systemctl", "show", "--property=LoadState,ActiveState,MainPID,ControlPID",
                             "haos-gateway.service"], check=True, capture_output=True, text=True, timeout=15)
    state = dict(line.split("=", 1) for line in result.stdout.splitlines() if "=" in line)
    if (state.get("LoadState") not in {"loaded", "masked"} or state.get("ActiveState") != "inactive"
            or state.get("MainPID") != "0" or state.get("ControlPID") != "0"):
        raise PermissionError("stop haos-gateway.service before changing pairing or transport credentials")


def load(config=CONFIG):
    from .gateway_publication import pending, validate_snapshot
    if pending(config):
        raise PermissionError("interrupted gateway publication; stop the gateway and recover-configuration")
    metadata = config.lstat()
    if not stat.S_ISDIR(metadata.st_mode) or metadata.st_uid != 0 or metadata.st_mode & 0o022:
        raise PermissionError("untrusted gateway configuration directory")
    policy = trusted_json(config / "gateways.json") if (config / "gateways.json").exists() else {
        "version": 1, "connectors": [], "bindings": []}
    GatewayPolicy(policy)
    secret_path = config / "gateway-credentials"
    if secret_path.exists() and stat.S_IMODE(secret_path.lstat().st_mode) & 0o077:
        raise PermissionError("transport credential store must be root-private")
    credentials = trusted_json(secret_path) if secret_path.exists() else {"connectors": {}}
    validate_snapshot(policy, credentials)
    if pending(config):
        raise PermissionError("gateway publication changed during inspection")
    return ({key: value for key, value in policy.items() if key != "publication"},
            {key: value for key, value in credentials.items() if key != "publication"})


def renewed_policy(policy, previous):
    """Preserve exact grants; newly paired or edited grants get a fresh epoch.

    Legacy grants acquire an epoch on their next owner publication. Old mission
    and relay records remain stored but cannot regain delivery authority through
    an identical later pairing, route edit reversal or stale policy submission.
    """
    GatewayPolicy(policy)
    old = GatewayPolicy(previous).bindings
    output = deepcopy(policy)
    for binding in output["bindings"]:
        before = old.get(binding["id"])
        if (before is None or "generation" not in before or binding != before):
            binding["generation"] = secrets.token_hex(32)
            binding['since'] = time.time_ns() // 1_000_000
    return output


def persist(policy, credentials, *, config=CONFIG, gid=None):
    if os.geteuid() != 0:
        raise PermissionError("gateway setup requires authenticated owner authority")
    from .gateway_publication import writer, publish
    with writer(config):
        previous, old_credentials = load(config)
        policy = deepcopy(policy)
        # A credential/account replacement requires fresh sender approval.
        # Preserve old records, but withdraw all bindings on that connector.
        changed = {key for key in credentials.get("connectors", {})
            if key in old_credentials["connectors"] and credentials["connectors"][key] != old_credentials["connectors"][key]}
        old_platforms = {row["id"]: row["platform"] for row in previous["connectors"]}
        changed.update(row["id"] for row in policy["connectors"] if row["id"] in old_platforms
            and row["platform"] != old_platforms[row["id"]])
        policy["bindings"] = [binding for binding in policy["bindings"] if binding["connector"] not in changed]
        policy = renewed_policy(policy, previous)
        gid = grp.getgrnam("haos-gateway").gr_gid if gid is None else gid
        publish(config, policy, credentials, previous, gid)


def owner_gateway(args):
    from .owner import audit
    if os.geteuid() != 0:
        raise PermissionError("gateway setup requires authenticated owner authority")
    if args.gateway_action == "recover-configuration":
        from .gateway_publication import recover
        stopped_gateway()
        value = recover(CONFIG, grp.getgrnam("haos-gateway").gr_gid)
        audit("gateway.configuration-recovered", {})
        return value
    if args.gateway_action in {"start", "stop"}:
        subprocess.run(["/usr/bin/systemctl", args.gateway_action, "haos-gateway.service"], check=True, timeout=30)
        audit("gateway." + args.gateway_action, {})
        return {"action": args.gateway_action}
    if args.gateway_action=='matrix-devices':return owner_matrix_devices(args.connector,args.sender)
    policy, credentials = load()
    if args.gateway_action == "status":
        return {"policy": policy, "credential_configured": sorted(credentials["connectors"])}
    if args.gateway_action in {"deliveries", "reconcile-delivery"}:
        return owner_delivery(args, policy)
    if args.gateway_action in {'ingress','reconcile-ingress','retry-ntfy-auth','retry-homeassistant-auth'}:
        return owner_ingress(args, policy)
    stopped_gateway()
    if args.gateway_action == "setup":
        if args.platform not in {"telegram", "discord", "slack", "mattermost", "matrix", "ntfy", "homeassistant"}:
            raise ValueError("currently provisioned transports: telegram, discord, slack, mattermost, matrix, ntfy, homeassistant")
        if any(c["id"] != args.connector and c["platform"] == args.platform for c in policy["connectors"]):
            raise ValueError("one isolated adapter per platform is currently supported")
        if any(c['id']==args.connector and c['platform']!=args.platform for c in policy['connectors']):
            policy['bindings']=[row for row in policy['bindings'] if row['connector']!=args.connector]
        # Validate the proposed connector before asking for a credential.
        policy["connectors"] = [c for c in policy["connectors"] if c["id"] != args.connector] + [{"id": args.connector, "platform": args.platform}]
        GatewayPolicy(policy)
        token = getpass.getpass("Bot token (stored only in the owner-protected credential store): ")
        if args.platform not in {'matrix','ntfy','homeassistant'} and (not 16 <= len(token) <= 4096 or any(c.isspace() or ord(c) < 32 for c in token)):
            raise ValueError("invalid transport credential")
        credentials["connectors"][args.connector] = {"token": token}
        if args.platform=='homeassistant':
            from .gateway_homeassistant_profile import credentials as ha_credentials
            url=input('Home Assistant HTTPS server URL (system-trusted certificate required): ')
            credentials['connectors'][args.connector]=ha_credentials({'token':token,'server_url':url})
        if args.platform=='slack':
            from .gateway_slack import validate_credentials
            app_token=getpass.getpass('Slack Socket Mode app token (private): ')
            validate_credentials(token,app_token)
            credentials['connectors'][args.connector]['app_token']=app_token
        if args.platform=='mattermost':
            from .gateway_mattermost import validate_credentials
            url=input('Mattermost HTTPS server URL (no token or credentials in URL): ')
            credentials['connectors'][args.connector]['server_url']=validate_credentials(token,url)
        if args.platform=='ntfy':
            from .gateway_ntfy_profile import credentials as ntfy_credentials
            url=input('ntfy HTTPS server URL (no embedded credentials): ')
            topic=input('Exact private ntfy topic (all its publishers share the approved identity): ')
            credentials['connectors'][args.connector]=ntfy_credentials({'token':token,'server_url':url,'topic':topic})
        if args.platform=='matrix':
            from .gateway_matrix_profile import credentials as matrix_credentials
            homeserver=input('Matrix HTTPS homeserver: ')
            user_id=input('Exact Matrix account ID (@user:server): ')
            device_id=input('Existing stable device ID belonging to this token: ')
            recovery=getpass.getpass('Existing Matrix recovery key (optional, private; empty skips): ')
            credentials['connectors'][args.connector]=matrix_credentials({'token':token,'homeserver':homeserver,
                'user_id':user_id,'device_id':device_id,**({'recovery_key':recovery} if recovery else {})})
    elif args.gateway_action == "pair":
        binding = {"id": args.binding, "connector": args.connector, "sender": args.sender, "chat": args.chat,
                   "scope": args.scope, "thread": args.thread, "identity": args.identity,
                   "capabilities": args.capabilities}
        selected=next((row for row in policy['connectors'] if row['id']==args.connector),None)
        devices=getattr(args,'matrix_device',[]);plain=getattr(args,'allow_plaintext',False)
        unmentioned=getattr(args,'no_require_mention',False)
        if selected and selected['platform']=='matrix':
            binding.update(matrix_devices=[dict(zip(('device_id','ed25519','curve25519'),row)) for row in devices],
                allow_plaintext=plain,require_mention=not unmentioned)
        elif devices or plain or unmentioned:
            raise ValueError('Matrix device/encryption options apply only to Matrix')
        trust=getattr(args,'trust_topic_publishers',False)
        if selected and selected['platform']=='ntfy':binding['trust_topic_publishers']=trust
        elif trust:raise ValueError('topic publisher trust applies only to ntfy')
        shared=getattr(args,'homeassistant_shared_notifications',False)
        system=getattr(args,'homeassistant_trust_system',False)
        if selected and selected['platform']=='homeassistant':
            if 'read' in binding['capabilities'] and shared is not True:
                raise ValueError('explicit approval of replies visible to every Home Assistant instance user required')
            binding['homeassistant_shared_notifications']=shared
            binding['homeassistant_trust_system']=system
        elif shared or system:raise ValueError('Home Assistant notification/system consent applies only to Home Assistant')
        policy["bindings"] = [b for b in policy["bindings"] if b["id"] != args.binding] + [binding]
    elif args.gateway_action == "revoke":
        if not any(b["id"] == args.binding for b in policy["bindings"]):
            raise KeyError("unknown gateway binding")
        policy["bindings"] = [b for b in policy["bindings"] if b["id"] != args.binding]
    elif args.gateway_action == "remove":
        policy["connectors"] = [c for c in policy["connectors"] if c["id"] != args.connector]
        policy["bindings"] = [b for b in policy["bindings"] if b["connector"] != args.connector]
        credentials["connectors"].pop(args.connector, None)
    persist(policy, credentials)
    audit("gateway." + args.gateway_action, {"connector": getattr(args, "connector", None), "binding": getattr(args, "binding", None)})
    return {"configured": True, "action": args.gateway_action, "restart_required": True}
