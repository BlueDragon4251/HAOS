"""Owner-only A2A server, named-peer and exact-context administration."""
from copy import deepcopy
import secrets
import time

from .gateway_a2a import credentials,scope,PreparedA2APolicy,validate_binding


def configure(connector,value):
    from .initial_setup import require_root,quiesce_for_setup
    from .gateway_setup import load,persist
    from .owner import audit
    require_root();value=credentials(value)
    policy,private=load()
    if any(row['id']!=connector and row['platform']=='a2a' for row in policy['connectors']):
        raise ValueError('one isolated A2A server supports up to sixteen named peers')
    if any(row['id']==connector and row['platform']!='a2a' for row in policy['connectors']):
        policy['bindings']=[row for row in policy['bindings'] if row['connector']!=connector]
    policy['connectors']=[row for row in policy['connectors'] if row['id']!=connector]+[{'id':connector,'platform':'a2a'}]
    PreparedA2APolicy(policy);quiesce_for_setup(gateway_only=True)
    private['connectors'][connector]=value;persist(policy,private)
    audit('setup.gateway',{'connector':connector,'platform':'a2a'})
    return {'configured':True,'platform':'a2a','sender_pairing_required':True,'restart_required':True,
        'external_reachability_verified':False,'message_sent':False}


def saved(connector):
    from .initial_setup import require_root
    from .gateway_setup import load
    require_root();policy,private=load()
    if not any(row['id']==connector and row['platform']=='a2a' for row in policy['connectors']):
        raise ValueError('select one saved A2A server')
    return policy,private,credentials(private['connectors'][connector],verify_tls=False)


def save_account(connector,server,peer,token,certificate_path='',private_key_path='',*,keep_tls=False,keep_token=False):
    from .initial_setup import require_root,read_line_tls_file
    from .gateway_setup import load
    require_root()
    if (not isinstance(server,dict) or set(server)!={'agent_name','port','public_url','bind_host','public_listener'}
            or type(keep_tls) is not bool or type(keep_token) is not bool):
        raise ValueError('exact A2A server fields and explicit private material reuse choices required')
    policy,private=load();old=None
    if any(row['id']==connector and row['platform']=='a2a' for row in policy['connectors']):old=credentials(private['connectors'][connector],verify_tls=False)
    if keep_tls:
        if old is None or certificate_path or private_key_path:raise ValueError('select saved TLS material or two replacement PEM files')
        certificate=old['tls']['certificate'];key=old['tls']['private_key']
    else:
        certificate=read_line_tls_file(certificate_path,'certificate');key=read_line_tls_file(private_key_path,'private_key')
    if keep_token:
        if old is None or peer not in old['peer_tokens'] or token:raise ValueError('keeping a bearer token requires its exact saved peer and an empty replacement field')
        token=old['peer_tokens'][peer]
    value=deepcopy(old) if old is not None else {}
    value.update(agent_name=server['agent_name'],port=server['port'],tls={'public_url':server['public_url'],
        'bind_host':server['bind_host'],'public_listener':server['public_listener'],'certificate':certificate,'private_key':key})
    value.setdefault('peer_tokens',{})[peer]=token
    return configure(connector,value)


def set_peer(connector,peer,token,*,keep_token=False,download_origins=None,callback_url=None,callback_secret='',keep_callback_secret=False):
    from .initial_setup import require_root
    require_root();_,_,value=saved(connector)
    if type(keep_token) is not bool or type(keep_callback_secret) is not bool:
        raise ValueError('explicit A2A key reuse choices required')
    if keep_token:
        if peer not in value['peer_tokens'] or token:raise ValueError('exact saved peer required to keep its private bearer token')
        token=value['peer_tokens'][peer]
    previous=value.get('callbacks',{}).get(peer)
    if callback_url is None and (callback_secret or keep_callback_secret):raise ValueError('select the exact callback destination before changing its signing key')
    if keep_callback_secret:
        if previous is None or callback_url!=previous['url'] or callback_secret:
            raise ValueError('keeping a signing key requires the same saved peer and exact callback destination')
        callback_secret=previous['secret']
    value['peer_tokens'][peer]=token
    if download_origins is not None:
        if download_origins:value.setdefault('download_origins',{})[peer]=download_origins
        elif 'download_origins' in value:value['download_origins'].pop(peer,None)
    if callback_url is not None:
        if callback_url or callback_secret:value.setdefault('callbacks',{})[peer]={'url':callback_url,'secret':callback_secret}
        elif 'callbacks' in value:value['callbacks'].pop(peer,None)
    return configure(connector,value)


def remove_peer(connector,peer):
    from .initial_setup import require_root
    require_root();_,_,value=saved(connector)
    if peer not in value['peer_tokens']:raise ValueError('select an exact saved A2A peer')
    if len(value['peer_tokens'])==1:raise ValueError('remove the connector to revoke its last peer')
    value['peer_tokens'].pop(peer)
    for key in ['callbacks','download_origins']:
        if key in value:value[key].pop(peer,None)
    return configure(connector,value)


