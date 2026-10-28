"""Signed LINE text admission behind independent timed owner grants."""
import asyncio
from contextvars import ContextVar
from datetime import datetime,timezone
import json
import re
import time
from types import MethodType

from .gateway import GatewayPolicy,SUPPORTED,digest

_USER=re.compile(r'U[0-9a-f]{32}\Z')
_CHAT=re.compile(r'[UCR][0-9a-f]{32}\Z')
_CURRENT=ContextVar('haos_line_retained_event',default=None)


class PreparedLINEPolicy(GatewayPolicy):
    platforms=frozenset(SUPPORTED|{'line'})

    def __init__(self,config):
        super().__init__(config)
        for binding in self.bindings.values():
            if self.connectors[binding['connector']]['platform']!='line':continue
            validate_binding(binding,require_epoch=True)


def validate_binding(binding,*,require_epoch=False):
    for approval in ['allow_media','allow_voice','allow_video']:
        if approval in binding and (type(binding[approval]) is not bool
                or binding[approval] and (not isinstance(binding['capabilities'],list) or 'create' not in binding['capabilities'])):
            raise ValueError('LINE media/voice needs separate boolean approval and mission-create rights')
    if 'allow_outbound_media' in binding and (type(binding['allow_outbound_media']) is not bool
            or binding['allow_outbound_media'] and 'read' not in binding['capabilities']):
        raise ValueError('LINE outbound media requires separate boolean approval and read rights')
    if (not _USER.fullmatch(binding['sender']) or not _CHAT.fullmatch(binding['chat'])
            or not _USER.fullmatch(binding['scope']) or binding['thread']
            or binding['chat'].startswith('U') and binding['chat']!=binding['sender']):
        raise ValueError('LINE requires exact user/chat/destination IDs; threads do not apply')
    if require_epoch and (not binding.get('generation') or type(binding.get('since')) is not int):
        raise ValueError('LINE transport requires an explicit timed owner grant')


def snapshot(policy,connector,destination):
    if (not isinstance(policy,GatewayPolicy) or not _USER.fullmatch(destination)
            or policy.connectors.get(connector,{}).get('platform')!='line'):
        raise PermissionError('prepared LINE destination authority required')
    return {'connector':connector,'destination':destination,
        'bindings':[digest(b) for b in policy.bindings.values() if b['connector']==connector and b['scope']==destination]}


def envelope(event,destination):
    if not isinstance(event,dict) or event.get('type')!='message' or event.get('mode')!='active':return None
    source=event.get('source');message=event.get('message');stamp=event.get('timestamp');identity=event.get('webhookEventId')
    if (not isinstance(source,dict) or not isinstance(message,dict) or type(stamp) is not int or stamp<=0
            or not isinstance(identity,str) or not re.fullmatch(r'[0-9A-HJKMNP-TV-Z]{26}',identity)
            or not _USER.fullmatch(destination) or not isinstance(source.get('userId'),str)
            or not _USER.fullmatch(source['userId']) or message.get('type') not in {'text','image','file','audio','video'}
            or not isinstance(message.get('id'),str) or not re.fullmatch(r'[1-9][0-9]{0,31}',message['id'])):return None
    if message['type']=='text':
        if not isinstance(message.get('text'),str) or not 1<=len(message['text'].encode())<=32000 or not message['text'].strip():return None
        text=message['text']
    else:
        from .gateway_media import MAX_BYTES,MAX_IMAGE_BYTES
        if message.get('contentProvider',{'type':'line'})!={'type':'line'}:return None
        if 'fileName' in message and (not isinstance(message['fileName'],str) or not 1<=len(message['fileName'].encode())<=512
                or any(ord(c)<32 for c in message['fileName'])):return None
        if 'fileSize' in message and (type(message['fileSize']) is not int or not 1<=message['fileSize']<=
                (MAX_IMAGE_BYTES if message['type']=='image' else MAX_BYTES)):return None
        if 'duration' in message and (message['type'] not in {'audio','video'} or type(message['duration']) is not int or not 1<=message['duration']<=120000):return None
        fields={key:message[key] for key in ('id','type','fileName','fileSize','contentProvider','duration') if key in message}
        kind={'image':'image','file':'document','audio':'voice','video':'video'}[message['type']]
        text=(f"Process the approved voice request (LINE message {message['id']}; metadata {digest(fields)})." if kind=='voice'
            else f"Inspect the attached {kind} (LINE message {message['id']}; metadata {digest(fields)}).")
    user=source['userId'];kind=source.get('type')
    if kind=='user' and set(source)=={'type','userId'}:chat=user
    elif kind=='group' and set(source)=={'type','userId','groupId'}:chat=source['groupId']
    elif kind=='room' and set(source)=={'type','userId','roomId'}:chat=source['roomId']
    else:return None
    if not isinstance(chat,str) or not _CHAT.fullmatch(chat) or chat[0]!={'user':'U','group':'C','room':'R'}[kind]:return None
    return {'platform':'line','sender':user,'chat':chat,'scope':destination,'thread':'',
        'message_id':digest([destination,identity]),'is_bot':False,'text':text},stamp/1000


