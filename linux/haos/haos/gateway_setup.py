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


def owner_email_account(connector):
    """Authenticate configured IMAP/SMTP in the private UID; never send mail."""
    if os.geteuid()!=0:raise PermissionError('email account inspection requires authenticated owner authority')
    stopped_gateway();policy,private=load()
    if not any(row['id']==connector and row['platform']=='email' for row in policy['connectors']):
        raise ValueError('select one configured email connector')
    from .gateway_email import credentials,authority
    from .gateway_email_process import command,response,ERRORS
    from .gateway_line_ingress import _object
    value=credentials(private['connectors'][connector]);publication=authority(connector,value)
    account=pwd.getpwnam('haos-gateway')
    if account.pw_uid==0 or account.pw_gid==0:raise PermissionError('email account inspection must drop root')
    request={'action':'probe','connector':connector,'credentials':value,'policy_sha256':publication,'parent_pid':os.getpid()}
    try:
        result=subprocess.run(command(),input=json.dumps(request,ensure_ascii=False)+'\n',text=True,
            capture_output=True,check=False,timeout=35,user=account.pw_uid,group=account.pw_gid,
            extra_groups=[],umask=0o077,cwd='/usr/lib/haos',
            env={'PATH':'/usr/bin:/bin','LANG':'C.UTF-8','PYTHONDONTWRITEBYTECODE':'1','HERMES_SAFE_MODE':'1'})
    except subprocess.TimeoutExpired:
        raise RuntimeError('E-Mail-Kontoprüfung abgebrochen: Zeitlimit; IMAP-/SMTP-Endpunkte und Netzwerk prüfen.') from None
    if result.returncode or len(result.stdout.encode())>16384:
        raise RuntimeError('E-Mail-Kontoprüfung fehlgeschlagen; private Runtime, Konto, TLS und Netzwerk prüfen.')
    def finite(_value):raise ValueError('finite private account response required')
    checked=response(json.loads(result.stdout,object_pairs_hook=_object,parse_constant=finite))
    authority(connector,value,publication)
    from .owner import audit
    if 'error' in checked:
        audit('gateway.email-account-inspected',{'connector':connector,'authenticated':False,'error':checked['error']})
        if checked['error'] not in ERRORS:raise ValueError('finite account diagnostic required')
        return {'authenticated':False,'error':checked['error'],'smtp_message_sent':False,
            'sender_grants_changed':False,'external_delivery_verified':False}
    from .owner import audit
    audit('gateway.email-account-inspected',{'connector':connector,'imap_authenticated':True,'smtp_authenticated':True})
    return {**checked,'authenticated':True,'sender_grants_changed':False,'external_delivery_verified':False}


