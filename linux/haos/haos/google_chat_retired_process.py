"""Closed historical-account Owner protocol; never manufactures active grants."""
from pathlib import Path
import stat

from .gateway import digest
from .gateway_google_chat_identity import validate,account_scope
from .gateway_google_chat_recovery import HEX,profile_name
from .google_chat_owner_process import ERRORS,oauth_response,file_response,_snapshot,_name

ACTIONS=frozenset({'profiles','tokens','revoke-token','quarantines','dispose-capsule','outputs','purge-output'})


def _public_config():
    from .gateway_publication import pending
    from .sandbox import trusted_json
    from .gateway_google_chat import PreparedGoogleChatPolicy
    config=Path('/etc/haos');own=config.lstat()
    if not stat.S_ISDIR(own.st_mode) or own.st_uid!=0 or own.st_mode&0o022 or pending(config):
        raise PermissionError('quiescent trusted Root gateway publication required')
    try:value=trusted_json(config/'gateways.json')
    except FileNotFoundError:return None
    PreparedGoogleChatPolicy(value)
    return value


def policy_snapshot():
    value=_public_config()
    return digest({'gateways':'absent','version':1}) if value is None else digest(value)


def current_policy():
    from .gateway_google_chat import PreparedGoogleChatPolicy
    value=_public_config()
    return None if value is None else PreparedGoogleChatPolicy(value)


def file_grants(policy,identity,subject):
    if policy is None:return 0
    expected=account_scope(identity)
    return sum(policy.connectors.get(row['connector'],{}).get('platform')=='google_chat'
        and row['scope']==expected and row['sender']==subject and 'read' in row['capabilities']
        and row.get('allow_outbound_media') is True for row in policy.bindings.values())


def command():
    from .google_chat_owner_process import command as active_command
    result=active_command();path=Path('/usr/lib/haos/haos/google_chat_retired_worker.py');own=path.lstat()
    if (path.resolve()!=path or not stat.S_ISREG(own.st_mode) or own.st_uid!=0 or own.st_mode&0o022 or own.st_nlink!=1):
        raise PermissionError('fixed Root-owned historical Google worker required')
    return [*result[:-1],'haos.google_chat_retired_worker']


def _hash(value):return isinstance(value,str) and bool(HEX.fullmatch(value))


def _identity(row):
    if not isinstance(row,dict) or set(row)!={'profile','identity','identity_sha256','snapshot_sha256'}:
        raise ValueError('closed historical Google app metadata required')
    profile_name(row['profile']);identity=validate(row['identity'])
    if (row['identity_sha256']!=digest(identity) or row['profile']!='google-chat-'+digest(account_scope(identity))
            or row['snapshot_sha256']!=digest({k:v for k,v in row.items() if k!='snapshot_sha256'})):
        raise ValueError('historical Google app/profile identity changed')
    return identity


def response(value,action,*,request=None,policy=None):
    if not isinstance(value,dict) or action not in ACTIONS:raise ValueError('closed historical Google response required')
    if set(value) in ({'error'},{'error','retry_after'}):
        if not isinstance(value['error'],str) or value['error'] not in ERRORS:raise ValueError('finite historical Google diagnostic required')
        if 'retry_after' in value and (type(value['retry_after']) is not int or not 0<=value['retry_after']<=86400):raise ValueError('bounded retry delay required')
        return value
    if action=='profiles':
        if (set(value)!={'profiles','identity_missing','history_truncated','network_requested','private_credentials_returned'}
                or value['network_requested'] is not False or value['private_credentials_returned'] is not False
                or type(value['history_truncated']) is not bool or not isinstance(value['profiles'],list) or len(value['profiles'])>128
                or not isinstance(value['identity_missing'],list) or len(value['identity_missing'])>128):raise ValueError('bounded historical app inventory required')
        names=[]
        for row in value['profiles']:_identity(row);names.append(row['profile'])
        for name in value['identity_missing']:profile_name(name);names.append(name)
        if len(names)!=len(set(names)) or len(names)>128:raise ValueError('unique bounded historical profile inventory required')
    else:
        if set(value)!={'account','result','active_authorization_returned'} or value['active_authorization_returned'] is not False:raise ValueError('closed selected historical account response required')
        identity=_identity(value['account']);selected=value['account']
        if request is not None and (selected['profile']!=request['profile']
                or action in {'revoke-token','dispose-capsule','purge-output'} and selected['identity_sha256']!=request['identity_sha256']):
            raise ValueError('historical account changed after Owner selection')
        if action=='outputs':
            result=value['result']
            if (not isinstance(result,dict) or set(result)!={'outputs','history_truncated','network_requested','private_bytes_returned'}
                    or not isinstance(result['outputs'],list) or len(result['outputs'])>64):raise ValueError('closed historical output inventory required')
            for row in result['outputs']:
                if (not isinstance(row,dict) or not _name(row.get('connector')) or row.get('account_scope')!=account_scope(identity)
                        or not _hash(row.get('ownership_sha256'))):raise ValueError('historical output app ownership required')
                _snapshot(row)
                public={k:v for k,v in row.items() if k not in {'connector','account_scope','ownership_sha256','snapshot_sha256'}}
                public['snapshot_sha256']=digest(public)
                file_response({**result,'outputs':[public]},'outputs',row['connector'])
            # Validate flags even when no rows exist.
            file_response({**result,'outputs':[]},'outputs','')
            return value
        if action=='purge-output':
            file_response(value['result'],'output-purge','',request=request)
            return value
        checked=oauth_response(value['result'],{'tokens':'oauth-tokens','revoke-token':'oauth-revoke','quarantines':'oauth-quarantines','dispose-capsule':'oauth-dispose'}[action],'',request=request)
        if action=='tokens':
            for row in checked['tokens']:
                if row['account_scope']!=account_scope(identity) or row['current_file_grants']!=file_grants(policy,identity,row['subject']) or row['public_client']['installed']['project_id']!=identity['project_id']:
                    raise ValueError('historical metadata cannot authorize active files or another app')
        elif action=='quarantines':
            for row in checked['quarantines']:
                if row['account_scope']!=account_scope(identity) or row['public_client']['installed']['project_id']!=identity['project_id']:raise ValueError('historical capsule belongs to another app')
        elif request is not None and checked['id']!=request['id']:raise ValueError('historical withdrawal changed selected token')
    return value
