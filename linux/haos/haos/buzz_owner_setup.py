"""Authenticated local owner handoff; private journals stay under gateway UID."""
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
    from .gateway_buzz import credentials,authority,PreparedBuzzPolicy
    from .gateway_publication import pending
    from .sandbox import trusted_json
    config=Path('/etc/haos');secret=config/'gateway-credentials'
    own=config.lstat()
    if not stat.S_ISDIR(own.st_mode) or own.st_uid!=0 or own.st_mode&0o022 or pending(config):
        raise PermissionError('matched root-owned Buzz publication required')
    own=secret.lstat()
    if not stat.S_ISREG(own.st_mode) or own.st_uid!=0 or own.st_mode&0o077:raise PermissionError('root-private Buzz credential store required')
    raw=trusted_json(config/'gateways.json');policy=PreparedBuzzPolicy(raw);private=trusted_json(secret)
    if (not isinstance(private,dict) or not set(private)<= {'connectors','publication'} or not isinstance(private.get('connectors'),dict)
            or private.get('publication')!=raw.get('publication') or policy.connectors.get(connector,{}).get('platform')!='buzz'):
        raise PermissionError('exact matched saved Buzz connector required')
    value=credentials(private['connectors'][connector])
    authority(connector,value)
    return raw,value


def _invoke(connector,action,params):
    from .initial_setup import require_root,quiesce_for_setup
    require_root()
    from .gateway_setup import stopped_gateway
    from .gateway_buzz import authority
    from .buzz_owner_process import command,response
    from .gateway_line_ingress import _object
    from .gateway_dingtalk_admission import finite
    from .redaction import Redactor
    from .owner import audit
    quiesce_for_setup(gateway_only=True);stopped_gateway();_,value=saved(connector)
    publication=authority(connector,value);account=pwd.getpwnam('haos-gateway')
    if account.pw_uid==0 or account.pw_gid==0:raise PermissionError('Buzz owner action requires its separate private gateway identity')
    owner_uid=int(os.environ.get('SUDO_UID','0'))
    request={'action':action,'connector':connector,'credentials':value,'policy_sha256':publication,'parent_pid':os.getpid(),
        'owner_uid':owner_uid,'params':params}
    try:result=subprocess.run(command(),input=json.dumps(request,ensure_ascii=False)+'\n',text=True,capture_output=True,timeout=50,
        user=account.pw_uid,group=account.pw_gid,extra_groups=[],umask=0o077,cwd='/usr/lib/haos',
        env={'PATH':'/usr/bin:/bin','LANG':'C.UTF-8','PYTHONDONTWRITEBYTECODE':'1','HERMES_SAFE_MODE':'1'})
    except subprocess.TimeoutExpired:raise RuntimeError('Buzz-Prüfung: Zeitlimit; private Runtime, Relay und Journal prüfen.') from None
    if result.returncode or len(result.stdout.encode())>262144:raise RuntimeError('Private Buzz-Prüfung fehlgeschlagen; Runtime und Journal prüfen.')
    if Redactor([value['private_key'],value.get('auth_tag','')]).text(result.stdout)!=result.stdout:
        raise PermissionError('private material in Buzz owner response')
    checked=response(json.loads(result.stdout,object_pairs_hook=_object,parse_constant=finite),action,value)
    authority(connector,value,publication)
    audit('gateway.buzz-owner-'+action,{'connector':connector,'message_sent':False,
        **({'receipt':checked['receipt'],'note_sha256':params['note_sha256']} if 'receipt' in checked else {})})
    return checked


def inspect(connector,action='account'):
    from .initial_setup import require_root
    require_root()
    if not isinstance(action,str) or action not in {'account','outputs','outgoing'}:raise ValueError('closed no-send Buzz inspection action required')
    return _invoke(connector,action,{})


def recover_upload(connector,row,action,note,*,confirmed=False):
    from .initial_setup import require_root
    require_root()
    from .gateway_buzz import HEX
    if (not isinstance(row,dict) or any(not isinstance(row.get(key),str) or not HEX.fullmatch(row[key]) for key in ['id','snapshot_sha256'])
            or not isinstance(action,str) or action not in {'retry-upload','purge-upload'} or confirmed is not True
            or not isinstance(note,str) or not 1<=len(note.strip())<=2000):raise PermissionError('explicit inspected Buzz upload decision and review note required')
    params={'id':row['id'],'action':action,'snapshot_sha256':row['snapshot_sha256'],'owner_uid':int(os.environ.get('SUDO_UID','0')),
        'note_sha256':hashlib.sha256(note.strip().encode()).hexdigest(),'confirmed':True}
    return _invoke(connector,'decide-output',params)


def approve_reply(connector,row,note,*,confirmed=False,confirmed_not_delivered=False):
    from .initial_setup import require_root
    require_root()
    from .gateway_buzz import HEX
    if (not isinstance(row,dict) or any(not isinstance(row.get(key),str) or not HEX.fullmatch(row[key]) for key in ['delivery_id','snapshot_sha256'])
            or type(row.get('attempt')) is not int or not 1<=row['attempt']<5 or row.get('connector')!=connector
            or confirmed is not True or confirmed_not_delivered is not True or not isinstance(note,str) or not 1<=len(note.strip())<=2000):
        raise PermissionError('explicit inspected Buzz reply decision and independent non-delivery confirmation required')
    params={key:row[key] for key in ['connector','delivery_id','attempt','snapshot_sha256']}
    params.update(owner_uid=int(os.environ.get('SUDO_UID','0')),note_sha256=hashlib.sha256(note.strip().encode()).hexdigest(),
        confirmed=True,confirmed_not_delivered=True)
    return _invoke(connector,'approve-retry',params)
