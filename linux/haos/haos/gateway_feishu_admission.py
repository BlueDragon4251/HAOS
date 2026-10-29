"""Independent projection of already-authenticated Feishu events before native I/O.

These helpers do not authenticate a socket/webhook or grant a sender. Transport
must supply verified bytes and the current root publication before calling them.
"""
import hashlib
import json
import math
import re
import time

from .gateway import GatewayPolicy,digest
from .gateway_feishu import credentials,scope,validate_binding,OPEN_ID,CHAT_ID,MESSAGE_ID,THREAD_ID
from .gateway_line_ingress import _object

MAX_EVENT=1024*1024
MAX_CONTENT=512*1024
TYPES=frozenset({'text','post','image','file','audio','media','merge_forward','share_chat','interactive','card'})


class Refused(PermissionError):
    def __init__(self,reason):
        super().__init__('Feishu source or content is not approved')
        self.reason=reason


def finite(_value):raise ValueError('finite platform JSON required')


def bounded(value):
    pending=[(value,0)];count=0
    while pending:
        item,depth=pending.pop();count+=1
        if count>16384 or depth>16:raise Refused('unsupported-content')
        if isinstance(item,dict):pending.extend((part,depth+1) for part in [*item.keys(),*item.values()])
        elif isinstance(item,list):pending.extend((part,depth+1) for part in item)
        elif isinstance(item,str):
            try:item.encode('utf-8')
            except UnicodeError:raise Refused('unsupported-content') from None
        elif type(item) is float and not math.isfinite(item):raise Refused('unsupported-content')
        elif type(item) not in {int,float,bool,type(None)}:raise Refused('unsupported-content')


def parse(raw):
    if not isinstance(raw,bytes) or not 1<=len(raw)<=MAX_EVENT:raise Refused('unsupported-content')
    try:value=json.loads(raw.decode('utf-8'),object_pairs_hook=_object,parse_constant=finite)
    except (ValueError,UnicodeError,RecursionError):raise Refused('unsupported-content') from None
    if not isinstance(value,dict):raise Refused('unsupported-content')
    bounded(value)
    return value


def milliseconds(value):
    if isinstance(value,str) and value.isascii() and value.isdecimal() and 1<=len(value)<=16 and not value.startswith('0'):
        value=int(value)
    if type(value) is not int or not 0<value<2**53:raise Refused('invalid-time')
    return value


def approve(policy,connector,value,raw):
    if not isinstance(policy,GatewayPolicy) or policy.connectors.get(connector,{}).get('platform')!='feishu':
        raise Refused('unapproved-route')
    value=credentials(value,verify_tls=False);data=parse(raw)
    try:
        header=data['header'];event=data['event'];sender=event['sender'];message=event['message']
        if any(not isinstance(part,dict) for part in [header,event,sender,message,sender.get('sender_id')]):
            raise Refused('unsupported-content')
        if data.get('schema')!='2.0' or header.get('event_type')!='im.message.receive_v1':raise Refused('unsupported-event')
        if header.get('app_id')!=value['app_id']:raise Refused('wrong-application')
        if header.get('tenant_key')!=value['tenant_key'] or sender.get('tenant_key')!=value['tenant_key']:
            raise Refused('wrong-tenant')
        identity=sender['sender_id'].get('open_id')
        if sender.get('sender_type')!='user' or identity==value['bot_open_id']:raise Refused('self-or-automated')
        if not isinstance(identity,str) or not OPEN_ID.fullmatch(identity):raise Refused('unapproved-route')
        if message.get('chat_type') not in {'p2p','group'}:raise Refused('unsupported-content')
        for key,pattern in [('chat_id',CHAT_ID),('message_id',MESSAGE_ID)]:
            if not isinstance(message.get(key),str) or not pattern.fullmatch(message[key]):raise Refused('unsupported-content')
        thread=message.get('thread_id')
        if thread is None:thread=''
        if not isinstance(thread,str) or thread and not THREAD_ID.fullmatch(thread):raise Refused('unsupported-content')
        for key in ['root_id','parent_id']:
            if message.get(key) is not None and (not isinstance(message[key],str) or message[key] and not MESSAGE_ID.fullmatch(message[key])):
                raise Refused('unsupported-content')
        if not isinstance(header.get('event_id'),str) or not re.fullmatch('[A-Za-z0-9_-]{16,128}',header['event_id']):
            raise Refused('unsupported-content')
        envelope={'platform':'feishu','sender':identity,'chat':message['chat_id'],'scope':scope(value),
            'thread':thread,'message_id':message['message_id'],'is_bot':False,'text':''}
        try:binding=policy.authorize(connector,envelope)
        except PermissionError:raise Refused('unapproved-route') from None
        validate_binding(binding)
        stamp=milliseconds(message.get('create_time'));event_at=milliseconds(header.get('create_time'))
        now=time.time()*1000
        if any(not binding['since']<part<=now+300000 for part in [stamp,event_at]):raise Refused('pre-grant')
        mentions=message.get('mentions')
        if mentions is None:mentions=[]
        if not isinstance(mentions,list) or len(mentions)>64 or any(not isinstance(part,dict) for part in mentions):
            raise Refused('unsupported-content')
        if message['chat_type']=='group' and binding.get('require_mention',True):
            if not any(isinstance(part.get('id'),dict) and part['id'].get('open_id')==value['bot_open_id'] for part in mentions):
                raise Refused('mention-required')
        if not isinstance(message.get('message_type'),str) or message['message_type'] not in TYPES:raise Refused('unsupported-content')
        content=message.get('content')
        if not isinstance(content,str) or not 1<=len(content.encode())<=MAX_CONTENT:raise Refused('unsupported-content')
        try:body=json.loads(content,object_pairs_hook=_object,parse_constant=finite)
        except (ValueError,RecursionError):raise Refused('unsupported-content') from None
        if not isinstance(body,dict):raise Refused('unsupported-content')
        bounded(body)
        if message['message_type']=='text' and not isinstance(body.get('text'),str):raise Refused('unsupported-content')
    except (KeyError,TypeError,UnicodeError):raise Refused('unsupported-content') from None
    policy.current_binding({'binding_id':binding['id'],'binding_digest':digest(binding)})
    return {'envelope':envelope,'binding_id':binding['id'],'binding_digest':digest(binding),
        'received_at':stamp/1000,'event_at':event_at/1000,'event_id':header['event_id'],
        'raw_sha256':hashlib.sha256(raw).hexdigest(),'credential_scope':digest([connector,value])}



