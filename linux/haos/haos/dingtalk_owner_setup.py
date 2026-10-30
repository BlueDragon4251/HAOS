"""Root owner setup and no-send account inspection; private keys stay in the broker UID."""
import json
import os
import pwd
import re
import subprocess

from .gateway import GatewayPolicy
from .gateway_dingtalk import credentials,authority,scope


def configure(connector,value):
    from .initial_setup import require_root,quiesce_for_setup
    from .gateway_setup import load,persist
    from .owner import audit
    require_root();value=credentials(value)
    policy,private=load()
    if any(row['id']!=connector and row['platform']=='dingtalk' for row in policy['connectors']):
        raise ValueError('one isolated adapter per platform is currently supported')
    if any(row['id']==connector and row['platform']!='dingtalk' for row in policy['connectors']):
        policy['bindings']=[row for row in policy['bindings'] if row['connector']!=connector]
    policy['connectors']=[row for row in policy['connectors'] if row['id']!=connector]+[{'id':connector,'platform':'dingtalk'}]
    GatewayPolicy(policy);quiesce_for_setup(gateway_only=True)
    private['connectors'][connector]=value;persist(policy,private)
    audit('setup.gateway',{'connector':connector,'platform':'dingtalk'})
    return {'configured':True,'platform':'dingtalk','sender_pairing_required':True,'restart_required':True,
        'external_reachability_verified':False,'corp_identity_verified':False,'robot_identity_verified':False}


def inspect(connector):
    if os.geteuid()!=0:raise PermissionError('authenticated owner required for DingTalk account inspection')
    from .gateway_setup import load,stopped_gateway
    from .gateway_dingtalk_process import command,response
    from .gateway_dingtalk_admission import finite
    from .gateway_line_ingress import _object
    from .owner import audit
    if os.geteuid()!=0:raise PermissionError('authenticated owner required for DingTalk account inspection')
    from .initial_setup import quiesce_for_setup
    quiesce_for_setup(gateway_only=True);stopped_gateway();policy,private=load()
    if not any(row['id']==connector and row['platform']=='dingtalk' for row in policy['connectors']):
        raise ValueError('select one saved DingTalk connector')
    value=credentials(private['connectors'][connector]);publication=authority(connector,value)
    account=pwd.getpwnam('haos-gateway')
    if account.pw_uid==0 or account.pw_gid==0:raise PermissionError('private account inspection must drop root')
    request={'action':'account','connector':connector,'credentials':value,'policy_sha256':publication,'parent_pid':os.getpid()}
    try:
        result=subprocess.run(command(),input=json.dumps(request,ensure_ascii=False)+'\n',text=True,
            capture_output=True,timeout=35,user=account.pw_uid,group=account.pw_gid,extra_groups=[],umask=0o077,
            cwd='/usr/lib/haos',env={'PATH':'/usr/bin:/bin','LANG':'C.UTF-8','PYTHONDONTWRITEBYTECODE':'1','HERMES_SAFE_MODE':'1'})
    except subprocess.TimeoutExpired:raise RuntimeError('DingTalk-Kontoprüfung: Zeitlimit; Netzwerk und App-Rechte prüfen.') from None
    if result.returncode or len(result.stdout.encode())>16384:
        raise RuntimeError('DingTalk-Kontoprüfung fehlgeschlagen; private Runtime, Netzwerk und Konto prüfen.')
    checked=response(json.loads(result.stdout,object_pairs_hook=_object,parse_constant=finite),value)
    authority(connector,value,publication)
    audit('gateway.dingtalk-account-inspected',{'connector':connector,'app_authenticated':'error' not in checked,
        **({'error':checked['error']} if 'error' in checked else {})})
    return {**checked,'sender_grants_changed':False,'external_delivery_verified':False}


def recovery(row,action,note,confirmed=False,*,confirmed_not_accepted=False):
    from .initial_setup import require_root
    from .gateway_setup import owner_gateway
    from types import SimpleNamespace
    require_root()
    if (not isinstance(row,dict) or action not in {'approve-dingtalk-retry','approve-dingtalk-part-retry','purge-dingtalk-source','purge-dingtalk-output-cache'}
            or confirmed is not True or not isinstance(note,str) or not 1<=len(note.strip())<=2000):
        raise PermissionError('exact inspected DingTalk owner decision and non-secret note required')
    args={'gateway_action':action,'note':note,'confirm_inspected':True,'snapshot_sha256':row.get('snapshot_sha256')}
    if action=='purge-dingtalk-source':args.update(profile=row.get('profile'),kind=row.get('kind'),id=row.get('id'))
    elif action=='purge-dingtalk-output-cache':args['id']=row.get('id')
    else:
        args.update(connector=row.get('connector'),delivery_id=row.get('delivery_id'),attempt=row.get('attempt'),
            confirm_not_accepted=confirmed_not_accepted)
        if action=='approve-dingtalk-part-retry':args.update(part=row.get('part'),operation=row.get('operation'))
    from .initial_setup import quiesce_for_setup
    quiesce_for_setup(gateway_only=True)
    return owner_gateway(SimpleNamespace(**args))


