"""Closed payload-free responses and fixed installed private Owner worker."""
from pathlib import Path
import re
import stat
import math

from .gateway import digest
from .gateway_google_chat import resource
from .gateway_google_chat_recovery import HEX,profile_name

ERRORS=frozenset({'authority-refused','storage-unavailable','runtime-unavailable','authentication-refused','rate-limited','identity-refused','transport-unavailable'})
ACTIONS=frozenset({'source-profiles','sources','outgoing','purge-source','approve-retry','retry-auth','oauth-begin','oauth-finish','oauth-sessions','oauth-tokens','oauth-revoke','oauth-quarantines','oauth-dispose'})
NAME=re.compile('[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}\\Z')


def command():
    root=Path('/usr/lib/haos');python=root/'hermes/.venv/bin/python'
    for path in [root,root/'haos',root/'hermes',root/'hermes/.venv',python.parent]:
        own=path.lstat()
        if not stat.S_ISDIR(own.st_mode) or own.st_uid!=0 or own.st_mode&0o022:
            raise PermissionError('root-owned private Google Chat Owner runtime required')
    own=python.resolve(strict=True).lstat()
    if not stat.S_ISREG(own.st_mode) or own.st_uid!=0 or own.st_mode&0o022:raise PermissionError('root-owned private Google Chat interpreter required')
    return [str(python),'-E','-s','-m','haos.google_chat_owner_worker']


def _hash(value):return isinstance(value,str) and HEX.fullmatch(value)
def _name(value):return isinstance(value,str) and NAME.fullmatch(value)
def _snapshot(row):
    if not _hash(row.get('snapshot_sha256')) or row['snapshot_sha256']!=digest({k:v for k,v in row.items() if k!='snapshot_sha256'}):
        raise ValueError('exact inspected Google Chat snapshot required')


