"""Prepared Google Chat account/routes; deliberately outside public activation."""
import json
import re
from urllib.parse import urlsplit

from .gateway import GatewayPolicy,SUPPORTED,digest

PROJECT=re.compile(r'[a-z][a-z0-9-]{4,61}[a-z0-9]\Z')
RESOURCE=re.compile(r'[A-Za-z0-9_-]{1,128}\Z')
EMAIL=re.compile(r'[a-z0-9][a-z0-9._+-]{0,127}@[a-z0-9][a-z0-9.-]{0,189}\.[a-z]{2,63}\Z')


def resource(value,kind,*,space=None):
    parts=value.split('/') if isinstance(value,str) else []
    if kind=='user':valid=len(parts)==2 and parts[0]=='users' and bool(re.fullmatch('[0-9]{1,32}',parts[1]))
    else:
        count={'space':2,'thread':4,'message':4}[kind]
        valid=len(parts)==count and parts[0]=='spaces' and bool(RESOURCE.fullmatch(parts[1]))
        if valid and count==4:
            pattern=r'[A-Za-z0-9_-]+(?:\.[A-Za-z0-9_-]+)*' if kind=='message' else r'[A-Za-z0-9_-]+'
            valid=parts[2]=={'thread':'threads','message':'messages'}[kind] and 1<=len(parts[3])<=128 and bool(re.fullmatch(pattern,parts[3]))
        if space is not None:valid=valid and '/'.join(parts[:2])==space
    if not valid:raise ValueError('exact Google Chat '+kind+' resource required; no email/display aliases or cross-space routes')
    return value


def credentials(value):
    if not isinstance(value,dict) or set(value)!={'service_account','bot_user','inbound'}:
        raise ValueError('explicit private Google Chat service account, expected bot resource and inbound transport required')
    sa=value['service_account']
    required={'type','project_id','private_key_id','private_key','client_email','client_id','auth_uri','token_uri','auth_provider_x509_cert_url','client_x509_cert_url'}
    if not isinstance(sa,dict) or not required<=set(sa)<=required|{'universe_domain'}:
        raise ValueError('complete dedicated Google service-account JSON required; no foreign ADC or arbitrary credential path')
    if (sa['type']!='service_account' or not isinstance(sa['project_id'],str) or not PROJECT.fullmatch(sa['project_id'])
            or not isinstance(sa['client_email'],str) or not EMAIL.fullmatch(sa['client_email'])
            or not sa['client_email'].endswith('@'+sa['project_id']+'.iam.gserviceaccount.com')
            or not isinstance(sa['private_key_id'],str) or not re.fullmatch('[a-f0-9]{40}',sa['private_key_id'])
            or not isinstance(sa['client_id'],str) or not re.fullmatch('[0-9]{1,32}',sa['client_id'])
            or sa['auth_uri']!='https://accounts.google.com/o/oauth2/auth'
            or sa['token_uri']!='https://oauth2.googleapis.com/token'
            or sa['auth_provider_x509_cert_url']!='https://www.googleapis.com/oauth2/v1/certs'
            or sa['client_x509_cert_url']!='https://www.googleapis.com/robot/v1/metadata/x509/'+sa['client_email'].replace('@','%40')
            or sa.get('universe_domain','googleapis.com')!='googleapis.com'):
        raise ValueError('dedicated exact Google service-account identity and official endpoints required')
    key=sa['private_key']
    if (not isinstance(key,str) or not 512<=len(key)<=16384 or not key.startswith('-----BEGIN PRIVATE KEY-----\n')
            or not key.endswith('-----END PRIVATE KEY-----\n') or '\r' in key):
        raise ValueError('bounded PKCS8 Google service-account key required; private SDK verifies key material before readiness')
    resource(value['bot_user'],'user');inbound=value['inbound']
    if not isinstance(inbound,dict) or not isinstance(inbound.get('mode'),str):raise ValueError('explicit inbound mode required')
    if inbound['mode']=='pubsub':
        if (set(inbound)!={'mode','subscription'} or not isinstance(inbound['subscription'],str)
                or not re.fullmatch('projects/'+re.escape(sa['project_id'])+'/subscriptions/[A-Za-z][A-Za-z0-9._~+%-]{2,254}',inbound['subscription'])):
            raise ValueError('exact same-project Pub/Sub pull subscription required')
    elif inbound['mode']=='http':
        if set(inbound)!={'mode','port','tls','audience','service_account_email'}:raise ValueError('HTTPS callback, audience and exact Google caller identity required')
        if type(inbound['port']) is not int or not 1024<=inbound['port']<=65535:raise ValueError('explicit unprivileged Google Chat HTTPS listener port required')
        from .gateway_line_tls import material
        tls=material(inbound['tls'],verify=False,webhook_path='/google-chat')
        audience=inbound['audience']
        if (not isinstance(audience,str) or not (audience==tls['public_url'] or re.fullmatch('[1-9][0-9]{0,31}',audience)) or urlsplit(audience).fragment
                or not isinstance(inbound['service_account_email'],str) or not EMAIL.fullmatch(inbound['service_account_email'])
                or not inbound['service_account_email'].endswith('.gserviceaccount.com')):
            raise ValueError('exact callback audience and dedicated Google service account required')
    else:raise ValueError('only explicit Pub/Sub pull or authenticated HTTPS callbacks supported')
    if len(json.dumps(value).encode())>65536:raise ValueError('private Google Chat configuration exceeds bound')
    return {**value,'service_account':dict(sa),'inbound':dict(inbound)}


def scope(value):
    return 'google-chat:'+digest([value['service_account']['project_id'],value['service_account']['client_email'],value['bot_user']])


def validate_binding(binding):
    resource(binding.get('sender'),'user');resource(binding.get('chat'),'space')
    if binding.get('thread'):resource(binding['thread'],'thread',space=binding['chat'])
    elif binding.get('thread')!='':raise ValueError('explicit empty or exact Google Chat thread required')
    if (not isinstance(binding.get('scope'),str) or not re.fullmatch('google-chat:[a-f0-9]{64}',binding['scope'])
            or not isinstance(binding.get('generation'),str) or not re.fullmatch('[a-f0-9]{64}',binding['generation'])
            or type(binding.get('since')) is not int or not 0<binding['since']<2**53):
        raise ValueError('exact account scope and fresh timed Google Chat owner grant required')
    caps=binding.get('capabilities')
    if (not isinstance(caps,list) or not caps or any(not isinstance(c,str) or c not in {'create','read','answer','cancel'} for c in caps)
            or len(set(caps))!=len(caps)):raise ValueError('explicit Google Chat mission capabilities required')
    for flag in ['require_mention','allow_media','allow_voice','allow_video','allow_outbound_media']:
        if flag in binding and type(binding[flag]) is not bool:raise ValueError('separate boolean Google Chat media/mention consent required')
        if binding.get(flag) is True and flag!='require_mention' and ('read' if flag=='allow_outbound_media' else 'create') not in caps:
            raise ValueError('Google Chat media consent requires corresponding mission capability')


class PreparedGoogleChatPolicy(GatewayPolicy):
    platforms=frozenset(SUPPORTED|{'google_chat'})

    def __init__(self,value):
        super().__init__(value)
        for binding in self.bindings.values():
            if self.connectors[binding['connector']]['platform']=='google_chat':validate_binding(binding)
