"""Prepared exact native Feishu reply intents; not connected to public send paths."""
import base64
from copy import deepcopy
import hashlib
import re
from types import MethodType

from .gateway import digest
from .gateway_feishu import scope
from .gateway_feishu_admission import approve,normalize,MAX_EVENT
from .redaction import Redactor


MAX_TEXT=4000


def specification(value,policy,connector,item,redactor):
    fields={'binding_id','binding_digest','delivery_id','attempt','source_id','source_sha256','source_base64','body'}
    if not isinstance(item,dict) or set(item)!=fields:raise ValueError('exact private Feishu reply intent required')
    if not isinstance(redactor,Redactor):raise PermissionError('private Feishu credential redaction required')
    for key in ['binding_digest','delivery_id','source_sha256']:
        if not isinstance(item[key],str) or not re.fullmatch('[0-9a-f]{64}',item[key]):raise ValueError('opaque immutable Feishu reply proof required')
    if type(item['attempt']) is not int or not 1<=item['attempt']<=5:raise ValueError('bounded Feishu outbox attempt required')
    if (not isinstance(item['source_base64'],str) or not 1<=len(item['source_base64'])<=4*((MAX_EVENT+2)//3)):
        raise ValueError('bounded private original Feishu reply source required')
    try:raw=base64.b64decode(item['source_base64'],validate=True)
    except (ValueError,UnicodeError):raise ValueError('canonical private Feishu source encoding required') from None
    if (not 1<=len(raw)<=MAX_EVENT or base64.b64encode(raw).decode()!=item['source_base64']
            or hashlib.sha256(raw).hexdigest()!=item['source_sha256']):raise ValueError('Feishu reply source bytes changed')
    binding=policy.current_binding({'binding_id':item['binding_id'],'binding_digest':item['binding_digest']})
    if (policy.connectors.get(connector,{}).get('platform')!='feishu' or binding['connector']!=connector
            or binding['scope']!=scope(value) or binding['sender']==value['bot_open_id'] or 'read' not in binding['capabilities']):
        raise PermissionError('exact current Feishu reply/read grant required')
    approval=approve(policy,connector,value,raw);projection=normalize(policy,connector,value,raw,approval,redactor)
    if (approval['binding_id']!=item['binding_id'] or approval['binding_digest']!=item['binding_digest']
            or projection['envelope']['message_id']!=item['source_id']):
        raise PermissionError('Feishu reply differs from independently approved original source')
    body=item['body']
    if (not isinstance(body,str) or not 1<=len(body.strip())<=MAX_TEXT or len(body)>MAX_TEXT
            or len(body.encode())>4*MAX_TEXT or '\0' in body):raise ValueError('one bounded native Feishu text chunk required')
    if redactor.text(body)!=body:raise PermissionError('private Feishu credential reflection refused')
    result=deepcopy(item)
    result.update(chat_id=binding['chat'],thread_id=binding['thread'],
        uuid=digest([item['delivery_id'],item['binding_digest'],item['source_id'],body])[:32])
    return result


def wire_target(adapter,blueprint):
    """Actual pinned formatter/codec, one reply to the exact retained message."""
    from plugins.platforms.feishu.adapter import FeishuAdapter
    text=adapter.format_message(blueprint['body'])
    chunks=adapter.truncate_message(text,adapter.MAX_MESSAGE_LENGTH)
    if chunks!=[text]:raise ValueError('one native Feishu message required per durable intent')
    kind,payload=FeishuAdapter._build_outbound_payload(adapter,text)
    if kind not in {'text','post'} or not isinstance(payload,str) or len(payload.encode())>128000:
        raise ValueError('bounded actual native text/post payload required')
    return {'chat_id':blueprint['chat_id'],'reply_to':blueprint['source_id'],'thread_id':blueprint['thread_id'],
        'msg_type':kind,'content':payload,'uuid':blueprint['uuid']}


def bind_single_native_send(adapter,target):
    """Keep native send/formatting/builders; forbid retries, fallback routes and new UUIDs."""
    from plugins.platforms.feishu.adapter import FeishuAdapter
    original=FeishuAdapter._build_reply_message_body
    def reply_body(*,content,msg_type,reply_in_thread,uuid_value):
        if content!=target['content'] or msg_type!=target['msg_type'] or reply_in_thread is not bool(target['thread_id']):
            raise PermissionError('native Feishu reply body changed')
        return original(content=content,msg_type=msg_type,reply_in_thread=reply_in_thread,uuid_value=target['uuid'])
    used=[False]
    async def once(self,*,chat_id,msg_type,payload,reply_to,metadata):
        if (used[0] or chat_id!=target['chat_id'] or msg_type!=target['msg_type'] or payload!=target['content']
                or reply_to!=target['reply_to'] or metadata!={'thread_id':target['thread_id']}):
            raise PermissionError('native Feishu retry or reply-route fallback refused')
        used[0]=True
        return await FeishuAdapter._send_raw_message(self,chat_id=chat_id,msg_type=msg_type,payload=payload,
            reply_to=reply_to,metadata=metadata)
    async def blocking(_self,function,*args,**kwargs):return function(*args,**kwargs)
    adapter._build_reply_message_body=reply_body
    adapter._feishu_send_with_retry=MethodType(once,adapter);adapter._run_blocking=MethodType(blocking,adapter)
    return adapter
