"""Prepared authenticated Root handoff; private recovery journals keep their UID."""
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
    from .gateway_google_chat import credentials,authority,PreparedGoogleChatPolicy,scope
    from .gateway_publication import pending
    from .sandbox import trusted_json
    config=Path('/etc/haos');secret=config/'gateway-credentials';own=config.lstat()
    if not stat.S_ISDIR(own.st_mode) or own.st_uid!=0 or own.st_mode&0o022 or pending(config):
        raise PermissionError('matched root-owned Google Chat publication required')
    own=secret.lstat()
    if not stat.S_ISREG(own.st_mode) or own.st_uid!=0 or own.st_mode&0o077:raise PermissionError('Root-private Google Chat credential store required')
    raw=trusted_json(config/'gateways.json');policy=PreparedGoogleChatPolicy(raw);private=trusted_json(secret)
    if (not isinstance(private,dict) or set(private) not in ({'connectors'},{'connectors','publication'})
            or not isinstance(private.get('connectors'),dict) or set(private['connectors'])!=set(policy.connectors)
            or private.get('publication')!=raw.get('publication') or policy.connectors.get(connector,{}).get('platform')!='google_chat'):
        raise PermissionError('exact matched saved Google Chat connector required')
    value=credentials(private['connectors'][connector])
    if any(name!=connector and row['platform']=='google_chat' and scope(credentials(private['connectors'][name]))==scope(value)
            for name,row in policy.connectors.items()):raise PermissionError('Google Chat account cannot belong to multiple connectors')
    authority(connector,value);return raw,value


def _runtime_state(account):
    """Create a missing service state root without repairing existing custody."""
    from .initial_setup import require_root
    require_root()
    flags=os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW|os.O_CLOEXEC
    parent=os.open('/var/lib',flags)
    try:
        own=os.fstat(parent)
        if own.st_uid!=0 or own.st_mode&0o022:raise PermissionError('trusted service state parent required')
        created=False
        try:os.mkdir('haos-gateway',0o700,dir_fd=parent);created=True
        except FileExistsError:pass
        try:state=os.open('haos-gateway',flags,dir_fd=parent)
        except OSError:raise PermissionError('private gateway state must be an actual service directory; preserve and inspect it') from None
        try:
            if created:os.fchown(state,account.pw_uid,account.pw_gid)
            own=os.fstat(state)
            if own.st_uid!=account.pw_uid or own.st_gid!=account.pw_gid or stat.S_IMODE(own.st_mode)!=0o700:
                raise PermissionError('existing private gateway state has unexpected ownership or permissions; preserve and inspect it')
            if created:os.fsync(state);os.fsync(parent)
        finally:os.close(state)
    finally:os.close(parent)


def _invoke(connector,action,params):
    from .initial_setup import require_root,quiesce_for_setup
    require_root()
    from .gateway_setup import stopped_gateway
    from .gateway_google_chat import authority
    from .google_chat_owner_process import command,response
    from .gateway_line_ingress import _object
    from .gateway_dingtalk_admission import finite
    from .redaction import Redactor
    from .owner import audit
    quiesce_for_setup(gateway_only=True);stopped_gateway();_,value=saved(connector)
    publication=authority(connector,value);account=pwd.getpwnam('haos-gateway')
    if account.pw_uid==0 or account.pw_gid==0:raise PermissionError('separate private Google Chat identity required')
    _runtime_state(account)
    request={'action':action,'connector':connector,'credentials':value,'policy_sha256':publication,'parent_pid':os.getpid(),
        'owner_uid':int(os.environ.get('SUDO_UID','0')),'params':params}
    try:
        result=subprocess.run(command(),input=json.dumps(request,ensure_ascii=False)+'\n',text=True,capture_output=True,timeout=45,
            user=account.pw_uid,group=account.pw_gid,extra_groups=[],umask=0o077,cwd='/usr/lib/haos',
            env={'PATH':'/usr/bin:/bin','LANG':'C.UTF-8','PYTHONDONTWRITEBYTECODE':'1','HERMES_SAFE_MODE':'1'})
    except subprocess.TimeoutExpired:raise RuntimeError('Google-Chat-Recovery: Zeitlimit; Runtime und privates Journal prüfen.') from None
    if result.returncode or len(result.stdout.encode())>262144:raise RuntimeError('Private Google-Chat-Recovery fehlgeschlagen; Runtime und Journal prüfen.')
    aliases=[value['service_account']['private_key']]
    if value['inbound']['mode']=='http':aliases.append(value['inbound']['tls']['private_key'])
    if action=='oauth-begin':aliases.append(params['client']['installed']['client_secret'])
    if action=='oauth-finish':
        from urllib.parse import urlsplit,parse_qs
        aliases.extend(parse_qs(urlsplit(params['callback']).query,max_num_fields=8).get('code',[]))
    if Redactor(aliases).text(result.stdout)!=result.stdout:raise PermissionError('private material in Google Chat Owner response')
    checked=response(json.loads(result.stdout,object_pairs_hook=_object,parse_constant=finite),action,connector,request=params)
    authority(connector,value,publication)
    audit('gateway.google-chat-owner-'+action,{'connector':connector,'message_sent':False,
        'network_requested':checked.get('network_requested',action in {'oauth-finish','oauth-revoke','oauth-dispose'}),
        **({'receipt':checked['receipt'],**({'note_sha256':params['note_sha256']} if 'note_sha256' in params else {})} if 'receipt' in checked else {})})
    return checked


