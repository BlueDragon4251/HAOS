"""One stopped-service recovery action under the private gateway UID; no SDK."""
import ctypes
import json
import os
from pathlib import Path
import resource
import signal
import sqlite3
import sys


def main():
    from .gateway_runtime import require_runtime_identity,prepare_runtime_home
    require_runtime_identity()
    if sys.version_info[:2]!=(3,11):raise PermissionError('pinned private Python 3.11 required')
    parent=os.getppid()
    if parent<=1:raise PermissionError('actual live authenticated Root handoff parent required')
    libc=ctypes.CDLL(None,use_errno=True)
    if libc.prctl(1,signal.SIGKILL,0,0,0)!=0 or os.getppid()!=parent:raise PermissionError('Owner parent lifetime guard required')
    if libc.prctl(38,1,0,0,0)!=0:raise PermissionError('private Owner worker must deny executable privilege changes')
    def root_parent():
        if os.getppid()!=parent or parent<=1:raise PermissionError('authenticated Owner parent was lost')
        status=Path('/proc/'+str(parent)+'/status').read_text()
        if next(line for line in status.splitlines() if line.startswith('Uid:')).split()[1:]!=['0']*4:
            raise PermissionError('Google Chat Owner action requires its actual authenticated Root parent')
    root_parent();resource.setrlimit(resource.RLIMIT_CORE,(0,0));resource.setrlimit(resource.RLIMIT_CPU,(15,15))
    resource.setrlimit(resource.RLIMIT_AS,(768*1024*1024,768*1024*1024));signal.signal(signal.SIGALRM,lambda *_:os._exit(124));signal.alarm(40)
    from .gateway_line_ingress import _object
    from .gateway_dingtalk_admission import finite
    from .gateway_google_chat import credentials,authority,PreparedGoogleChatPolicy,scope
    from .gateway_google_chat_recovery import HEX,profile_name
    from .google_chat_owner_process import ACTIONS,response
    from .sandbox import trusted_json
    raw=sys.stdin.buffer.read(65537)
    if len(raw)>65536:raise ValueError('bounded Google Chat Owner request required')
    request=json.loads(raw,object_pairs_hook=_object,parse_constant=finite)
    if (not isinstance(request,dict) or set(request)!={'action','connector','credentials','policy_sha256','parent_pid','params','owner_uid'}
            or not isinstance(request['action'],str) or request['action'] not in ACTIONS
            or not isinstance(request['connector'],str) or type(request['parent_pid']) is not int or request['parent_pid']!=parent
            or not isinstance(request['policy_sha256'],str) or not HEX.fullmatch(request['policy_sha256'])
            or type(request['owner_uid']) is not int or not 0<=request['owner_uid']<2**32-1 or not isinstance(request['params'],dict)):
        raise PermissionError('closed authenticated private Google Chat Owner action required')
    action=request['action'];params=request['params'];connector=request['connector'];value=credentials(request['credentials'])
    if action in {'source-profiles','outgoing'}:
        if params:raise ValueError('Google Chat inventory takes no implicit selector')
    elif action=='sources':
        if set(params)!={'profile'}:raise ValueError('one exact Google Chat source profile required')
    elif params.get('owner_uid')!=request['owner_uid']:raise PermissionError('Google Chat decision changed its authenticated Owner actor')
    def current():
        root_parent();authority(connector,value,request['policy_sha256'])
        return PreparedGoogleChatPolicy(trusted_json(Path('/etc/haos/gateways.json')))
    from .redaction import Redactor
    aliases=[value['service_account']['private_key']]
    if value['inbound']['mode']=='http':aliases.append(value['inbound']['tls']['private_key'])
    redactor=Redactor(aliases);lease=None;inbox=None;store=None
    try:
        current();prepare_runtime_home()
        from .gateway_line_profile import _directory
        from .gateway_matrix_profile import acquire_lease
        from .gateway import digest
        profiles=Path('/var/lib/haos-gateway/profiles');profile=None
        selected=params.get('profile')
        if selected is not None:profile_name(selected)
        if profiles.exists():
            _directory(profiles);profile=profiles/(selected or 'google-chat-'+digest(scope(value)))
            if profile.exists():lease=acquire_lease(profile)
        if action=='source-profiles':
            names=[]
            if profiles.exists():
                for path in profiles.iterdir():
                    if path.name.startswith('google-chat-'):
                        profile_name(path.name);_directory(path);names.append(path.name)
                        if len(names)>65536:raise ValueError('Google Chat profile history exceeds bound')
            result={'profiles':sorted(names)[:128],'history_truncated':len(names)>128,'network_requested':False,'private_bytes_returned':False}
        elif action in {'sources','purge-source'}:
            from .gateway_google_chat_custody import Originals
            from .gateway_google_chat_recovery import sources,purge_source
            if profile is None or not (profile/'originals.sqlite').exists():
                if action=='purge-source':raise PermissionError('retained Google Chat original required')
                result={'profile':selected,'sources':[],'history_truncated':False,'network_requested':False,'private_bytes_returned':False}
            else:
                store=Originals(profile/'originals.sqlite',redactor)
                result=sources(store,current(),profile.name) if action=='sources' else purge_source(store,current(),params)
        else:
            from .gateway_raw import NativeInbox
            from .gateway_google_chat_recovery import outgoing,approve_retry,retry_auth
            from .gateway_google_chat_text import TextLedger
            database=Path('/var/lib/haos-gateway/native-inbox.db')
            if not database.exists():
                if action=='outgoing':result={'outgoing':[],'history_truncated':False,'network_requested':False,'private_bytes_returned':False}
                else:raise PermissionError('retained Google Chat private journal required for decision')
            else:
                inbox=NativeInbox(database,redactor);TextLedger(inbox,connector,value,current,current)
                if action=='outgoing':result=outgoing(inbox,current(),connector,value)
                elif action=='retry-auth':result=retry_auth(inbox,current(),connector,value,params)
                else:result=approve_retry(inbox,current(),connector,value,params)
        current();checked=response(result,action,connector);encoded=json.dumps(checked,ensure_ascii=False,allow_nan=False)
        if len(encoded.encode())>262144 or redactor.text(encoded)!=encoded:raise PermissionError('bounded nonprivate Google Chat Owner result required')
        print(encoded)
    except PermissionError:print(json.dumps({'error':'authority-refused'}))
    except (ImportError,ModuleNotFoundError):print(json.dumps({'error':'runtime-unavailable'}))
    except (ValueError,OSError,sqlite3.Error,KeyError,TypeError):print(json.dumps({'error':'storage-unavailable'}))
    finally:
        if inbox is not None:inbox.close()
        if store is not None:store.close()
        if lease is not None:os.close(lease)


if __name__=='__main__':main()
