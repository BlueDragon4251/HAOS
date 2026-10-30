"""Authenticated Root entry points for metadata and withdrawal after app removal."""
import hashlib
import json
import os
import pwd
import subprocess


def _invoke(action,params):
    from .initial_setup import require_root,quiesce_for_setup
    require_root()
    from .gateway_setup import stopped_gateway
    from .google_chat_owner_setup import _runtime_state
    from .google_chat_retired_process import command,response,policy_snapshot,current_policy
    from .gateway_line_ingress import _object
    from .gateway_dingtalk_admission import finite
    from .owner import audit
    quiesce_for_setup(gateway_only=True);stopped_gateway();publication=policy_snapshot()
    account=pwd.getpwnam('haos-gateway')
    if account.pw_uid==0 or account.pw_gid==0:raise PermissionError('separate historical Google gateway identity required')
    _runtime_state(account)
    request={'action':action,'policy_sha256':publication,'parent_pid':os.getpid(),
        'owner_uid':int(os.environ.get('SUDO_UID','0')),'params':params}
    try:
        result=subprocess.run(command(),input=json.dumps(request,ensure_ascii=False)+'\n',text=True,capture_output=True,timeout=45,
            user=account.pw_uid,group=account.pw_gid,extra_groups=[],umask=0o077,cwd='/usr/lib/haos',
            env={'PATH':'/usr/bin:/bin','LANG':'C.UTF-8','PYTHONDONTWRITEBYTECODE':'1','HERMES_SAFE_MODE':'1'})
    except subprocess.TimeoutExpired:raise RuntimeError('Historische Google-Konten: Zeitlimit; privaten Worker und Journal prüfen.') from None
    if result.returncode or len(result.stdout.encode())>262144:
        raise RuntimeError('Historische Google-Konten: privater Worker fehlgeschlagen; Runtime und Journal prüfen.')
    checked=response(json.loads(result.stdout,object_pairs_hook=_object,parse_constant=finite),action,request=params,policy=current_policy())
    if policy_snapshot()!=publication:raise PermissionError('Root configuration changed during historical account action')
    audit('gateway.google-chat-historical-'+action,{'profile':params.get('profile'),'message_sent':False,
        'network_requested':checked.get('result',{}).get('network_requested',False),
        **({'note_sha256':params['note_sha256']} if 'note_sha256' in params else {}),
        **({'receipt':checked['result']['receipt']} if 'receipt' in checked.get('result',{}) else {})})
    return checked


def profiles():
    from .initial_setup import require_root
    require_root();return _invoke('profiles',{})


def restore_identity(profile,identity,note,*,confirmed=False):
    from .initial_setup import require_root
    require_root()
    from .gateway_google_chat_identity import validate,account_scope
    from .gateway_google_chat_recovery import profile_name
    from .gateway import digest
    from .owner import audit
    identity=validate(identity);profile=profile_name(profile)
    if profile!='google-chat-'+digest(account_scope(identity)):
        raise PermissionError('öffentliche Original-App-Identität passt nicht zum erhaltenen Profil; nichts wird ersetzt')
    if confirmed is not True or not isinstance(note,str) or not 1<=len(note.strip())<=2000:
        raise PermissionError('exakte ursprüngliche öffentliche Identität prüfen, begründen und ausdrücklich bestätigen')
    params={'profile':profile,'identity':identity,'owner_uid':int(os.environ.get('SUDO_UID','0')),
        'note_sha256':hashlib.sha256(note.strip().encode()).hexdigest(),'confirmed':True}
    # A durable Root intent precedes even this non-authorizing metadata write.
    audit('gateway.google-chat-historical-identity-intent',{'profile':profile,'identity_sha256':digest(identity),'note_sha256':params['note_sha256']})
    return _invoke('restore-identity',params)


def tokens(profile):
    from .initial_setup import require_root
    require_root()
    from .gateway_google_chat_recovery import profile_name
    return _invoke('tokens',{'profile':profile_name(profile)})


def revoke(account,row,note,*,confirmed=False):
    from .initial_setup import require_root
    require_root()
    from .gateway_google_chat_recovery import HEX
    from .google_chat_retired_process import _identity
    if (confirmed is not True or not isinstance(note,str) or not 1<=len(note.strip())<=2000
            or not isinstance(row,dict) or not isinstance(row.get('id'),str) or not HEX.fullmatch(row['id'])
            or type(row.get('generation')) is not int or not 1<=row['generation']<2**53):
        raise PermissionError('exaktes historisches Google-Token auswählen, begründen und Widerruf bestätigen')
    try:identity=_identity(account)
    except (ValueError,KeyError,TypeError):raise PermissionError('historisches Google-App-Profil wurde nach der Auswahl geändert; neu prüfen') from None
    from .gateway_google_chat_identity import account_scope
    if row.get('account_scope')!=account_scope(identity):raise PermissionError('historisches Token gehört nicht zum ausgewählten App-Profil')
    params={'profile':account['profile'],'identity_sha256':account['identity_sha256'],'id':row['id'],'generation':row['generation'],
        'owner_uid':int(os.environ.get('SUDO_UID','0')),'note_sha256':hashlib.sha256(note.strip().encode()).hexdigest(),'confirmed':True}
    return _invoke('revoke-token',params)