def sources(profile=None,kind=None):
    from .initial_setup import require_root
    from .gateway_setup import owner_gateway
    from types import SimpleNamespace
    require_root()
    if profile is not None and (not isinstance(profile,str) or not re.fullmatch('dingtalk-[0-9a-f]{64}',profile)):raise ValueError('opaque DingTalk profile required')
    if kind is not None and (profile is None or not isinstance(kind,str) or kind not in {'original'}):raise ValueError('exact DingTalk source kind required')
    from .initial_setup import quiesce_for_setup
    quiesce_for_setup(gateway_only=True)
    return owner_gateway(SimpleNamespace(gateway_action='dingtalk-sources',profile=profile,kind=kind))


def retry_auth(connector):
    from .initial_setup import require_root
    from .gateway_setup import owner_gateway
    from types import SimpleNamespace
    require_root()
    if not isinstance(connector,str) or not re.fullmatch('[a-zA-Z0-9][a-zA-Z0-9_.:-]{0,127}',connector):raise ValueError('exact saved DingTalk connector required')
    from .initial_setup import quiesce_for_setup
    quiesce_for_setup(gateway_only=True)
    return owner_gateway(SimpleNamespace(gateway_action='retry-dingtalk-auth',connector=connector,
        note='Owner requested a new DingTalk authentication check'))


def outputs():
    from .initial_setup import require_root,quiesce_for_setup
    from .gateway_setup import owner_gateway
    from types import SimpleNamespace
    require_root();quiesce_for_setup(gateway_only=True)
    return owner_gateway(SimpleNamespace(gateway_action='dingtalk-output-cache'))


def observe(connector,observation):
    """Explicit no-send challenge observation; owner must separately approve IDs."""
    from .initial_setup import require_root,quiesce_for_setup
    require_root()
    from .gateway_setup import load,stopped_gateway
    from .gateway_dingtalk_process import command
    from .gateway_dingtalk_pairing import challenge
    from .gateway_dingtalk_admission import finite
    from .gateway_line_ingress import _object
    from .owner import audit
    import signal
    require_root();observation=challenge(observation)
    quiesce_for_setup(gateway_only=True);stopped_gateway();policy,private=load()
    if not any(row['id']==connector and row['platform']=='dingtalk' for row in policy['connectors']):
        raise ValueError('select one saved DingTalk connector')
    value=credentials(private['connectors'][connector]);publication=authority(connector,value)
    account=pwd.getpwnam('haos-gateway')
    if account.pw_uid==0 or account.pw_gid==0:raise PermissionError('pairing observation must drop root')
    args=command();args[-1]='haos.gateway_dingtalk_pairing_worker'
    payload=json.dumps({'connector':connector,'credentials':value,'policy_sha256':publication,
        'parent_pid':os.getpid(),'observation':observation},ensure_ascii=False)
    process=subprocess.Popen(args,stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,
        user=account.pw_uid,group=account.pw_gid,extra_groups=[],umask=0o077,start_new_session=True,cwd='/usr/lib/haos',
        env={'PATH':'/usr/bin:/bin','LANG':'C.UTF-8','PYTHONDONTWRITEBYTECODE':'1','HERMES_SAFE_MODE':'1'})
    try:
        out,_err=process.communicate(payload,timeout=80)
        if process.returncode or len(out.encode())>16384:raise RuntimeError('DingTalk-Zuordnung fehlgeschlagen; Konto, Verbindung und Erfassungszeit prüfen.')
    except BaseException:
        if process.poll() is None:
            try:os.killpg(process.pid,signal.SIGKILL)
            except ProcessLookupError:pass
        process.communicate();raise
    checked=json.loads(out,object_pairs_hook=_object,parse_constant=finite)
    authority(connector,value,publication)
    if not isinstance(checked,dict) or checked.get('sender_grants_changed') is not False:raise ValueError('untrusted observation response')
    if checked.get('observed') is True:
        from .gateway import digest
        from .gateway_dingtalk import identity
        item=checked.get('candidate');proof=checked.get('observation_receipt_sha256')
        if (set(checked)!={'observed','candidate','observation_receipt_sha256','sender_grants_changed','external_delivery_verified'}
                or checked['external_delivery_verified'] is not False or not isinstance(item,dict)
                or set(item)!={'sender','chat','scope','thread','message_id','conversation_type','created_at','source_sha256',
                    'challenge_sha256','authorized','mission_created','message_sent'}
                or any(item[k] is not False for k in ['authorized','mission_created','message_sent'])
                or item['scope']!=scope(value) or item['thread']!='' or item['conversation_type'] not in {'1','2'}
                or type(item['created_at']) is not int or not observation['since']<item['created_at']<=observation['until']
                or item['challenge_sha256']!=digest(observation) or proof!=digest([connector,digest(observation)])
                or not isinstance(item['source_sha256'],str) or not re.fullmatch('[0-9a-f]{64}',item['source_sha256'])):
            raise ValueError('exact retained observation result required')
        for key in ['sender','chat','message_id']:identity(item[key])
        audit('gateway.dingtalk-identity-observed',{'connector':connector,'receipt_sha256':proof,'sender_grants_changed':False})
    elif (set(checked)!={'observed','error','sender_grants_changed','message_sent','mission_created'}
            or checked['observed'] is not False or checked['error']!='observation-timeout'
            or checked['message_sent'] is not False or checked['mission_created'] is not False):
        raise ValueError('finite no-send observation timeout required')
    return checked
