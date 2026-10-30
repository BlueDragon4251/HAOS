"""One stopped-service recovery/OAuth action under the private gateway UID."""
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
    from .gateway import Conflict
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
    if action in {'source-profiles','outgoing','oauth-sessions','oauth-tokens','oauth-quarantines','files','outputs'}:
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
    if action=='oauth-begin':
        from .gateway_google_chat_oauth import client
        aliases.append(client(params.get('client'),value)['installed']['client_secret'])
    if action=='oauth-finish' and isinstance(params.get('callback'),str):
        from urllib.parse import urlsplit,parse_qs
        aliases.extend(parse_qs(urlsplit(params['callback']).query,max_num_fields=8).get('code',[]))
    redactor=Redactor(aliases);lease=None;inbox=None;store=None
    import logging
    from .gateway_runtime import SafeFormatter
    handler=logging.StreamHandler();handler.setFormatter(SafeFormatter(redactor));logging.basicConfig(level=logging.WARNING,handlers=[handler],force=True)
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
        if action=='oauth-begin' and (profile is None or not profile.exists()):
            from .gateway_google_chat_oauth import route,client
            route(current(),connector,value,params.get('binding_id'),params.get('binding_digest'));client(params.get('client'),value)
            if not profiles.exists():profiles.mkdir(mode=0o700)
            _directory(profiles);profile=profiles/('google-chat-'+digest(scope(value)))
            profile.mkdir(mode=0o700);lease=acquire_lease(profile)
        if action.startswith('oauth-'):
            from .gateway_google_chat_oauth import OAuthStore,HEX,route,client
            from .gateway_raw import NativeInbox
            from .gateway_google_chat_oauth_tokens import TokenVault
            database=profile/'user-oauth.sqlite' if profile is not None else None
            if database is None or not database.exists() and action!='oauth-begin':
                if action not in {'oauth-sessions','oauth-tokens','oauth-quarantines','files','outputs'}:raise PermissionError('retained private OAuth profile required')
                key={'oauth-sessions':'sessions','oauth-tokens':'tokens','oauth-quarantines':'quarantines'}[action]
                result={key:[],'history_truncated':False,'network_requested':False,'private_bytes_returned' if key=='sessions' else 'private_credentials_returned':False}
            else:
                inbox=NativeInbox(database,redactor);oauth=OAuthStore(inbox)
                if action=='oauth-begin':
                    if (set(params)!={'binding_id','binding_digest','subject','client','owner_uid','note_sha256','confirmed'}
                            or params['subject']!=route(current(),connector,value,params['binding_id'],params['binding_digest'])['sender']):
                        raise PermissionError('closed current Owner user/client enrollment required')
                    row=oauth.begin(current(),connector,value,params['client'],params['binding_id'],params['binding_digest'],
                        owner_uid=params['owner_uid'],note_sha256=params['note_sha256'],confirmed=params['confirmed'])
                    from .gateway_google_chat_oauth_sdk import authorization
                    result=authorization(row)
                elif action=='oauth-finish':
                    if (set(params)!={'id','subject','callback','owner_uid','confirmed'} or params['confirmed'] is not True
                            or not isinstance(params['id'],str) or not HEX.fullmatch(params['id'])):
                        raise PermissionError('closed explicitly submitted Owner OAuth callback required')
                    expected=inbox.db.execute('SELECT subject FROM google_chat_oauth_pending WHERE id=?',(params['id'],)).fetchone()
                    if expected is None or expected['subject']!=params['subject']:raise PermissionError('OAuth selected user changed')
                    from .gateway_google_chat_oauth_sdk import finish
                    import asyncio
                    result=asyncio.run(finish(oauth,current,connector,value,params['id'],params['callback'],owner_uid=params['owner_uid']))
                elif action=='oauth-sessions':result=oauth.inventory()
                elif action=='oauth-tokens':result=TokenVault(oauth).inventory(current(),connector,value)
                elif action=='oauth-quarantines':
                    from .gateway_google_chat_oauth_quarantine import inventory
                    result=inventory(oauth,value)
                else:
                    import asyncio
                    if action=='oauth-revoke':
                        from .gateway_google_chat_oauth_revoke import revoke
                        result=asyncio.run(revoke(oauth,current,connector,value,params,current))
                    else:
                        from .gateway_google_chat_oauth_quarantine import dispose
                        result=asyncio.run(dispose(oauth,current,connector,value,params,current))
        elif action=='source-profiles':
            names=[]
            if profiles.exists():
                for path in profiles.iterdir():
                    if path.name.startswith('google-chat-'):
                        profile_name(path.name);_directory(path);names.append(path.name)
                        if len(names)>65536:raise ValueError('Google Chat profile history exceeds bound')
            result={'profiles':sorted(names)[:128],'history_truncated':len(names)>128,'network_requested':False,'private_bytes_returned':False}
        elif action in {'files','outputs','file-decide','output-purge'}:
            from .gateway_raw import NativeInbox
            from .gateway_google_chat_file_recovery import inventory,outputs,decide,purge
            database=Path('/var/lib/haos-gateway/native-inbox.db')
            if not database.exists():
                if action not in {'files','outputs'}:raise PermissionError('retained Google file journal required')
                result={action:[],'history_truncated':False,'network_requested':False,'private_bytes_returned':False}
            else:
                inbox=NativeInbox(database,redactor)
                if profile is not None and (profile/'originals.sqlite').exists():
                    from .gateway_google_chat_custody import Originals
                    store=Originals(profile/'originals.sqlite',redactor)
                if action=='files':result=inventory(inbox,current(),connector,value,current,originals=store)
                elif action=='outputs':result=outputs(inbox,current(),connector,value,current)
                elif action=='file-decide':result=decide(inbox,current(),connector,value,params,current,originals=store)
                else:result=purge(inbox,current(),connector,value,params,current)
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
        current();checked=response(result,action,connector,request=params);encoded=json.dumps(checked,ensure_ascii=False,allow_nan=False)
        if len(encoded.encode())>262144 or redactor.text(encoded)!=encoded:raise PermissionError('bounded nonprivate Google Chat Owner result required')
        print(encoded)
    except PermissionError as error:
        from .gateway_google_chat_oauth_tokens import Deferred
        if isinstance(error,Deferred):print(json.dumps({'error':'rate-limited' if error.status=='rate-limited' else 'authentication-refused','retry_after':error.retry_after}))
        else:print(json.dumps({'error':'authority-refused'}))
    except Conflict:print(json.dumps({'error':'authority-refused'}))
    except RuntimeError as error:
        from .gateway_google_chat_oauth_sdk import EnrollmentFailure
        if not isinstance(error,EnrollmentFailure):raise
        category={'rate-limited':'rate-limited','identity-refused':'identity-refused','sdk-refused':'authentication-refused','exchange-uncertain':'transport-unavailable','storage-unavailable':'storage-unavailable'}.get(error.status,'authority-refused')
        print(json.dumps({'error':category,'retry_after':min(86400,max(0,error.retry_after))}))
    except (ImportError,ModuleNotFoundError):print(json.dumps({'error':'runtime-unavailable'}))
    except (ValueError,OSError,sqlite3.Error,KeyError,TypeError):print(json.dumps({'error':'storage-unavailable'}))
    finally:
        if inbox is not None:inbox.close()
        if store is not None:store.close()
        if lease is not None:os.close(lease)


if __name__=='__main__':main()
