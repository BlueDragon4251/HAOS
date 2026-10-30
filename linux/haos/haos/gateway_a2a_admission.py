"""Bounded A2A wire admission behind token-derived identity and independent grants."""
import hashlib
import math
import re
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
            or not {'message'}<=set(data['params'])<={'message','contextId','configuration'}):
        raise Refused('unsupported-content')
    params=data['params'];message=params['message']
    if (not isinstance(message,dict) or set(message) not in ({'messageId','contextId','role','parts'},{'messageId','contextId','role','parts','taskId','metadata'})
            or not isinstance(message['role'],str) or message['role'] not in {'ROLE_USER','user'}):
        raise Refused('unsupported-content')
    if 'taskId' in message and (not isinstance(message['taskId'],str) or not re.fullmatch('task-[0-9a-f]{16}',message['taskId'])):
        raise Refused('unsupported-content')
    if 'taskId' in message and (not isinstance(message['metadata'],dict) or set(message['metadata'])!={'haosQuestionEpoch'}
            or not isinstance(message['metadata']['haosQuestionEpoch'],str) or not re.fullmatch('[0-9a-f]{64}',message['metadata']['haosQuestionEpoch'])):
        raise Refused('exact-question-epoch-required')
    try:
        identity=opaque(message['messageId']);context=opaque(message['contextId'])
    except ValueError:raise Refused('unsupported-content') from None
    if 'contextId' in params and params['contextId']!=context:raise Refused('ambiguous-context')
    parts=message['parts']
    if not isinstance(parts,list) or not 1<=len(parts)<=16:raise Refused('unsupported-content')
    for part in parts:
        if not isinstance(part,dict):raise Refused('unsupported-content')
        if 'text' not in part:continue
        if (not {'text'}<=set(part)<={'text','kind','type','mediaType'}
                or not isinstance(part['text'],str) or len(part['text'].encode())>32000
                or 'kind' in part and part['kind']!='text' or 'type' in part and part['type']!='text'
                or 'mediaType' in part and part['mediaType']!='text/plain'):
            raise Refused('unsupported-content')
    from plugins.platforms.a2a import protocol,security
    aliases=set([*value['peer_tokens'].values(),value['tls']['private_key'],*[item['secret'] for item in value.get('callbacks',{}).values()]])
    # Credentials embedded in JSON escapes must not become agent input either.
    for _ in range(2):
        import json
        aliases|={json.dumps(secret,ensure_ascii=ascii)[1:-1] for secret in tuple(aliases) for ascii in (True,False)}
    # Derive aliases only from fixed account material, never from the previous
    # expansion. Escaping already escaped PEM aliases on every request grows
    # exponentially and can exhaust a real long-lived worker during replay.
    redactor.secrets=sorted(set(redactor.secrets)|aliases,key=len,reverse=True)
    from .gateway_a2a_media import projection
    try:projected,resources=projection(value,peer,params,redactor)
    except (ValueError,PermissionError):raise Refused('unapproved-media') from None
    if resources and 'taskId' in message:raise Refused('text-only-clarification-required')
    text=protocol.extract_text(projected)
    if (not text or len(text.encode())>32000 or protocol.extract_context_id(projected)!=context):raise Refused('unsupported-content')
    if redactor.text(text)!=text:raise Refused('private-reflection')
    framed=security.wrap_inbound(peer,text)
    if not isinstance(framed,str) or len(framed.encode())>32000 or redactor.text(framed)!=framed:
        raise Refused('private-reflection')
    envelope={'platform':'a2a','sender':peer,'chat':context,'scope':scope(value,peer),'thread':'',
        'message_id':identity,'is_bot':False,'text':framed}
    try:binding=policy.authorize(connector,envelope)
    except PermissionError:raise Refused('unapproved-route') from None
    validate_binding(binding)
    if 'configuration' in params:
        owner=value.get('callbacks',{}).get(peer)
        if ('taskId' in message or owner is None or binding.get('allow_callback') is not True or 'read' not in binding['capabilities']
                or params['configuration']!={'taskPushNotificationConfig':{'url':owner['url']}}):
            raise Refused('independent-callback-approval-required')
    from .gateway_media import approved
    if any(not approved(binding,resource['kind']) for resource in resources):raise Refused('independent-media-consent-required')
    required='answer' if 'taskId' in message else 'create'
    if required not in binding['capabilities']:raise Refused('mission-'+required+'-required')
    # The server's authenticated receive instant is used: A2A's Message has no
    # trustworthy sender timestamp. Durable first admission binds the grant; an
    # old source cannot be recreated under a later generation on replay.
    received=time.time() if received_at is None else received_at
    if type(received) not in {int,float} or not math.isfinite(received) or not 0<received<=time.time()+300:
        raise Refused('invalid-time')
    if binding['since']>=received*1000:raise Refused('pre-grant')
    policy.current_binding({'binding_id':binding['id'],'binding_digest':digest(binding)})
    return {**({'target_task_id':message['taskId'],'question_epoch':message['metadata']['haosQuestionEpoch']} if 'taskId' in message else {}),
        **({'resources':resources} if resources else {}),'envelope':envelope,'binding_id':binding['id'],'binding_digest':digest(binding),
        'credential_scope':digest([connector,value]),'raw_sha256':hashlib.sha256(raw).hexdigest(),'received_at':received}