def inspect(connector,action='outgoing',*,profile=None):
    from .initial_setup import require_root
    require_root()
    if not isinstance(action,str) or action not in {'source-profiles','sources','outgoing','files','outputs'}:raise ValueError('closed no-network Google Chat inspection required')
    params={}
    if action=='sources':
        from .gateway_google_chat_recovery import profile_name
        from .gateway_google_chat import scope
        from .gateway import digest
        if profile is None:_,value=saved(connector);profile='google-chat-'+digest(scope(value))
        params={'profile':profile_name(profile)}
    elif profile is not None:raise ValueError('Google Chat profile selector only applies to original inspection')
    return _invoke(connector,action,params)


def _decision(note,confirmed):
    from .initial_setup import require_root
    require_root()
    if confirmed is not True or not isinstance(note,str) or not 1<=len(note.strip())<=2000:
        raise PermissionError('Google-Chat-Entscheidung ausdrücklich bestätigen und begründen.')
    return {'owner_uid':int(os.environ.get('SUDO_UID','0')),'note_sha256':hashlib.sha256(note.strip().encode()).hexdigest(),'confirmed':True}


def retry_auth(connector,note,*,confirmed=False):
    return _invoke(connector,'retry-auth',{'connector':connector,**_decision(note,confirmed)})


def purge_source(connector,row,note,*,confirmed=False):
    params=_decision(note,confirmed)
    from .gateway_google_chat_recovery import HEX,profile_name
    if (not isinstance(row,dict) or any(not isinstance(row.get(k),str) or not HEX.fullmatch(row[k]) for k in ['id','snapshot_sha256'])
            or row.get('purge_allowed') is not True):raise PermissionError('exact inspected withdrawn Google Chat original required')
    params.update({k:row[k] for k in ['id','snapshot_sha256']});params['profile']=profile_name(row.get('profile'))
    return _invoke(connector,'purge-source',params)


def approve_reply(connector,row,part_id,note,*,confirmed=False,confirmed_not_delivered=False):
    params=_decision(note,confirmed)
    from .gateway_google_chat_recovery import HEX
    if (not isinstance(row,dict) or row.get('connector')!=connector or confirmed_not_delivered is not True
            or any(not isinstance(row.get(k),str) or not HEX.fullmatch(row[k]) for k in ['id','snapshot_sha256'])
            or not isinstance(part_id,str) or not HEX.fullmatch(part_id)):
        raise PermissionError('exact inspected Google Chat reply part and independent non-delivery confirmation required')
    params.update({k:row[k] for k in ['id','snapshot_sha256']});params.update(connector=connector,part_id=part_id,confirmed_not_delivered=True)
    return _invoke(connector,'approve-retry',params)