def owner_ingress(args, policy):
    """Owner authenticates; only the gateway UID opens its private native journal."""
    from .owner import audit
    if os.geteuid() != 0:
        raise PermissionError('native ingress recovery requires authenticated owner authority')
    stopped_gateway()
    if any(row.get('platform')=='email' for row in policy['connectors']):
        from .gateway_email import PreparedEmailPolicy
        PreparedEmailPolicy(policy)
    else:GatewayPolicy(policy)
    params = {'after':args.after} if args.gateway_action == 'ingress' else None
    if args.gateway_action=='media-cache':params={}
    if args.gateway_action=='purge-media-cache':
        if (not isinstance(args.note,str) or not 1<=len(args.note.strip())<=2000 or args.confirm_inspected is not True):
            raise PermissionError('explicit non-secret cache inspection and confirmation required')
        from .gateway_media import references
        references([args.id])
        params={'id':args.id,'owner_uid':int(os.environ.get('SUDO_UID','0')),
            'note_sha256':hashlib.sha256(args.note.strip().encode()).hexdigest(),'confirmed':True}
    if args.gateway_action in {'retry-ntfy-auth','retry-homeassistant-auth','retry-irc-auth','retry-line-auth','retry-sms-auth','retry-email-auth'}:
        platform={'retry-ntfy-auth':'ntfy','retry-homeassistant-auth':'homeassistant','retry-irc-auth':'irc','retry-line-auth':'line','retry-sms-auth':'sms','retry-email-auth':'email'}[args.gateway_action]
        if not any(row['id']==args.connector and row['platform']==platform for row in policy['connectors']):
            raise ValueError('select one configured connector for this authentication recheck')
        if not isinstance(args.note,str) or not 1<=len(args.note.strip())<=2000:
            raise ValueError('bounded non-secret owner action context required')
        params={'connector':args.connector,'owner_uid':int(os.environ.get('SUDO_UID','0')),
            'note_sha256':hashlib.sha256(args.note.strip().encode()).hexdigest()}
    if args.gateway_action=='email-sources':params={'profile':args.profile}
    if args.gateway_action in {'recover-email-mailbox','purge-email-source','approve-email-retry'}:
        if (not isinstance(args.note,str) or not 1<=len(args.note.strip())<=2000 or args.confirm_inspected is not True):
            raise PermissionError('explicit inspected email decision and non-secret context required')
        params={'owner_uid':int(os.environ.get('SUDO_UID','0')),'note_sha256':hashlib.sha256(args.note.strip().encode()).hexdigest(),
            'confirmed':True,'snapshot_sha256':args.snapshot_sha256}
        if args.gateway_action=='recover-email-mailbox':params['identity']=args.identity
        elif args.gateway_action=='purge-email-source':params.update(profile=args.profile,id=args.id)
        else:params.update(connector=args.connector,delivery_id=args.delivery_id,attempt=args.attempt,confirmed_not_delivered=args.confirm_not_delivered)
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
    if args.gateway_action in {'retry-ntfy-auth','retry-homeassistant-auth','retry-irc-auth','retry-line-auth','retry-sms-auth','retry-email-auth'}:
        audit('gateway.'+platform+'-auth-retry',{**value,'note_sha256':params['note_sha256']})
    if args.gateway_action=='purge-media-cache':
        audit('gateway.media-cache-purged',{**value,'note_sha256':params['note_sha256']})
    if args.gateway_action == 'reconcile-ingress':
        audit('gateway.ingress-reconciled',{**value,'note_sha256':params['note_sha256']})
    if args.gateway_action in {'recover-email-mailbox','purge-email-source','approve-email-retry'}:
        audit('gateway.'+args.gateway_action,{**value,'note_sha256':params['note_sha256']})
    return value