def media_permissions(message_type,body,key,native_type):
    """Wire resource selectors are not media consent (native media becomes file)."""
    flags={'image':'allow_media','file':'allow_media','audio':'allow_voice','video':'allow_video','media':'allow_video'}
    if message_type in {'image','file','audio','media'}:return [flags[message_type]]
    required=set();pending=[body]
    if message_type=='post':
        while pending:
            item=pending.pop()
            if isinstance(item,dict):
                tag=item.get('tag');tag=tag.strip().lower() if isinstance(tag,str) else ''
                if tag in {'img','file','audio','video','media'} and (item.get('image_key') if tag=='img' else item.get('file_key'))==key:
                    required.add(flags['image' if tag=='img' else tag])
                pending.extend(item.values())
            elif isinstance(item,list):pending.extend(item)
    if not required:required.add(flags[native_type])
    return sorted(required)


def normalize(policy,connector,value,raw,approval,redactor):
    """Actual pinned pure codec only. No SDK client, resource fetch or file write."""
    checked=approve(policy,connector,value,raw)
    if checked!=approval:raise Refused('changed-source')
    binding=policy.current_binding(checked)
    from .redaction import Redactor
    if not isinstance(redactor,Redactor):raise Refused('private-redaction-required')
    try:
        from plugins.platforms.feishu import adapter as native
        if not native._load_lark_oapi():raise Refused('runtime-unavailable')
        from lark_oapi.api.im.v1 import P2ImMessageReceiveV1
    except ImportError:raise Refused('runtime-unavailable') from None
    try:
        data=P2ImMessageReceiveV1(parse(raw));message=data.event.message
        normalized=native.normalize_feishu_message(message_type=message.message_type,raw_content=message.content,
            mentions=message.mentions,bot=native._FeishuBotIdentity(open_id=value['bot_open_id']))
    except (ValueError,TypeError,KeyError,AttributeError,RecursionError):raise Refused('unsupported-content') from None
    resources=[]
    for key in normalized.image_keys:resources.append({'key':key,'type':'image','name':''})
    for ref in normalized.media_refs:resources.append({'key':ref.file_key,'type':ref.resource_type,'name':ref.file_name})
    if len(resources)>4:raise Refused('unsupported-content')
    seen=set()
    for resource in resources:
        key=resource['key'];kind=resource['type'];name=resource['name']
        if (not isinstance(key,str) or not re.fullmatch('[A-Za-z0-9_-]{1,256}',key) or key in seen
                or kind not in {'image','file','audio','video','media'} or not isinstance(name,str) or len(name.encode())>512
                or any(ord(char)<32 or ord(char)==127 for char in name)):
            raise Refused('unsupported-content')
        seen.add(key)
        permissions=media_permissions(message.message_type,json.loads(message.content),key,kind)
        if any(not binding.get(flag,False) for flag in permissions) or 'create' not in binding['capabilities']:
            raise Refused('media-not-approved')
        resource['permissions']=permissions
    if message.message_type in {'image','file','audio','media'} and not resources:raise Refused('unsupported-content')
    text=native._strip_edge_self_mentions(normalized.text_content,normalized.mentions)
    if not text.startswith('/'):
        hint=native._build_mention_hint(normalized.mentions)
        if hint:text=hint+'\n\n'+text if text else hint
    if not text and resources:text='[Feishu attachment]'
    if (not isinstance(text,str) or not 1<=len(text.strip())<=32000 or len(text.encode())>128000
            or '\0' in text):raise Refused('unsupported-content')
    if redactor.text(text)!=text:raise Refused('credential-reflection')
    if approve(policy,connector,value,raw)!=checked:raise Refused('changed-source')
    return {'envelope':{**checked['envelope'],'text':text},'resources':resources}