def quarantines(profile):
    from .initial_setup import require_root
    require_root()
    from .gateway_google_chat_recovery import profile_name
    return _invoke('quarantines',{'profile':profile_name(profile)})


def dispose(account,row,note,*,confirmed=False):
    from .initial_setup import require_root
    require_root()
    from .gateway_google_chat_recovery import HEX
    from .google_chat_retired_process import _identity
    if (confirmed is not True or not isinstance(note,str) or not 1<=len(note.strip())<=2000
            or not isinstance(row,dict) or any(not isinstance(row.get(k),str) or not HEX.fullmatch(row[k]) for k in ['id','snapshot_sha256'])):
        raise PermissionError('exakte historische Google-Quarantäne auswählen, begründen und Widerruf bestätigen')
    try:identity=_identity(account)
    except (ValueError,KeyError,TypeError):raise PermissionError('historisches Google-App-Profil geändert; neu prüfen') from None
    from .gateway_google_chat_identity import account_scope
    if row.get('account_scope')!=account_scope(identity):raise PermissionError('Quarantäne gehört nicht zum ausgewählten historischen App-Profil')
    params={'profile':account['profile'],'identity_sha256':account['identity_sha256'],'id':row['id'],'snapshot_sha256':row['snapshot_sha256'],
        'owner_uid':int(os.environ.get('SUDO_UID','0')),'note_sha256':hashlib.sha256(note.strip().encode()).hexdigest(),'confirmed':True}
    return _invoke('dispose-capsule',params)


def outputs(profile):
    from .initial_setup import require_root
    require_root()
    from .gateway_google_chat_recovery import profile_name
    return _invoke('outputs',{'profile':profile_name(profile)})


def purge_output(account,row,note,*,confirmed=False):
    from .initial_setup import require_root
    require_root()
    from .gateway_google_chat_recovery import HEX
    from .google_chat_retired_process import _identity
    from .google_chat_owner_process import NAME
    if (confirmed is not True or not isinstance(note,str) or not 1<=len(note.strip())<=2000 or not isinstance(row,dict)
            or any(not isinstance(row.get(k),str) or not HEX.fullmatch(row[k]) for k in ['id','snapshot_sha256','ownership_sha256'])
            or not isinstance(row.get('connector'),str) or not NAME.fullmatch(row['connector']) or row.get('purge_allowed') is not True):
        raise PermissionError('exakte freigegebene historische Ausgabebereinigung auswählen, begründen und bestätigen')
    try:identity=_identity(account)
    except (ValueError,KeyError,TypeError):raise PermissionError('historisches Ausgabe-App-Profil geändert; neu prüfen') from None
    from .gateway_google_chat_identity import account_scope
    if row.get('account_scope')!=account_scope(identity):raise PermissionError('Ausgabe gehört nicht zum ausgewählten historischen App-Profil')
    params={'profile':account['profile'],'identity_sha256':account['identity_sha256'],
        **{k:row[k] for k in ['id','snapshot_sha256','connector','ownership_sha256']},
        'owner_uid':int(os.environ.get('SUDO_UID','0')),'note_sha256':hashlib.sha256(note.strip().encode()).hexdigest(),'confirmed':True}
    return _invoke('purge-output',params)


def unassociated_outputs():
    from .initial_setup import require_root
    require_root()
    return _invoke('unassociated-outputs',{})


def purge_unassociated_output(row,note,*,confirmed=False):
    from .initial_setup import require_root
    require_root()
    from .gateway_google_chat_recovery import HEX
    if (confirmed is not True or not isinstance(note,str) or not 1<=len(note.strip())<=2000 or not isinstance(row,dict)
            or any(not isinstance(row.get(k),str) or not HEX.fullmatch(row[k]) for k in ['id','snapshot_sha256'])
            or row.get('purge_allowed') is not True):
        raise PermissionError('exakte unzugeordnete Ausgabe prüfen, ausdrücklich zur lokalen Bereinigung freigeben und begründen')
    params={k:row[k] for k in ['id','snapshot_sha256']}
    params.update(owner_uid=int(os.environ.get('SUDO_UID','0')),note_sha256=hashlib.sha256(note.strip().encode()).hexdigest(),confirmed=True)
    return _invoke('purge-unassociated-output',params)