def response(value,action,connector,*,request=None):
    if not isinstance(value,dict) or action not in ACTIONS:raise ValueError('closed Google Chat Owner response required')
    if set(value) in ({'error'},{'error','retry_after'}):
        if not isinstance(value['error'],str) or value['error'] not in ERRORS:raise ValueError('finite Google Chat Owner diagnostic required')
        if 'retry_after' in value and (type(value['retry_after']) is not int or not 0<=value['retry_after']<=86400):raise ValueError('bounded private OAuth retry delay required')
        return value
    if action.startswith('oauth-'):return oauth_response(value,action,connector,request=request)
    if value.get('network_requested') is not False:raise ValueError('Google Chat recovery action cannot request network I/O')
    if action in {'source-profiles','sources','outgoing'}:
        key='profiles' if action=='source-profiles' else action
        fields={key,'history_truncated','network_requested','private_bytes_returned'}|({'profile'} if action=='sources' else set())
        if (set(value)!=fields or value['private_bytes_returned'] is not False or type(value['history_truncated']) is not bool
                or not isinstance(value[key],list) or len(value[key])>(64 if action=='outgoing' else 128)):
            raise ValueError('bounded payload-free Google Chat inventory required')
        if action=='sources':profile_name(value['profile'])
        for row in value[key]:
            if action=='source-profiles':profile_name(row);continue
            if not isinstance(row,dict):raise ValueError('closed Google Chat inventory row required')
            if action=='sources':
                fields={'id','connector','message_id','binding_id','binding_digest','created_at','admitted_receipt','profile','source_sha256',
                    'actual_sha256','stored_bytes','proof_sha256','current_grant','purge_allowed','state','authentication_reverified','private_bytes_returned','snapshot_sha256'}
                if (set(row)!=fields or row['profile']!=value['profile'] or not _name(row['connector']) or not _name(row['binding_id'])
                        or any(not _hash(row[k]) for k in ['id','binding_digest','source_sha256','proof_sha256'])
                        or row['actual_sha256'] is not None and not _hash(row['actual_sha256'])
                        or row['admitted_receipt']!='' and not _hash(row['admitted_receipt'])
                        or type(row['created_at']) not in {int,float} or not math.isfinite(row['created_at']) or not 0<row['created_at']<=253402300799
                        or type(row['stored_bytes']) is not int or not 0<=row['stored_bytes']<=1048576
                        or row['state'] not in {'retained','purged','damaged'} or row['authentication_reverified'] is not False
                        or any(type(row[k]) is not bool for k in ['current_grant','purge_allowed'])
                        or row['current_grant']==row['purge_allowed'] or row['private_bytes_returned'] is not False):
                    raise ValueError('closed Google Chat original snapshot required')
                resource(row['message_id'],'message')
            else:
                fields={'id','connector','binding_id','binding_digest','source_id','source_sha256','context_sha256','content_sha256','state',
                    'expected_parts','confirmed_parts','receipt','current_account','current_grant','source_projection_available','parts',
                    'private_bytes_returned','recipient_read_verified','snapshot_sha256'}
                if (set(row)!=fields or row['connector']!=connector or not _name(row['binding_id'])
                        or any(not _hash(row[k]) for k in ['id','binding_digest','source_sha256','context_sha256','content_sha256'])
                        or row['state'] not in {'writing','confirmed'} or type(row['expected_parts']) is not int or not 1<=row['expected_parts']<=64
                        or type(row['confirmed_parts']) is not int or not 0<=row['confirmed_parts']<=row['expected_parts']
                        or any(type(row[k]) is not bool for k in ['current_account','current_grant','source_projection_available'])
                        or row['private_bytes_returned'] is not False or row['recipient_read_verified'] is not False
                        or not isinstance(row['parts'],list) or len(row['parts'])!=(row['expected_parts'] if row['source_projection_available'] else 0)):
                    raise ValueError('closed Google Chat reply group snapshot required')
                resource(row['source_id'],'message');chat=row['source_id'].split('/messages/')[0]
                if row['receipt'] is not None:resource(row['receipt'],'message',space=chat)
                for index,part in enumerate(row['parts']):
                    if (not isinstance(part,dict) or set(part)!={'id','part','state','receipt','body_sha256','body_bytes','retry_generation'}
                            or not _hash(part['id']) or type(part['part']) is not int or part['part']!=index
                            or part['state'] not in {'not-started','writing','confirmed','owner-retry-approved'}
                            or type(part['retry_generation']) is not int or not 0<=part['retry_generation']<=4
                            or type(part['body_bytes']) is not int or not 0<=part['body_bytes']<=65536
                            or part['body_sha256'] is not None and not _hash(part['body_sha256'])
                            or (part['state']=='not-started')!=(part['body_sha256'] is None and part['body_bytes']==0)):
                        raise ValueError('closed Google Chat reply part snapshot required')
                    if (part['state']=='confirmed')!=(part['receipt'] is not None):raise ValueError('exact confirmed part receipt required')
                    if part['receipt'] is not None:resource(part['receipt'],'message',space=chat)
                if sum(p['state']=='confirmed' for p in row['parts'])!=row['confirmed_parts']:raise ValueError('exact confirmed Google Chat part count required')
                if row['state']=='confirmed' and (row['confirmed_parts']!=row['expected_parts'] or row['receipt']!=row['parts'][-1]['receipt']):
                    raise ValueError('all exact part receipts required for confirmed Google Chat group')
            _snapshot(row)
    else:
        if value.get('message_sent') is not False or not _hash(value.get('receipt')):raise ValueError('no-send audited Google Chat decision receipt required')
        if action=='purge-source':
            if (set(value)!={'id','receipt','network_requested','message_sent','tombstones_retained','other_copies_backups_and_WAL_erasure_not_claimed'}
                    or not _hash(value['id']) or value['tombstones_retained'] is not True or value['other_copies_backups_and_WAL_erasure_not_claimed'] is not True):
                raise ValueError('closed Google Chat source disposal receipt required')
        elif action=='retry-auth':
            if (set(value)!={'connector','authentication_blocks_cleared','receipt','network_requested','message_sent'} or value['connector']!=connector
                    or type(value['authentication_blocks_cleared']) is not int or not 0<=value['authentication_blocks_cleared']<=65536):
                raise ValueError('closed Google Chat auth recheck receipt required')
        elif action=='approve-retry':
            if (set(value)!={'id','part_id','receipt','retry_generation','private_retry_approved','stable_client_and_request_id_reuse_required','network_requested','message_sent'}
                    or any(not _hash(value[k]) for k in ['id','part_id']) or type(value['retry_generation']) is not int or not 1<=value['retry_generation']<=4
                    or value['private_retry_approved'] is not True or value['stable_client_and_request_id_reuse_required'] is not True):
                raise ValueError('closed Google Chat one-shot retry receipt required')
    return value