def _object(pairs):
    result={}
    for key,value in pairs:
        if key in result:raise ValueError('duplicate signed LINE JSON field')
        result[key]=value
    return result


def capture(adapter,body,signature,authority):
    if (not isinstance(body,bytes) or not 1<=len(body)<=65536 or not isinstance(signature,str)
            or not re.fullmatch(r'[A-Za-z0-9+/]{43}=',signature)):
        raise PermissionError('bounded signed LINE request required')
    from plugins.platforms.line.adapter import verify_line_signature
    if not verify_line_signature(body,signature,adapter.channel_secret):raise PermissionError('invalid LINE signature')
    payload=json.loads(body,object_pairs_hook=_object)
    if (not isinstance(authority,dict) or set(authority)!={'connector','destination','bindings'}
            or not isinstance(payload,dict) or set(payload)!={'destination','events'}
            or payload['destination']!=authority['destination'] or not isinstance(payload['events'],list)
            or len(payload['events'])>64):raise PermissionError('signed LINE destination or batch mismatch')
    native=adapter._haos_native;policy=native.policy()
    if snapshot(policy,native.connector,authority['destination'])!=authority:raise PermissionError('LINE owner authority changed')
    # Validate the whole batch before committing any of its admissible events.
    admitted=[]
    for event in payload['events']:
        decoded=envelope(event,authority['destination'])
        if decoded is None:continue
        source,stamp=decoded
        try:binding=policy.authorize(native.connector,source)
        except PermissionError:continue
        validate_binding(binding,require_epoch=True)
        is_media=event['message']['type']!='text'
        if is_media:
            from .gateway_media import authorize
            try:authorize(policy,native.connector,source,{'image':'image','file':'document','audio':'voice','video':'video'}[event['message']['type']])
            except PermissionError:continue
        if stamp*1000<=binding['since'] or stamp>time.time()+300:raise PermissionError('LINE event outside timed owner grant')
        # Reply tokens are single-use capabilities, never persisted in raw payload.
        sanitized={key:value for key,value in event.items() if key in {'type','mode','source','message','timestamp','webhookEventId'}}
        message_fields=('id','type','fileName','fileSize','contentProvider','duration') if is_media else ('id','type','text')
        sanitized['message']={key:event['message'][key] for key in message_fields if key in event['message']}
        from .redaction import Redactor
        private=Redactor([adapter.channel_secret,adapter.channel_access_token,event.get('replyToken','')])
        source={**source,'text':private.text(source['text'])}
        if not is_media:sanitized['message']['text']=source['text']
        admitted.append((source,stamp,sanitized))
    return [native.inbox.admit(policy,native.connector,source,{'event':event},received_at=stamp)
        for source,stamp,event in admitted]


