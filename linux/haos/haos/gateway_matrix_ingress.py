"""Independent prepared Matrix admission before native Hermes text preparation."""
import asyncio
from contextvars import ContextVar
import time
from types import MethodType

from .gateway import digest
from .gateway_matrix_policy import authorize_original,opaque

_CURRENT=ContextVar('haos_matrix_retained_source',default=None)


def plain_envelope(event):
    from mautrix.types import EventType
    if event.type!=EventType.ROOM_MESSAGE:return None
    content=event.content.serialize() if hasattr(event.content,'serialize') else event.content
    if not isinstance(content,dict) or content.get('msgtype')!='m.text':return None
    body=content.get('body');relation=content.get('m.relates_to') or {}
    if not isinstance(relation,dict) or relation.get('rel_type')=='m.replace':return None
    thread=relation.get('event_id') if relation.get('rel_type')=='m.thread' else ''
    if relation.get('rel_type') not in {None,'m.thread'}:return None
    if (not isinstance(body,str) or not 1<=len(body.strip())<=32000
            or not opaque(str(event.sender),'@') or not opaque(str(event.room_id),'!')
            or not opaque(str(event.event_id),'$') or relation.get('rel_type')=='m.thread' and not opaque(thread,'$')):return None
    return {'platform':'matrix','sender':str(event.sender),'chat':str(event.room_id),'scope':'',
        'thread':thread or '','message_id':str(event.event_id),'is_bot':False,'text':body}


async def capture(adapter,event):
    from .gateway_matrix_sync import active_page,verified_crypto
    if getattr(adapter,'_haos_stopping',False):raise ConnectionError('Matrix ingress is stopping')
    source=plain_envelope(event)
    if source is None or source['sender'].lower()==adapter._user_id.lower():return None
    if adapter._is_system_or_bridge_sender(source['sender']):return None
    native=adapter._haos_native;policy=native.policy();page=active_page()
    original_ms=event.timestamp
    crypto=verified_crypto(event)
    try:binding=authorize_original(policy,native.connector,source,original_ms,page['authority'],crypto)
    except PermissionError:return None
    content=event.content.serialize() if hasattr(event.content,'serialize') else event.content
    mention_ids=(content.get('m.mentions') or {}).get('user_ids') if isinstance(content.get('m.mentions') or {},dict) else None
    if binding['require_mention'] and not adapter._is_bot_mentioned(source['text'],content.get('formatted_body'),mention_ids):return None
    payload={'event':event.serialize(),'original_ms':original_ms}
    return native.inbox.admit(policy,native.connector,source,payload,received_at=original_ms/1000)


async def dispatch_stored(adapter,original,key):
    from mautrix.types import Event
    if getattr(adapter,'_haos_stopping',False):return False
    lock=getattr(adapter,'_haos_matrix_decode_lock',None)
    if lock is None:lock=adapter._haos_matrix_decode_lock=asyncio.Lock()
    async with lock:
        native=adapter._haos_native;row=native.inbox.claim(key,native.policy())
        if row is None:return False
        try:
            binding=native.policy().current_binding(row)
            event=Event.deserialize(row['payload']['event']);decoded=plain_envelope(event)
            if decoded is None or any(decoded[name]!=row['envelope'][name] for name in
                    ('platform','sender','chat','scope','thread','message_id','is_bot')):
                raise ValueError('retained Matrix original changed its owner source')
        except BaseException:
            native.inbox.retry(key);raise
        tasks=getattr(adapter,'_haos_receive_tasks',None)
        if tasks is None:tasks=adapter._haos_receive_tasks=set()
        task=asyncio.current_task();tasks.add(task)
        token=_CURRENT.set({'adapter':adapter,'source':row['envelope'],'binding':binding,'accepted':False})
        before=adapter._startup_ts
        try:
            # HAOS retains original timestamps and applies grant/24-hour bounds;
            # native startup grace must not erase a retained recovery obligation.
            adapter._startup_ts=0
            await original(adapter,event)
            native.policy().current_binding(row)
            accepted=_CURRENT.get()['accepted'];native.inbox.complete(key,accepted)
            return accepted
        except BaseException:native.inbox.retry(key);raise
        finally:
            adapter._startup_ts=before;_CURRENT.reset(token);tasks.discard(task)


def admitted(adapter,accepted):
    state=_CURRENT.get()
    if state is not None and state['adapter'] is adapter:state['accepted']=accepted is True


def install(adapter):
    original=type(adapter)._on_room_message
    adapter._haos_native_dispatch=original
    async def receive(self,event):
        key=await capture(self,event)
        if key is not None:return await dispatch_stored(self,original,key)
    async def allowed(self,room):
        state=_CURRENT.get()
        return state is not None and state['adapter'] is self and state['source']['chat']==room
    async def display(_self,_room,sender):return sender
    async def context(self,room,sender,event_id,body,content,relation):
        state=_CURRENT.get()
        if (state is None or state['adapter'] is not self or state['source']['chat']!=room
                or state['source']['sender']!=sender or state['source']['message_id']!=event_id):
            raise PermissionError('native Matrix decoder has no exact retained owner source')
        source=state['source'];binding=state['binding']
        if (relation.get('event_id') if relation.get('rel_type')=='m.thread' else '')!=source['thread']:
            raise PermissionError('native Matrix decoder changed the approved thread')
        mention_ids=(content.get('m.mentions') or {}).get('user_ids') if isinstance(content.get('m.mentions') or {},dict) else None
        mentioned=self._is_bot_mentioned(body,content.get('formatted_body'),mention_ids)
        if binding['require_mention'] and not mentioned:return None
        if mentioned:body=self._strip_mention(body)
        target=self.build_source(chat_id=room,chat_name=room,chat_type='group',user_id=sender,user_name=sender,
            scope_id=None,thread_id=source['thread'] or None,message_id=event_id)
        return body,False,'group',source['thread'] or None,sender,target
    adapter._on_room_message=MethodType(receive,adapter)
    adapter._is_allowed_matrix_room_event=MethodType(allowed,adapter)
    adapter._is_duplicate_event=MethodType(lambda self,_event:False,adapter)
    adapter._get_display_name=MethodType(display,adapter)
    adapter._resolve_message_context=MethodType(context,adapter)
    adapter._background_read_receipt=lambda *_args,**_kwargs:None
    return adapter


def attach_client(adapter,client):
    """Reject unapproved timeline actors before crypto/device/profile lookups."""
    from .gateway_matrix_sync import active_page
    def gate(event):
        source_type=str(event.type)
        if source_type not in {'m.room.message','m.room.encrypted'}:return True
        page=active_page();authority=page['authority'];native=adapter._haos_native
        if authority.get('connector')!=native.connector:return False
        policy=native.policy()
        for binding in policy.bindings.values():
            if (binding['connector']==native.connector and binding['sender']==str(event.sender)
                    and binding['chat']==str(event.room_id) and digest(binding) in authority.get('binding_digests',[])
                    and type(event.timestamp) is int and type(binding.get('since')) is int
                    and binding['since']<event.timestamp<=time.time()*1000+300000):return True
        return False
    client._haos_sync_source_gate=gate
    return client
