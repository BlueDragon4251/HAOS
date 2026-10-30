"""One-shot no-send A2A inspection under the real gateway UID, never root."""
import ctypes
import json
import math
import os
from pathlib import Path
import re
import resource
import signal
import socket
import sqlite3
import stat
import sys


def readonly(path):
    base=Path('/var/lib/haos-gateway');path=Path(path)
    if base not in path.parents:raise PermissionError('fixed private A2A journal namespace required')
    directory=path.parent
    while True:
        info=directory.lstat()
        if not stat.S_ISDIR(info.st_mode) or info.st_uid!=os.geteuid() or info.st_mode&0o077:
            raise PermissionError('private A2A journal ancestry required')
        if directory==base:break
        directory=directory.parent
    for candidate in [path,path.with_name(path.name+'-wal'),path.with_name(path.name+'-shm')]:
        try:info=candidate.lstat()
        except FileNotFoundError:
            if candidate==path:raise
            continue
        if not stat.S_ISREG(info.st_mode) or info.st_uid!=os.geteuid() or info.st_mode&0o077 or info.st_nlink!=1:
            raise PermissionError('private single-link A2A journal required')
    db=sqlite3.connect('file:'+str(path)+'?mode=ro',uri=True);db.row_factory=sqlite3.Row;db.execute('PRAGMA query_only=ON');return db


