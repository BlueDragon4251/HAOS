"""Root owner setup and no-send account inspection; private keys stay in the broker UID."""
import json
import os
import pwd
import re
import subprocess

from .gateway import GatewayPolicy
from .gateway_feishu import credentials,authority,scope


def configure(connector,value):
    from .initial_setup import require_root,quiesce_for_setup
    from .gateway_setup import load,persist
    from .owner import audit
    require_root();value=credentials(value)
    policy,private=load()
    if any(row['id']!=connector and row['platform']=='feishu' for row in policy['connectors']):
        raise ValueError('one isolated adapter per platform is currently supported')
    if any(row['id']==connector and row['platform']!='feishu' for row in policy['connectors']):
        policy['bindings']=[row for row in policy['bindings'] if row['connector']!=connector]
    policy['connectors']=[row for row in policy['connectors'] if row['id']!=connector]+[{'id':connector,'platform':'feishu'}]
    GatewayPolicy(policy);quiesce_for_setup(gateway_only=True)
    private['connectors'][connector]=value;persist(policy,private)
    audit('setup.gateway',{'connector':connector,'platform':'feishu'})
    return {'configured':True,'platform':'feishu','sender_pairing_required':True,'restart_required':True,
        'external_reachability_verified':False,'tenant_identity_verified':False}


def inspect(connector):
    if os.geteuid()!=0:raise PermissionError('authenticated owner required for Feishu account inspection')
    from .gateway_setup import load,stopped_gateway
    from .gateway_feishu_process import command,response
    from .gateway_feishu_http import finite
    from .gateway_line_ingress import _object
    from .owner import audit
    if os.geteuid()!=0:raise PermissionError('authenticated owner required for Feishu account inspection')
    from .initial_setup import quiesce_for_setup
    quiesce_for_setup(gateway_only=True);stopped_gateway();policy,private=load()
    if not any(row['id']==connector and row['platform']=='feishu' for row in policy['connectors']):
        raise ValueError('select one saved Feishu connector')
    value=credentials(private['connectors'][connector],verify_tls=False);publication=authority(connector,value)
    account=pwd.getpwnam('haos-gateway')
    if account.pw_uid==0 or account.pw_gid==0:raise PermissionError('private account inspection must drop root')
    request={'action':'account','connector':connector,'credentials':value,'policy_sha256':publication,'parent_pid':os.getpid()}
    try:
        result=subprocess.run(command(),input=json.dumps(request,ensure_ascii=False)+'\n',text=True,
            capture_output=True,timeout=35,user=account.pw_uid,group=account.pw_gid,extra_groups=[],umask=0o077,
            cwd='/usr/lib/haos',env={'PATH':'/usr/bin:/bin','LANG':'C.UTF-8','PYTHONDONTWRITEBYTECODE':'1','HERMES_SAFE_MODE':'1'})
    except subprocess.TimeoutExpired:raise RuntimeError('Feishu-Kontoprüfung: Zeitlimit; Netzwerk und App-Rechte prüfen.') from None
    if result.returncode or len(result.stdout.encode())>16384:
        raise RuntimeError('Feishu-Kontoprüfung fehlgeschlagen; private Runtime, Netzwerk und Konto prüfen.')
    checked=response(json.loads(result.stdout,object_pairs_hook=_object,parse_constant=finite),value)
    authority(connector,value,publication)
    audit('gateway.feishu-account-inspected',{'connector':connector,'bot_identity_verified':'error' not in checked,
        **({'error':checked['error']} if 'error' in checked else {})})
    return {**checked,'sender_grants_changed':False,'external_delivery_verified':False}


def recovery(row,action,note,confirmed=False,*,confirmed_not_accepted=False):
    from .initial_setup import require_root
    from .gateway_setup import owner_gateway
    from types import SimpleNamespace
    require_root()
    if (not isinstance(row,dict) or action not in {'approve-feishu-retry','approve-feishu-part-retry','purge-feishu-source'}
            or confirmed is not True or not isinstance(note,str) or not 1<=len(note.strip())<=2000):
        raise PermissionError('exact inspected Feishu owner decision and non-secret note required')
    args={'gateway_action':action,'note':note,'confirm_inspected':True,'snapshot_sha256':row.get('snapshot_sha256')}
    if action=='purge-feishu-source':args.update(profile=row.get('profile'),kind=row.get('kind'),id=row.get('id'))
    else:
        args.update(connector=row.get('connector'),delivery_id=row.get('delivery_id'),attempt=row.get('attempt'),
            confirm_not_accepted=confirmed_not_accepted)
        if action=='approve-feishu-part-retry':args.update(part=row.get('part'),operation=row.get('operation'))
    from .initial_setup import quiesce_for_setup
    quiesce_for_setup(gateway_only=True)
    return owner_gateway(SimpleNamespace(**args))


def sources(profile=None,kind=None):
    from .initial_setup import require_root
    from .gateway_setup import owner_gateway
    from types import SimpleNamespace
    require_root()
    if profile is not None and (not isinstance(profile,str) or not re.fullmatch('feishu-[0-9a-f]{64}',profile)):raise ValueError('opaque Feishu profile required')
    if kind is not None and (profile is None or not isinstance(kind,str) or kind not in {'original','webhook'}):raise ValueError('exact Feishu source kind required')
    from .initial_setup import quiesce_for_setup
    quiesce_for_setup(gateway_only=True)
    return owner_gateway(SimpleNamespace(gateway_action='feishu-sources',profile=profile,kind=kind))


def retry_auth(connector):
    from .initial_setup import require_root
    from .gateway_setup import owner_gateway
    from types import SimpleNamespace
    require_root()
    if not isinstance(connector,str) or not re.fullmatch('[a-zA-Z0-9][a-zA-Z0-9_.:-]{0,127}',connector):raise ValueError('exact saved Feishu connector required')
    from .initial_setup import quiesce_for_setup
    quiesce_for_setup(gateway_only=True)
    return owner_gateway(SimpleNamespace(gateway_action='retry-feishu-auth',connector=connector,
        note='Owner requested a new Feishu authentication check'))
