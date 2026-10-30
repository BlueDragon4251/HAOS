"""Installed private interpreter selection and finite owner worker responses."""
import os
import re
import base64
import json
import math
from pathlib import Path
import stat

ERRORS=frozenset({'sdk-unavailable','listener-unavailable','storage-unavailable','authority-refused'})


def cursor_token(value):
    return base64.urlsafe_b64encode(json.dumps(value,separators=(',',':')).encode()).decode().rstrip('=')


def cursor_value(value):
    if value=='':return [0,0,0]
    if not isinstance(value,str) or not re.fullmatch('[A-Za-z0-9_-]{1,64}',value):raise ValueError('bounded A2A inventory cursor required')
    try:decoded=json.loads(base64.b64decode(value+'='*((-len(value))%4),altchars=b'-_',validate=True))
    except (ValueError,RecursionError):raise ValueError('invalid A2A inventory cursor') from None
    if (not isinstance(decoded,list) or len(decoded)!=3 or any(type(item) is not int or not 0<=item<=65536 for item in decoded)
            or decoded[1]>16 or cursor_token(decoded)!=value):raise ValueError('canonical bounded A2A inventory cursor required')
    return decoded


def command():
    root=Path('/usr/lib/haos');python=root/'hermes/.venv/bin/python'
    for path in [root,root/'haos',root/'hermes',root/'hermes/.venv',python.parent]:
        info=path.lstat()
        if not stat.S_ISDIR(info.st_mode) or info.st_uid!=0 or info.st_mode&0o022:
            raise PermissionError('root-owned installed A2A owner runtime required')
    info=python.resolve(strict=True).lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_uid!=0 or info.st_mode&0o022:
        raise PermissionError('root-owned installed A2A interpreter required')
    return [str(python),'-E','-s','-m','haos.a2a_owner_worker']


def response(value,action):
    if isinstance(value,dict) and set(value)=={'error'}:
        if value['error'] not in ERRORS:raise ValueError('finite private A2A owner diagnostic required')
        return value
    if not isinstance(value,dict) or value.get('message_sent') is not False or value.get('mission_created') is not False:
        raise ValueError('explicit no-send/no-mission A2A owner result required')
    if action=='inspect':
        fields={'runtime_ready','tls_material_valid','listener_bindable','external_reachability_verified','message_sent','mission_created'}
        if set(value)!=fields or any(value[k] is not True for k in ['runtime_ready','tls_material_valid','listener_bindable']) or value['external_reachability_verified'] is not False:
            raise ValueError('exact no-send A2A listener inspection result required')
    elif action=='sources':
        if (set(value)!={'tasks','has_more','cursor','message_sent','mission_created'} or not isinstance(value['tasks'],list)
                or len(value['tasks'])>32 or type(value['has_more']) is not bool or not isinstance(value['cursor'],str)
                or bool(value['cursor'])!=value['has_more']):raise ValueError('bounded private A2A source inventory required')
        cursor_value(value['cursor'])
        from .gateway import digest
        states={'TASK_STATE_SUBMITTED','TASK_STATE_WORKING','TASK_STATE_INPUT_REQUIRED','TASK_STATE_COMPLETED','TASK_STATE_FAILED','TASK_STATE_CANCELED','TASK_STATE_REJECTED'}
        callback_states={'prepared','retryable','writing','acknowledged','uncertain','authentication-refused','revoked','superseded','damaged','transport-refused'}
        fields={'profile','peer_journal','task_id','peer','context','native_state','parent_admitted','original_id','source_key','binding_id','binding_digest','credential_scope','current_account','current_grant','uncertain_transitions','uncertain_controls','uncertain_results','callbacks','original_retained','resources','resource_attempts','resource_retry_at','snapshot_sha256'}
        for row in value['tasks']:
            if (not isinstance(row,dict) or set(row)!=fields or not isinstance(row['profile'],str) or not re.fullmatch('a2a-[0-9a-f]{64}',row['profile'])
                    or not isinstance(row['peer_journal'],str) or not re.fullmatch('peer-[0-9a-f]{64}',row['peer_journal'])
                    or not isinstance(row['task_id'],str) or not re.fullmatch('task-[0-9a-f]{16}',row['task_id'])
                    or not isinstance(row['peer'],str) or not re.fullmatch('[A-Za-z0-9][A-Za-z0-9_.-]{0,63}',row['peer'])
                    or row['peer_journal']!='peer-'+digest(row['peer'])
                    or not isinstance(row['context'],str) or not re.fullmatch('[A-Za-z0-9][A-Za-z0-9_-]{0,127}',row['context'])
                    or not isinstance(row['native_state'],str) or row['native_state'] not in states or type(row['parent_admitted']) is not bool
                    or any(not isinstance(row[key],str) or not re.fullmatch('[0-9a-f]{64}',row[key]) for key in ['original_id','source_key','binding_digest','credential_scope','snapshot_sha256'])
                    or not isinstance(row['binding_id'],str) or not re.fullmatch('[a-zA-Z0-9][a-zA-Z0-9_.:-]{0,127}',row['binding_id'])
                    or type(row['uncertain_transitions']) is not int or not 0<=row['uncertain_transitions']<=32
                    or type(row['uncertain_controls']) is not int or not 0<=row['uncertain_controls']<=2
                    or type(row['uncertain_results']) is not int or not 0<=row['uncertain_results']<=32
                    or type(row['current_account']) is not bool or type(row['current_grant']) is not bool or type(row['original_retained']) is not bool
                    or not isinstance(row['resources'],dict) or not set(row['resources'])<={'prepared','retained','authentication-refused','rate-limited','transport-unavailable','source-unavailable','private-reflection'}
                    or any(type(count) is not int or not 1<=count<=4 for count in row['resources'].values()) or sum(row['resources'].values())>4
                    or type(row['resource_attempts']) is not int or not 0<=row['resource_attempts']<=8
                    or type(row['resource_retry_at']) not in {int,float} or not math.isfinite(row['resource_retry_at']) or row['resource_retry_at']<0
                    or not isinstance(row['callbacks'],dict) or not set(row['callbacks'])<=callback_states
                    or any(type(count) is not int or not 0<=count<=32 for count in row['callbacks'].values())
                    or row['snapshot_sha256']!=digest({key:item for key,item in row.items() if key!='snapshot_sha256'})):
                raise ValueError('exact finite retained A2A source snapshot required')
    elif action in {'retry-source-auth','purge-source-inputs','purge-task-outputs'}:
        if (set(value)!={'action','receipt','affected','removed_bytes','message_sent','mission_created'} or value['action']!=action
                or not isinstance(value['receipt'],str) or not re.fullmatch('[0-9a-f]{64}',value['receipt'])
                or type(value['affected']) is not int or not 0<=value['affected']<=129
                or type(value['removed_bytes']) is not int or not 0<=value['removed_bytes']<=65*1024*1024
                or action=='retry-source-auth' and (not 1<=value['affected']<=4 or value['removed_bytes']!=0)):
            raise ValueError('finite no-send A2A recovery receipt required')
    else:raise ValueError('unsupported private A2A owner action')
    return value