async def dispatch_stored(adapter,key):
    native=adapter._haos_native
    async with adapter._haos_line_lock:
        row=native.inbox.claim(key,native.policy())
        if row is None:return False
        token=None
        try:
            decoded=envelope(row['payload']['event'],row['envelope']['scope'])
            if decoded is None or decoded[0]!=row['envelope']:raise PermissionError('retained LINE event changed')
            if adapter._client is not None:raise PermissionError('prepared LINE decoder must have no live client')
            state={'adapter':adapter,'row':row,'accepted':False,'media':None};token=_CURRENT.set(state)
            await adapter._haos_line_decode(adapter,row['payload']['event'])
            native.policy().current_binding(row);native.inbox.complete(key,state['accepted'])
            return state['accepted']
        except BaseException:native.inbox.retry(key);raise
        finally:
            if token is not None:_CURRENT.reset(token)


def install(adapter):
    from .gateway_runtime import adapter_envelope
    adapter._haos_line_decode=type(adapter)._handle_message_event
    adapter._haos_line_lock=asyncio.Lock()
    original_build=adapter.build_source;original_handle=adapter.handle_message
    async def deny(_self,*_args,**_kwargs):raise PermissionError('LINE requires retained independent owner admission')
    def source(self,**kwargs):
        state=_CURRENT.get()
        if state is None or state['adapter'] is not self:raise PermissionError('no retained LINE source')
        value=state['row']['envelope']
        kwargs.update(chat_id=value['chat'],user_id=value['sender'],scope_id=value['scope'],thread_id=None,
            message_id=value['message_id'],is_bot=False)
        return original_build(**kwargs)
    async def handle(self,event):
        state=_CURRENT.get()
        if state is None or state['adapter'] is not self:raise PermissionError('no retained LINE event')
        self._haos_native.policy().current_binding(state['row'])
        event.message_id=state['row']['envelope']['message_id'];event.timestamp=datetime.fromtimestamp(state['row']['created_at'],timezone.utc)
        if state['media'] is not None:
            from .gateway_media_relay import event_scope
            expected=state['row']['payload']['event']['message']['type']
            if event.text!='['+expected+']':raise PermissionError('LINE native media codec changed retained kind')
            event.text=state['row']['envelope']['text']
            item=state['media'];mime='image/'+item['descriptor']['format'] if item['descriptor']['kind']=='image' else 'application/octet-stream'
            with event_scope(event,[item['id']],[mime]):
                if adapter_envelope(event,'line')!=state['row']['envelope']:raise PermissionError('LINE native media source changed')
                await original_handle(event)
        else:
            if adapter_envelope(event,'line')!=state['row']['envelope']:raise PermissionError('LINE native codec changed approved source')
            await original_handle(event)
        state['accepted']=event._gateway_accepted is True
    async def download(self,message_id,msg_type,*,filename=None):
        state=_CURRENT.get()
        if state is None or state['adapter'] is not self:raise PermissionError('no retained LINE media event')
        row=state['row'];message=row['payload']['event']['message'];kind={'image':'image','file':'document','audio':'voice','video':'video'}.get(msg_type)
        if message_id!=message['id'] or msg_type!=message['type'] or msg_type not in {'image','file','audio','video'}:
            raise PermissionError('native LINE media identity changed')
        def current():
            from .gateway_media import authorize
            policy=self._haos_native.policy();policy.current_binding(row)
            authorize(policy,self._haos_native.connector,row['envelope'],kind)
            return policy
        cache=self._haos_media_cache;policy=current();item=cache.find(policy,self._haos_native.connector,row['envelope'],retained=True)
        if item is None:
            cache.capacity()
            data=await self._haos_line_content.fetch(message_id,kind,current)
            item=cache.put(current(),self._haos_native.connector,row['envelope'],data,kind)
        state['media']=item
        mime='image/'+item['descriptor']['format'] if kind=='image' else 'application/octet-stream'
        return 'haos-media:'+item['id'],mime
    for name in ('connect','_handle_webhook','_dispatch_event','_handle_message_event','_handle_postback_event',
            '_download_media','_handle_media','send','send_typing','send_image','send_image_file','send_document',
            'send_voice','send_video','send_multiple_images'):
        setattr(adapter,name,MethodType(deny,adapter))
    adapter.build_source=MethodType(source,adapter);adapter.handle_message=MethodType(handle,adapter)
    adapter._download_media=MethodType(download,adapter)
    return adapter
