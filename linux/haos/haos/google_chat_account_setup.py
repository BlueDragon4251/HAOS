"""Authenticated Owner account publication; never runs the native agent setup."""
import json


def configure(connector,value):
    from .initial_setup import require_root,quiesce_for_setup
    require_root()
    from .gateway_google_chat import credentials,scope
    from .gateway_setup import load,persist
    from .gateway import GatewayPolicy
    from .owner import audit
    value=credentials(value)
    if value['inbound']['mode']=='pubsub' and value['inbound'].get('trust_topic_publishers') is not True:
        raise PermissionError('Pub/Sub transport authenticates the subscription, not each event publisher; explicitly approve all authorized topic publishers')
    if value['inbound']['mode']=='http':
        from .gateway_line_tls import material
        material(value['inbound']['tls'],verify=True,webhook_path='/google-chat')
    policy,private=load()
    if any(row['id']!=connector and row['platform']=='google_chat' and scope(private['connectors'][row['id']])==scope(value)
            for row in policy['connectors']):raise ValueError('Eine Google-App-Identität darf nur einem Konnektor gehören.')
    old=next((row for row in policy['connectors'] if row['id']==connector),None)
    if old is not None and (old['platform']!='google_chat' or private['connectors'].get(connector)!=value):
        policy['bindings']=[row for row in policy['bindings'] if row['connector']!=connector]
    policy['connectors']=[row for row in policy['connectors'] if row['id']!=connector]+[{'id':connector,'platform':'google_chat'}]
    GatewayPolicy(policy);quiesce_for_setup(gateway_only=True)
    private['connectors'][connector]=value;persist(policy,private)
    audit('setup.gateway',{'connector':connector,'platform':'google_chat'})
    return {'configured':True,'platform':'google_chat','sender_pairing_required':True,'restart_required':True,
        'message_sent':False,'external_acceptance_verified':False}


def public(value):
    from .gateway_google_chat import credentials,scope
    value=credentials(value);sa=value['service_account'];inbound=value['inbound']
    info=({k:inbound[k] for k in ['mode','subscription']}|{'trust_topic_publishers':inbound.get('trust_topic_publishers',False)}
        if inbound['mode']=='pubsub' else {k:inbound[k] for k in ['mode','port','audience','service_account_email']}|
        {'public_url':inbound['tls']['public_url'],'saved_tls':True})
    return {'project_id':sa['project_id'],'service_account_email':sa['client_email'],'bot_user':value['bot_user'],
        'inbound':info,'saved_service_account':True,'scope':scope(value)}


def save_account(connector,bot_user,inbound,service_account_json='',*,keep_service_account=False):
    from .initial_setup import require_root
    require_root()
    if type(keep_service_account) is not bool or not isinstance(service_account_json,str):
        raise ValueError('Ausdrückliche Wahl zwischen gespeichertem und neuem privaten Google-Konto erforderlich.')
    if keep_service_account:
        if service_account_json:raise ValueError('Gespeichertes Konto oder neues JSON wählen; niemals beides.')
        from .google_chat_owner_setup import saved
        _,old=saved(connector);account=old['service_account']
    else:
        if not 1<=len(service_account_json.encode())<=32768:raise ValueError('Begrenztes vollständiges privates Service-Account-JSON erforderlich.')
        from .gateway_line_ingress import _object
        from .gateway_dingtalk_admission import finite
        account=json.loads(service_account_json,object_pairs_hook=_object,parse_constant=finite)
    return configure(connector,{'service_account':account,'bot_user':bot_user,'inbound':inbound})