def owner_delivery(args, policy):
    """Drop root before opening controller-owned SQLite; keep credentials out of the child."""
    from .owner import audit, stopped
    if os.geteuid() != 0:
        raise PermissionError("outbox reconciliation requires authenticated owner authority")
    stopped_gateway()
    stopped()
    if any(row.get('platform')=='email' for row in policy['connectors']):
        from .gateway_email import PreparedEmailPolicy
        PreparedEmailPolicy(policy)
    else:GatewayPolicy(policy)
    params = {"after": args.after} if args.gateway_action == "deliveries" else None
    if args.gateway_action=='media-list':params={}
    if args.gateway_action=='purge-media':
        from .gateway_media import references
        if (args.confirmed is not True or not isinstance(args.note,str) or not 1<=len(args.note.strip())<=2000):
            raise PermissionError('explicit inspected owner media decision required')
        ids=references(args.ids)
        if not ids:raise ValueError('explicit media IDs required')
        params={'ids':ids,'owner_uid':int(os.environ.get('SUDO_UID','0')),
            'note_sha256':hashlib.sha256(args.note.strip().encode()).hexdigest(),'confirmed':True}
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
    if result.returncode or len(result.stdout) > 2 * 1024 * 1024:
        raise RuntimeError("offline outbox recovery failed; inspect the private ledger and selected attempt")
    value = json.loads(result.stdout)
    if args.gateway_action=='purge-media':
        audit('gateway.media.purged',{**value,'note_sha256':params['note_sha256']})
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
    if args.gateway_action=='email-account':return owner_email_account(args.connector)
    policy, credentials = load()
    if args.gateway_action == "status":
        return {"policy": policy, "credential_configured": sorted(credentials["connectors"])}
    if args.gateway_action in {"deliveries", "reconcile-delivery"}:
        return owner_delivery(args, policy)
    if args.gateway_action in {'ingress','reconcile-ingress','retry-ntfy-auth','retry-homeassistant-auth','retry-irc-auth','retry-line-auth','retry-sms-auth','retry-email-auth','recover-email-mailbox','email-sources','purge-email-source','approve-email-retry','media-cache','purge-media-cache'}:
        return owner_ingress(args, policy)
    stopped_gateway()
    if args.gateway_action == "setup":
        if args.platform not in GatewayPolicy.platforms:
            raise ValueError("select an implemented transport")
        if args.platform=='email':
            from .initial_setup import configure_email_gateway
            account={'address':input('Exact dedicated email address (canonical lowercase): '),
                'password':getpass.getpass('Private email app/account password: ')}
            for protocol,default in [('imap',993),('smtp',465)]:
                account[protocol+'_host']=input(protocol.upper()+' exact TLS hostname: ')
                raw=input(protocol.upper()+' port ['+str(default)+']: ') or str(default)
                if not raw.isascii() or not raw.isdecimal() or len(raw)>5 or not 1<=int(raw)<=65535:
                    raise ValueError('mail port must contain digits from 1 to 65535')
                account[protocol+'_port']=int(raw)
                account[protocol+'_security']=input(protocol.upper()+' TLS mode (tls/starttls) [tls]: ') or 'tls'
            account['authserv_id']=input('Exact trusted receiving Authentication-Results authserv-id: ')
            consent=input('Independently verified receiving server strips forged own Authentication-Results and prepends trusted results? Type VERIFIED: ')=='VERIFIED'
            return configure_email_gateway(args.connector,account,trust_authentication_results=consent)
        if args.platform=='sms':
            from .initial_setup import configure_sms_gateway,read_line_tls_file
            account=input('Exact Twilio Account SID (AC + 32 hex digits): ')
            token=getpass.getpass('Private Twilio auth token: ')
            number=input('Owned Twilio receiving number (E.164): ')
            raw_port=input('Local HTTPS listener port [8647]: ') or '8647'
            if not raw_port.isascii() or not raw_port.isdecimal() or len(raw_port)>5 or not 1024<=int(raw_port)<=65535:
                raise ValueError('SMS local listener port must contain digits from 1024 to 65535')
            url=input('Public HTTPS URL (https://hostname/webhooks/twilio): ')
            certificate=read_line_tls_file(input('Private certificate-chain PEM file: '),'certificate')
            key=read_line_tls_file(input('Private unencrypted key PEM file: '),'private_key')
            bind=input('Listener bind host [127.0.0.1] (0.0.0.0 or :: requires public consent): ') or '127.0.0.1'
            consent=False
            if bind!='127.0.0.1':
                consent=input('Explicitly approve public listener by typing PUBLIC: ')=='PUBLIC'
            return configure_sms_gateway(args.connector,account,token,number,int(raw_port),
                {'public_url':url,'certificate':certificate,'private_key':key,'bind_host':bind,'public_listener':consent})
        if args.platform=='line':
            from .initial_setup import configure_line_gateway,read_line_tls_file
            secret=getpass.getpass('Private LINE channel secret: ')
            access=getpass.getpass('Private LINE channel access token: ')
            destination=input('Exact LINE bot destination (U + 32 lowercase hex digits): ')
            raw_port=input('Local HTTPS listener port [8646]: ') or '8646'
            if not raw_port.isascii() or not raw_port.isdecimal() or len(raw_port)>5 or not 1024<=int(raw_port)<=65535:
                raise ValueError('LINE local listener port must contain digits from 1024 to 65535')
            url=input('Public HTTPS URL (https://hostname/line/webhook): ')
            certificate=read_line_tls_file(input('Private certificate-chain PEM file: '),'certificate')
            key=read_line_tls_file(input('Private unencrypted key PEM file: '),'private_key')
            bind=input('Listener bind host [127.0.0.1] (0.0.0.0 or :: requires public consent): ') or '127.0.0.1'
            consent=False
            if bind!='127.0.0.1':
                consent=input('Explicitly approve public listener by typing PUBLIC: ')=='PUBLIC'
            return configure_line_gateway(args.connector,secret,access,destination,int(raw_port),
                {'public_url':url,'certificate':certificate,'private_key':key,'bind_host':bind,'public_listener':consent})
        if any(c["id"] != args.connector and c["platform"] == args.platform for c in policy["connectors"]):
            raise ValueError("one isolated adapter per platform is currently supported")
        if any(c['id']==args.connector and c['platform']!=args.platform for c in policy['connectors']):
            policy['bindings']=[row for row in policy['bindings'] if row['connector']!=args.connector]
        # Validate the proposed connector before asking for a credential.
        policy["connectors"] = [c for c in policy["connectors"] if c["id"] != args.connector] + [{"id": args.connector, "platform": args.platform}]
        GatewayPolicy(policy)
        token = "" if args.platform=="irc" else getpass.getpass("Bot token (stored only in the owner-protected credential store): ")
        if args.platform not in {'matrix','ntfy','homeassistant','irc'} and (not 16 <= len(token) <= 4096 or any(c.isspace() or ord(c) < 32 for c in token)):
            raise ValueError("invalid transport credential")
        credentials["connectors"][args.connector] = {"token": token}
        if args.platform=='irc':
            from .gateway_irc_transport import credentials as irc_credentials
            server=input('IRC TLS hostname (system-trusted certificate required): ')
            raw_port=input('IRC TLS port [6697]: ') or '6697'
            if not raw_port.isascii() or not raw_port.isdecimal() or len(raw_port)>5 or not 1<=int(raw_port)<=65535:
                raise ValueError('IRC TLS port must contain digits from 1 to 65535')
            port=int(raw_port)
            nickname=input('IRC bot nickname: ');channel=input('Exact canonical IRC channel (#channel or &channel): ')
            username=input('SASL account (empty for no account login): ')
            if not username and input('Explicitly approve no SASL login by typing ANONYMOUS: ')!='ANONYMOUS':
                raise ValueError('explicit owner approval of anonymous IRC connection required')
            password=getpass.getpass('Private SASL password: ') if username else ''
            server_password=getpass.getpass('Private server PASS password (optional): ')
            channel_password=getpass.getpass('Private channel key (optional, for +k channels): ')
            credentials['connectors'][args.connector]=irc_credentials({'server':server,'port':port,'nickname':nickname,'channel':channel,
                **({'server_password':server_password} if server_password else {}),
                **({'channel_password':channel_password} if channel_password else {}),
                **({'sasl_username':username,'sasl_password':password} if username else {})})
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
        if selected and selected['platform']=='email':
            from .initial_setup import pair_gateway_sender
            return pair_gateway_sender(args.binding,args.connector,args.sender,args.chat,args.identity,
                tuple(args.capabilities),scope=args.scope,thread=args.thread,
                allow_media=getattr(args,'allow_media',False),allow_voice=getattr(args,'allow_voice',False),
                allow_video=getattr(args,'allow_video',False),allow_outbound_media=getattr(args,'allow_outbound_media',False))
        if selected and selected['platform'] in {'line','sms'}:
            saved=credentials['connectors'][args.connector]
            destination=saved['destination'] if selected['platform']=='line' else saved['account_sid']+':'+saved['from_number']
            if binding['scope'] and binding['scope']!=destination:raise ValueError('Gateway scope differs from the saved receiving identity')
            if binding['sender']==destination:raise ValueError('Gateway sender must differ from its receiving identity')
            binding['scope']=destination
            binding['allow_media']=getattr(args,'allow_media',False)
            binding['allow_voice']=getattr(args,'allow_voice',False)
            binding['allow_video']=getattr(args,'allow_video',False)
            binding['allow_outbound_media']=getattr(args,'allow_outbound_media',False)
            if binding['allow_outbound_media'] and 'tls' not in credentials['connectors'][args.connector]:
                raise ValueError('configure public HTTPS/TLS before approving gateway output files')
            if binding['allow_voice']:
                if 'create' not in binding['capabilities']:raise ValueError('Gateway voice approval requires mission-create rights')
                from .speech_setup import status as speech_status
                speech=speech_status()
                if not all(speech[key] for key in ['enabled','runtime_ready','model_ready']):
                    raise PermissionError('configure the reviewed local speech model/service before approving gateway voice')
        elif getattr(args,'allow_media',False) or getattr(args,'allow_voice',False) or getattr(args,'allow_video',False) or getattr(args,'allow_outbound_media',False):raise ValueError('media approval applies only to reviewed LINE/SMS paths')
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
        if selected and selected['platform']=='irc':
            configured=credentials['connectors'][args.connector];expected=f"{configured['server']}:{configured['port']}"
            if binding['scope'] and binding['scope']!=expected or binding['chat']!=configured['channel']:
                raise ValueError('IRC route differs from configured TLS server/channel')
            binding['scope']=expected
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
