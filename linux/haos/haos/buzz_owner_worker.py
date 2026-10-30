"""One closed root-parent owner action under the private gateway UID."""
import asyncio
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
    parent=os.getppid();libc=ctypes.CDLL(None,use_errno=True)
    if libc.prctl(1,signal.SIGKILL,0,0,0)!=0 or os.getppid()!=parent:raise PermissionError('owner parent lifetime guard required')
    if libc.prctl(38,1,0,0,0)!=0:raise PermissionError('private owner worker must deny executable privilege changes')
    def root_parent():
        if os.getppid()!=parent:raise PermissionError('authenticated owner parent was lost')
        status=Path('/proc/'+str(parent)+'/status').read_text()
        if next(line for line in status.splitlines() if line.startswith('Uid:')).split()[1:]!=['0']*4:
            raise PermissionError('Buzz owner action requires its actual authenticated root parent')
    root_parent();resource.setrlimit(resource.RLIMIT_CORE,(0,0));resource.setrlimit(resource.RLIMIT_CPU,(15,15))
    resource.setrlimit(resource.RLIMIT_AS,(768*1024*1024,768*1024*1024))
    signal.signal(signal.SIGALRM,lambda *_:os._exit(124));signal.alarm(45)
    raw=sys.stdin.buffer.read(65537)
    if len(raw)>65536:raise ValueError('bounded private Buzz owner request required')
    from .gateway_line_ingress import _object
    from .gateway_dingtalk_admission import finite
    from .gateway_buzz import credentials,authority,HEX,PreparedBuzzPolicy,scope
    from .gateway_buzz_cli import QueryFailed
    from .sandbox import trusted_json
    request=json.loads(raw,object_pairs_hook=_object,parse_constant=finite)
    if (not isinstance(request,dict) or set(request)!={'action','connector','credentials','policy_sha256','parent_pid','params','owner_uid'}
            or not isinstance(request['action'],str) or request['action'] not in {'account','outputs','decide-output','outgoing','approve-retry'}
            or not isinstance(request['connector'],str) or type(request['parent_pid']) is not int or request['parent_pid']!=parent
            or not isinstance(request['policy_sha256'],str) or not HEX.fullmatch(request['policy_sha256'])
            or type(request['owner_uid']) is not int or not 0<=request['owner_uid']<2**32-1 or not isinstance(request['params'],dict)):
        raise PermissionError('closed authenticated private Buzz owner action required')
    if request['action'] in {'account','outputs','outgoing'}:
        if request['params']:raise ValueError('Buzz inspection takes no implicit selectors')
    elif request['params'].get('owner_uid')!=request['owner_uid']:raise PermissionError('Buzz decision changed its authenticated owner actor')
    value=credentials(request['credentials'])
    def current():
        root_parent();authority(request['connector'],value,request['policy_sha256'])
        return PreparedBuzzPolicy(trusted_json(Path('/etc/haos/gateways.json')))
    current();home=prepare_runtime_home()
    from .redaction import Redactor
    aliases=[value['private_key'],value.get('auth_tag','')]
    if value.get('auth_tag'):
        tag=json.loads(value['auth_tag']);aliases.extend([repr(tag),*[json.dumps(tag,ensure_ascii=mode) for mode in [True,False]]])
    redactor=Redactor([part for part in aliases if part])
    import logging
    from .gateway_runtime import SafeFormatter
    handler=logging.StreamHandler();handler.setFormatter(SafeFormatter(redactor));logging.basicConfig(level=logging.WARNING,handlers=[handler],force=True)
    lease=None;inbox=None
    try:
        from .gateway_line_profile import _directory
        from .gateway_matrix_profile import acquire_lease
        from .gateway import digest
        profiles=Path('/var/lib/haos-gateway/profiles')
        if profiles.exists():
            _directory(profiles);profile=profiles/('buzz-'+digest([value['relay_url'],value['public_key']]))
            if profile.exists():lease=acquire_lease(profile)
        if request['action']=='account':
            from .gateway_buzz_cli import Reader
            from plugins.platforms.buzz.nostr_auth import decode_private_key,public_key_hex
            try:
                scalar=format(decode_private_key(value['private_key']),'064x')
                if public_key_hex(value['private_key'])!=value['public_key']:raise ValueError('private identity mismatch')
            except ValueError:
                print(json.dumps({'error':'identity-refused'}));return
            redactor.secrets=Redactor([*redactor.secrets,scalar]).secrets
            reader=Reader(request['connector'],value,current,redactor)
            async def inspect():
                await reader.run(['users','get'])
                for channel in value['channels']:await reader.run(['channels','get','--channel',channel])
            asyncio.run(inspect());result={'runtime_ready':True,'identity_verified':True,'read_query_succeeded':True,
                'account_scope':scope(value),'channels_checked':len(value['channels']),'message_sent':False,
                'mission_created':False,'grants_changed':False,'external_acceptance_verified':False}
        else:
            database=Path('/var/lib/haos-gateway/native-inbox.db')
            if not database.exists():
                if request['action']=='outputs':result={'outputs':[],'history_truncated':False,'network_requested':False,'private_bytes_returned':False}
                elif request['action']=='outgoing':result={'outgoing':[],'network_requested':False}
                else:raise PermissionError('no retained Buzz journal for an owner decision')
            else:
                from .gateway_raw import NativeInbox
                inbox=NativeInbox(database,redactor)
                from .gateway_buzz_output_recovery import inventory,decide
                from .gateway_buzz_recovery import outgoing,approve_retry
                if request['action']=='outputs':result=inventory(inbox,current())
                elif request['action']=='outgoing':result={'outgoing':outgoing(inbox),'network_requested':False}
                elif request['action']=='decide-output':result=decide(inbox,current(),value,request['params'])
                else:result={**approve_retry(inbox,current(),request['params']),'network_requested':False,'message_sent':False}
        current();encoded=json.dumps(result,ensure_ascii=False,allow_nan=False)
        if len(encoded.encode())>262144 or redactor.text(encoded)!=encoded:raise PermissionError('bounded nonprivate Buzz owner result required')
        print(encoded)
    except QueryFailed as error:
        category={'authentication_refused':'authentication-refused','rate_limited':'rate-limited',
            'identity_mismatch':'identity-refused','private_reflection':'private-reflection'}.get(error.category,'transport-unavailable')
        print(json.dumps({'error':category}))
    except (ImportError,ModuleNotFoundError):print(json.dumps({'error':'sdk-unavailable'}))
    except PermissionError:print(json.dumps({'error':'authority-refused'}))
    except (ValueError,OSError,sqlite3.Error):print(json.dumps({'error':'storage-unavailable'}))
    finally:
        if inbox is not None:inbox.close()
        if lease is not None:os.close(lease)


if __name__=='__main__':main()