def pair(binding_id,connector,peer,context,identity,capabilities,*,allow_media=False,allow_voice=False,allow_video=False,allow_outbound_media=False,allow_callback=False):
    from .initial_setup import require_root,quiesce_for_setup
    from .gateway_setup import persist
    from .owner import audit
    require_root();policy,private,value=saved(connector)
    caps=list(capabilities)
    if (not caps or not set(caps)<={'create','read','cancel','answer'} or len(set(caps))!=len(caps)
            or any(cap in caps for cap in ['cancel','answer']) and 'read' not in caps):
        raise ValueError('A2A supports exact create/read/cancel/answer rights; cancel and answers need read access')
    if peer not in value['peer_tokens']:raise ValueError('pair an exact saved named peer, never a wildcard or network address')
    item={'id':binding_id,'connector':connector,'sender':peer,'chat':context,'scope':scope(value,peer),'thread':'','identity':identity,
        'capabilities':caps,'generation':secrets.token_hex(32),'since':time.time_ns()//1_000_000,
        'allow_media':allow_media,'allow_voice':allow_voice,'allow_video':allow_video,'allow_outbound_media':allow_outbound_media,'allow_callback':allow_callback}
    validate_binding(item)
    if allow_callback and peer not in value.get('callbacks',{}):raise ValueError('save this peer callback destination and separate signing key before granting callbacks')
    if allow_voice:
        from .speech_setup import status
        speech=status()
        if not all(speech[key] for key in ['enabled','runtime_ready','model_ready']):
            raise PermissionError('configure the reviewed local speech service/model before approving A2A voice')
    policy['bindings']=[row for row in policy['bindings'] if row['id']!=binding_id]+[item]
    PreparedA2APolicy(policy);quiesce_for_setup(gateway_only=True);persist(policy,private)
    audit('setup.gateway-pair',{'binding':binding_id,'connector':connector})
    return {'paired':True,'binding':binding_id,'message_sent':False}


def public(value):
    """Public configuration for authenticated owner forms; no key or PEM material."""
    return {'agent_name':value['agent_name'],'port':value['port'],'public_url':value['tls']['public_url'],
        'bind_host':value['tls']['bind_host'],'public_listener':value['tls']['public_listener'],'saved_tls':True,
        'peers':[{'name':peer,'saved_token':True,'download_origins':value.get('download_origins',{}).get(peer,[]),
            'callback_url':value.get('callbacks',{}).get(peer,{}).get('url',''),
            'saved_callback_secret':peer in value.get('callbacks',{})} for peer in value['peer_tokens']]}


def _invoke(connector,action,params):
    from .initial_setup import require_root,quiesce_for_setup
    from .gateway_setup import stopped_gateway
    from .gateway_a2a import authority
    from .a2a_owner_process import command,response
    from .gateway_line_ingress import _object
    from .gateway_dingtalk_admission import finite
    from .owner import audit
    import json,os,pwd,subprocess
    require_root()
    quiesce_for_setup(gateway_only=True);stopped_gateway();_,_,value=saved(connector)
    publication=authority(connector,value);account=pwd.getpwnam('haos-gateway')
    if account.pw_uid==0 or account.pw_gid==0:raise PermissionError('A2A owner inspection must use the separate private gateway UID')
    request={'action':action,'connector':connector,'credentials':value,'policy_sha256':publication,'parent_pid':os.getpid(),
        'params':params}
    try:
        result=subprocess.run(command(),input=json.dumps(request,ensure_ascii=False)+'\n',text=True,capture_output=True,timeout=25,
            user=account.pw_uid,group=account.pw_gid,extra_groups=[],umask=0o077,cwd='/usr/lib/haos',
            env={'PATH':'/usr/bin:/bin','LANG':'C.UTF-8','PYTHONDONTWRITEBYTECODE':'1','HERMES_SAFE_MODE':'1'})
    except subprocess.TimeoutExpired:raise RuntimeError('A2A-Prüfung: Zeitlimit; private Runtime und gespeicherten Zustand prüfen.') from None
    if result.returncode or len(result.stdout.encode())>65536:raise RuntimeError('Private A2A-Prüfung fehlgeschlagen; Runtime und Journal prüfen.')
    from .redaction import Redactor
    secrets=[*value['peer_tokens'].values(),value['tls']['private_key'],*[item['secret'] for item in value.get('callbacks',{}).values()]]
    if Redactor(secrets).text(result.stdout)!=result.stdout:raise PermissionError('private material in A2A inspection response')
    checked=response(json.loads(result.stdout,object_pairs_hook=_object,parse_constant=finite),action)
    authority(connector,value,publication);audit('gateway.a2a-owner-inspected' if action in {'inspect','sources'} else 'gateway.a2a-owner-recovered',
        {'connector':connector,'action':action,'message_sent':False,**({'receipt':checked['receipt'],'note_sha256':params['note_sha256']} if 'receipt' in checked else {})})
    return checked


def inspect(connector,action='inspect',cursor=''):
    from .a2a_owner_process import cursor_value
    if action not in {'inspect','sources'}:raise ValueError('select a closed A2A no-send inspection action')
    cursor_value(cursor)
    if action=='inspect' and cursor:raise ValueError('listener inspection does not use a source cursor')
    return _invoke(connector,action,{'cursor':cursor} if action=='sources' else {})


def recover(connector,row,action,note,*,confirmed=False):
    from .initial_setup import require_root
    from .a2a_owner_process import response
    from .a2a_owner_recovery import ACTIONS,parameters
    from .gateway import digest
    require_root()
    if action not in ACTIONS or confirmed is not True or not isinstance(note,str) or not 1<=len(note.strip())<=2000:
        raise PermissionError('explicit inspected owner recovery decision and bounded review note required')
    response({'tasks':[row],'has_more':False,'cursor':'','message_sent':False,'mission_created':False},'sources')
    params={key:row[key] for key in ['profile','peer_journal','task_id','snapshot_sha256']}
    params['note_sha256']=digest(note.strip());parameters(params)
    return _invoke(connector,action,params)
