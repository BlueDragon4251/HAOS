"""Bounded A2A wire admission behind token-derived identity and independent grants."""
import hashlib
import math
import time

from .gateway import GatewayPolicy,digest
from .gateway_a2a import opaque,scope,validate_binding
from .gateway_dingtalk_admission import parse as bounded_json,Refused as InvalidJSON
from .redaction import Redactor

SEND=frozenset({'SendMessage','SendStreamingMessage','message/send','message/stream'})


class Refused(PermissionError):
    def __init__(self,reason):
        super().__init__('A2A source or content is not approved');self.reason=reason


def parse(raw):
    try:return bounded_json(raw)
    except InvalidJSON:raise Refused('unsupported-content') from None


def security_context(value):
    """Actual frozen token comparer, never an IP/shared-token authentication mode."""
    from plugins.platforms.a2a.security import A2ASecurityContext
    peers=value['peer_tokens']
    return A2ASecurityContext(bearer_token='',peer_tokens=tuple((token,name) for name,token in sorted(peers.items())),
        trusted_peers=frozenset(peers),allow_all_users=False,requested_host=value['tls']['bind_host'],push_secret='')


def approve(policy,connector,value,peer,raw,redactor,*,received_at=None):
    if (not isinstance(policy,GatewayPolicy) or policy.connectors.get(connector,{}).get('platform')!='a2a'
            or not isinstance(peer,str) or peer not in value['peer_tokens'] or not isinstance(redactor,Redactor)):
        raise Refused('unapproved-route')
    data=parse(raw)
    if (set(data)!={'jsonrpc','id','method','params'} or data['jsonrpc']!='2.0'
            or type(data['id']) not in {str,int} or isinstance(data['id'],str) and not 1<=len(data['id'])<=128
            or type(data['id']) is int and not -(2**53)<data['id']<2**53
            or not isinstance(data['method'],str) or data['method'] not in SEND or not isinstance(data['params'],dict)
            or set(data['params']) not in ({'message'},{'message','contextId'})):
        raise Refused('unsupported-content')
    params=data['params'];message=params['message']
    if (not isinstance(message,dict) or set(message)!={'messageId','contextId','role','parts'}
            or not isinstance(message['role'],str) or message['role'] not in {'ROLE_USER','user'}):
        raise Refused('unsupported-content')
    try:
        identity=opaque(message['messageId']);context=opaque(message['contextId'])
    except ValueError:raise Refused('unsupported-content') from None
    if 'contextId' in params and params['contextId']!=context:raise Refused('ambiguous-context')
    parts=message['parts']
    if not isinstance(parts,list) or not 1<=len(parts)<=16:raise Refused('unsupported-content')
    for part in parts:
        if (not isinstance(part,dict) or not {'text'}<=set(part)<={'text','kind','type','mediaType'}
                or not isinstance(part['text'],str) or len(part['text'].encode())>32000
                or 'kind' in part and part['kind']!='text' or 'type' in part and part['type']!='text'
                or 'mediaType' in part and part['mediaType']!='text/plain'):
            raise Refused('unsupported-content')
    from plugins.platforms.a2a import protocol,security
    text=protocol.extract_text(params)
    if (not text or len(text.encode())>32000 or protocol.extract_context_id(params)!=context):raise Refused('unsupported-content')
    redactor.secrets=sorted(set([*redactor.secrets,*value['peer_tokens'].values(),value['tls']['private_key']]),key=len,reverse=True)
    # Credentials embedded in JSON escapes must not become agent input either.
    for _ in range(2):
        import json
        redactor.secrets=sorted(set([*redactor.secrets,*(json.dumps(secret,ensure_ascii=ascii)[1:-1]
            for secret in redactor.secrets for ascii in (True,False))]),key=len,reverse=True)
    if redactor.text(text)!=text:raise Refused('private-reflection')
    framed=security.wrap_inbound(peer,text)
    if not isinstance(framed,str) or len(framed.encode())>32000 or redactor.text(framed)!=framed:
        raise Refused('private-reflection')
    envelope={'platform':'a2a','sender':peer,'chat':context,'scope':scope(value,peer),'thread':'',
        'message_id':identity,'is_bot':False,'text':framed}
    try:binding=policy.authorize(connector,envelope)
    except PermissionError:raise Refused('unapproved-route') from None
    validate_binding(binding)
    if 'create' not in binding['capabilities']:raise Refused('mission-create-required')
    # The server's authenticated receive instant is used: A2A's Message has no
    # trustworthy sender timestamp. Durable first admission binds the grant; an
    # old source cannot be recreated under a later generation on replay.
    received=time.time() if received_at is None else received_at
    if type(received) not in {int,float} or not math.isfinite(received) or not 0<received<=time.time()+300:
        raise Refused('invalid-time')
    if binding['since']>=received*1000:raise Refused('pre-grant')
    policy.current_binding({'binding_id':binding['id'],'binding_digest':digest(binding)})
    return {'envelope':envelope,'binding_id':binding['id'],'binding_digest':digest(binding),
        'credential_scope':digest([connector,value]),'raw_sha256':hashlib.sha256(raw).hexdigest(),'received_at':received}
