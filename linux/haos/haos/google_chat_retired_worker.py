"""One authenticated Root historical-account handoff; no service-account key input."""
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
    if libc.prctl(1,signal.SIGKILL,0,0,0)!=0 or os.getppid()!=parent:raise PermissionError('Root parent lifetime guard required')
    if libc.prctl(38,1,0,0,0)!=0:raise PermissionError('private historical worker must deny privilege changes')
    def root_parent():
        if os.getppid()!=parent:raise PermissionError('authenticated Owner parent lost')
        fields=next(line for line in Path('/proc/'+str(parent)+'/status').read_text().splitlines() if line.startswith('Uid:')).split()[1:]
        if fields!=['0']*4:raise PermissionError('actual authenticated Root parent required')
    root_parent();resource.setrlimit(resource.RLIMIT_CORE,(0,0));resource.setrlimit(resource.RLIMIT_CPU,(15,15))
    resource.setrlimit(resource.RLIMIT_AS,(768*1024*1024,768*1024*1024));signal.signal(signal.SIGALRM,lambda *_:os._exit(124));signal.alarm(40)
    from .gateway import Conflict,digest
    from .gateway_line_ingress import _object
    from .gateway_dingtalk_admission import finite
    from .gateway_google_chat_recovery import HEX,profile_name
    from .google_chat_retired_process import ACTIONS,policy_snapshot,response,current_policy,file_grants
    raw=sys.stdin.buffer.read(65537)
    if len(raw)>65536:raise ValueError('bounded historical Google request required')
    request=json.loads(raw,object_pairs_hook=_object,parse_constant=finite)
    if (not isinstance(request,dict) or set(request)!={'action','policy_sha256','parent_pid','owner_uid','params'}
            or not isinstance(request['action'],str) or request['action'] not in ACTIONS or request['parent_pid']!=parent
            or type(request['parent_pid']) is not int or type(request['owner_uid']) is not int or not 0<=request['owner_uid']<2**32-1
            or not isinstance(request['policy_sha256'],str) or not HEX.fullmatch(request['policy_sha256']) or not isinstance(request['params'],dict)):
        raise PermissionError('closed authenticated historical Google request required')
    action=request['action'];params=request['params']
    if action=='profiles':
        if params:raise ValueError('historical profile inventory takes no selector')
    elif action=='tokens':
        if set(params)!={'profile'}:raise ValueError('one exact historical profile required')
        profile_name(params['profile'])
    else:
        if (set(params)!={'profile','identity_sha256','id','generation','owner_uid','note_sha256','confirmed'}
                or params['owner_uid']!=request['owner_uid'] or params['confirmed'] is not True
                or any(not isinstance(params[k],str) or not HEX.fullmatch(params[k]) for k in ['identity_sha256','id','note_sha256'])
                or type(params['generation']) is not int or not 1<=params['generation']<2**53):
            raise PermissionError('closed explicitly confirmed historical token withdrawal required')
        profile_name(params['profile'])
    def current():
        root_parent()
        if policy_snapshot()!=request['policy_sha256']:raise PermissionError('Root gateway policy changed during historical Owner action')
    from .redaction import Redactor
    redactor=Redactor([]);lease=None;inbox=None
    import logging
    from .gateway_runtime import SafeFormatter
    handler=logging.StreamHandler();handler.setFormatter(SafeFormatter(redactor));logging.basicConfig(level=logging.WARNING,handlers=[handler],force=True)
    try:
        current();prepare_runtime_home()
        from .gateway_line_profile import _directory
        from .gateway_matrix_profile import acquire_lease
        from .gateway_google_chat_identity import load,account_scope
        profiles=Path('/var/lib/haos-gateway/profiles')
        if profiles.exists():_directory(profiles)
        if action=='profiles':
            rows=[];missing=[];count=0
            if profiles.exists():
                for profile in sorted(profiles.iterdir(),key=lambda item:item.name):
                    if not profile.name.startswith('google-chat-'):continue
                    profile_name(profile.name);_directory(profile);count+=1
                    if count>65536:raise Conflict('historical profile capacity exceeded')
                    if count>128:continue
                    held=acquire_lease(profile)
                    try:
                        try:identity=load(profile)
                        except FileNotFoundError:missing.append(profile.name);continue
                        row={'profile':profile.name,'identity':identity,'identity_sha256':digest(identity)}
                        rows.append({**row,'snapshot_sha256':digest(row)})
                    finally:os.close(held)
            result={'profiles':rows,'identity_missing':missing,'history_truncated':count>128,'network_requested':False,'private_credentials_returned':False}
        else:
            _directory(profiles);profile=profiles/params['profile'];lease=acquire_lease(profile);identity=load(profile)
            row={'profile':profile.name,'identity':identity,'identity_sha256':digest(identity)};account={**row,'snapshot_sha256':digest(row)}
            def selected():
                current()
                if load(profile)!=identity:raise PermissionError('historical app identity changed during Owner action')
            selected();database=profile/'user-oauth.sqlite'
            if not database.exists():
                if action!='tokens':raise PermissionError('retained historical user token required')
                value={'tokens':[],'history_truncated':False,'network_requested':False,'private_credentials_returned':False}
            else:
                from .gateway_raw import NativeInbox
                from .gateway_google_chat_oauth import OAuthStore
                from .gateway_google_chat_oauth_tokens import TokenVault
                inbox=NativeInbox(database,redactor);store=OAuthStore(inbox);vault=TokenVault(store)
                if action=='tokens':
                    value=vault.inventory_identity(identity);published=current_policy()
                    for token in value['tokens']:
                        token['current_file_grants']=file_grants(published,identity,token['subject'])
                        token['snapshot_sha256']=digest({k:v for k,v in token.items() if k!='snapshot_sha256'})
                else:
                    if params['identity_sha256']!=account['identity_sha256']:raise PermissionError('historical app changed after Owner inspection')
                    from .gateway_google_chat_oauth_revoke import revoke_retired
                    import asyncio
                    decision={k:params[k] for k in ['id','generation','owner_uid','note_sha256','confirmed']}
                    value=asyncio.run(revoke_retired(store,identity,decision,selected))
            selected();result={'account':account,'result':value,'active_authorization_returned':False}
        current();checked=response(result,action,request=params,policy=current_policy());encoded=json.dumps(checked,ensure_ascii=False,allow_nan=False)
        if len(encoded.encode())>262144 or redactor.text(encoded)!=encoded:raise PermissionError('bounded nonprivate historical Google response required')
        print(encoded)
    except PermissionError:print(json.dumps({'error':'authority-refused'}))
    except Conflict:print(json.dumps({'error':'authority-refused'}))
    except (ImportError,ModuleNotFoundError):print(json.dumps({'error':'runtime-unavailable'}))
    except (ValueError,OSError,sqlite3.Error,KeyError,TypeError):print(json.dumps({'error':'storage-unavailable'}))
    finally:
        if inbox is not None:inbox.close()
        if lease is not None:os.close(lease)


if __name__=='__main__':main()
