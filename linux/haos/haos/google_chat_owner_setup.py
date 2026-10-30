"""Prepared authenticated Root handoff; private recovery journals keep their UID."""
import hashlib
import json
import os
from pathlib import Path
import pwd
import stat
import subprocess


def saved(connector):
    from .initial_setup import require_root
    require_root()
    from .gateway_google_chat import credentials,authority,PreparedGoogleChatPolicy,scope
    from .gateway_publication import pending
    from .sandbox import trusted_json
    config=Path('/etc/haos');secret=config/'gateway-credentials';own=config.lstat()
    if not stat.S_ISDIR(own.st_mode) or own.st_uid!=0 or own.st_mode&0o022 or pending(config):
        raise PermissionError('matched root-owned Google Chat publication required')
    own=secret.lstat()
    if not stat.S_ISREG(own.st_mode) or own.st_uid!=0 or own.st_mode&0o077:raise PermissionError('Root-private Google Chat credential store required')
    raw=trusted_json(config/'gateways.json');policy=PreparedGoogleChatPolicy(raw);private=trusted_json(secret)
    if (not isinstance(private,dict) or set(private) not in ({'connectors'},{'connectors','publication'})
            or not isinstance(private.get('connectors'),dict) or set(private['connectors'])!=set(policy.connectors)
            or private.get('publication')!=raw.get('publication') or policy.connectors.get(connector,{}).get('platform')!='google_chat'):
        raise PermissionError('exact matched saved Google Chat connector required')
    value=credentials(private['connectors'][connector])
    if any(name!=connector and row['platform']=='google_chat' and scope(credentials(private['connectors'][name]))==scope(value)
            for name,row in policy.connectors.items()):raise PermissionError('Google Chat account cannot belong to multiple connectors')
    authority(connector,value);return raw,value


def _invoke(connector,action,params):
    from .initial_setup import require_root,quiesce_for_setup
    require_root()
    from .gateway_setup import stopped_gateway
    from .gateway_google_chat import authority
    from .google_chat_owner_process import command,response
    from .gateway_line_ingress import _object
    from .gateway_dingtalk_admission import finite
    from .redaction import Redactor
    from .owner import audit
    quiesce_for_setup(gateway_only=True);stopped_gateway();_,value=saved(connector)
    publication=authority(connector,value);account=pwd.getpwnam('haos-gateway')
    if account.pw_uid==0 or account.pw_gid==0:raise PermissionError('separate private Google Chat identity required')
    request={'action':action,'connector':connector,'credentials':value,'policy_sha256':publication,'parent_pid':os.getpid(),
        'owner_uid':int(os.environ.get('SUDO_UID','0')),'params':params}
    try:
        result=subprocess.run(command(),input=json.dumps(request,ensure_ascii=False)+'\n',text=True,capture_output=True,timeout=45,
            user=account.pw_uid,group=account.pw_gid,extra_groups=[],umask=0o077,cwd='/usr/lib/haos',
            env={'PATH':'/usr/bin:/bin','LANG':'C.UTF-8','PYTHONDONTWRITEBYTECODE':'1','HERMES_SAFE_MODE':'1'})
    except subprocess.TimeoutExpired:raise RuntimeError('Google-Chat-Recovery: Zeitlimit; Runtime und privates Journal prüfen.') from None
    if result.returncode or len(result.stdout.encode())>262144:raise RuntimeError('Private Google-Chat-Recovery fehlgeschlagen; Runtime und Journal prüfen.')
    aliases=[value['service_account']['private_key']]
    if value['inbound']['mode']=='http':aliases.append(value['inbound']['tls']['private_key'])
    if Redactor(aliases).text(result.stdout)!=result.stdout:raise PermissionError('private material in Google Chat Owner response')
    checked=response(json.loads(result.stdout,object_pairs_hook=_object,parse_constant=finite),action,connector)
    authority(connector,value,publication)
    audit('gateway.google-chat-owner-'+action,{'connector':connector,'message_sent':False,'network_requested':False,
        **({'receipt':checked['receipt'],'note_sha256':params['note_sha256']} if 'receipt' in checked else {})})
    return checked


def inspect(connector,action='outgoing',*,profile=None):
    from .initial_setup import require_root
    require_root()
    if not isinstance(action,str) or action not in {'source-profiles','sources','outgoing'}:raise ValueError('closed no-network Google Chat inspection required')
    params={}
    if action=='sources':
        from .gateway_google_chat_recovery import profile_name
        from .gateway_google_chat import scope
        from .gateway import digest
        if profile is None:_,value=saved(connector);profile='google-chat-'+digest(scope(value))
        params={'profile':profile_name(profile)}
    elif profile is not None:raise ValueError('Google Chat profile selector only applies to original inspection')
    return _invoke(connector,action,params)


def _decision(note,confirmed):
    from .initial_setup import require_root
    require_root()
    if confirmed is not True or not isinstance(note,str) or not 1<=len(note.strip())<=2000:
        raise PermissionError('Google-Chat-Entscheidung ausdrücklich bestätigen und begründen.')
    return {'owner_uid':int(os.environ.get('SUDO_UID','0')),'note_sha256':hashlib.sha256(note.strip().encode()).hexdigest(),'confirmed':True}


def retry_auth(connector,note,*,confirmed=False):
    return _invoke(connector,'retry-auth',{'connector':connector,**_decision(note,confirmed)})


def purge_source(connector,row,note,*,confirmed=False):
    params=_decision(note,confirmed)
    from .gateway_google_chat_recovery import HEX,profile_name
    if (not isinstance(row,dict) or any(not isinstance(row.get(k),str) or not HEX.fullmatch(row[k]) for k in ['id','snapshot_sha256'])
            or row.get('purge_allowed') is not True):raise PermissionError('exact inspected withdrawn Google Chat original required')
    params.update({k:row[k] for k in ['id','snapshot_sha256']});params['profile']=profile_name(row.get('profile'))
    return _invoke(connector,'purge-source',params)


def approve_reply(connector,row,part_id,note,*,confirmed=False,confirmed_not_delivered=False):
    params=_decision(note,confirmed)
    from .gateway_google_chat_recovery import HEX
    if (not isinstance(row,dict) or row.get('connector')!=connector or confirmed_not_delivered is not True
            or any(not isinstance(row.get(k),str) or not HEX.fullmatch(row[k]) for k in ['id','snapshot_sha256'])
            or not isinstance(part_id,str) or not HEX.fullmatch(part_id)):
        raise PermissionError('exact inspected Google Chat reply part and independent non-delivery confirmation required')
    params.update({k:row[k] for k in ['id','snapshot_sha256']});params.update(connector=connector,part_id=part_id,confirmed_not_delivered=True)
    return _invoke(connector,'approve-retry',params)