def oauth_response(value,action,connector,*,request=None):
    from .gateway_google_chat_oauth import SCOPES,REDIRECT_URI
    if action=='oauth-begin':
        fields={'id','authorization_url','subject','expires_at','network_requested','message_sent','private_verifier_or_credentials_returned'}
        if (set(value)!=fields or not _hash(value['id']) or value['network_requested'] is not False or value['message_sent'] is not False
                or value['private_verifier_or_credentials_returned'] is not False or type(value['expires_at']) not in {int,float}
                or not math.isfinite(value['expires_at']) or not 0<value['expires_at']<=253402300799
                or not isinstance(value['authorization_url'],str) or not 1<=len(value['authorization_url'])<=4096):
            raise ValueError('closed private Google OAuth authorization result required')
        from urllib.parse import urlsplit,parse_qs
        url=urlsplit(value['authorization_url']);params=parse_qs(url.query,strict_parsing=True,max_num_fields=16)
        keys={'response_type','client_id','redirect_uri','scope','state','nonce','access_type','prompt','include_granted_scopes','code_challenge','code_challenge_method'}
        if (url.scheme!='https' or url.netloc!='accounts.google.com' or url.path!='/o/oauth2/auth' or url.fragment or set(params)!=keys
                or any(len(values)!=1 for values in params.values()) or params['response_type']!=['code'] or params['redirect_uri']!=[REDIRECT_URI]
                or set(params['scope'][0].split())!=set(SCOPES) or params['access_type']!=['offline'] or params['prompt']!=['consent']
                or params['include_granted_scopes']!=['false'] or params['code_challenge_method']!=['S256']
                or any(not re.fullmatch('[A-Za-z0-9_-]{43,128}',params[k][0]) for k in ['state','nonce','code_challenge'])):
            raise ValueError('exact Google authorization URL without private verifier/credentials required')
        if request is not None and (params['client_id']!=[request['client']['installed']['client_id']] or value['subject']!=request['subject']):
            raise ValueError('Google authorization changed its Root-selected client or user')
        resource(value['subject'],'user')
    elif action=='oauth-finish':
        if (set(value)!={'id','subject','status','generation','receipt','network_requested','message_sent','private_credentials_returned'}
                or any(not _hash(value[k]) for k in ['id','receipt']) or value['status']!='active' or type(value['generation']) is not int
                or not 1<=value['generation']<2**53 or value['network_requested'] is not True or value['message_sent'] is not False
                or value['private_credentials_returned'] is not False):raise ValueError('closed verified private Google enrollment receipt required')
        resource(value['subject'],'user')
        # Acceptance returns the credential identity, not the pending session ID.
        if request is not None and value['subject']!=request['subject']:
            raise ValueError('verified Google user differs from selected Owner session')
    elif action in {'oauth-sessions','oauth-tokens','oauth-quarantines'}:
        key={'oauth-sessions':'sessions','oauth-tokens':'tokens','oauth-quarantines':'quarantines'}[action]
        flag='private_bytes_returned' if key=='sessions' else 'private_credentials_returned'
        if (set(value)!={key,'history_truncated','network_requested',flag} or value['network_requested'] is not False or value[flag] is not False
                or type(value['history_truncated']) is not bool or not isinstance(value[key],list) or len(value[key])>(128 if key=='tokens' else 64)):
            raise ValueError('bounded payload-free private OAuth inventory required')
        for row in value[key]:
            if not isinstance(row,dict):raise ValueError('closed private OAuth metadata required')
            if key=='sessions':
                if (set(row)!={'id','connector','binding_id','binding_digest','account_scope','client_sha256','subject','status','created_at','expires_at'}
                        or row['connector']!=connector or not _name(row['binding_id']) or row['status'] not in {'awaiting','exchanging','complete','refused','uncertain','cancelled'}
                        or any(not _hash(row[k]) for k in ['id','binding_digest','client_sha256'])):raise ValueError('closed private OAuth session metadata required')
                for field in ['created_at','expires_at']:
                    if type(row[field]) not in {int,float} or not math.isfinite(row[field]) or not 0<row[field]<=253402300799:raise ValueError('bounded OAuth session time required')
                resource(row['subject'],'user')
            elif key=='tokens':
                fields={'id','account_scope','subject','client_sha256','status','updated_at','generation','public_client','transport_status','next_attempt','scopes','scope_upgrade_required','current_file_grants','private_credentials_returned','snapshot_sha256'}
                if (set(row)!=fields or any(not _hash(row[k]) for k in ['id','client_sha256'])
                        or row['status'] not in {'active','superseded','revoked-local','revoked-remote'}
                        or row['transport_status'] not in {'ready','refreshing','rate-limited','authentication-refused','refresh-uncertain','revoked-local'}
                        or type(row['generation']) is not int or not 1<=row['generation']<2**53
                        or type(row['scope_upgrade_required']) is not bool or type(row['current_file_grants']) is not int or not 0<=row['current_file_grants']<=512
                        or row['private_credentials_returned'] is not False or not isinstance(row['scopes'],list) or any(not isinstance(s,str) or s not in SCOPES for s in row['scopes'])):
                    raise ValueError('closed private Google user credential status required')
                for field in ['updated_at','next_attempt']:
                    if type(row[field]) not in {int,float} or not math.isfinite(row[field]) or not 0<=row[field]<=253402300799:raise ValueError('bounded Google user status time required')
                resource(row['subject'],'user');_snapshot(row)
            else:
                fields={'id','pending_id','account_scope','subject_expected','client_sha256','tokens_sha256','state','created_at','origin','public_client','stored_bytes','has_refresh_token','actual_user_verified','api_use_authorized','remote_revocation_verified','private_credentials_returned','snapshot_sha256'}
                if (set(row)!=fields or any(not _hash(row[k]) for k in ['id','pending_id','client_sha256','tokens_sha256'])
                        or row['origin'] not in {'enrollment','refresh'} or row['state'] not in {'rejected','revocation-pending','revoked-remote'}
                        or type(row['stored_bytes']) is not int or not 0<=row['stored_bytes']<=65536 or type(row['has_refresh_token']) is not bool
                        or any(row[k] is not False for k in ['actual_user_verified','api_use_authorized','private_credentials_returned'])
                        or row['remote_revocation_verified']!=(row['state']=='revoked-remote') or type(row['created_at']) not in {int,float}
                        or not math.isfinite(row['created_at'])):raise ValueError('closed rejected Google credential status required')
                resource(row['subject_expected'],'user');_snapshot(row)
            if not isinstance(row['account_scope'],str) or not re.fullmatch('google-chat:[a-f0-9]{64}',row['account_scope']):raise ValueError('exact private Google account scope required')
            if key!='sessions':
                public=row['public_client']
                if (not isinstance(public,dict) or set(public)!={'installed'} or not isinstance(public['installed'],dict)
                        or set(public['installed'])!={'client_id','project_id','auth_uri','token_uri','auth_provider_x509_cert_url','redirect_uris'}):
                    raise ValueError('private credential material cannot become public OAuth client metadata')
                info=public['installed']
                if (not isinstance(info['client_id'],str) or not re.fullmatch('[0-9]{1,32}-[A-Za-z0-9_-]{1,128}\\.apps\\.googleusercontent\\.com',info['client_id'])
                        or not isinstance(info['project_id'],str) or not re.fullmatch('[a-z][a-z0-9-]{4,61}[a-z0-9]',info['project_id'])
                        or info['auth_uri']!='https://accounts.google.com/o/oauth2/auth' or info['token_uri']!='https://oauth2.googleapis.com/token'
                        or info['auth_provider_x509_cert_url']!='https://www.googleapis.com/oauth2/v1/certs' or info['redirect_uris']!=['http://localhost']):
                    raise ValueError('exact public Google client protocol required')
    elif action in {'oauth-revoke','oauth-dispose'}:
        common={'id','receipt','remote_status','remote_revocation_verified','network_requested','message_sent','retry_after','private_credentials_returned'}
        if (set(value)!=(common|({'locally_revoked'} if action=='oauth-revoke' else {'api_use_authorized'}))
                or any(not _hash(value[k]) for k in ['id','receipt']) or value['remote_status'] not in {'confirmed','refused','rate-limited','uncertain'}
                or value['remote_revocation_verified']!=(value['remote_status']=='confirmed') or type(value['network_requested']) is not bool
                or value['message_sent'] is not False or value['private_credentials_returned'] is not False
                or type(value['retry_after']) is not int or not 0<=value['retry_after']<=86400
                or (value['locally_revoked'] is not True if action=='oauth-revoke' else value['api_use_authorized'] is not False)):
            raise ValueError('closed Google local/remote withdrawal receipt required')
    else:raise ValueError('unsupported private Google OAuth response')
    return value