def resources(profile,row):
    db=readonly(profile/'originals.db')
    try:
        original=db.execute('SELECT source_key,binding_digest,credential_scope,length(data) AS bytes FROM a2a_raw_events WHERE id=?',(row['raw_id'],)).fetchone()
        if original is None or any(original[key]!=row[key] for key in ['source_key','binding_digest','credential_scope']):raise ValueError('native A2A original source mapping changed')
        tables={item[0] for item in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        entries=db.execute('SELECT state,attempt,next_attempt FROM a2a_input_resources WHERE raw_id=?',(row['raw_id'],)).fetchall() if 'a2a_input_resources' in tables else []
        states={};attempt=0;retry_at=0
        if len(entries)>4:raise ValueError('bounded A2A resource inventory required')
        for item in entries:
            if (item['state'] not in {'prepared','retained','authentication-refused','rate-limited','transport-unavailable','source-unavailable','private-reflection'}
                    or type(item['attempt']) is not int or not 0<=item['attempt']<=8 or type(item['next_attempt']) not in {int,float}
                    or not math.isfinite(item['next_attempt']) or item['next_attempt']<0):raise ValueError('finite retained A2A resource status required')
            states[item['state']]=states.get(item['state'],0)+1;attempt=max(attempt,item['attempt']);retry_at=max(retry_at,item['next_attempt'])
        return {'original_retained':original['bytes']>0,'resources':states,'resource_attempts':attempt,'resource_retry_at':retry_at}
    finally:db.close()


def sources(current,cursor='',credential_scope=None,policy=None):
    from .a2a_owner_process import cursor_value,cursor_token
    start_profile,start_peer,start_task=cursor_value(cursor)
    from .gateway import digest
    from .gateway_matrix_profile import acquire_lease
    parent=Path('/var/lib/haos-gateway/profiles');result=[]
    if not parent.exists():return {'tasks':[],'has_more':False,'cursor':'','message_sent':False,'mission_created':False}
    info=parent.lstat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid!=os.geteuid() or info.st_mode&0o077:raise PermissionError('private gateway profile directory required')
    profiles=sorted(path for path in parent.iterdir() if re.fullmatch('a2a-[0-9a-f]{64}',path.name))
    if len(profiles)>65536:raise ValueError('bounded A2A profile history required')
    for profile_index,profile in enumerate(profiles):
        if profile_index<start_profile:continue
        current();lease=acquire_lease(profile)
        try:
            peers=sorted(path for path in profile.iterdir() if re.fullmatch('peer-[0-9a-f]{64}',path.name))
            if len(peers)>16:raise PermissionError('bounded retained A2A peer inventory required')
            for peer_index,peer in enumerate(peers):
                if profile_index==start_profile and peer_index<start_peer:continue
                task_offset=start_task if (profile_index,peer_index)==(start_profile,start_peer) else 0
                if not (peer/'tasks.db').exists():continue
                db=readonly(peer/'tasks.db')
                try:
                    for task_index,row in enumerate(db.execute('SELECT * FROM a2a_tasks ORDER BY updated_at DESC,task_id LIMIT 33 OFFSET ?',(task_offset,))):
                        current()
                        if len(result)>=32:
                            return {'tasks':result,'has_more':True,'cursor':cursor_token([profile_index,peer_index,task_offset+task_index]),'message_sent':False,'mission_created':False}
                        if (not isinstance(row['record'],str) or len(row['record'].encode())>65536
                                or row['record_sha256']!=digest([row['source_key'],row['raw_id'],row['binding_digest'],row['credential_scope'],row['record']])):
                            raise ValueError('damaged retained native A2A source proof')
                        from .gateway_line_ingress import _object
                        from .gateway_dingtalk_admission import finite
                        record=json.loads(row['record'],object_pairs_hook=_object,parse_constant=finite)
                        if (record.get('task_id')!=row['task_id'] or record.get('peer')!=row['peer'] or record.get('context_id')!=row['context_id']
                                or json.dumps(record,sort_keys=True,separators=(',',':'),ensure_ascii=False)!=row['record']
                                or row['admitted_receipt'] not in {'',row['source_key']}
                                or not re.fullmatch('task-[0-9a-f]{16}',row['task_id'])
                                or not re.fullmatch('[A-Za-z0-9][A-Za-z0-9_.-]{0,63}',row['peer'])
                                or not re.fullmatch('[A-Za-z0-9][A-Za-z0-9_-]{0,127}',row['context_id'])):
                            raise ValueError('damaged retained native A2A task identity')
                        states={'TASK_STATE_SUBMITTED','TASK_STATE_WORKING','TASK_STATE_INPUT_REQUIRED','TASK_STATE_COMPLETED','TASK_STATE_FAILED','TASK_STATE_CANCELED','TASK_STATE_REJECTED'}
                        if record.get('state') not in states:raise ValueError('finite retained A2A task state required')
                        tables={item[0] for item in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
                        callbacks=dict(db.execute('SELECT state,COUNT(*) FROM a2a_callback_deliveries WHERE task_id=? GROUP BY state',(row['task_id'],)).fetchall()) if 'a2a_callback_deliveries' in tables else {}
                        uncertain=db.execute("SELECT COUNT(*) FROM a2a_task_transitions WHERE task_id=? AND state!='committed'",(row['task_id'],)).fetchone()[0]
                        controls=db.execute("SELECT COUNT(*) FROM a2a_control_intents WHERE task_id=? AND state!='committed'",(row['task_id'],)).fetchone()[0] if 'a2a_control_intents' in tables else 0
                        active=False
                        if policy is not None and credential_scope==row['credential_scope']:
                            try:policy.current_binding(dict(row));active=True
                            except PermissionError:pass
                        summary={'profile':profile.name,'peer_journal':peer.name,'task_id':row['task_id'],'peer':row['peer'],'context':row['context_id'],
                            'native_state':record['state'],'parent_admitted':row['admitted_receipt']==row['source_key'],'original_id':row['raw_id'],
                            'source_key':row['source_key'],'binding_id':row['binding_id'],'binding_digest':row['binding_digest'],
                            'credential_scope':row['credential_scope'],'current_account':credential_scope==row['credential_scope'],'current_grant':active,
                            'uncertain_transitions':uncertain,'uncertain_controls':controls,'callbacks':callbacks,**resources(profile,row)}
                        summary['snapshot_sha256']=digest(summary);result.append(summary)
                finally:db.close()
        finally:os.close(lease)
    return {'tasks':result,'has_more':False,'cursor':'','message_sent':False,'mission_created':False}


def main():
    from .gateway_runtime import require_runtime_identity,prepare_runtime_home
    require_runtime_identity()
    if sys.version_info[:2]!=(3,11):raise PermissionError('pinned private Python 3.11 required')
    parent=os.getppid();libc=ctypes.CDLL(None,use_errno=True)
    if libc.prctl(1,signal.SIGKILL,0,0,0)!=0 or os.getppid()!=parent:raise PermissionError('private owner parent lifetime guard required')
    owner_status=Path('/proc/'+str(parent)+'/status').read_text()
    uid=next(line for line in owner_status.splitlines() if line.startswith('Uid:')).split()[1:]
    if uid!=['0','0','0','0']:raise PermissionError('A2A owner worker requires its actual authenticated root parent')
    resource.setrlimit(resource.RLIMIT_CORE,(0,0));resource.setrlimit(resource.RLIMIT_CPU,(15,15))
    raw=sys.stdin.buffer.read(65537)
    if len(raw)>65536:raise ValueError('bounded private owner request required')
    from .gateway_line_ingress import _object
    from .gateway_dingtalk_admission import finite
    request=json.loads(raw,object_pairs_hook=_object,parse_constant=finite)
    if (not isinstance(request,dict) or set(request)!={'action','connector','credentials','policy_sha256','parent_pid','params'}
            or request['action'] not in {'inspect','sources'} or type(request['parent_pid']) is not int or request['parent_pid']!=parent
            or os.getppid()!=parent or not isinstance(request['policy_sha256'],str) or not re.fullmatch('[0-9a-f]{64}',request['policy_sha256'])):
        raise ValueError('closed private A2A owner action required')
    if (not isinstance(request['params'],dict) or (request['params']!={} if request['action']=='inspect' else set(request['params'])!={'cursor'})):
        raise ValueError('closed A2A inspection parameters required')
    from .gateway_a2a import credentials,authority
    try:
        value=credentials(request['credentials'],verify_tls=request['action']=='inspect')
        def current():authority(request['connector'],value,request['policy_sha256'])
        current();prepare_runtime_home()
        if request['action']=='sources':
            from .gateway import digest
            from .gateway_a2a import PreparedA2APolicy
            from .sandbox import trusted_json
            result=sources(current,request['params']['cursor'],digest([request['connector'],value]),PreparedA2APolicy(trusted_json(Path('/etc/haos/gateways.json'))))
        else:
            from plugins.platforms.a2a.adapter import A2AAdapter
            if not all(callable(getattr(A2AAdapter,name,None)) for name in ['_prepare_task','_open_push_notification','_send_push_notification','_rpc_push_config_create']):
                print(json.dumps({'error':'sdk-unavailable'}));return
            host=value['tls']['bind_host'];family=socket.AF_INET6 if ':' in host else socket.AF_INET
            try:
                with socket.socket(family,socket.SOCK_STREAM) as listener:
                    listener.setsockopt(socket.SOL_SOCKET,socket.SO_REUSEADDR,1);listener.bind((host,value['port']))
            except OSError:
                print(json.dumps({'error':'listener-unavailable'}));return
            result={'runtime_ready':True,'tls_material_valid':True,'listener_bindable':True,'external_reachability_verified':False,'message_sent':False,'mission_created':False}
        current();print(json.dumps(result,ensure_ascii=False,allow_nan=False))
    except (ImportError,ModuleNotFoundError):print(json.dumps({'error':'sdk-unavailable'}))
    except PermissionError:print(json.dumps({'error':'authority-refused'}))
    except (sqlite3.Error,ValueError,OSError):print(json.dumps({'error':'storage-unavailable'}))


if __name__=='__main__':main()
