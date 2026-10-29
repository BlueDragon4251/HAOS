"""Retained native Feishu text dispatch through independent durable HAOS admission."""
import asyncio
from contextvars import ContextVar
from datetime import datetime,timezone
from types import MethodType

from .gateway import Conflict,digest
from .gateway_feishu_admission import parse,Refused

_CURRENT=ContextVar('haos_retained_feishu',default=None)


def capture(adapter,raw):
    native=adapter._haos_native;adapter._haos_feishu_check();policy=native.policy()
    item=adapter._haos_feishu_raw.capture(policy,native.connector,adapter._haos_feishu_value,raw)
    binding=policy.authorize(native.connector,item['envelope'])
    latest=native.policy();latest.current_binding({'binding_id':binding['id'],'binding_digest':digest(binding)})
    native.inbox.db.execute('''CREATE TABLE IF NOT EXISTS feishu_source_context(
        source_key TEXT PRIMARY KEY,connector TEXT NOT NULL,raw_id TEXT NOT NULL,binding_digest TEXT NOT NULL,
        scope TEXT NOT NULL,chat TEXT NOT NULL,thread TEXT NOT NULL,message_id TEXT NOT NULL,sender TEXT NOT NULL)''')
    envelope=item['envelope']
    values=(item['source_key'],native.connector,item['id'],digest(binding),envelope['scope'],envelope['chat'],
        envelope['thread'],envelope['message_id'],envelope['sender'])
    old=native.inbox.db.execute('SELECT * FROM feishu_source_context WHERE source_key=?',(item['source_key'],)).fetchone()
    if old is None:native.inbox.db.execute('INSERT INTO feishu_source_context VALUES(?,?,?,?,?,?,?,?,?)',values)
    elif tuple(old)!=values:raise Conflict('Feishu replay changed retained reply context or authority')
    adapter._haos_feishu_check();latest=native.policy();latest.current_binding({'binding_id':binding['id'],'binding_digest':digest(binding)})
    key=native.inbox.admit(latest,native.connector,envelope,{'raw_id':item['id']},received_at=item['received_at'])
    if key!=item['source_key']:raise Conflict('Feishu original and native input identity differ')
    return key


async def dispatch_stored(adapter,key):
    native=adapter._haos_native
    async with adapter._haos_feishu_decode_lock:
        row=native.inbox.claim(key,native.policy())
        if row is None:return False
        state={'adapter':adapter,'row':row,'accepted':False};token=_CURRENT.set(state)
        try:
            adapter._haos_feishu_check();native.policy().current_binding(row)
            if not isinstance(row['payload'],dict) or set(row['payload'])!={'raw_id'}:raise ValueError('exact retained Feishu original required')
            item=adapter._haos_feishu_raw.get(native.policy(),native.connector,adapter._haos_feishu_value,row['payload']['raw_id'])
            if item['envelope']!=row['envelope'] or item['source_key']!=key:raise Conflict('retained Feishu projection changed')
            if item['resources']:raise Refused('media-runtime-unavailable')
            from lark_oapi.api.im.v1 import P2ImMessageReceiveV1
            raw=parse(item['raw']);state.update(raw=raw,resources=[])
            from .gateway_matrix_profile import scope
            with scope(adapter._haos_feishu_home,adapter._haos_feishu_environment):
                await adapter._haos_feishu_decode(adapter,P2ImMessageReceiveV1(raw))
            adapter._haos_feishu_check();native.policy().current_binding(row)
            native.inbox.complete(key,state['accepted']);return state['accepted']
        except BaseException:native.inbox.retry(key);raise
        finally:_CURRENT.reset(token)