def oauth_inspect(connector,kind='tokens'):
    from .initial_setup import require_root
    require_root()
    if kind not in {'sessions','tokens','quarantines'}:raise ValueError('closed private OAuth inspection required')
    return _invoke(connector,'oauth-'+kind,{})


def oauth_begin(connector,binding_id,configuration,note,*,confirmed=False):
    params=_decision(note,confirmed)
    from .gateway_google_chat import PreparedGoogleChatPolicy
    from .gateway_google_chat_oauth import client,route
    from .gateway import digest
    raw,account=saved(connector);selected=PreparedGoogleChatPolicy(raw);binding=selected.bindings.get(binding_id)
    if binding is None:raise PermissionError('current exact paired Google user required')
    route(selected,connector,account,binding_id,digest(binding))
    params.update(binding_id=binding_id,binding_digest=digest(binding),subject=binding['sender'],client=client(configuration,account))
    return _invoke(connector,'oauth-begin',params)


def oauth_finish(connector,session,returned_url,*,confirmed=False):
    from .initial_setup import require_root
    require_root()
    from .gateway_google_chat_recovery import HEX
    from .gateway_google_chat import resource
    if (confirmed is not True or not isinstance(session,dict) or not isinstance(session.get('id'),str) or not HEX.fullmatch(session['id'])
            or not isinstance(returned_url,str) or not 1<=len(returned_url)<=8192):raise PermissionError('exact selected pending Google user and full callback required')
    return _invoke(connector,'oauth-finish',{'id':session['id'],'subject':resource(session.get('subject'),'user'),'callback':returned_url,
        'owner_uid':int(os.environ.get('SUDO_UID','0')),'confirmed':True})


def oauth_revoke(connector,row,note,*,confirmed=False):
    params=_decision(note,confirmed)
    from .gateway_google_chat_recovery import HEX
    if (not isinstance(row,dict) or not isinstance(row.get('id'),str) or not HEX.fullmatch(row['id'])
            or type(row.get('generation')) is not int or not 1<=row['generation']<2**53):raise PermissionError('exact inspected Google user token generation required')
    return _invoke(connector,'oauth-revoke',dict(params,id=row['id'],generation=row['generation']))


def oauth_dispose(connector,row,note,*,confirmed=False):
    params=_decision(note,confirmed)
    from .gateway_google_chat_recovery import HEX
    if not isinstance(row,dict) or any(not isinstance(row.get(k),str) or not HEX.fullmatch(row[k]) for k in ['id','snapshot_sha256']):
        raise PermissionError('exact inspected rejected Google credential capsule required')
    return _invoke(connector,'oauth-dispose',dict(params,id=row['id'],snapshot_sha256=row['snapshot_sha256']))



def file_retry(connector,row,action,note,*,confirmed=False,confirmed_not_delivered=False):
    params=_decision(note,confirmed)
    from .gateway_google_chat_files import HEX
    if (not isinstance(action,str) or action not in {'retry-upload','retry-file'} or type(confirmed_not_delivered) is not bool
            or confirmed_not_delivered!=(action=='retry-file') or not isinstance(row,dict)
            or row.get('connector')!=connector or any(not isinstance(row.get(k),str) or not HEX.fullmatch(row[k]) for k in ['id','snapshot_sha256'])
            or row.get('upload_retry_allowed' if action=='retry-upload' else 'file_retry_allowed') is not True):
        raise PermissionError('exact inspected eligible Google file decision and independent non-delivery confirmation required')
    return _invoke(connector,'file-decide',dict(params,id=row['id'],snapshot_sha256=row['snapshot_sha256'],action=action,confirmed_not_delivered=confirmed_not_delivered))


def output_purge(connector,row,note,*,confirmed=False):
    params=_decision(note,confirmed)
    from .gateway_google_chat_files import HEX
    if (not isinstance(row,dict) or row.get('purge_allowed') is not True
            or any(not isinstance(row.get(k),str) or not HEX.fullmatch(row[k]) for k in ['id','snapshot_sha256'])):
        raise PermissionError('exact inspected withdrawn Google output snapshot required')
    return _invoke(connector,'output-purge',dict(params,id=row['id'],snapshot_sha256=row['snapshot_sha256']))
