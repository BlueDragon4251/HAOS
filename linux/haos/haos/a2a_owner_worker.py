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




def sources(current,cursor='',credential_scope=None,policy=None):
    from .a2a_owner_process import cursor_value,cursor_token
    start_profile,start_peer,start_task=cursor_value(cursor)
    from .a2a_owner_records import readonly,task_summary
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
                        result.append(task_summary(profile,peer,db,row,credential_scope,policy))
                finally:db.close()
        finally:os.close(lease)
    return {'tasks':result,'has_more':False,'cursor':'','message_sent':False,'mission_created':False}


def main():
    from .gateway_runtime import require_runtime_identity,prepare_runtime_home
    require_runtime_identity()
    if sys.version_info[:2]!=(3,11):raise PermissionError('pinned private Python 3.11 required')
    parent=os.getppid();libc=ctypes.CDLL(None,use_errno=True)
    if libc.prctl(1,signal.SIGKILL,0,0,0)!=0 or os.getppid()!=parent:raise PermissionError('private owner parent lifetime guard required')
    if libc.prctl(38,1,0,0,0)!=0:raise PermissionError('private owner worker must deny new executable privileges')
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
            or request['action'] not in {'inspect','sources','retry-source-auth','purge-source-inputs','purge-task-outputs'} or type(request['parent_pid']) is not int or request['parent_pid']!=parent
            or os.getppid()!=parent or not isinstance(request['policy_sha256'],str) or not re.fullmatch('[0-9a-f]{64}',request['policy_sha256'])):
        raise ValueError('closed private A2A owner action required')
    if not isinstance(request['params'],dict):raise ValueError('closed A2A owner parameters required')
    if request['action'] in {'inspect','sources'}:
        if (request['params']!={} if request['action']=='inspect' else set(request['params'])!={'cursor'}):raise ValueError('closed A2A inspection parameters required')
    else:
        from .a2a_owner_recovery import parameters
        parameters(request['params'])
    from .gateway_a2a import credentials,authority
    try:
        value=credentials(request['credentials'],verify_tls=request['action']=='inspect')
        def current():authority(request['connector'],value,request['policy_sha256'])
        current();prepare_runtime_home()
        if request['action']!='inspect':
            from .gateway import digest
            from .gateway_a2a import PreparedA2APolicy
            from .sandbox import trusted_json
            policy=PreparedA2APolicy(trusted_json(Path('/etc/haos/gateways.json')))
            if request['action']=='sources':result=sources(current,request['params']['cursor'],digest([request['connector'],value]),policy)
            else:
                from .a2a_owner_recovery import recover
                from .redaction import Redactor
                private=[*value['peer_tokens'].values(),value['tls']['private_key'],*[item['secret'] for item in value.get('callbacks',{}).values()]]
                result=recover(request['action'],request['params'],current,request['connector'],value,request['policy_sha256'],policy,Redactor(private))
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