def install(adapter):
    if (not callable(getattr(adapter,'set_durable_message_handler',None)) or not callable(getattr(adapter,'_haos_admit',None))
            or hasattr(adapter,'_haos_feishu_decode')):raise TypeError('one actual native Feishu adapter with durable ingress MRO required')
    original_build=adapter.build_source;original_handle=adapter.handle_message;original_admit=adapter._admit
    adapter._haos_feishu_decode=type(adapter)._handle_message_event_data
    adapter._haos_feishu_decode_lock=asyncio.Lock()
    def current(self):
        state=_CURRENT.get()
        if state is None or state['adapter'] is not self:raise PermissionError('no retained independently approved Feishu context')
        self._haos_feishu_check();self._haos_native.policy().current_binding(state['row']);return state
    def admit(self,sender,message):
        state=current(self);row=state['row']['envelope']
        if (getattr(getattr(sender,'sender_id',None),'open_id',None)!=row['sender']
                or getattr(message,'message_id',None)!=row['message_id'] or getattr(message,'chat_id',None)!=row['chat']
                or (getattr(message,'thread_id',None) or '')!=row['thread']):raise PermissionError('native Feishu admission source changed')
        return original_admit(sender,message)
    async def duplicate(self,message_id):
        if message_id!=current(self)['row']['envelope']['message_id']:raise PermissionError('native Feishu message differs from retained source')
        return False  # Only the actual durable NativeInbox claim owns replay suppression.
    async def sender_profile(self,sender_id,*,is_bot=False):
        row=current(self)['row']['envelope']
        if is_bot is not False or getattr(sender_id,'open_id',None)!=row['sender']:raise PermissionError('Feishu source aliases are not authority')
        return {'user_id':row['sender'],'user_name':row['sender'],'user_id_alt':None}
    async def chat_info(self,chat_id):
        state=current(self);row=state['row']['envelope']
        if chat_id!=row['chat']:raise PermissionError('Feishu chat lookup differs from approved source')
        kind='dm' if state['raw']['event']['message']['chat_type']=='p2p' else 'group'
        return {'id':chat_id,'name':chat_id,'type':kind}
    async def quote(self,message_id):
        state=current(self);message=state['raw']['event']['message']
        if message_id not in {message.get('parent_id'),message.get('root_id')}:raise PermissionError('unapproved Feishu quote lookup')
        # Account-bound remote quote reads are connected with the transport.
        return None
    def source(self,**kwargs):
        row=current(self)['row']['envelope']
        if (kwargs.get('chat_id')!=row['chat'] or kwargs.get('user_id')!=row['sender']
                or (kwargs.get('thread_id') or '')!=row['thread'] or kwargs.get('message_id')!=row['message_id']
                or kwargs.get('is_bot') is not False):raise PermissionError('native Feishu source changed before durable admission')
        kwargs.update(scope_id=row['scope'],user_id_alt=None)
        return original_build(**kwargs)
    async def handle(self,event):
        state=current(self);row=state['row'];envelope=row['envelope']
        if event.media_urls or event.media_types:raise PermissionError('Feishu media requires a retained private resource path')
        if event.text!=envelope['text'] or event.message_id!=envelope['message_id']:raise Conflict('native Feishu text or message identity changed')
        from .gateway_runtime import adapter_envelope
        if adapter_envelope(event,'feishu')!=envelope:raise Conflict('native Feishu source differs from independent owner route')
        event.timestamp=datetime.fromtimestamp(row['created_at'],timezone.utc);event.channel_prompt=None
        await original_handle(event);state['accepted']=event._gateway_accepted is True
    async def dispatch(self,event):
        current(self)
        # Native burst buffers cannot acknowledge before durable HAOS acceptance.
        await self._handle_message_with_guards(event)
    def no_prompt(self,*_args,**_kwargs):current(self);return None
    async def deny(_self,*_args,**_kwargs):raise PermissionError('Feishu operation has no reviewed HAOS transport capability')
    def deny_event(_self,*_args,**_kwargs):raise PermissionError('Feishu event has no authenticated retained capture boundary')
    for name,method in {'_admit':admit,'_is_duplicate':duplicate,'_resolve_sender_profile':sender_profile,
            'get_chat_info':chat_info,'_fetch_message_text':quote,'build_source':source,'handle_message':handle,
            '_dispatch_inbound_event':dispatch,'_resolve_channel_prompt':no_prompt}.items():
        setattr(adapter,name,MethodType(method,adapter))
    for name in ['connect','send','edit_message','send_document','send_voice','send_video','send_image_file','send_image',
            'send_animation','send_update_prompt','_send_exec_approval_prompt','_send_interactive_card','_dispatch_synthetic_event']:
        setattr(adapter,name,MethodType(deny,adapter))
    for name in ['_on_message_event','_on_card_action_trigger','_on_reaction_event','_on_drive_comment_event','_on_meeting_invited_event']:
        setattr(adapter,name,MethodType(deny_event,adapter))
    return adapter
